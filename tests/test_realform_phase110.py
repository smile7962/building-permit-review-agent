"""Synthetic PDF layout regression tests; no external Gemini call."""
import unittest
from pathlib import Path
from realform_benchmark import run_realform_benchmark
from parser import parse_application
from server import FIELD_KEYS

ROOT=Path(__file__).resolve().parents[1]

class RealFormFixtureTest(unittest.TestCase):
    def test_pdf_score(self):
        report=run_realform_benchmark(FIELD_KEYS)
        self.assertEqual(report['summary']['cases'],2)
        self.assertEqual(report['summary']['expected_fields'],29)
        self.assertEqual(report['summary']['counts']['correct'],27)
        self.assertEqual(report['summary']['counts']['missing'],2)

    def test_lot_and_count(self):
        p=ROOT/'benchmarks/realform/permit_checkmark.pdf'
        _,v,s,*_=parse_application(p.name,p.read_bytes(),FIELD_KEYS)
        self.assertEqual(v['site_address'],'경기도 파주시 합성동 101-7')
        self.assertEqual(v['building_count'],'1')
        self.assertEqual(s['site_address']['method'],'대지위치·명시 지번 결합')

    def test_extension_preserves_overall_area(self):
        p=ROOT/'benchmarks/realform/extension_overall.pdf'
        _,v,_,*_=parse_application(p.name,p.read_bytes(),FIELD_KEYS)
        self.assertEqual(v['total_floor_area_m2'],'254.30')
        self.assertNotIn('building_count',v)
        self.assertNotIn('work_type',v)
