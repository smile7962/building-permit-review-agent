"""Phase 1.8 regression tests — mocked transport, no real credentials or network."""
import hashlib
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
from ai_review import ai_config, _call_llm, _post_chat_completion, test_ai_connection
from case_store import CaseStore
from synthetic_gate import EXPECTED_SHA256, is_approved_fixture, require_approved_fixture, require_bundled_fixture_integrity

ROOT = Path(__file__).resolve().parents[1]
REMOTE = {'available': True, 'model': 'test-model', 'mode': 'external', 'base_url': 'https://api.openai.com/v1'}


class RealApiSafeTests(unittest.TestCase):
    def test_only_exact_bundled_bytes(self):
        data = (ROOT / 'samples' / 'sample_application.txt').read_bytes()
        self.assertTrue(is_approved_fixture(data))
        self.assertIn(hashlib.sha256(data).hexdigest(), EXPECTED_SHA256)
        for altered in (data + b'\n', b'fake'):
            self.assertFalse(is_approved_fixture(altered))
            with self.assertRaisesRegex(ValueError, '차단'):
                require_approved_fixture(altered)
        require_bundled_fixture_integrity()

    def test_connection_fixed_text_only_and_no_storage(self):
        seen = []
        def fake(payload):
            seen.append(payload)
            return {'choices': [{'message': {'content': 'PING_OK'}}],
                    'usage': {'total_tokens': 37}}
        result = test_ai_connection(REMOTE, transport=fake)
        self.assertTrue(result['connected'])
        self.assertFalse(result['sent_document'])
        self.assertEqual(result['requests'], 1)
        self.assertEqual(result['usage_tokens'], 37)
        self.assertFalse(seen[0]['store'])
        self.assertEqual(seen[0]['max_completion_tokens'], 40)
        self.assertNotIn('temperature', seen[0])
        self.assertNotIn('대지위치', str(seen[0]))

    def test_missing_or_empty_provider_response(self):
        with self.assertRaisesRegex(ValueError, '형식'):
            test_ai_connection(REMOTE, transport=lambda _: {'choices': []})
        with self.assertRaisesRegex(ValueError, '비어'):
            test_ai_connection(REMOTE, transport=lambda _: {'choices': [{'message': {'content': ''}}]})

    def test_extract_request_compatible_with_new_models(self):
        payloads = []
        def fake(payload):
            payloads.append(payload)
            return {'choices': [{'message': {'content': '{}'}}]}
        _call_llm(REMOTE, [{'id': 1, 'text': '[모의] 건축 구분: 신축'}],
                  {'work_type'}, transport=fake)
        self.assertNotIn('temperature', payloads[0])
        self.assertEqual(payloads[0]['max_completion_tokens'], 2500)
        self.assertIs(payloads[0]['store'], False)

    def test_failure_status_redacted(self):
        import io
        def unauthorized(_):
            raise urllib.error.HTTPError('https://api.openai.com/v1/chat/completions',
                401, 'hidden key=sk-secret', {}, io.BytesIO(b'{"error":"sk-secret"}'))
        with patch('ai_review._no_redirect_request', side_effect=unauthorized):
            with self.assertRaisesRegex(ValueError, 'API 키') as result:
                test_ai_connection(REMOTE)
            self.assertNotIn('sk-secret', str(result.exception))

    def test_connection_url_rejects_http_external(self):
        with self.assertRaisesRegex(ValueError, 'HTTPS'):
            _post_chat_completion({**REMOTE, 'base_url': 'http://example.org/v1'},
                                  {'model': 'test-model'})

    def test_no_credentials_returned_from_config(self):
        with patch.dict('os.environ', {'AI_MODE': 'on', 'AI_MODEL': 'gpt-4.1-mini',
                     'AI_API_KEY': 'sk-secret', 'AI_BASE_URL': 'https://api.openai.com/v1'}):
            config = ai_config()
        self.assertTrue(config['available'])
        self.assertNotIn('sk-secret', json.dumps(config))


class ConnectionHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        server.STORE = CaseStore(self.temp.name, server.FIELD_KEYS, server.MASTER['version'])
        self.web = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.thread = threading.Thread(target=self.web.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.web.server_port)

    def tearDown(self):
        self.web.shutdown(); self.web.server_close(); self.thread.join()
        server.STORE = None; self.temp.cleanup()

    def post(self, path, data):
        req = urllib.request.Request(self.url + path, data=json.dumps(data).encode(),
                                      method='POST')
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    def test_connection_no_consent_or_documents(self):
        with self.assertRaises(urllib.error.HTTPError) as ex:
            self.post('/api/ai-connect-test', {'consent': False})
        self.assertEqual(ex.exception.code, 400)
        before = server.STORE.state()
        with patch.object(server, 'test_ai_connection', return_value={
                  'connected': True, 'model': 'fake', 'sent_document': False, 'requests': 1}):
            result = self.post('/api/ai-connect-test', {'consent': True})
        self.assertTrue(result['result']['connected'])
        self.assertEqual(before['history'], server.STORE.state()['history'])
        self.assertEqual(before['documents'], server.STORE.state()['documents'])

    def test_external_ai_review_blocks_tagged_but_unauthorized_document(self):
        content = '[모의 건축허가 신청서]\n대지면적: 900㎡\n'.encode('utf-8')
        req = urllib.request.Request(self.url + '/api/upload?name=fake.txt',
                                     data=content, method='POST')
        with urllib.request.urlopen(req, timeout=10) as resp:
            doc = json.loads(resp.read())['case']['documents'][0]
        with patch.object(server, 'ai_config', return_value=REMOTE), \
             patch.object(server, 'compare_ai', side_effect=AssertionError('must not transmit')):
            with self.assertRaises(urllib.error.HTTPError) as ex:
                self.post('/api/ai-review', {'consent': True, 'document_id': doc['id']})
            self.assertEqual(ex.exception.code, 400)
            self.assertIn('전송 차단', ex.exception.read().decode('utf-8'))

    def test_state_only_model_not_key(self):
        with patch.dict('os.environ', {'AI_MODE': 'on', 'AI_MODEL': 'gpt-4.1-mini',
                    'AI_API_KEY': 'sk-secret', 'AI_BASE_URL': 'https://api.openai.com/v1'}):
            with urllib.request.urlopen(self.url + '/api/state') as resp:
                data = resp.read().decode('utf-8')
        self.assertNotIn('sk-secret', data)
        self.assertIn('gpt-4.1-mini', data)


if __name__ == '__main__':
    unittest.main()
