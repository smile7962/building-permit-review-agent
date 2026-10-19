"""Phase 2 rule-candidate / review persistence tests. No remote AI or legal verdicts."""
import json
import tempfile
import unittest
import urllib.error
import urllib.request
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer

import server
from case_store import CaseStore
from legal_review import build, priority, MASTER, snapshot

ROOT=Path(__file__).resolve().parents[1]

class LegalReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.s=CaseStore(self.temp.name,server.FIELD_KEYS,server.MASTER['version'])
        self.values={'permit_type':'건축허가','work_type':'신축','site_address':'파주시 모의동 1',
                     'primary_use':'단독주택','zoning':'계획관리지역'}
        self.s.save_values(self.values)
    def tearDown(self):self.temp.cleanup()
    def test_items_never_predetermine_applicability(self):
        r=build(self.values)
        self.assertEqual(len(r['items']),113)
        self.assertTrue(all(x['applicability']=='미확인' and x['progress']=='미착수' for x in r['items']))
        self.assertFalse(r['confirmed_at'])
        self.assertTrue(all(x['url'].startswith('https://www.law.go.kr/') for x in r['items']))
    def test_priority_residential_and_extension_only_hints(self):
        sunny=next(x for x in MASTER['items'] if x['id']=='C08')
        adjust=next(x for x in MASTER['items'] if x['id']=='C13')
        self.assertEqual(priority(sunny,{'zoning':'제2종일반주거지역'}),'우선 확인')
        self.assertEqual(priority(sunny,{'zoning':'계획관리지역'}),'적용 여부 확인')
        self.assertEqual(priority(adjust,{'work_type':'증축'}),'우선 확인')
        self.assertEqual(priority(adjust,{'work_type':'신축'}),'적용 여부 확인')
    def test_requires_step1_confirmation(self):
        with self.assertRaisesRegex(ValueError,'STEP 01'):self.s.build_legal()
    def test_edit_records_and_case_export_restore(self):
        self.s.confirm(server.REQUIRED_KEYS)
        case=self.s.build_legal();self.assertEqual(case['legal_review']['master_version'],MASTER['version'])
        self.assertFalse(case['legal_review']['outdated'])
        case=self.s.update_legal('C01','적용','검토기록완료','허가서류 검토 초안·원문 별도 확인')
        self.assertEqual(case['legal_review']['items'][0]['progress'],'검토기록완료')
        self.assertIsNone(case['legal_review']['confirmed_at'])
        blob=self.s.export_bytes();self.s.new_case();self.assertIsNone(self.s.state()['legal_review'])
        restored=self.s.open_case(blob)
        self.assertEqual(restored['legal_review']['items'][0]['note'],'허가서류 검토 초안·원문 별도 확인')
        self.assertEqual(restored['legal_review']['items'][0]['applicability'],'적용')
    def test_invalid_evidence_and_tampered_status_blocked(self):
        self.s.confirm(server.REQUIRED_KEYS);self.s.build_legal()
        for args in [('C01','비적용','미착수',''),('C01','미확인','검토기록완료','abc'),
                     ('C01','적법','검토기록완료','abc'),('C99','적용','검토중','')]:
            with self.assertRaises(ValueError):self.s.update_legal(*args)
        with self.assertRaisesRegex(ValueError,'미완료'):self.s.confirm_legal()
    def test_confirm_complete_and_invalidate_after_edit(self):
        self.s.confirm(server.REQUIRED_KEYS);self.s.build_legal()
        for item in MASTER['items']:
            self.s.update_legal(item['id'],'적용','검토기록완료','담당자 원문·도면 검토기록: 추가 검증 예정')
        state=self.s.confirm_legal()
        self.assertTrue(state['legal_review']['confirmed_at'])
        self.values['site_address']='파주시 합성동 2';state=self.s.save_values(self.values)
        self.assertTrue(state['legal_review']['outdated'])
        with self.assertRaises(ValueError):self.s.update_legal('C01','적용','검토중','다시 검토')
        with self.assertRaises(ValueError):self.s.confirm_legal()
        self.s.confirm(server.REQUIRED_KEYS)
        res=self.s.build_legal();self.assertIsNone(res['legal_review']['confirmed_at'])
        self.assertEqual(res['legal_review']['items'][0]['progress'],'미착수')
        self.assertFalse(res['legal_review']['outdated'])
    def test_snapshot_stable(self):
        self.assertEqual(snapshot({'b':'2','a':'1'}),snapshot({'a':'1','b':'2'}))
        self.assertNotEqual(snapshot({'a':'1'}),snapshot({'a':'2'}))

class Phase2HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();server.STORE=CaseStore(self.temp.name,server.FIELD_KEYS,server.MASTER['version'])
        self.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://127.0.0.1:{self.http.server_port}'
    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join()
        server.STORE=None;self.temp.cleanup()
    def request(self,path,obj=None):
        data=None if obj is None else json.dumps(obj).encode('utf-8')
        with urllib.request.urlopen(urllib.request.Request(self.base+path,data=data,method='POST' if obj is not None else 'GET'),timeout=7) as r:return json.loads(r.read())
    def test_rest_api_candidates_and_roundtrip(self):
        self.assertEqual(len(self.request('/api/state')['legal_master']['items']),113)
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.request('/api/legal-build',{'init':True})
        self.assertEqual(e.exception.code,400)
        vals={'permit_type':'건축신고','work_type':'증축','site_address':'파주시 합성동 1','primary_use':'단독주택'}
        self.request('/api/save',{'values':vals});self.request('/api/confirm',{'confirm':True})
        res=self.request('/api/legal-build',{'init':True})
        self.assertEqual(len(res['case']['legal_review']['items']),113)
        res=self.request('/api/legal-update',{'id':'C13','applicability':'적용','progress':'검토중','note':'기존 대장 확인'})
        self.assertEqual(next(x for x in res['case']['legal_review']['items'] if x['id']=='C13')['note'],'기존 대장 확인')
        self.assertEqual(next(x for x in res['case']['legal_review']['items'] if x['id']=='C13')['priority'],'우선 확인')
    def test_no_external_calls(self):
        # No endpoints for Phase2 invoke any AI provider.
        original=server.ai_config
        server.ai_config=lambda:{'available':False,'mode':'external','model':'','provider':'gemini'}
        try:
            self.assertEqual(len(self.request('/api/state')['legal_master']['items']),113)
        finally:server.ai_config=original

if __name__=='__main__':unittest.main()
