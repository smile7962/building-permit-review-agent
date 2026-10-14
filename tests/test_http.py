"""End-to-end local HTTP checks without third-party test packages."""
import hashlib
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import server
from case_store import CaseStore

ROOT = Path(__file__).resolve().parents[1]

class LocalHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        server.STORE = CaseStore(self.temp.name, server.FIELD_KEYS, server.MASTER['version'])
        self.httpd = ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.httpd.serve_forever,daemon=True)
        self.thread.start()
        self.base=f'http://127.0.0.1:{self.httpd.server_port}'

    def tearDown(self):
        self.httpd.shutdown();self.httpd.server_close();self.thread.join()
        server.STORE=None
        self.temp.cleanup()

    def request(self,path,method='GET',data=None):
        req=urllib.request.Request(self.base+path,data=data,method=method)
        with urllib.request.urlopen(req,timeout=5) as result:
            return result.read(),dict(result.headers)

    def test_home_page_and_static(self):
        body,_=self.request('/')
        self.assertIn('건축ON'.encode(),body)
        js,_=self.request('/static/app.js')
        self.assertIn(b'confirmFields',js)

    def test_http_case_lifecycle(self):
        text=(ROOT/'samples'/'sample_application.txt').read_bytes()
        from urllib.parse import quote
        raw,_=self.request('/api/upload?name='+quote('sample_application.txt'),method='POST',data=text)
        obj=json.loads(raw)
        self.assertEqual(obj['found'],16)
        self.assertEqual(obj['case']['values']['site_area_m2'],'450.00')
        values=obj['case']['values'];values['site_area_m2']='451.00'
        raw,_=self.request('/api/save',method='POST',data=json.dumps({'values':values},ensure_ascii=False).encode())
        self.assertIsNone(json.loads(raw)['case']['confirmed_at'])
        raw,_=self.request('/api/confirm',method='POST',data=b'{}')
        self.assertIsNotNone(json.loads(raw)['case']['confirmed_at'])
        export,headers=self.request('/api/export')
        self.assertTrue(export.startswith(b'SQLite format 3'))
        self.assertIn('.bcase',headers['Content-Disposition'])
        self.request('/api/new',method='POST',data=b'{}')
        raw,_=self.request('/api/open',method='POST',data=export)
        restored=json.loads(raw)['case']
        self.assertEqual(restored['values']['site_area_m2'],'451.00')
        source,_=self.request('/api/document?id='+str(restored['documents'][0]['id']))
        self.assertEqual(source,text)

    def test_rejects_unsupported_document(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.request('/api/upload?name=unexpected.exe',method='POST',data=b'hello')
        self.assertEqual(cm.exception.code,400)

if __name__=='__main__': unittest.main()
