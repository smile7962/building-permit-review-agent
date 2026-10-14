"""Synthetic-only Phase 1.3 checks. Do not commit any citizen's application."""
import hashlib
import tempfile
import unittest

from case_store import CaseStore
from seumteo_details import extract_details, selected_work_type


def line(i,text,where='1쪽',cells=None):
    d={'n':i,'text':text,'where':where}
    if cells is not None:
        d['cells']=[{'col':k,'text':v} for k,v in cells]
    return d


class Phase13Tests(unittest.TestCase):
    def test_explicit_checked_box(self):
        source=[line(1,'건축구분'),line(2,'[ ] 신축 [√] 증축 [ ] 개축')]
        self.assertEqual(selected_work_type(source)['value'],'증축')

    def test_unmarked_cannot_infer(self):
        source=[line(1,'건축구분'),line(2,'[ ] 신축 [ ] 증축'),
                line(3,'1 증축 철근콘크리트')]
        self.assertIsNone(selected_work_type(source))

    def test_multiple_marks_cannot_infer(self):
        source=[line(1,'건축구분'),line(2,'[x] 신축 [x] 증축')]
        self.assertIsNone(selected_work_type(source))

    def test_xls_buildings_and_floor_rows_are_separate(self):
        rows=[line(1,'Ⅱ. 동별 개요','Page 3 1행'),
              line(2,'⑦동명칭 및 번호 | 주건축물제1동','Page 3 2행',[(8,'⑦동명칭 및 번호'),(10,'주건축물제1동')]),
              line(3,'※ 연면적(㎡) | 150','Page 3 3행',[(8,'※ 연면적(㎡)'),(10,'150')]),
              line(4,'Ⅱ. 동별 개요','Page 4 1행'),
              line(5,'⑦동명칭 및 번호 | 주건축물제2동','Page 4 2행',[(8,'⑦동명칭 및 번호'),(10,'주건축물제2동')]),
              line(6,'※ 연면적(㎡) | 90','Page 4 3행',[(8,'※ 연면적(㎡)'),(10,'90')]),
              line(7,'Ⅲ. 층별 개요','Page 5 1행'),
              line(8,'동 명칭 및 번호 (주건축물제1동)','Page 5 2행'),
              line(9,'1 | 신축 | 철근콘크리트구조 | 단독주택 | 150','Page 5 3행',[(4,'1'),(5,'신축'),(6,'철근콘크리트구조'),(7,'단독주택'),(8,'150')]),
              line(10,'동 명칭 및 번호 (주건축물제2동)','Page 5 4행'),
              line(11,'1 | 신축 | 철근콘크리트구조 | 근린생활시설 | 90','Page 5 5행',[(4,'1'),(5,'신축'),(6,'철근콘크리트구조'),(7,'근린생활시설'),(8,'90')])]
        details=extract_details(rows)
        self.assertEqual(len(details['buildings']),2)
        self.assertEqual([x['proposed']['floor_area_m2']['value'] for x in details['buildings']],['150','90'])
        self.assertEqual([x['proposed']['area_m2'] for x in details['floors']],['150','90'])
        self.assertEqual(details['floors'][1]['building_name'],'주건축물제2동')

    def test_pdf_existing_vs_increase(self):
        rows=[line(1,'Ⅱ. 동별 개요','3쪽'),
              line(2,'주건축물제1동 ⑦동명칭 및 번호 주건축물제1동','3쪽'),
              line(3,'260 ※ 건축면적(㎡) 270.92','3쪽'),
              line(4,'480.96 ※ 연면적(㎡) 51.81','3쪽'),
              line(5,'Ⅲ. 층별 개요','4쪽'),
              line(6,'동 명칭 및 번호(주건축물제1동)','4쪽'),
              line(7,'단독주택) 260 1 증축 경량철골구조','4쪽'),
              line(8,'외부계단) 8.32','4쪽'),
              line(9,'2 증축 철근콘크리트구조','4쪽'),
              line(10,'소매점(테라스) 39.03','4쪽')]
        details=extract_details(rows)
        self.assertEqual(details['buildings'][0]['existing']['floor_area_m2']['value'],'480.96')
        self.assertEqual(details['buildings'][0]['proposed']['floor_area_m2']['value'],'51.81')
        self.assertEqual(details['floors'][0]['existing']['area_m2'],'260')
        self.assertEqual(details['floors'][0]['proposed']['area_m2'],'8.32')
        self.assertTrue(details['floors'][0]['review_required'])

    def test_unsupported_without_detail(self):
        self.assertEqual(extract_details([line(1,'모의건축개요')])['floors'],[])

    def test_patch_save_and_reopen_case(self):
        with tempfile.TemporaryDirectory() as d:
            store=CaseStore(d,{'work_type','site_address'},'demo')
            lines=[line(1,'Ⅱ. 동별 개요','3쪽'),line(2,'주건축물제1동 ⑦동명칭 및 번호 주건축물제1동','3쪽'),
                   line(3,'480.96 ※ 연면적(㎡) 51.81','3쪽')]
            details=extract_details(lines)
            original=b'SYNTHETIC test document'
            store.add_application('synthetic.pdf',hashlib.sha256(original).hexdigest(),
                'application/pdf',original,lines,{'site_address':'모의동 12'}, {},'규칙 기반',details)
            confirmed_doc=store.state()['application_details']
            self.assertEqual(confirmed_doc['buildings'][0]['proposed']['floor_area_m2']['value'],'51.81')
            self.assertEqual(confirmed_doc['buildings'][0]['source']['document_id'],1)
            store.save_values({'site_address':'모의동 12','work_type':'증축'})
            store.confirm(['site_address','work_type'])
            updated=store.patch_detail('buildings',0,'proposed','floor_area_m2','51.82')
            self.assertIsNone(updated['confirmed_at'])
            self.assertTrue(updated['application_details']['buildings'][0]['proposed']['floor_area_m2']['edited_by_user'])
            bcase=store.export_bytes()
            store.new_case()
            restored=store.open_case(bcase)
            self.assertEqual(restored['application_details']['buildings'][0]['proposed']['floor_area_m2']['value'],'51.82')
            self.assertEqual(store.document(1)['content'],original)

    def test_invalid_detail_write(self):
        with tempfile.TemporaryDirectory() as d:
            store=CaseStore(d,{'work_type'},'demo')
            with self.assertRaises(ValueError):store.patch_detail('buildings',0,'proposed','unknown','1')

if __name__=='__main__':unittest.main()
