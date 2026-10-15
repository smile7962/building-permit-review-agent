"""Synthetic-only AI provider tests. NO external network / no real personal data."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from parser import parse_application
from ai_review import ai_config, compare_ai, _protect_content
from case_store import CaseStore

ROOT=Path(__file__).resolve().parents[1]
KEYS={'permit_type','work_type','site_address','site_area_m2','building_area_m2',
      'total_floor_area_m2','building_coverage_percent','floor_area_ratio_percent',
      'primary_use','structure','above_ground_floors','underground_floors',
      'building_count','parking_spaces','zoning','notes'}
CFG={'available':True,'model':'test-model','mode':'external','base_url':'https://invalid.test/v1'}

class AiDraftTests(unittest.TestCase):
    def setUp(self):
        self.data=(ROOT/'samples/sample_application.txt').read_bytes()
        self.lines,self.local,self.sources,_,_=parse_application('sample_application.txt',self.data,KEYS)

    def mock_result(self, fields, cites):
        def fake(payload):
            self.assertIn('messages',payload)
            return {'choices':[{'message':{'content':json.dumps({'fields':fields,'source_lines':cites},ensure_ascii=False)}}]}
        return fake

    def line_num(self, prefix):
        return next(x['n'] for x in self.lines if x['text'].startswith(prefix))

    def test_ai_agreement_is_separate(self):
        result=compare_ai(self.lines,self.local,KEYS,config=CFG,transport=self.mock_result(
            {'site_area_m2':'450.00'}, {'site_area_m2':[self.line_num('대지면적:')]}))
        self.assertEqual(result['suggestions']['site_area_m2']['status'],'일치')
        self.assertTrue(result['suggestions']['site_area_m2']['verified'])
        self.assertEqual(self.local['site_area_m2'],'450.00')

    def test_ai_difference_not_auto_applied(self):
        result=compare_ai(self.lines,self.local,KEYS,config=CFG,transport=self.mock_result(
            {'site_area_m2':'451'}, {'site_area_m2':[self.line_num('대지면적:')]}))
        self.assertFalse(result['suggestions']['site_area_m2']['verified'])
        self.assertEqual(result['suggestions']['site_area_m2']['status'],'근거 재확인')
        self.assertEqual(self.local['site_area_m2'],'450.00')

    def test_uncited_hallucination_not_usable(self):
        result=compare_ai(self.lines,self.local,KEYS,config=CFG,transport=self.mock_result(
            {'parking_spaces':'999'}, {'parking_spaces':[999999]}))
        self.assertFalse(result['suggestions']['parking_spaces']['verified'])

    def test_unknown_field_ignored(self):
        result=compare_ai(self.lines,self.local,KEYS,config=CFG,transport=self.mock_result(
            {'unapproved':'abc'}, {'unapproved':[1]}))
        self.assertEqual(result['suggestions'],{})

    def test_external_blocks_real_like_form(self):
        lines=[{'n':1,'text':'건축허가 신청서','where':'1쪽'},
               {'n':2,'text':'건축주 홍길동','where':'1쪽'}]
        with self.assertRaisesRegex(ValueError,'모의·합성'):
            _protect_content(lines,True)

    def test_external_blocks_personal_data_even_synthetic(self):
        lines=[{'n':1,'text':'[모의 합성자료]','where':'1쪽'},
               {'n':2,'text':'휴대전화 010-1234-5678','where':'1쪽'}]
        with self.assertRaisesRegex(ValueError,'차단'):
            _protect_content(lines,True)

    def test_applicant_section_not_sent(self):
        lines=self.lines+[{'n':100,'text':'건축주: 가상의 인물','where':'2쪽'}]
        excerpts=_protect_content(lines,True)
        self.assertNotIn('건축주: 가상의 인물',str(excerpts))

    def test_no_ai_config_by_default(self):
        with patch.dict(os.environ,{'AI_MODE':'off','AI_MODEL':'example','AI_API_KEY':'x'}):
            self.assertFalse(ai_config()['available'])

    def test_explicit_application_records_history_and_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            case=CaseStore(tmp,KEYS,'v1')
            case.add_application('demo.txt','fake','text/plain',self.data,self.lines,self.local,self.sources,'규칙 기반')
            old=case.state();doc_id=old['documents'][0]['id']
            fields={'site_area_m2':'450.00','parking_spaces':'999'}
            citations={'site_area_m2':[self.line_num('대지면적:')],'parking_spaces':[555]}
            result=compare_ai(self.lines,self.local,KEYS,config=CFG,transport=self.mock_result(fields,citations))
            case.record_ai_review(result,doc_id)
            self.assertEqual(case.state()['values']['site_area_m2'],'450.00')
            with self.assertRaisesRegex(ValueError,'근거'):
                case.apply_ai_review(result['run_id'],['parking_spaces'])
            original=case.state()['values']['site_area_m2']
            assert original=='450.00'
            case.apply_ai_review(result['run_id'],['site_area_m2'])
            state=case.state();self.assertIsNone(state['confirmed_at'])
            self.assertEqual(state['sources']['site_area_m2']['method'],'AI 분석 제안')
            blob=case.export_bytes()
            case.new_case();case.open_case(blob)
            self.assertEqual(case.state()['ai_review']['run_id'],result['run_id'])
            self.assertEqual(case.state()['values']['site_area_m2'],'450.00')

    def test_invalid_selection_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            case=CaseStore(tmp,KEYS,'v1')
            with self.assertRaisesRegex(ValueError,'선택'):
                case.apply_ai_review('missing',[])

if __name__=='__main__': unittest.main()
