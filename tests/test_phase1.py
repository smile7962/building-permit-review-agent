"""Run: python -m unittest discover -s tests -v"""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from case_store import CaseStore
from parser import parse_application, extract_lines, ai_available

ROOT = Path(__file__).resolve().parents[1]
MASTER = json.loads((ROOT / 'masters' / 'fields.json').read_text(encoding='utf-8'))
KEYS = {x['key'] for x in MASTER['fields']}
REQUIRED = [x['key'] for x in MASTER['fields'] if x.get('required')]

class Phase1Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = CaseStore(Path(self.temp.name) / 'workspace', KEYS, MASTER['version'])

    def tearDown(self):
        self.temp.cleanup()

    def test_initial_state(self):
        state = self.store.state()
        self.assertFalse(state['values'])
        self.assertFalse(state['confirmed_at'])
        self.assertEqual(state['master_version'], MASTER['version'])

    def test_upload_extract_edit_confirm_export_reopen(self):
        original=(ROOT/'samples'/'sample_application.txt').read_bytes()
        lines, values, sources, method, warning=parse_application('sample_application.txt',original,KEYS)
        self.assertEqual(values['permit_type'],'건축허가')
        self.assertEqual(values['site_area_m2'],'450.00')
        self.assertEqual(values['above_ground_floors'],'2')
        self.assertEqual(values['parking_spaces'],'2')
        state=self.store.add_application('sample_application.txt','test-sha','text/plain',original,lines,values,sources,method)
        self.assertEqual(state['documents'][0]['filename'],'sample_application.txt')
        self.assertEqual(self.store.document(state['documents'][0]['id'])['content'],original)
        values['total_floor_area_m2']='269.20'
        state=self.store.save_values(values)
        self.assertTrue(state['sources']['total_floor_area_m2']['edited_by_user'])
        state=self.store.confirm(REQUIRED)
        self.assertIsNotNone(state['confirmed_at'])
        blob=self.store.export_bytes()
        self.assertTrue(blob.startswith(b'SQLite format 3'))
        self.store.new_case()
        self.assertEqual(self.store.state()['documents'],[])
        restored=self.store.open_case(blob)
        self.assertEqual(restored['values']['total_floor_area_m2'],'269.20')
        self.assertIsNotNone(restored['confirmed_at'])
        self.assertEqual(len(restored['documents']),1)
        values['total_floor_area_m2']='270'
        self.assertIsNone(self.store.save_values(values)['confirmed_at'])

    def test_required_validation(self):
        with self.assertRaises(ValueError): self.store.confirm(REQUIRED)

    def test_bad_case_cannot_replace_active(self):
        initial=self.store.state()['case_id']
        with self.assertRaises(ValueError): self.store.open_case(b'not-an-sqlite-file')
        self.assertEqual(self.store.state()['case_id'],initial)

    def test_invalid_field_rejected(self):
        with self.assertRaises(ValueError): self.store.save_values({'hacked':'yes'})

    def test_source_provenance(self):
        data='신청 구분: 건축신고\n대지 위치: 가상의 소재지\n주용도: 단독주택'.encode()
        lines=extract_lines('test.txt',data)
        _, values, sources, _, _=parse_application('test.txt',data,KEYS)
        self.assertEqual(sources['site_address']['line'],2)
        self.assertEqual(sources['primary_use']['evidence'], '주용도: 단독주택')
        self.assertEqual(values['permit_type'],'건축신고')

if __name__=='__main__': unittest.main()
