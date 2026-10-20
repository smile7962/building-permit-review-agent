"""Human-in-the-loop legal review candidates. No compliance or non-applicability verdicts."""
import hashlib
import json
from pathlib import Path
from screening import screen_item, summarize_screen, evidence_values, SCREEN_VERSION
from review_guidance import guidance

ROOT=Path(__file__).resolve().parent
MASTER=json.loads((ROOT/'masters'/'legal_checklist.json').read_text(encoding='utf-8'))
IDS=frozenset(item['id'] for item in MASTER['items'])
APPLICABILITY=frozenset(('미확인','적용','비적용'))
PROGRESS=frozenset(('미착수','검토중','검토기록완료'))


def snapshot(values):
    return hashlib.sha256(json.dumps(values,sort_keys=True,ensure_ascii=False,
                      separators=(',',':')).encode('utf-8')).hexdigest()


def priority(item, values):
    """Only review hints. Never says non-applicable or legally compliant."""
    kind=item.get('condition')
    if kind=='alteration':
        return '우선 확인' if values.get('work_type') in ('증축','개축','재축','대수선','이전','허가사항 변경','신고사항 변경','용도변경') else '적용 여부 확인'
    if kind=='residential_zoning':
        zoning=values.get('zoning','')
        if '일반주거' in zoning or '전용주거' in zoning:
            return '우선 확인'
        # Other zones may have separate provisions; do NOT mark exemption.
        return '적용 여부 확인'
    title=item['title']
    use=values.get('primary_use','')
    work=values.get('work_type','')
    zoning=values.get('zoning','')
    special={
      '공동주택 채광·인동간격': ('공동주택','다세대','연립','아파트'),
      '피난안전구역·대피공간': ('공동주택','아파트','오피스텔'),
      '장애인 전용주차장': ('근린생활','판매시설','업무시설','의료시설','집회시설'),
      '교통약자 편의시설': ('근린생활','판매시설','업무시설','의료시설','집회시설'),
    }
    if title in special:
        return '우선 확인' if any(t in use for t in special[title]) else '적용 여부 확인'
    if title in ('증축 시 추가 주차대수','증축 전·후 면적 구분','기존·신규 주차대수 구분',
                 '기존 건축물 대장·허가이력','종전 건축법·조례 부칙 및 특례'):
        return '우선 확인' if work in ('증축','개축','재축','대수선','용도변경') else '적용 여부 확인'
    if title in ('정북방향 일조 이격',):
        return '우선 확인' if ('주거지역' in zoning) else '적용 여부 확인'
    return '확인 자료 부족' if any(not values.get(f) for f in item['fields']) else '일반 검토 후보' 


def build(values, design_evidence=None):
    design_evidence=evidence_values(design_evidence or {})
    items=[]
    for src in MASTER['items']:
        items.append({**src,'priority':priority(src,values),
                      'facts':{k:values.get(k,'') for k in src['fields']},
                      'screening':screen_item(src,values,design_evidence),
                      'guidance':guidance(src),
                      'applicability':'미확인','progress':'미착수','note':'','reviewed_at':None,
                      'review_result':'미검토','drawing_value':'','drawing_ref':'','criteria_ref':''})
    return {'master_version':MASTER['version'],'master_as_of':MASTER['as_of'],
            'values_sha256':snapshot(values),'confirmed_at':None,'items':items,
            'design_evidence':design_evidence,'screening_version':SCREEN_VERSION,
            'screening_summary':summarize_screen(items),
            'disclaimer':MASTER['disclaimer']}


def validate_edit(item_id, applicability, progress, note):
    if item_id not in IDS:raise ValueError('유효하지 않은 검토항목입니다.')
    if applicability not in APPLICABILITY:raise ValueError('적용 여부를 다시 선택하세요.')
    if progress not in PROGRESS:raise ValueError('검토 진행 상태를 다시 선택하세요.')
    if not isinstance(note,str) or len(note)>2500:raise ValueError('검토 의견은 2,500자 이하여야 합니다.')
    if applicability=='비적용' and not note.strip():
        raise ValueError('비적용 판단 시 구체적인 사유를 입력하세요.')
    if progress=='검토기록완료' and (applicability=='미확인' or not note.strip()):
        raise ValueError('검토기록 완료에는 적용 여부와 담당자 검토의견이 필요합니다.')
    return {'applicability':applicability,'progress':progress,'note':note.strip()}


def refresh_screen(review, values):
    """Populate screening for reopened legacy cases without silently changing stored judgments."""
    ev=review.get('design_evidence') or {}
    for item in review.get('items',[]):
        item['screening']=screen_item(item,values,ev)
        item['guidance']=guidance(item)
    review['screening_summary']=summarize_screen(review.get('items',[]))
    return review
