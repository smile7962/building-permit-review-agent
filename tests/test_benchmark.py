"""Synthetic benchmark correctness, opt-in security and read-only HTTP path."""
import json
import threading
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import server
from ai_review import _normal
from benchmark import GOLD_FILE, equivalent, grade, run_benchmark
from case_store import CaseStore
from parser import parse_application


class BenchmarkScoring(unittest.TestCase):
    def test_normalize_numeric_equivalence_not_partial_digits(self):
        self.assertTrue(equivalent('site_area_m2','1,200.00','1200'))
        self.assertFalse(equivalent('site_area_m2','12','120'))
        self.assertFalse(equivalent('site_area_m2','NaN','NaN'))

    def test_missing_wrong_false_positive_and_ungrounded(self):
        report = grade({'site_area_m2':'450','work_type':'증축'},
                       {'site_area_m2':'460','zoning':'임의값','work_type':'증축'},
                       {'site_area_m2','work_type','zoning','building_count'},
                       evidence={'site_area_m2':True,'work_type':False,'zoning':True})
        self.assertEqual(report['counts'], {'correct':0,'wrong':1,'missing':0,
                                           'extra':1,'unverified':1,'empty_correct':1})
        self.assertEqual(report['accuracy'],0.0)

    def test_local_rules_all_synthetic(self):
        with patch('ai_review._no_redirect_request', side_effect=AssertionError('no web')):
            report=run_benchmark(allowed_keys=server.FIELD_KEYS)
        self.assertEqual(report['rules']['summary']['expected_fields'],62)
        self.assertEqual(report['rules']['summary']['counts']['correct'],62)
        self.assertEqual(report['requests_to_model'],0)
        self.assertEqual(report['rules']['summary']['counts']['empty_correct'],2)

    def test_ai_requires_explicit_consent_and_config(self):
        with self.assertRaisesRegex(ValueError,'동의'):
            run_benchmark('ai')
        with patch.dict('os.environ',{'AI_MODE':'off'},clear=True):
            with self.assertRaisesRegex(ValueError,'설정'):
                run_benchmark('ai',consent=True)

    def test_reject_unknown_modes(self):
        with self.assertRaisesRegex(ValueError,'rules 또는 ai'):
            run_benchmark('uploaded_case')

    def test_injected_mock_llm_uses_four_synthetic_only(self):
        manifest=json.loads(GOLD_FILE.read_text(encoding='utf-8'))
        calls=[]
        def transport(payload):
            excerpts=json.loads(payload['messages'][1]['content'])
            first=excerpts[0]['text']
            current=next(x for x in manifest['cases'] if x['id'] in first or
                         {'permit_house':'단독주택 사례','notice_shop':'근린생활시설','permit_parking':'주차장 복합층','notice_extension':'단독주택 증축'}[x['id']] in first)
            fields={}; source_lines={}
            for key,value in current['expected'].items():
                alias={
                    'permit_type':'신청 구분','work_type':'건축 구분','site_address':'대지 위치',
                    'site_area_m2':'대지면적','building_area_m2':'건축면적',
                    'total_floor_area_m2':'연면적','building_coverage_percent':'건폐율',
                    'floor_area_ratio_percent':'용적률','primary_use':'주용도',
                    'structure':'구조','above_ground_floors':'지상층수',
                    'underground_floors':'지하층수','building_count':'건축물 동수',
                    'parking_spaces':'주차','zoning':'용도지역','notes':'특이사항'
                }[key]
                candidates=[x for x in excerpts if x['text'].startswith(alias)]
                if candidates:
                    fields[key]=value;source_lines[key]=[candidates[0]['id']]
            calls.append(excerpts)
            return {'choices':[{'message':{'content':json.dumps({'fields':fields,'source_lines':source_lines},ensure_ascii=False)}}]}
        fake={'available':True,'model':'가상-LM(실제 모델 아님)','mode':'external','base_url':'https://example.invalid/v1'}
        with patch('ai_review._no_redirect_request',side_effect=AssertionError('no network')):
            report=run_benchmark('ai',consent=True,allowed_keys=server.FIELD_KEYS,config=fake,transport=transport)
        self.assertEqual(len(calls),4)
        self.assertEqual(report['requests_to_model'],4)
        self.assertEqual(report['rules']['summary']['counts']['correct'],62)
        self.assertEqual(report['ai']['summary']['counts']['correct'],62)
        self.assertEqual(report['ai']['summary']['counts']['extra'],0)
        self.assertTrue(all('합성' in c[0]['text'] or '모의' in c[0]['text'] or 'SYNTHETIC' in c[0]['text'] for c in calls))


class BenchmarkHttp(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        server.STORE=CaseStore(self.temp.name,server.FIELD_KEYS,server.MASTER['version'])
        self.web=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.web.serve_forever,daemon=True)
        self.thread.start()
        self.url=f'http://127.0.0.1:{self.web.server_port}'
    def tearDown(self):
        self.web.shutdown();self.web.server_close();self.thread.join();server.STORE=None;self.temp.cleanup()
    def post(self,obj):
        data=json.dumps(obj).encode()
        req=urllib.request.Request(self.url+'/api/benchmark',data=data,method='POST')
        with urllib.request.urlopen(req,timeout=12) as rsp:return json.loads(rsp.read())

    def test_report_does_not_modify_active_case(self):
        before=server.STORE.state()
        report=self.post({'mode':'rules','filename':'/sensitive/case.txt','consent':False})
        after=server.STORE.state()
        self.assertEqual(before['case_id'],after['case_id'])
        self.assertEqual(before['history'],after['history'])
        self.assertEqual(before['documents'],after['documents'])
        self.assertFalse(report['real_document_used'])
        self.assertFalse(report['active_case_modified'])
        self.assertEqual(report['rules']['summary']['counts']['correct'],62)

    def test_http_blocks_ai_without_consent(self):
        with self.assertRaises(urllib.error.HTTPError) as err:self.post({'mode':'ai','consent':False})
        self.assertEqual(err.exception.code,400)
        self.assertIn('동의',err.exception.read().decode('utf-8'))

    def test_http_rejects_unknown_mode(self):
        with self.assertRaises(urllib.error.HTTPError) as err:self.post({'mode':'../../private'})
        self.assertEqual(err.exception.code,400)


if __name__ == '__main__':unittest.main()
