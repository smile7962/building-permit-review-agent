"""Phase 1.10: reproducible, local-first practical-format benchmark.

Synthetic PDF/XLSX only. Actual civic records must not be sent to any cloud AI.
Source documents are immutable inputs; neither active .bcase nor gold data change.
"""
import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from benchmark import grade, _combine
from ai_review import ai_config, compare_ai
from parser import parse_application
from seumteo_details import extract_details

ROOT=Path(__file__).resolve().parent
FOLDER=ROOT/'practical_fixtures'
GOLD=FOLDER/'gold.json'


def checked_fixture_bytes(entry):
    # Manifest is bundled at install time. File names cannot escape the folder.
    name=entry['file']
    if Path(name).name!=name or Path(name).suffix.lower() not in ('.pdf','.xlsx'):
        raise ValueError('허용되지 않은 합성서식 경로입니다.')
    raw=(FOLDER/name).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=entry['sha256']:
        raise ValueError('합성 시험서식 파일이 변경되었습니다. 평가를 중단합니다.')
    return raw


def same_number(a,b):
    try:
        return Decimal(str(a).replace(',',''))==Decimal(str(b).replace(',',''))
    except (InvalidOperation,TypeError,ValueError):
        return False


def verify_details(details,expected):
    actual_names=[x['building_name'] for x in details['buildings']]
    names=expected['building_names']
    checks=[]
    checks.append({'item':'동별 명칭 및 건수', 'ok':actual_names==names,
                   'expected':names,'actual':actual_names})
    actual_prop=[f['proposed'].get('area_m2') for f in details['floors']]
    expected_prop=expected['floor_proposed_areas']
    checks.append({'item':'층별 신청란 면적',
                   'ok':len(actual_prop)==len(expected_prop) and all(same_number(a,b) for a,b in zip(actual_prop,expected_prop)),
                   'expected':expected_prop,'actual':actual_prop})
    expected_existing=expected.get('floor_existing_areas',[])
    if expected_existing:
        actual_existing=[f['existing'].get('area_m2') for f in details['floors']]
        checks.append({'item':'층별 기존 면적',
            'ok':len(actual_existing)==len(expected_existing) and all(same_number(a,b) for a,b in zip(actual_existing,expected_existing)),
            'expected':expected_existing,'actual':actual_existing})
    if expected.get('building_proposed_floor_area_m2'):
        actual=details['buildings'][0]['proposed'].get('floor_area_m2',{}).get('value') if details['buildings'] else None
        expected_area=expected['building_proposed_floor_area_m2']
        checks.append({'item':'동별 신청란 연면적 (전체와 구별)',
            'ok':same_number(actual,expected_area), 'expected':expected_area,'actual':actual})
    return {'correct':sum(x['ok'] for x in checks),'total':len(checks),'checks':checks}


def run_practical_benchmark(mode='rules',*, consent=False,allowed_keys=None,transport=None,config=None):
    if mode not in ('rules','ai'):
        raise ValueError('rules 또는 ai 평가 모드를 지정하세요.')
    if mode=='ai' and consent is not True:
        raise ValueError('합성 PDF/XLSX 추출 텍스트의 외부 전송에 동의해야 합니다.')
    if mode=='ai':
        config=config or ai_config()
        if not config['available']:
            raise ValueError('Gemini 등의 AI 모델 연결 설정이 필요합니다.')
    manifest=json.loads(GOLD.read_text(encoding='utf8'))
    cases=[];ai_cases=[];all_details=[]
    keys=set(allowed_keys or manifest['cases'][0]['expected'].keys())
    keys.update({'building_count','work_type','zoning'})
    for entry in manifest['cases']:
        raw=checked_fixture_bytes(entry)
        lines,values,sources,_,_=parse_application(entry['file'],raw,keys,False)
        detail=verify_details(extract_details(lines),entry['details'])
        all_details.append(detail)
        base={'id':entry['id'],'description':entry['description'],'file_format':Path(entry['file']).suffix.lower(),
              'detail_score':detail,'checksum_verified':True}
        cases.append({**base,'score':grade(entry['expected'],values,keys)})
        if mode=='ai':
            # No document bytes, fixed hashed fixture only, extracted evidence text.
            # This evaluates the AI's 16-field extraction, not multimodal OCR.
            draft=compare_ai(lines,values,keys,transport=transport,config=config)
            suggestions=draft['suggestions']
            ai_values={k:x['value'] for k,x in suggestions.items()}
            evidence={k:x['verified'] for k,x in suggestions.items()}
            ai_cases.append({**base,'score':grade(entry['expected'],ai_values,keys,evidence=evidence),
                             'model':config['model'],'sent_lines':draft['sent_lines']})
    detailed_correct=sum(d['correct'] for d in all_details)
    detailed_total=sum(d['total'] for d in all_details)
    result={'benchmark_version':manifest['version'],'mode':mode,'practical':True,
            'real_document_used':False,'active_case_modified':False,
            'rules':{'summary':_combine(cases),'cases':cases},
            'details_summary':{'correct':detailed_correct,'total':detailed_total},
            'notice':'합성 PDF·XLSX 4건을 기존 텍스트·좌표 추출기로 처리한 결과입니다. 정부 공식 양식이나 실제 서식 정확도가 아니며, Gemini에도 원본 PDF 이미지 자체는 전송하지 않습니다.'}
    if mode=='ai':
        result['ai']={'model':config['model'],'summary':_combine(ai_cases),'cases':ai_cases}
        result['requests_to_model']=len(ai_cases)
    else:result['requests_to_model']=0
    return result


if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument('--mode',choices=['rules','ai'],default='rules')
    ap.add_argument('--confirm-synthetic-send',action='store_true')
    args=ap.parse_args()
    print(json.dumps(run_practical_benchmark(args.mode,consent=args.confirm_synthetic_send),ensure_ascii=False,indent=2))
