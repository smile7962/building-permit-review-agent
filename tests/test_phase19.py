"""Gemini-default regression tests — mocked API only, no real credentials."""
import json
import os
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import ai_review
import server
from case_store import CaseStore


class GeminiDefaultTests(unittest.TestCase):
    def test_gemini_is_the_default(self):
        with patch.dict(os.environ, {'AI_MODE': 'on', 'GEMINI_API_KEY': 'fake-test'}, clear=True):
            cfg = ai_review.ai_config()
        self.assertTrue(cfg['available'])
        self.assertEqual(cfg['provider'], 'gemini')
        self.assertEqual(cfg['model'], 'gemini-3.1-flash-lite')
        self.assertEqual(cfg['base_url'], ai_review.GEMINI_ENDPOINT)
        self.assertNotIn('fake-test', json.dumps(cfg))

    def test_launcher_gemini_config(self):
        with patch.dict(os.environ, {'AI_MODE': 'on', 'AI_PROVIDER': 'gemini',
                'AI_MODEL': 'gemini-3.1-flash-lite',
                'AI_BASE_URL': 'https://generativelanguage.googleapis.com/v1beta/openai',
                'AI_API_KEY': 'fake-test'}, clear=True):
            self.assertTrue(ai_review.ai_config()['available'])

    def test_off_without_a_key(self):
        with patch.dict(os.environ, {}, clear=True):
            cfg = ai_review.ai_config()
        self.assertFalse(cfg['available'])
        self.assertEqual(cfg['provider'], 'gemini')

    def test_openai_optional(self):
        with patch.dict(os.environ, {'AI_MODE': 'on', 'AI_PROVIDER': 'openai',
                'OPENAI_API_KEY': 'fake-test'}, clear=True):
            cfg = ai_review.ai_config()
        self.assertEqual(cfg['provider'], 'openai')
        self.assertEqual(cfg['model'], 'gpt-4.1-mini')
        self.assertTrue(cfg['available'])

    def test_existing_openai_url_still_works(self):
        with patch.dict(os.environ, {'AI_MODE': 'on',
                'AI_BASE_URL': 'https://api.openai.com/v1',
                'AI_API_KEY': 'fake-test'}, clear=True):
            self.assertEqual(ai_review.ai_config()['provider'], 'openai')

    def test_local_compatible_still_works(self):
        with patch.dict(os.environ, {'AI_MODE': 'on',
                'AI_BASE_URL': 'http://127.0.0.1:11434/v1',
                'AI_MODEL': 'local'}, clear=True):
            cfg = ai_review.ai_config()
        self.assertEqual(cfg['provider'], 'compatible')
        self.assertTrue(cfg['available'])

    def test_mismatched_provider_rejected(self):
        with patch.dict(os.environ, {'AI_MODE': 'on', 'AI_PROVIDER': 'gemini',
                'GEMINI_API_KEY': 'fake-test',
                'AI_BASE_URL': 'https://not-google.example/v1'}, clear=True):
            with self.assertRaisesRegex(ValueError, '일치하지'):
                ai_review.ai_config()
        with self.assertRaisesRegex(ValueError, '공식 서버'):
            ai_review._post_chat_completion({'provider': 'gemini',
                'base_url': 'https://not-google.example/v1', 'model': 'gemini-3.1-flash-lite'},
                {'model': 'test'})

    def test_gemini_ping_does_not_send_documents(self):
        cfg = {'provider':'gemini', 'model':'gemini-3.1-flash-lite',
            'available':True, 'base_url':ai_review.GEMINI_ENDPOINT, 'mode':'external'}
        requests = []
        def response(payload):
            requests.append(payload)
            return {'choices':[{'message':{'content':'PING_OK'}}]}
        report = ai_review.test_ai_connection(cfg, transport=response)
        self.assertTrue(report['connected'])
        self.assertFalse(report['sent_document'])
        self.assertEqual(requests[0]['reasoning_effort'], 'low')
        self.assertNotIn('store', requests[0])
        self.assertNotIn('temperature', requests[0])

    def test_gemini_extract_keeps_original_evidence(self):
        cfg = {'provider':'gemini', 'model':'gemini-3.1-flash-lite',
            'available':True, 'base_url':ai_review.GEMINI_ENDPOINT, 'mode':'external'}
        data = []
        def response(payload):
            data.append(payload)
            return {'choices':[{'message':{'content':json.dumps(
                {'fields':{'site_area_m2':'450.00'},
                 'source_lines':{'site_area_m2':[2]}})}}]}
        lines = [{'n':1, 'text':'[모의 건축허가 신청서]'},
                 {'n':2, 'text':'대지면적: 450.00㎡'}]
        result = ai_review.compare_ai(lines, {'site_area_m2':'500.00'}, {'site_area_m2'},
                                      config=cfg, transport=response)
        self.assertEqual(result['suggestions']['site_area_m2']['status'], '불일치')
        self.assertTrue(result['suggestions']['site_area_m2']['verified'])
        self.assertEqual(data[0]['reasoning_effort'], 'low')

    def test_api_state_redacts_gemini_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            server.STORE = CaseStore(tmp, server.FIELD_KEYS, server.MASTER['version'])
            http = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
            thread = threading.Thread(target=http.serve_forever, daemon=True)
            thread.start()
            try:
                with patch.dict(os.environ, {'AI_MODE': 'on',
                                            'GEMINI_API_KEY': 'secret-test'}, clear=True):
                    with urllib.request.urlopen(
                        f'http://127.0.0.1:{http.server_port}/api/state', timeout=5) as resp:
                        data = resp.read().decode('utf-8')
                self.assertEqual(json.loads(data)['ai_provider'], 'gemini')
                self.assertNotIn('secret-test', data)
            finally:
                http.shutdown()
                http.server_close()
                thread.join()
                server.STORE = None


if __name__ == '__main__':
    unittest.main()
