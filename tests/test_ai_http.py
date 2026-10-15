"""API integration for opt-in AI draft; no remote calls."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
import server
from case_store import CaseStore

class AiHttpFlow(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        server.STORE=CaseStore(self.tmp.name,server.FIELD_KEYS,server.MASTER['version'])
        self.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True)
        self.thread.start()
        self.base='http://127.0.0.1:'+str(self.http.server_port)

    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join()
        server.STORE=None;self.tmp.cleanup()

    def request(self,path,payload=None,raw=False):
        data=(payload if raw else json.dumps(payload,ensure_ascii=False).encode('utf-8')) if payload is not None else None
        request=urllib.request.Request(self.base+path,data=data,method='POST' if data is not None else 'GET')
        with urllib.request.urlopen(request,timeout=10) as response:
            return response.read()

    def test_no_consent_blocks_model_invocation(self):
        source=(Path(__file__).resolve().parents[1]/'samples/sample_application.txt').read_bytes()
        uploaded=json.loads(self.request('/api/upload?name=sample_application.txt',source,True))['case']
        doc=uploaded['documents'][0]['id']
        with patch.object(server,'compare_ai') as ai:
            with self.assertRaises(urllib.error.HTTPError) as denied:
                self.request('/api/ai-review',{'document_id':doc,'consent':False})
            self.assertEqual(denied.exception.code,400)
            ai.assert_not_called()

    def test_ai_review_comparison_not_automatic_and_case_reopen(self):
        source=(Path(__file__).resolve().parents[1]/'samples/sample_application.txt').read_bytes()
        uploaded=json.loads(self.request('/api/upload?name=sample_application.txt',source,True))['case']
        doc=uploaded['documents'][0]['id']
        def stub(lines,values,keys):
            evidence=next(x for x in lines if x['text'].startswith('대지면적:'))
            return {'run_id':'synthetic-run','model':'offline-stub','mode':'external',
                    'suggestions':{'site_area_m2':{'label':'대지면적','value':'450.00','local_value':'450.00',
                    'status':'일치','verified':True,
                    'source':{'line':evidence['n'],'where':evidence['where'],'evidence':evidence['text'],'method':'AI 분석 제안'}}},
                    'counts':{'same':1,'different':0,'missing':0,'needs_evidence':0}}
        with patch.object(server,'compare_ai',side_effect=stub):
            review=json.loads(self.request('/api/ai-review',{'document_id':doc,'consent':True}))['case']
        self.assertEqual(review['values']['site_area_m2'],'450.00')
        self.assertNotEqual(review['sources']['site_area_m2']['method'],'AI 분석 제안')
        self.assertEqual(review['ai_review']['run_id'],'synthetic-run')
        changed=json.loads(self.request('/api/ai-apply',{'run_id':'synthetic-run','keys':['site_area_m2']}))['case']
        self.assertEqual(changed['sources']['site_area_m2']['method'],'AI 분석 제안')
        exported=self.request('/api/export')
        self.request('/api/new',{})
        restored=json.loads(self.request('/api/open',exported,True))['case']
        self.assertEqual(restored['ai_review']['run_id'],'synthetic-run')

if __name__=='__main__':unittest.main()
