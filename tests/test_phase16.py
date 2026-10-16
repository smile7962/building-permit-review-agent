"""Tests for synthetic-only offline comparison; no external LLM calls."""
import hashlib
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import server
from case_store import CaseStore
from demo_review import DEMO_FILE, compare_synthetic_demo
from parser import parse_application


class OfflineDemoTests(unittest.TestCase):
    def setUp(self):
        self.raw = DEMO_FILE.read_bytes()
        self.lines, self.values, _, _, _ = parse_application(
            DEMO_FILE.name, self.raw, server.FIELD_KEYS)

    def test_16_fixture_values_grounded(self):
        result = compare_synthetic_demo(
            self.raw, self.lines, self.values, server.FIELD_KEYS)
        self.assertEqual(result['counts'], dict(
            same=16, different=0, missing=0, needs_evidence=0))
        self.assertEqual(result['mode'], 'demo')
        self.assertIn('실제 AI 아님', result['model'])
        self.assertTrue(all(x['verified'] for x in result['suggestions'].values()))

    def test_mismatch_missing_no_external_network(self):
        revised = {**self.values, 'site_area_m2': '500', 'parking_spaces': ''}
        with patch('ai_review._no_redirect_request',
                   side_effect=AssertionError('external network prohibited')):
            result = compare_synthetic_demo(
                self.raw, self.lines, revised, server.FIELD_KEYS)
        self.assertEqual(result['suggestions']['site_area_m2']['status'], '불일치')
        self.assertEqual(result['suggestions']['parking_spaces']['status'], 'AI만 제안')
        self.assertEqual(result['suggestions']['site_area_m2']['value'], '450.00')
        self.assertEqual(revised['site_area_m2'], '500')

    def test_reject_changed_document_even_named_like_fixture(self):
        with self.assertRaisesRegex(ValueError, '제공된'):
            compare_synthetic_demo(
                self.raw + b'\n', self.lines, self.values, server.FIELD_KEYS)

    def test_explicit_non_ai_provenance(self):
        result = compare_synthetic_demo(
            self.raw, self.lines, self.values, server.FIELD_KEYS)
        self.assertIn('실제 AI 아님',
                      result['suggestions']['site_area_m2']['source']['method'])
        self.assertIn('실제 LLM을 호출하지', result['notice'])


class DemoHttpFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        server.STORE = CaseStore(
            self.tmp.name, server.FIELD_KEYS, server.MASTER['version'])
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.thread = threading.Thread(
            target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.http.server_port)

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        server.STORE = None
        self.tmp.cleanup()

    def request(self, path, payload=None, raw=False):
        if payload is None:
            data = None
        elif raw:
            data = payload
        else:
            data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(
            self.base + path, data=data,
            method='POST' if data is not None else 'GET')
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read()

    def test_http_comparison_apply_export_reopen(self):
        initial = json.loads(self.request(
            '/api/upload?name=sample_application.txt',
            DEMO_FILE.read_bytes(), True))['case']
        doc_id = initial['documents'][0]['id']
        changed = {**initial['values'], 'site_area_m2': '500.00',
                   'parking_spaces': ''}
        self.request('/api/save', {'values': changed})
        with patch.object(server, 'compare_ai',
                          side_effect=AssertionError('real AI must not run')):
            draft = json.loads(self.request(
                '/api/demo-review', {'document_id': doc_id}))['case']
        review = draft['ai_review']
        self.assertEqual(draft['values']['site_area_m2'], '500.00')
        self.assertEqual(review['mode'], 'demo')
        self.assertEqual(review['counts']['different'], 1)
        self.assertEqual(review['counts']['missing'], 1)
        applied = json.loads(self.request(
            '/api/ai-apply', {'run_id': review['run_id'],
                              'keys': ['site_area_m2', 'parking_spaces']}))['case']
        self.assertEqual(applied['values']['site_area_m2'], '450.00')
        self.assertEqual(applied['values']['parking_spaces'], '2')
        self.assertIn('실제 AI 아님',
                      applied['sources']['site_area_m2']['method'])
        data = self.request('/api/export')
        self.request('/api/new', {})
        restored = json.loads(self.request('/api/open', data, True))['case']
        self.assertEqual(restored['ai_review']['mode'], 'demo')
        self.assertEqual(restored['values']['site_area_m2'], '450.00')
        self.assertTrue(any('모의' in h['detail'] for h in restored['history']))

    def test_http_reject_non_fixture(self):
        fake = '[모의 건축허가 신청서]\n대지면적: 999㎡\n'.encode()
        case = json.loads(self.request(
            '/api/upload?name=other.txt', fake, True))['case']
        doc_id = case['documents'][0]['id']
        with self.assertRaises(urllib.error.HTTPError) as exc:
            self.request('/api/demo-review', {'document_id': doc_id})
        self.assertEqual(exc.exception.code, 400)
        self.assertIn('samples/sample_application.txt',
                      exc.exception.read().decode())

    def test_state_exposes_fixture_digest(self):
        state = json.loads(self.request('/api/state'))
        self.assertEqual(state['demo_sha256'],
                         hashlib.sha256(DEMO_FILE.read_bytes()).hexdigest())

    def test_http_reject_when_no_document(self):
        with self.assertRaises(urllib.error.HTTPError) as exc:
            self.request('/api/demo-review', {'document_id': 1})
        self.assertEqual(exc.exception.code, 400)


if __name__ == '__main__':
    unittest.main()
