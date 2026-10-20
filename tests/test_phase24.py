"""Phase 2.4 drawing/criteria/human decision roundtrip tests; no external API."""
import tempfile
import unittest
from case_store import CaseStore
from review_guidance import EXAMPLES,validate_verification
from review_report import preview
import server

VALUES={'permit_type':'건축허가','work_type':'신축','site_address':'파주시 모의동 1',
    'primary_use':'단독주택','zoning':'계획관리지역','site_area_m2':'450',
    'building_area_m2':'130','parking_spaces':'2','total_floor_area_m2':'268.20'}
EVIDENCE={'road_frontage_m':'1.5','road_status':'확인됨',
    'legal_coverage_max_pct':'20','legal_far_max_pct':'50',
    'far_chargeable_area_m2':'268.20','legal_parking_min_spaces':'3',
    'legal_basis_reference':'합성 시험, 실제 법정 상한 아님'}

class LegalDetailTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.s=CaseStore(self.temp.name,server.FIELD_KEYS,server.MASTER['version'])
        self.s.save_values(VALUES)
        self.s.confirm(server.REQUIRED_KEYS)
        self.s.build_legal()
        self.s.update_design_evidence(EVIDENCE)
    def tearDown(self):self.temp.cleanup()
    def test_guided_items_versus_generic(self):
        rows=self.s.state()['legal_review']['items']
        self.assertEqual(len(rows),113)
        self.assertEqual(len(EXAMPLES),7)
        self.assertIn('2m',next(x for x in rows if x['id']=='D019')['guidance']['rule'])
        self.assertIn('미검증',next(x for x in rows if x['id']=='D098')['guidance']['verification'])
    def test_missing_proof_rejected(self):
        for verdict in ('적정(담당자 확인)','보완 필요'):
            with self.assertRaises(ValueError):
                validate_verification(verdict,'1.5','','건축법 제44조','의견')
    def test_drawing_and_verdict_export_restore(self):
        case=self.s.save_legal_verification('D019','적용','검토중','접도 예외 확인 필요',
              '보완 필요','1.5m','배치도 A-101','건축법 제44조, 2026-10-20')
        report=preview(case)
        entry=next(x for x in report['rows'] if x['id']=='D019')
        self.assertEqual(entry['drawing_ref'],'배치도 A-101')
        self.assertEqual(report['summary']['보완'],1)
        raw=self.s.export_bytes()
        self.s.new_case()
        back=self.s.open_case(raw)
        self.assertEqual(next(x for x in back['legal_review']['items'] if x['id']=='D019')['drawing_value'],'1.5m')
    def test_changed_design_invalidates_outcome(self):
        self.s.save_legal_verification('D019','적용','검토기록완료','다시 확인',
           '보완 필요','1.5m','배치도 A-101','건축법 제44조')
        case=self.s.update_design_evidence({**EVIDENCE,'road_frontage_m':'3'})
        row=next(x for x in case['legal_review']['items'] if x['id']=='D019')
        self.assertEqual(row['review_result'],'미검토')
        self.assertEqual(row['progress'],'검토중')
        self.assertEqual(preview(case)['summary']['보완'],0)
    def test_changed_application_is_outdated(self):
        self.s.save_values({**VALUES,'site_address':'파주시 모의동 2'})
        self.assertEqual(preview(self.s.state())['status'],'재검토 필요')
    def test_inconsistent_nonapplicable_blocked(self):
        with self.assertRaises(ValueError):
            self.s.save_legal_verification('D019','적용','검토중','비적용 사유',
                 '비적용(담당자 확인)','','','법령 확인')
    def test_report_without_legal_is_empty(self):
        self.s.new_case()
        self.assertEqual(preview(self.s.state())['rows'],[])

if __name__=='__main__':unittest.main()
