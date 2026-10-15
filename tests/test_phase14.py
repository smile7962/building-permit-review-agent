"""Synthetic-only parser regressions for Phase 1.4 (no real application data)."""
import types
import unittest
from unittest.mock import patch
from pdf_vectors import checked_work_type as pdf_mark
from xls_markers import _option_for_anchor
from seumteo_layout import parse_seumteo
from seumteo_details import selected_work_type

KEYS={'site_address','building_count','work_type','permit_type'}


def line(n, text, where='1쪽'):
    return {'n':n,'text':text,'where':where}


class FakePdf:
    pdf=None
    def get_contents(self):
        return b''
    def extract_text(self, visitor_text=None):
        def word(t,x,y):
            for i,c in enumerate(t):
                visitor_text(c,[1,0,0,1,0,0],[1,0,0,1,x+i*8,y],None,10)
        word('건축구분',56,667)
        for label,x in [('신축',141),('증축',221),('개축',289),
                        ('재축',357),('이전',425),('대수선',496)]:
            word(label,x,680)


def tick(x,y):
    return [([x,y],b'm'),([x+5.1,y],b'l'),([x+5.1,y+5.1],b'l'),
            ([x,y+5.1],b'l'),([],b'h'),([],b'f')]


class Phase14Tests(unittest.TestCase):
    def pdf(self, shapes):
        with patch('pypdf.generic.ContentStream',
                   return_value=types.SimpleNamespace(operations=shapes)):
            return pdf_mark(FakePdf())

    def test_pdf_single_checked_vector(self):
        self.assertEqual(self.pdf(tick(201.5,682))['value'],'증축')

    def test_pdf_no_tick_is_not_selected(self):
        self.assertIsNone(self.pdf([]))

    def test_pdf_multiple_ticks_are_not_selected(self):
        self.assertIsNone(self.pdf(tick(121.5,682)+tick(201.5,682)))

    def test_pdf_unrelated_drawing_is_not_selected(self):
        self.assertIsNone(self.pdf(tick(201.5,555)))

    def test_xls_picture_between_box_and_label(self):
        cells=[{'col':0,'text':'건축구분'},{'col':3,'text':'[  ]'},
               {'col':6,'text':'신축'},{'col':11,'text':'[  ]'},
               {'col':12,'text':'증축'}]
        self.assertEqual(_option_for_anchor(cells,(4,5,9,10)),['신축'])

    def test_xls_unrelated_picture_is_ignored(self):
        cells=[{'col':3,'text':'[  ]'},{'col':6,'text':'신축'}]
        self.assertEqual(_option_for_anchor(cells,(20,22,9,10)),[])

    def test_xls_overlapping_option_is_ignored(self):
        cells=[{'col':3,'text':'[  ]'},{'col':6,'text':'신축'}]
        self.assertEqual(_option_for_anchor(cells,(6,7,9,10)),[])

    def test_graphic_source_is_labelled(self):
        got=selected_work_type([line(1,'건축구분: 신축','1쪽 · PDF 벡터 체크표시')])
        self.assertEqual(got['value'],'신축')
        self.assertIn('벡터',got['source']['where'])

    def test_pdf_lot_join(self):
        values,sources=parse_seumteo([line(1,'대지위치 경기도 모의시 시험동'),
                 line(2,'지번'),line(3,'123 - 4'),line(4,'관련지번')],KEYS)
        self.assertEqual(values['site_address'],'경기도 모의시 시험동 123-4')

    def test_related_lot_not_mistaken(self):
        values,_=parse_seumteo([line(1,'대지위치 경기도 모의시 시험동'),
                    line(2,'지번'),line(3,'관련지번'),line(4,'345')],KEYS)
        self.assertEqual(values['site_address'],'경기도 모의시 시험동')

    def test_first_page_building_count(self):
        values,_=parse_seumteo([line(1,'Ⅰ. 전체 개요'),
              line(2,'④건축물명칭 가상건물 주건축물수 2 동 부속건축물 0 동')],KEYS)
        self.assertEqual(values['building_count'],'2')

    def test_blank_count_must_remain_missing(self):
        values,_=parse_seumteo([line(1,'Ⅰ. 전체 개요'),
                    line(2,'④건축물명칭 건물 주건축물수 동 부속건축물 동 0 ㎡'),
                    line(3,'주건축물제1동','3쪽')],KEYS)
        self.assertNotIn('building_count',values)

    def test_applicant_address_not_used_for_site(self):
        values,_=parse_seumteo([line(1,'건축주 주소: 경기도 모의시 사람동 55-1'),
            line(2,'대지위치 경기도 모의시 실제동'),line(3,'지번'),line(4,'100')],KEYS)
        self.assertEqual(values['site_address'],'경기도 모의시 실제동 100')


if __name__=='__main__':unittest.main()
