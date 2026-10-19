"""Phase 2 regression tests for reviewer-controlled legal checklist."""
import json
import tempfile
import unittest
import urllib.error
import urllib.request
import threading
from http.server import ThreadingHTTPServer

import server
from case_store import CaseStore
from legal_review import build, priority, MASTER, snapshot


class Phase2Core(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=CaseStore(self.tmp.name,server.FIELD_KEYS,server.MASTER['version'])
        self.values={'permit_type':'건축허가','work_type':'신축',
                     'site_address':'파주시 합성동 1','primary_use':'단독주택'}
        self.store.save_values(self.values)

    def tearDown(self):self.tmp.cleanup()

    def test_14_candidates_not_legal_decisions(self):
        data=build(self.values)
        self.assertEqual(len(data['items']),14)
        self.assertTrue(all(x['applicability']=='미확인' and x['progress']=='미착수' for x in data['items']))

    def test_priority_only_not_exemption(self):
        item=next(x for x in MASTER['items'] if x['id']=='C08')
        self.assertEqual(priority(item,{'zoning':'일반주거지역'}),'우선 확인')
        self.assertEqual(priority(item,{'zoning':'계획관리지역'}),'적용 여부 확인')

    def test_requires_phase1_confirmation(self):
        with self.assertRaisesRegex(ValueError,'STEP 01'):self.store.build_legal()

    def test_invalid_decisions_blocked(self):
        self.store.confirm(server.REQUIRED_KEYS);self.store.build_legal()
        for args in [('C01','비적용','미착수',''),
                     ('C01','미확인','검토기록완료','x'),
                     ('C01','적법','검토기록완료','x'),
                     ('C99','적용','검토중','')]:
            with self.assertRaises(ValueError):self.store.update_legal(*args)

    def test_build_edit_export_reopen(self):
        self.store.confirm(server.REQUIRED_KEYS);self.store.build_legal()
        data=self.store.update_legal('C01','적용','검토중','담당자가 조항 원문 확인 중')
        self.assertEqual(data['legal_review']['items'][0]['note'],'담당자가 조항 원문 확인 중')
        blob=self.store.export_bytes();self.store.new_case()
        back=self.store.open_case(blob)
        self.assertEqual(back['legal_review']['items'][0]['applicability'],'적용')

    def test_completion_requires_every_item(self):
        self.store.confirm(server.REQUIRED_KEYS);self.store.build_legal()
        with self.assertRaisesRegex(ValueError,'미완료'):self.store.confirm_legal()
        for row in MASTER['items']:
            self.store.update_legal(row['id'],'적용','검토기록완료','담당자가 원문과 도면 대조')
        self.assertTrue(self.store.confirm_legal()['legal_review']['confirmed_at'])

    def test_edit_invalidates_review(self):
        self.store.confirm(server.REQUIRED_KEYS);self.store.build_legal()
        self.values['site_address']='파주시 합성동 2'
        data=self.store.save_values(self.values)
        self.assertTrue(data['legal_review']['outdated'])
        with self.assertRaises(ValueError):self.store.confirm_legal()
        self.store.confirm(server.REQUIRED_KEYS)
        self.assertFalse(self.store.build_legal()['legal_review']['outdated'])

    def test_hash_is_order_independent(self):
        self.assertEqual(snapshot({'a':'1','b':'2'}),snapshot({'b':'2','a':'1'}))


class Phase2Http(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        server.STORE=CaseStore(self.tmp.name,server.FIELD_KEYS,server.MASTER['version'])
        self.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True)
        self.thread.start()
        self.url='http://127.0.0.1:'+str(self.http.server_port)

    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join()
        server.STORE=None;self.tmp.cleanup()

    def call(self,route,payload=None):
        raw=None if payload is None else json.dumps(payload).encode('utf-8')
        req=urllib.request.Request(self.url+route,data=raw,
                                   method='POST' if raw is not None else 'GET')
        with urllib.request.urlopen(req,timeout=8) as r:return json.loads(r.read())

    def test_http_lifecycle(self):
        self.assertEqual(len(self.call('/api/state')['legal_master']['items']),14)
        with self.assertRaises(urllib.error.HTTPError):
            self.call('/api/legal-build',{'init':True})
        self.call('/api/save',{'values':{'permit_type':'건축신고','work_type':'증축',
            'site_address':'파주시 합성동 10','primary_use':'단독주택'}})
        self.call('/api/confirm',{'confirm':True})
        self.assertEqual(len(self.call('/api/legal-build',{'init':True})['case']['legal_review']['items']),14)
        result=self.call('/api/legal-update',{'id':'C13','applicability':'적용',
                                              'progress':'검토중','note':'기존 대장 확인'})
        item=next(x for x in result['case']['legal_review']['items'] if x['id']=='C13')
        self.assertEqual(item['priority'],'우선 확인')
        self.assertEqual(item['note'],'기존 대장 확인')


if __name__=='__main__':unittest.main()
