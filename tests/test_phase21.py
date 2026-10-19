"""Phase 2.1 comprehensive source-linked review master regression; synthetic data only."""
import json
import tempfile
import unittest
from pathlib import Path

import server
from case_store import CaseStore
from legal_review import MASTER, IDS, build, priority, validate_edit


class ComprehensiveLegalMaster(unittest.TestCase):
    def setUp(self):
        self.items=MASTER['items']

    def test_counts_ids_unique_and_hierarchy(self):
        self.assertEqual(len(self.items),113)
        self.assertEqual(len({x['id'] for x in self.items}),113)
        self.assertEqual(len([x for x in self.items if x['level']=='대표항목']),14)
        self.assertEqual(len([x for x in self.items if x['level']=='세부항목']),99)
        self.assertEqual(len(MASTER['categories']),12)
        self.assertEqual({x['id'] for x in self.items if x['level']=='대표항목'},set('C%02d'%i for i in range(1,15)))
        self.assertTrue(all(x['parent_id'] in IDS for x in self.items if x['level']=='세부항목'))

    def test_source_quality_and_source_documents(self):
        for x in self.items:
            with self.subTest(x=x['id']):
                self.assertTrue(x['basis'].strip())
                self.assertTrue(x['url'].startswith('https://www.law.go.kr/') or x['url'].startswith('https://law.go.kr/'))
                self.assertTrue(x['question'].strip())
                self.assertTrue(x['required_docs'])
                self.assertTrue(all(f in server.FIELD_KEYS for f in x['fields']))
                self.assertTrue('확인' in x['reference_status'])

    def test_no_automatic_applicability_or_legal_conclusion(self):
        values={'permit_type':'건축신고','work_type':'증축','zoning':'계획관리지역',
                'primary_use':'단독주택','site_address':'파주시 가상동 3'}
        candidate=build(values)
        self.assertEqual(len(candidate['items']),113)
        self.assertTrue(all(x['applicability']=='미확인' and x['progress']=='미착수' and not x['note']
                            for x in candidate['items']))
        self.assertFalse(candidate['confirmed_at'])
        self.assertEqual(next(x for x in candidate['items'] if x['title']=='증축 전·후 면적 구분')['priority'],'우선 확인')

    def test_unknown_zoning_does_not_auto_exempt_sunlight(self):
        i=next(x for x in self.items if x['id']=='C08')
        self.assertEqual(priority(i,{'zoning':'계획관리지역'}),'적용 여부 확인')
        self.assertEqual(priority(i,{'zoning':'일반주거지역'}),'우선 확인')

    def test_disabled_legality_shortcuts(self):
        for term in ('적법','위법','자동판정','불필요'):
            with self.assertRaises(ValueError):validate_edit('D001',term,'검토기록완료','담당자 판단 필요')
        with self.assertRaises(ValueError):validate_edit('D001','비적용','검토중','')

    def test_ordinance_effective_date_warning_in_master(self):
        self.assertIn('2027-01-01',MASTER['disclaimer'])
        self.assertTrue(any('주차장 설치' in x['name'] for x in MASTER['reviewed_sources']))

    def test_values_missing_becomes_incomplete_hint_not_exclusion(self):
        data=build({'permit_type':'건축허가'})
        self.assertEqual(len(data['items']),113)
        self.assertTrue(any(i['priority']=='확인 자료 부족' for i in data['items']))


class OldCaseCompatibility(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=CaseStore(self.tmp.name,server.FIELD_KEYS,server.MASTER['version'])
        self.store.save_values({'permit_type':'건축허가','work_type':'신축','site_address':'파주시 모의동 1',
                                'primary_use':'단독주택'})
        self.store.confirm(server.REQUIRED_KEYS)

    def tearDown(self): self.tmp.cleanup()

    def test_new_review_saved_and_reopened(self):
        case=self.store.build_legal()
        self.assertEqual(len(case['legal_review']['items']),113)
        case=self.store.update_legal('D003','적용','검토중','합성 설계도서와 법령 검토 예정')
        saved=self.store.export_bytes()
        self.store.new_case()
        reopened=self.store.open_case(saved)
        item=next(i for i in reopened['legal_review']['items'] if i['id']=='D003')
        self.assertEqual(item['note'],'합성 설계도서와 법령 검토 예정')
        self.assertFalse(reopened['legal_review']['outdated'])

    def test_old_version_review_not_silently_confirmed(self):
        self.store.build_legal()
        with self.store.lock,self.store._connect() as con:
            row=con.execute("SELECT id,payload_json FROM records WHERE category='legal_checklist' ORDER BY id DESC LIMIT 1").fetchone()
            payload=json.loads(row['payload_json']);payload['master_version']='2026-10-19-draft-1'
            payload['confirmed_at']='2026-10-01T00:00:00'
            con.execute('UPDATE records SET payload_json=? WHERE id=?',(json.dumps(payload,ensure_ascii=False),row['id']))
        case=self.store.state()
        self.assertTrue(case['legal_review']['outdated'])
        with self.assertRaises(ValueError):self.store.confirm_legal()
        # New candidate snapshot is explicit and creates a new record, preserving older review data.
        updated=self.store.build_legal()
        self.assertFalse(updated['legal_review']['outdated'])
        self.assertIsNone(updated['legal_review']['confirmed_at'])
        with self.store._connect(readonly=True) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM records WHERE category='legal_checklist'").fetchone()[0],2)


if __name__=='__main__': unittest.main()
