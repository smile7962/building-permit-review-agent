"""Case-aware PRELIMINARY screening, never a legal approval/non-applicability decision.

Only verified legislation is hard-coded: Building Act 44(1), 61(1).
All local zoning maximums / parking requirements are explicitly supplied by a reviewer.
Source inputs not in Seumteo's 16 fields are recorded as separate design evidence.
"""
from decimal import Decimal, InvalidOperation
import re

SCREEN_VERSION = '2026-10-19-pilot1'
DESIGN_FIELDS = [
    {'key':'road_frontage_m','label':'설계도서상 접도 길이(m)','kind':'number','hint':'배치도·현황도로 확인, 건축법상 도로 여부 별도 확인'},
    {'key':'road_width_m','label':'설계도서상 도로 폭(m)','kind':'number','hint':'도로 지정·확폭·후퇴 여부 별도 확인'},
    {'key':'road_status','label':'건축법상 도로 확인','kind':'select','options':['','확인됨','확인되지 않음','추가조사 필요'],'hint':'도로 지정·공고/법적 지위를 담당자가 확인'},
    {'key':'north_setback_m','label':'설계도서상 정북 이격거리(m)','kind':'number','hint':'대지경계선·높이별 기준은 별도 법령 확인'},
    {'key':'building_height_m','label':'설계도서상 건축물 높이(m)','kind':'number','hint':'최고높이·계획고 등 세부 산정 필요'},
    {'key':'legal_coverage_max_pct','label':'검증된 해당 필지 건폐율 상한(%)','kind':'number','hint':'적용 조례·예외·부칙 확인 후 담당자 입력'},
    {'key':'legal_far_max_pct','label':'검증된 해당 필지 용적률 상한(%)','kind':'number','hint':'용적률 산정용 연면적 및 제외면적 별도 확인'},
    {'key':'far_chargeable_area_m2','label':'설계도서상 용적률 산정용 연면적(㎡)','kind':'number','hint':'신청서 전체 연면적과 다를 수 있음'},
    {'key':'legal_parking_min_spaces','label':'검증된 법정 부설주차장 대수(대)','kind':'number','hint':'용도·증축부분·기존 대수·조례 확인 후 담당자 입력'},
    {'key':'fire_district','label':'방화지구 여부','kind':'select','options':['','해당','비해당','추가조사 필요'],'hint':'토지이용계획확인서로 조사'},
    {'key':'farmland','label':'농지전용 검토 여부','kind':'select','options':['','대상 의심','대상 아님 확인','추가조사 필요'],'hint':'지목·현황·농지법 용어 구분 필요'},
    {'key':'forestland','label':'산지전용 검토 여부','kind':'select','options':['','대상 의심','대상 아님 확인','추가조사 필요'],'hint':'산지 여부와 전용허가 의제 확인'},
    {'key':'legal_basis_reference','label':'설계기준 확인 출처/시행일','kind':'text','hint':'법령·조례명, 조문, 시행일과 검토 기준일을 구체적으로 기재'},
]
FIELD_KEYS = {f['key'] for f in DESIGN_FIELDS}
NUMBER_KEYS = {f['key'] for f in DESIGN_FIELDS if f['kind']=='number'}
ALTERATION = {'증축','개축','재축','대수선','이전','허가사항 변경','신고사항 변경','용도변경'}
APARTMENTS = ('공동주택','아파트','연립주택','다세대주택')
# Provisional categories only, NOT determinations of legal applicability.
COMMON = {'D001','D002','D006','D007','D009','D010','D017','D018','D019','D020',
          'D021','D025','D027','D028','D034','D035','D036','D037','D038','D039',
          'D040','D044','D046','D051','D070','D073','D094','D095','D096'}
ACTION_RULES = {
    'D003':{'대수선'}, 'D004':{'용도변경'},
    'D005':{'허가사항 변경','신고사항 변경'},
    'D071':{'증축'},'D072':{'용도변경'},
    **{f'D{i:03d}':ALTERATION for i in range(87,94)},
    'D048':ALTERATION,
}
REGION_ITEMS = {'C08','D041'}
APT_ITEMS = {'D042','D061'}
SITE_ITEMS = {'D058':('fire_district','해당'),
              'D078':('farmland','대상 의심'),
              'D079':('forestland','대상 의심')}


def num(text):
    if text is None or isinstance(text,bool): return None
    try:
        value = Decimal(str(text).replace(',','').strip())
        return value if value.is_finite() else None
    except (InvalidOperation, ValueError):return None


def evidence_values(raw):
    if not isinstance(raw,dict) or set(raw)-FIELD_KEYS:
        raise ValueError('설계도서 검토 입력 항목이 올바르지 않습니다.')
    cleaned={}
    for spec in DESIGN_FIELDS:
        k=spec['key']; value=raw.get(k,'')
        if not isinstance(value,str) or len(value)>500:
            raise ValueError(f'{spec["label"]}: 입력값을 확인하세요.')
        value=value.strip()
        if spec['kind']=='number' and value:
            v=num(value)
            if v is None or v<0 or v>100000000:
                raise ValueError(f'{spec["label"]}: 0 이상의 유효한 숫자가 필요합니다.')
            if k in ('legal_coverage_max_pct','legal_far_max_pct') and v>10000:
                raise ValueError(f'{spec["label"]}: 비정상적으로 큰 백분율입니다.')
        if spec['kind']=='select' and value not in spec['options']:
            raise ValueError(f'{spec["label"]}: 선택 항목을 확인하세요.')
        cleaned[k]=value
    # Legal numbers are user-verified, never guessed. Require a citable basis.
    if any(cleaned.get(k) for k in ('legal_coverage_max_pct','legal_far_max_pct','legal_parking_min_spaces')) and not cleaned['legal_basis_reference']:
        raise ValueError('건폐율·용적률 상한이나 주차장 법정대수를 입력하려면 법령·조례 출처 및 시행일을 기록하세요.')
    return cleaned


def _status(kind, reason, missing=(), check=None):
    return {'status':kind,'reason':reason,'missing_inputs':list(missing),'check':check}


def _safe_percent(x):
    return f'{x.quantize(Decimal("0.01"))}%'


def _calc_coverage(values,ev):
    site=num(values.get('site_area_m2'));building=num(values.get('building_area_m2'))
    if not site or building is None:return _status('자료필요','건폐율 산정자료 부족',('대지면적','건축면적'))
    rate=building/site*100; legal=num(ev.get('legal_coverage_max_pct'))
    evidence=f'입력 건축면적 {building}㎡ ÷ 대지면적 {site}㎡ = {_safe_percent(rate)}'
    if legal is None:return _status('검토대상',evidence+' · 지역별 검증된 건폐율 상한 필요',('법정 건폐율 상한','법령·조례 시행일'))
    compare='기준값 이하 (적용·면적산정 재확인)' if rate<=legal else '기준값 초과 의심 (예외·산정법 확인)'
    return _status('검토대상',evidence+f' / 입력 기준 {_safe_percent(legal)}',(),{'kind':'coverage','computed':str(rate.quantize(Decimal("0.01"))),'standard':str(legal),'result':compare,'attention':'warning' if rate>legal else 'ok'})


def _calc_far(values,ev):
    site=num(values.get('site_area_m2'));special=num(ev.get('far_chargeable_area_m2'))
    if not site or special is None:return _status('자료필요','용적률은 총 연면적이 아닌 산정용 연면적을 확인해야 합니다.',('대지면적','용적률 산정용 연면적'))
    rate=special/site*100;legal=num(ev.get('legal_far_max_pct'))
    base=f'용적률 산정용 연면적 {special}㎡ ÷ 대지면적 {site}㎡ = {_safe_percent(rate)}'
    if legal is None:return _status('검토대상',base+' · 해당 필지 상한·부칙 확인 필요',('법정 용적률 상한'))
    compare='기준값 이하 (제외면적·특례 확인)' if rate<=legal else '기준값 초과 의심 (예외·산정 확인)'
    return _status('검토대상',base+f' / 입력 기준 {_safe_percent(legal)}',(),{'kind':'far','computed':str(rate.quantize(Decimal("0.01"))),'standard':str(legal),'result':compare,'attention':'warning' if rate>legal else 'ok'})


def _calc_road(ev):
    frontage=num(ev.get('road_frontage_m'));road=ev.get('road_status')
    if frontage is None or road in ('','추가조사 필요'):
        return _status('자료필요','건축법 제44조 기본 접도요건 검토 전 도로의 법적 지위와 접도길이 확인 필요',('건축법상 도로 여부','접도길이(m)'))
    if road=='확인되지 않음':
        return _status('자료필요','접한 통로가 건축법상 도로인지 확인되지 않았습니다. 도로 지정·예외 여부 조사 필요',('도로 법적 지위','도로 지정·공고 자료'))
    side='기본 접도길이 2m 이상' if frontage>=Decimal('2') else '기본 접도길이 2m 미만 (예외 검토 필요)'
    return _status('검토대상',f'설계 접도길이 {frontage}m · {side}. 건축법 제44조 단서 및 제2항·시행령 검토 필요',(),{
        'kind':'road','measured':str(frontage),'standard':'2','result':side+' · 법적 적합성 미판단','attention':'warning' if frontage<Decimal('2') else 'ok'})


def _calc_parking(values,ev):
    planned=num(values.get('parking_spaces'));required=num(ev.get('legal_parking_min_spaces'))
    if planned is None or required is None:return _status('자료필요','주차장법·파주시 조례에 따라 필요 대수를 산정한 뒤 계획 대수와 대조해야 합니다.',('계획 주차대수','검증된 필요 주차대수'))
    result='수량상 충족 추정 (규격·증축/용도변경·산정 확인)' if planned>=required else '계획 대수 부족 의심 (완화·기존대수 확인)'
    return _status('검토대상',f'계획 {planned}대 / 법정대수 입력 {required}대',(),{'kind':'parking','measured':str(planned),'standard':str(required),'result':result,'attention':'warning' if planned<required else 'ok'})


def screen_item(item, values, evidence=None):
    """An auditable triage explanation, NOT a determination of legal applicability."""
    ev=evidence or {};key=item['id'];work=values.get('work_type','');zone=values.get('zoning','');use=values.get('primary_use','')
    if item.get('level')=='대표항목':return _status('분류항목','대표 항목은 세부 스크리닝에서 제외하고 목차로만 사용합니다.')
    if key in ACTION_RULES:
        if not work:return _status('자료필요','건축행위가 미확정이어서 해당 항목의 조건을 판단할 수 없습니다.',('신축·증축·용도변경 등 건축구분',))
        if work in ACTION_RULES[key]:return _status('검토대상',f'건축구분 {work}에 해당하는 검토 후보입니다. 도면·기존대장 확인 필요.')
        return _status('우선낮음',f'현재 건축구분은 {work}입니다. 본 항목의 상황별 조건과 직접 연결되지 않습니다. 필요한 경우 담당자가 전체 보기에서 선택합니다.')
    if key in REGION_ITEMS:
        if not zone:return _status('자료필요','용도지역이 확인되지 않았습니다.',('용도지역',))
        if any(x in zone for x in ('전용주거','일반주거')):
            return _status('검토대상','전용·일반주거지역은 건축법 제61조제1항 정북 일조 검토 조건에 해당합니다. 시행령 제86조 거리·높이·예외 검증 필요.',('정북 이격·높이 도면',))
        return _status('우선낮음','현재 입력한 용도지역에서는 제61조제1항 정북방향 기준이 직접 연결되지 않습니다. 공동주택 채광 등 다른 기준은 별도 검토합니다.')
    if key in APT_ITEMS:
        if not use:return _status('자료필요','주용도·주택형태 확인 필요',('주용도',))
        if any(x in use for x in APARTMENTS):return _status('검토대상','공동주택 조건과 관련 있습니다. 채광창·동간거리·면적 확인 필요.')
        return _status('우선낮음','입력된 주용도가 공동주택 계열로 확인되지 않았습니다. 복합용도나 도면에 따라 재검토할 수 있습니다.')
    if key in SITE_ITEMS:
        field,trigger=SITE_ITEMS[key];v=ev.get(field,'')
        if not v or v=='추가조사 필요':return _status('자료필요','토지이용계획·지목·현황 확인 필요',tuple(x['label'] for x in DESIGN_FIELDS if x['key']==field))
        return _status('검토대상' if v==trigger else '우선낮음',f'담당자가 입력한 토지 조건: {v}. 원문·도면 확인 필요.')
    if key in ('D019','C02'):return _calc_road(ev)
    if key in ('D038','C06'):return _calc_coverage(values,ev)
    if key in ('D039','C07'):return _calc_far(values,ev)
    if key in ('D070','C11'):return _calc_parking(values,ev)
    if key in COMMON:
        needs=[f for f in item.get('fields',[]) if not values.get(f)]
        if needs:return _status('자료필요','기초 신청정보 미입력: '+', '.join(needs),needs)
        return _status('검토대상','신청정보로 관련 검토대상 후보를 선정했습니다. 법령 상세 기준과 도면 수치를 확인하세요.')
    return _status('자료필요','해당 항목의 적용을 결정할 추가 도면·토지 정보 또는 정밀 법령규칙이 아직 준비되지 않았습니다.',tuple(item.get('required_docs',[])[:3]))


def summarize_screen(items):
    counts={k:0 for k in ('검토대상','자료필요','우선낮음','분류항목','주의검토')}
    for item in items:
        status=item.get('screening',{}).get('status','자료필요')
        counts[status]=counts.get(status,0)+1
        if item.get('screening',{}).get('check',{} ) and item['screening']['check'].get('attention')=='warning':
            counts['주의검토']+=1
    return counts
