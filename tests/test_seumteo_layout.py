"""Synthetic-only regression tests. Never commit actual application data."""
import unittest
from seumteo_layout import parse_seumteo
from xls_legacy import read_xls_cells

KEYS = {'permit_type', 'work_type', 'site_area_m2', 'building_area_m2',
        'total_floor_area_m2', 'building_coverage_percent', 'floor_area_ratio_percent',
        'primary_use', 'parking_spaces', 'site_address', 'zoning', 'structure',
        'above_ground_floors', 'underground_floors', 'building_count'}


def line(n, text, where='1쪽', cells=None):
    row = {'n':n,'text':text,'where':where}
    if cells is not None:
        row['cells'] = [{'col': i * 3, 'text': c} for i, c in enumerate(cells)]
    return row


class TestSeumteoForm(unittest.TestCase):
    def test_pdf_summary_preferred_over_building_area(self):
        lines = [
            line(1, '건축ㆍ대수선ㆍ용도변경 (변경)허가 신청서'),
            line(2, 'Ⅰ. 전체 개요'),
            line(3, '대지면적 400 ㎡ 건축면적 100 ㎡'),
            line(4, '건폐율 25 ％ 연면적 합계 250 ㎡'),
            line(5, '연면적 합계(용적률 산정용) 240 ㎡ 용적률 60 ％'),
            line(6, '⑤주용도'), line(7, '단독주택'),
            line(8, '총 주차대수'), line(9, '2 대'),
            line(10, '용도지역'), line(11, '제1종일반주거지역'),
            line(12, '※ 연면적(㎡) 25', '3쪽')
        ]
        values, src = parse_seumteo(lines, KEYS)
        self.assertEqual(values['permit_type'], '건축허가')
        self.assertEqual(values['site_area_m2'], '400')
        self.assertEqual(values['building_area_m2'], '100')
        self.assertEqual(values['total_floor_area_m2'], '250')
        self.assertEqual(values['floor_area_ratio_percent'], '60')
        self.assertEqual(values['parking_spaces'], '2')
        self.assertEqual(values['zoning'], '제1종일반주거지역')
        self.assertEqual(src['total_floor_area_m2']['where'], '1쪽')
        self.assertNotIn('work_type', values)

    def test_xls_cells_summary_and_proposed_structure(self):
        lines = [
            line(1, '건축ㆍ대수선ㆍ용도변경 (변경)신고서', 'Page 1 1행'),
            line(2, '대지면적 | 450 | ㎡ | 건축면적 | 130 | ㎡', 'Page 1 41행',
                 ['대지면적','450','㎡','건축면적','130','㎡']),
            line(3, '건폐율 | 28.89 | 연면적 합계 | 268.20', 'Page 1 42행',
                 ['건폐율','28.89','연면적 합계','268.20']),
            line(4, '⑤주용도 | 단독주택 | 총 주차대수 | 2 | 대', 'Page 1 45행',
                 ['⑤주용도','단독주택','총 주차대수','2','대']),
            line(5, '주구조 | 철근콘크리트구조', 'Page 3 14행', ['주구조','철근콘크리트구조']),
            line(6, '층수 | 지하 : | 층 | 지상 : | 2 | 층', 'Page 3 22행',
                 ['층수','지하 :','층','지상 :','2','층'])
        ]
        values, _ = parse_seumteo(lines, KEYS)
        self.assertEqual(values['permit_type'], '건축신고')
        self.assertEqual(values['site_area_m2'], '450')
        self.assertEqual(values['total_floor_area_m2'], '268.20')
        self.assertEqual(values['structure'], '철근콘크리트구조')
        self.assertEqual(values['above_ground_floors'], '2')

    def test_corrupted_xls_fails_closed(self):
        with self.assertRaises(ValueError):
            list(read_xls_cells(b'not an xls'))

if __name__ == '__main__':
    unittest.main()
