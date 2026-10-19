"""Read-only scoring of bundled synthetic PDF fixtures (never network)."""
import json
from pathlib import Path
from benchmark import grade, _combine
from parser import parse_application
ROOT=Path(__file__).resolve().parent
FOLDER=ROOT/'benchmarks'/'realform'
def run_realform_benchmark(allowed_keys):
    cases=json.loads((FOLDER/'gold.json').read_text(encoding='utf-8'))['cases']
    output=[]
    for item in cases:
        p=FOLDER/item['file']
        if p.name!=item['file'] or p.suffix!='.pdf':
            raise ValueError('허용되지 않은 시험파일 경로')
        lines,values,sources,_,_=parse_application(p.name,p.read_bytes(),allowed_keys)
        score=grade(item['expected'],values,allowed_keys)
        output.append({'id':item['id'],'format':'PDF','score':score,
            'source_coverage':sum(bool(sources.get(k,{}).get('line')) for k in values)})
    return {'dataset':'실무형 합성 PDF · 실제 민원자료 미사용','mode':'offline-rules',
            'summary':_combine(output),'cases':output,
            'notice':'합성 서식만 평가했습니다. 실제 세움터 서식이나 AI 비전·OCR 정확도를 뜻하지 않습니다.'}
