import unittest
from parser import parse_application

KEYS = {'permit_type','work_type','site_address','site_area_m2','building_area_m2',
        'total_floor_area_m2','building_coverage_percent','floor_area_ratio_percent',
        'primary_use','structure','above_ground_floors','underground_floors',
        'building_count','parking_spaces','zoning','notes'}

class ParserPhase11(unittest.TestCase):
    def parse(self, body):
        _, values, sources, method, warning = parse_application('demo.txt', body.encode(), KEYS)
        self.assertFalse(warning)
        return values, sources

    def test_labelled_number_with_units(self):
        values, sources = self.parse('대지면적(㎡) 1,234.56\n건축면적: 123.40㎡\n지상층수 2층')
        self.assertEqual(values['site_area_m2'], '1234.56')
        self.assertEqual(values['building_area_m2'], '123.40')
        self.assertEqual(values['above_ground_floors'], '2')
        self.assertEqual(sources['site_area_m2']['line'], 1)

    def test_table_fragments(self):
        values, _ = self.parse('건축 구분: 신축 | 주용도: 단독주택 | 구조: 철근콘크리트구조')
        self.assertEqual(values['work_type'], '신축')
        self.assertEqual(values['primary_use'], '단독주택')
        self.assertEqual(values['structure'], '철근콘크리트구조')

    def test_no_inference_from_heading(self):
        values, _ = self.parse('건축허가(신고) 신청서\n비고: 건축허가 신고 처리방법')
        self.assertNotIn('permit_type', values)

    def test_ambiguous_permit_field(self):
        values, _ = self.parse('신청 구분: 건축허가·신고')
        self.assertNotIn('permit_type', values)

    def test_no_numeric_guess(self):
        values, _ = self.parse('연면적: 검토중 2026년\n주차대수: 산정전 4대')
        self.assertNotIn('total_floor_area_m2', values)
        self.assertNotIn('parking_spaces', values)

    def test_source_trace(self):
        values, sources = self.parse('대지 위치: 파주시 모의동 11\n연면적: 200㎡')
        self.assertEqual(sources['total_floor_area_m2']['evidence'], '연면적: 200㎡')
        self.assertEqual(sources['site_address']['line'], 1)

if __name__ == '__main__':
    unittest.main()
