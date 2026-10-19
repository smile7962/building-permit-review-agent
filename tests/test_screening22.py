"""Phase 2.2 dynamic case-relevant screening, not a legality decision."""
import json
import tempfile
import unittest
import urllib.error
import urllib.request
import threading
from http.server import ThreadingHTTPServer

import server
from case_store import CaseStore
from screening import screen_item, evidence_values, DESIGN_FIELDS, num
from legal_review import MASTER, build

INDEX = {i['id']:i for i in MASTER['items']}
SYNTHETIC = {'permit_type':'건축신고', 'work_type':'신축', 'site_address':'파주시 가상동 1',
    'primary_use':'단독주택','zoning':'계획관리지역','site_area_m2':'500','building_area_m2':'125',
    'total_floor_area_m2':'220','building_coverage_percent':'25.00','parking_spaces':'1',
    'floor_area_ratio_percent':'44.00'}

class ScreeningEngineTest(unittest.TestCase):
    def test_new_vs_extension_changes_subset(self):
        new=build(SYNTHETIC)
        extension=build({**SYNTHETIC,'work_type':'증축'})
        def item(r,k): return next(i for i in r['items'] if i['id']==k)
        self.assertEqual(item(new,'D071')['screening']['status'],'우선낮음')
        self.assertEqual(item(extension,'D071')['screening']['status'],'검토대상')
        self.assertEqual(item(new,'D089')['screening']['status'],'우선낮음')
        self.assertEqual(item(extension,'D089')['screening']['status'],'검토대상')
        self.assertEqual(item(new,'D001')['screening']['status'],'검토대상')
        self.assertEqual(new['screening_summary']['분류항목'],14)
        self.assertEqual(len(new['items']),113)

    def test_zoning_and_joint_housing_triggers(self):
        self.assertEqual(screen_item(INDEX['D041'],SYNTHETIC)['status'],'우선낮음')
        r=screen_item(INDEX['D041'],{**SYNTHETIC,'zoning':'제1종일반주거지역'})
        self.assertEqual(r['status'],'검토대상')
        self.assertIn('제61조',r['reason'])
        self.assertEqual(screen_item(INDEX['D042'],SYNTHETIC)['status'],'우선낮음')
        self.assertEqual(screen_item(INDEX['D042'],{**SYNTHETIC,'primary_use':'공동주택(다세대주택)'})['status'],'검토대상')

    def test_access_2m_non_final_and_exceptions(self):
        r=screen_item(INDEX['D019'],SYNTHETIC,{'road_frontage_m':'1.5','road_status':'확인됨'})
        self.assertEqual(r['status'],'검토대상')
        self.assertIn('2m 미만',r['reason'])
        self.assertIn('예외',r['reason'])
        self.assertNotIn('위법',r['check']['result'])
        no_road=screen_item(INDEX['D019'],SYNTHETIC,{'road_frontage_m':'3','road_status':'확인되지 않음'})
        self.assertEqual(no_road['status'],'자료필요')

    def test_coverage_requires_reviewer_verified_limit(self):
        r=screen_item(INDEX['D038'],SYNTHETIC)
        self.assertEqual(r['status'],'검토대상')
        self.assertIsNone(r['check'])
        ev=evidence_values({'legal_coverage_max_pct':'20','legal_basis_reference':'가상의 조례 제XX조, 시행 2026-10-01'})
        r=screen_item(INDEX['D038'],SYNTHETIC,ev)
        self.assertEqual(r['check']['computed'],'25.00')
        self.assertIn('초과 의심',r['check']['result'])
        self.assertNotIn('위법',r['reason'])

    def test_far_uses_chargeable_area_not_total_gross_area(self):
        val={**SYNTHETIC,'total_floor_area_m2':'500'}
        self.assertEqual(screen_item(INDEX['D039'],val)['status'],'자료필요')
        ev=evidence_values({'far_chargeable_area_m2':'200', 'legal_far_max_pct':'60',
                             'legal_basis_reference':'담당자 검토 가상 기준'})
        r=screen_item(INDEX['D039'],val,ev)
        self.assertEqual(r['check']['computed'],'40.00')

    def test_parking_needs_manual_local_ordinance_requirement(self):
        self.assertEqual(screen_item(INDEX['D070'],SYNTHETIC)['status'],'자료필요')
        ev=evidence_values({'legal_parking_min_spaces':'2','legal_basis_reference':'가상 조례 기준'})
        r=screen_item(INDEX['D070'],SYNTHETIC,ev)
        self.assertIn('부족 의심',r['check']['result'])
        self.assertNotIn('부적법',r['check']['result'])

    def test_fields_rejected_without_source_and_bad_numbers(self):
        with self.assertRaises(ValueError):evidence_values({'legal_coverage_max_pct':'60'})
        with self.assertRaises(ValueError):evidence_values({'road_frontage_m':'-1'})
        with self.assertRaises(ValueError):evidence_values({'road_status':'무조건 적법'})
        with self.assertRaises(ValueError):evidence_values({'dangerous':'x'})
        self.assertIsNone(num('NaN'))

    def test_no_guess_for_unknown_land_status(self):
        self.assertEqual(screen_item(INDEX['D078'],SYNTHETIC)['status'],'자료필요')
        self.assertEqual(screen_item(INDEX['D079'],SYNTHETIC)['status'],'자료필요')

class ScreeningStorageTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=CaseStore(self.temp.name,server.FIELD_KEYS,server.MASTER['version'])
        self.store.save_values(SYNTHETIC)
        self.store.confirm(server.REQUIRED_KEYS)
        self.store.build_legal()
    def tearDown(self):self.temp.cleanup()

    def test_design_evidence_stored_and_restored(self):
        raw={'road_frontage_m':'1.5','road_status':'확인됨',
             'legal_coverage_max_pct':'20',
             'legal_basis_reference':'가상 조례: 2026-10-19'}
        a=self.store.update_design_evidence(raw)
        self.assertEqual(a['legal_review']['design_evidence']['road_frontage_m'],'1.5')
        item=next(i for i in a['legal_review']['items'] if i['id']=='D019')
        self.assertIn('2m 미만',item['screening']['reason'])
        data=self.store.export_bytes();self.store.new_case();b=self.store.open_case(data)
        self.assertEqual(b['legal_review']['design_evidence']['road_frontage_m'],'1.5')

    def test_design_evidence_edit_invalidates_completed_review(self):
        self.store.update_legal('D019','적용','검토기록완료','예외 조항 검토했음')
        changed=self.store.update_design_evidence({'road_frontage_m':'2.5','road_status':'확인됨'})
        item=next(i for i in changed['legal_review']['items'] if i['id']=='D019')
        self.assertEqual(item['progress'],'검토중')
        self.assertEqual(item['applicability'],'미확인')
        self.assertEqual(item['note'],'예외 조항 검토했음')
        self.assertFalse(changed['legal_review']['confirmed_at'])

    def test_old_review_reopen_enriched_with_screening(self):
        with self.store.lock,self.store._connect() as con:
            rec=con.execute("SELECT id,payload_json FROM records WHERE category='legal_checklist' ORDER BY id DESC LIMIT 1").fetchone()
            old=json.loads(rec['payload_json'])
            for item in old['items']:item.pop('screening',None)
            old.pop('screening_version',None)
            con.execute('UPDATE records SET payload_json=? WHERE id=?',(json.dumps(old),rec['id']))
        state=self.store.state()['legal_review']
        self.assertTrue(state['screening_needs_refresh'])
        self.assertEqual(len(state['items']),113)
        self.assertIn('screening',state['items'][0])

if __name__=='__main__':unittest.main()
