"""Practical-format regression tests. No external Gemini calls or real citizen data."""
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
from parser import parse_application
from practical_benchmark import (FOLDER, GOLD, checked_fixture_bytes,
                                 run_practical_benchmark, verify_details)
from seumteo_details import extract_details


class PracticalFormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(GOLD.read_text(encoding='utf-8'))

    def test_four_fixture_files_with_hashes(self):
        self.assertEqual(len(self.manifest['cases']), 4)
        self.assertEqual({x['file'].split('.')[-1] for x in self.manifest['cases']}, {'pdf', 'xlsx'})
        for entry in self.manifest['cases']:
            self.assertGreater(len(checked_fixture_bytes(entry)), 2000)
            self.assertIn('합성', self.manifest['notice'])

    def test_all_62_core_fields_and_13_detail_checks(self):
        report = run_practical_benchmark(allowed_keys=server.FIELD_KEYS)
        self.assertEqual(report['rules']['summary']['expected_fields'], 62)
        self.assertEqual(report['rules']['summary']['counts']['correct'], 62)
        self.assertEqual(report['rules']['summary']['counts']['empty_correct'], 2)
        self.assertEqual(report['details_summary'], {'correct': 13, 'total': 13})
        self.assertEqual(report['requests_to_model'], 0)
        self.assertFalse(report['real_document_used'])

    def test_pdf_vector_marks_are_exact_and_unmarked_stays_empty(self):
        for name, expected in (('synthetic_permit_house.pdf', '신축'),
                               ('synthetic_notice_extension.pdf', '증축'),
                               ('synthetic_unmarked_permit.pdf', None)):
            raw = (FOLDER/name).read_bytes()
            lines, values, sources, _, _ = parse_application(name, raw, server.FIELD_KEYS)
            self.assertEqual(values.get('work_type'), expected)
            self.assertEqual('work_type' in sources, expected is not None)

    def test_pdf_lot_join_no_personal_address(self):
        p = FOLDER/'synthetic_notice_extension.pdf'
        lines, values, sources, _, _ = parse_application(p.name, p.read_bytes(), server.FIELD_KEYS)
        self.assertEqual(values['site_address'], '경기도 파주시 임시리 23-8')
        self.assertIn('지번', sources['site_address']['evidence'])
        self.assertNotIn('building_count', values)  # source blank, NOT guessed from a building

    def test_xlsx_keeps_cell_indices_and_4_floors(self):
        p = FOLDER/'synthetic_permit_parking.xlsx'
        lines, values, _, _, _ = parse_application(p.name, p.read_bytes(), server.FIELD_KEYS)
        self.assertEqual(values['work_type'], '신축')
        self.assertEqual(values['site_address'], '경기도 파주시 테스트동 88-12')
        self.assertTrue(any('cells' in x for x in lines))
        self.assertEqual(len(extract_details(lines)['floors']), 4)

    def test_extension_areas_not_total_area(self):
        p = FOLDER/'synthetic_notice_extension.pdf'
        lines, values, _, _, _ = parse_application(p.name, p.read_bytes(), server.FIELD_KEYS)
        detail = extract_details(lines)
        self.assertEqual(values['total_floor_area_m2'], '254.30')
        self.assertEqual(detail['buildings'][0]['proposed']['floor_area_m2']['value'], '40.00')
        self.assertEqual([f['existing']['area_m2'] for f in detail['floors']], ['110', '100'])
        self.assertEqual([f['proposed']['area_m2'] for f in detail['floors']], ['25.00', '15.00'])

    def test_modified_checksum_blocks_evaluation(self):
        entry=dict(self.manifest['cases'][0],sha256='0'*64)
        with self.assertRaisesRegex(ValueError, '변경'):
            checked_fixture_bytes(entry)
        with self.assertRaisesRegex(ValueError, '경로'):
            checked_fixture_bytes({**entry, 'file': '../another.pdf'})

    def test_details_grade_catches_floor_mismatch(self):
        expected=self.manifest['cases'][1]['details']
        result=verify_details({'buildings':[{'building_name':'주건축물제1동','proposed':{'floor_area_m2':{'value':'40'}}}],
                               'floors':[{'proposed':{'area_m2':'70'},'existing':{'area_m2':'110'}},
                                         {'proposed':{'area_m2':'15'},'existing':{'area_m2':'100'}}]},expected)
        self.assertLess(result['correct'],result['total'])

    def test_ai_requires_consent_even_with_mocked_config(self):
        with self.assertRaisesRegex(ValueError,'동의'):
            run_practical_benchmark('ai',consent=False)


class PracticalBenchmarkHttp(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        server.STORE=CaseStore(self.temp.name,server.FIELD_KEYS,server.MASTER['version'])
        self.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True)
        self.thread.start()
        self.base=f'http://127.0.0.1:{self.http.server_port}'

    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join()
        server.STORE=None;self.temp.cleanup()

    def post(self, data):
        req=urllib.request.Request(self.base+'/api/practical-benchmark',
                   data=json.dumps(data).encode(),method='POST')
        with urllib.request.urlopen(req,timeout=30) as r:return json.loads(r.read())

    def test_no_case_mutation(self):
        state=server.STORE.state()
        result=self.post({'mode':'rules'})
        self.assertEqual(result['rules']['summary']['counts']['correct'],62)
        self.assertEqual(result['details_summary']['correct'],13)
        self.assertEqual(state['history'],server.STORE.state()['history'])
        self.assertEqual(state['documents'],server.STORE.state()['documents'])

    def test_ai_no_consent_and_invalid_mode(self):
        for mode,consent in (('ai',False),('bad',True)):
            with self.assertRaises(urllib.error.HTTPError) as r:
                self.post({'mode':mode,'consent':consent})
            self.assertEqual(r.exception.code,400)

    def test_ui_serves_practical_buttons(self):
        with urllib.request.urlopen(self.base) as response:
            html=response.read().decode('utf8')
        self.assertIn('practicalRulesButton',html)
        self.assertIn('practicalAiButton',html)


if __name__=='__main__':unittest.main()
