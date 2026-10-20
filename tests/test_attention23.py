"""Phase 2.3: deterministic warning metadata; never a legal violation verdict."""
import unittest
from screening import screen_item, summarize_screen
from legal_review import MASTER, build
from case_store import CaseStore
from server import FIELD_KEYS, MASTER as APPLICATION_MASTER, REQUIRED_KEYS
import tempfile

INDEX = {it['id']: it for it in MASTER['items']}
CASE = {'permit_type':'건축허가', 'work_type':'신축','primary_use':'단독주택',
        'zoning':'계획관리지역','site_address':'경기도 파주시 모의동 123-45',
        'site_area_m2':'450','building_area_m2':'130','total_floor_area_m2':'268.20',
        'parking_spaces':'2'}
RISK = {'road_frontage_m':'1.5','road_status':'확인됨',
        'legal_coverage_max_pct':'20', 'legal_far_max_pct':'50',
        'far_chargeable_area_m2':'268.20','legal_parking_min_spaces':'3',
        'legal_basis_reference':'단위테스트용 임의 기준. 실제 법령기준 아님'}

class WarningTagTests(unittest.TestCase):
    def test_warning_four_numeric_conditions(self):
        for key in ('D019','D038','D039','D070'):
            with self.subTest(field=key):
                row=screen_item(INDEX[key],CASE,RISK)
                self.assertEqual(row['check']['attention'],'warning')
                self.assertEqual(row['status'],'검토대상')
                self.assertNotIn('위법',row['check']['result'])

    def test_ok_when_at_or_better_than_standard(self):
        safe={**RISK,'road_frontage_m':'2', 'legal_coverage_max_pct':'28.8888888889',
              'legal_far_max_pct':'59.60', 'legal_parking_min_spaces':'2'}
        safe['legal_coverage_max_pct']='30'
        for key in ('D019','D038','D039','D070'):
            with self.subTest(field=key):
                self.assertEqual(screen_item(INDEX[key],CASE,safe)['check']['attention'],'ok')

    def test_equal_threshold_is_not_warning(self):
        safe={**RISK,'road_frontage_m':'2', 'legal_coverage_max_pct':'28.888888888888888888888888888889',
              'legal_far_max_pct':'59.6', 'legal_parking_min_spaces':'2'}
        for key in ('D019','D039','D070'):
            with self.subTest(field=key):
                self.assertEqual(screen_item(INDEX[key],CASE,safe)['check']['attention'],'ok')

    def test_missing_inputs_not_marked_as_warning(self):
        for key in ('D019','D038','D039','D070'):
            with self.subTest(field=key):
                check=screen_item(INDEX[key],CASE,{}).get('check')
                self.assertFalse(check and check.get('attention')=='warning')

    def test_counts_warning_only_not_summary_groups(self):
        review=build(CASE,RISK)
        self.assertEqual(review['screening_summary']['주의검토'],4)
        self.assertEqual(sum(bool(it.get('screening',{}).get('check') and it['screening']['check'].get('attention')=='warning') for it in review['items']),4)
        self.assertEqual(review['screening_summary']['분류항목'],14)

    def test_old_bcase_reopen_refreshes_warning_without_overwriting_opinion(self):
        with tempfile.TemporaryDirectory() as tmp:
            st=CaseStore(tmp,FIELD_KEYS,APPLICATION_MASTER['version'])
            st.save_values(CASE)
            st.confirm(REQUIRED_KEYS)
            st.build_legal()
            st.update_design_evidence(RISK)
            st.update_legal('D019','적용','검토중','모의 설계 기준에 따라 별도 확인 필요')
            binary=st.export_bytes()
            st.new_case()
            case=st.open_case(binary)
            legal=case['legal_review']
            self.assertFalse(legal['screening_needs_refresh'])
            self.assertEqual(legal['screening_summary']['주의검토'],4)
            note=next(x for x in legal['items'] if x['id']=='D019')
            self.assertEqual(note['note'],'모의 설계 기준에 따라 별도 확인 필요')

if __name__=='__main__':unittest.main()
