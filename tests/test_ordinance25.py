"""Conservative Paju ordinance screening, source version, persistence, HTTP regressions."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from case_store import CaseStore
from ordinance_review import (assess,validate_inputs,validate_decision,ZONE_NAMES,
                              BCR,FAR,VERSION)
from review_report import preview
import server

CASE={'permit_type':'건축허가','work_type':'신축','site_address':'파주시 모의동 1',
      'primary_use':'단독주택','zoning':'계획관리지역','site_area_m2':'450',
      'building_area_m2':'130','total_floor_area_m2':'268.20',
      'above_ground_floors':'2','parking_spaces':'2'}
EV={'far_chargeable_area_m2':'268.2'}
INPUT={'parking_scenario':'신축·단일용도','parking_type':'단독주택(다가구 제외)',
       'parking_area_m2':'268.2','basis_date':'2026-10-21'}

def row(checks,key):return next(x for x in checks if x['id']==key)

class OrdinanceRules(unittest.TestCase):
    def test_all_21_zones_maps_and_distinct_appendix_modes(self):
        self.assertEqual(len(ZONE_NAMES),len(BCR));self.assertEqual(len(ZONE_NAMES),len(FAR))
        self.assertEqual(len(set(ZONE_NAMES)),21)
        for zone in ZONE_NAMES:
            checks=assess({**CASE,'zoning':zone},EV,INPUT)['checks']
            self.assertIn('제31조',row(checks,'PZ01')['reference'])
            self.assertIn('%',row(checks,'PZ02')['criterion'])
            self.assertIn('%',row(checks,'PZ03')['criterion'])
        self.assertIn('금지 용도 열거',row(assess(CASE,EV,INPUT)['checks'],'PZ01')['criterion'])
        self.assertIn('허용 용도 열거',row(assess({**CASE,'zoning':'제1종 일반주거지역'},EV,INPUT)['checks'],'PZ01')['criterion'])
    def test_plan_mgmt_basic_comparisons_and_asof(self):
        r=assess(CASE,EV,INPUT)
        self.assertEqual(r['sources']['zoning'],'2025-03-20')
        self.assertEqual(r['sources']['parking'],'2019-12-27')
        self.assertEqual(row(r['checks'],'PZ02')['attention'],'ok')
        self.assertEqual(row(r['checks'],'PZ03')['attention'],'ok')
        self.assertIn('40%',row(r['checks'],'PZ02')['criterion'])
        self.assertIn('100%',row(r['checks'],'PZ03')['criterion'])
    def test_missing_far_chargeable_area_not_replaced_by_total_floor(self):
        r=assess(CASE,{},INPUT)
        self.assertEqual(row(r['checks'],'PZ03')['attention'],'info')
        self.assertIn('보류',row(r['checks'],'PZ03')['result'])
    def test_numeric_above_threshold_warns_and_equality_does_not(self):
        case={**CASE,'site_area_m2':'100','building_area_m2':'40'}
        r=assess(case,{'far_chargeable_area_m2':'100'},INPUT)['checks']
        self.assertEqual(row(r,'PZ02')['attention'],'ok')
        self.assertEqual(row(r,'PZ03')['attention'],'ok')
        case['building_area_m2']='40.01'
        self.assertEqual(row(assess(case,EV,INPUT)['checks'],'PZ02')['attention'],'warning')
    def test_zoning_warning_only_auditable_explicit_bans(self):
        for c in ({**CASE,'primary_use':'아파트'}, {**CASE,'above_ground_floors':'5'},
                  {**CASE,'primary_use':'업무시설'}):
            self.assertEqual(row(assess(c,EV,INPUT)['checks'],'PZ01')['attention'],'warning')
        self.assertEqual(row(assess({**CASE,'primary_use':'단독주택'},EV,INPUT)['checks'],'PZ01')['attention'],'info')
        self.assertEqual(row(assess({**CASE,'zoning':'알수없는 지역'},EV,INPUT)['checks'],'PZ01')['attention'],'info')
    def test_parking_simple_single_family_and_round_half(self):
        for size,expected in [('50','0'),('100','1'),('149','1'),('150','2'),('200','2'),('250','3')]:
            d={**INPUT,'parking_area_m2':size}
            p=row(assess(CASE,EV,d)['checks'],'PZ04')
            self.assertIn(f'약 {expected}대',p['result'])
        p=row(assess(CASE,EV,INPUT)['checks'],'PZ04')
        self.assertEqual(p['attention'],'warning')
        self.assertIn('2019년 구판',p['result'])
    def test_parking_extension_household_and_mixed_rejected(self):
        for work,kind in [('증축','신축·단일용도'),('신축','복합용도')]:
            p=row(assess({**CASE,'work_type':work},EV,{**INPUT,'parking_scenario':kind})['checks'],'PZ04')
            self.assertEqual(p['attention'],'info')
            self.assertIn('보류',p['result'])
        p=row(assess(CASE,EV,{**INPUT,'parking_type':'다가구·공동주택·오피스텔 등(세대별 산정)'})['checks'],'PZ04')
        self.assertIn('보류',p['result'])
    def test_setback_values_and_negative_validation(self):
        d={**INPUT,'boundary_setback_m':'0.4','building_road_width_m':'6','building_line_setback_m':'0.8'}
        self.assertEqual(row(assess(CASE,EV,d)['checks'],'PZ05')['attention'],'warning')
        self.assertEqual(row(assess(CASE,EV,{**d,'boundary_setback_m':'0.5','building_line_setback_m':'1'})['checks'],'PZ05')['attention'],'info')
        with self.assertRaises(ValueError):validate_inputs({**INPUT,'parking_area_m2':'-1'})
        with self.assertRaises(ValueError):validate_inputs({**INPUT,'unexpected':'x'})
        with self.assertRaises(ValueError):validate_decision('적정(담당자 확인)','','','')

class OrdinanceCaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=CaseStore(self.tmp.name,server.FIELD_KEYS,server.MASTER['version'])
        self.store.save_values(CASE);self.store.confirm(server.REQUIRED_KEYS)
        self.store.build_legal()
        self.store.update_design_evidence({k:str(v) for k,v in {**EV,'road_status':'확인됨'}.items()})
    def tearDown(self):self.tmp.cleanup()
    def test_roundtrip_preview_and_human_decision(self):
        a=self.store.save_ordinance_inputs(INPUT)
        self.assertEqual(len(a['ordinance_review']['checks']),5)
        a=self.store.save_ordinance_decision('PZ04','추가 확인','2019년 별표이므로 최신판 확인 필요','','')
        self.assertEqual(row(a['ordinance_review']['checks'],'PZ04')['human_review']['review_result'],'추가 확인')
        self.assertEqual(len(preview(a)['ordinance_checks']),5)
        binary=self.store.export_bytes();self.store.new_case()
        reopened=self.store.open_case(binary)
        self.assertEqual(row(reopened['ordinance_review']['checks'],'PZ04')['human_review']['note'],'2019년 별표이므로 최신판 확인 필요')
    def test_changed_case_or_design_evidence_invalidates_decisions(self):
        self.store.save_ordinance_inputs(INPUT)
        self.store.save_ordinance_decision('PZ02','추가 확인','기준 확인 필요','','')
        e=self.store.state()['legal_review']['design_evidence']
        self.store.update_design_evidence({**e,'far_chargeable_area_m2':'280'})
        state=self.store.state()
        self.assertTrue(state['ordinance_review']['outdated'])
        self.assertNotIn('human_review',row(state['ordinance_review']['checks'],'PZ02'))
        with self.assertRaisesRegex(ValueError,'변경'):
            self.store.save_ordinance_decision('PZ02','추가 확인','의견','','')
    def test_case_edit_requires_recheck_and_unchanged_inputs_keep_decisions(self):
        self.store.save_ordinance_inputs(INPUT)
        self.store.save_ordinance_decision('PZ02','추가 확인','조건 확인','','')
        self.store.save_ordinance_inputs(INPUT)
        self.assertFalse(self.store.state()['ordinance_review']['outdated'])
        self.assertIn('human_review',row(self.store.state()['ordinance_review']['checks'],'PZ02'))
        self.store.save_values({**CASE,'building_area_m2':'155'})
        self.assertTrue(self.store.state()['ordinance_review']['outdated'])
    def test_human_confirm_requires_references(self):
        self.store.save_ordinance_inputs(INPUT)
        with self.assertRaisesRegex(ValueError,'근거'):
            self.store.save_ordinance_decision('PZ02','적정(담당자 확인)','문제 없음','','')

class OrdinanceHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        server.STORE=CaseStore(self.tmp.name,server.FIELD_KEYS,server.MASTER['version'])
        self.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.http.server_port}'
    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join()
        server.STORE=None;self.tmp.cleanup()
    def post(self,path,d):
        b=json.dumps(d,ensure_ascii=False).encode()
        req=urllib.request.Request(self.url+path,data=b,method='POST',headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=10) as r:return json.loads(r.read())
    def test_http_workflow_and_bad_input(self):
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/ordinance-inputs',{'values':INPUT})
        self.post('/api/save',{'values':CASE});self.post('/api/confirm',{'confirm':True})
        self.post('/api/legal-build',{'init':True})
        a=self.post('/api/ordinance-inputs',{'values':INPUT})['case']['ordinance_review']
        self.assertEqual(a['version'],VERSION)
        self.assertEqual(len(a['checks']),5)
        a=self.post('/api/ordinance-decision',{'id':'PZ04','review_result':'추가 확인','note':'현행판 확인','drawing_ref':'','criteria_ref':''})
        self.assertIn('human_review',row(a['case']['ordinance_review']['checks'],'PZ04'))
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/ordinance-decision',{'id':'unknown','review_result':'추가 확인','note':'안됨','drawing_ref':'','criteria_ref':''})

if __name__=='__main__':unittest.main()
