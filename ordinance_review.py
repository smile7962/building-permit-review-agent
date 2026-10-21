"""Paju ordinance *pre-check*, explicitly bound to user-supplied historical documents.

This module does NOT determine legality, actual effective law, or zone-use permission.
No automatic decisions are made from unverified supplementary provisions.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from legal_review import snapshot

VERSION = '2026-10-21-phase25-pilot1'
ZONING_DATE = '2025-03-20'  # user supplied Ordinance #2204
BUILDING_DATE = '2025-03-20'  # user supplied Ordinance #2205
PARKING_DATE = '2019-12-27'  # user supplied annex 2; historical, DO NOT claim current
ZONE_NAMES = (
    '제1종 전용주거지역','제2종 전용주거지역','제1종 일반주거지역','제2종 일반주거지역',
    '제3종 일반주거지역','준주거지역','중심상업지역','일반상업지역','근린상업지역','유통상업지역',
    '전용공업지역','일반공업지역','준공업지역','보전녹지지역','생산녹지지역','자연녹지지역',
    '보전관리지역','생산관리지역','계획관리지역','농림지역','자연환경보전지역')
# Section 32(1) and 33(1) of user-supplied Paju Urban Planning Ordinance, March 20, 2025.
BCR = (40,50,60,60,50,60,80,80,70,70,70,70,70,20,20,20,20,20,40,20,20)
FAR = (80,120,180,250,300,300,1000,900,600,600,200,250,250,50,50,80,80,80,100,50,50)
# These annexes list NOT permitted uses. Others list possible permitted uses,
# but absence from either must never be used as a final legal conclusion.
DENY_ANNEXES = frozenset((6,7,8,9,10,13,19))
PARKING_TYPES = {
    '위락시설': ('1',50),
    '문화 및 집회시설': ('2',75),
    '판매시설': ('2',75),
    '업무시설(오피스텔 제외)': ('2',75),
    '제1종 근린생활시설(제외시설 아님)': ('3',100),
    '제2종 근린생활시설': ('3',100),
    '단독주택(다가구 제외)': ('4',None),
    '공장(특례 아닌 일반)': ('7',175),
    '창고시설': ('8',200),
    '그 밖의 건축물': ('10',200),
}
INPUT_FIELDS = [
    {'key':'parking_scenario','label':'주차 산정 유형', 'options':['','신축·단일용도','복합용도','증축','용도변경','기타']},
    {'key':'parking_type','label':'주차시설물 세부유형', 'options':['',*PARKING_TYPES.keys(),'다가구·공동주택·오피스텔 등(세대별 산정)']},
    {'key':'parking_area_m2','label':'해당 용도 시설면적(㎡, 공용면적 포함)', 'kind':'number'},
    {'key':'building_line_setback_m','label':'건축선 이격거리(m)', 'kind':'number'},
    {'key':'boundary_setback_m','label':'인접대지경계선 이격거리(m)', 'kind':'number'},
    {'key':'building_road_width_m','label':'접한 도로 너비(m)', 'kind':'number'},
    {'key':'basis_date','label':'담당자가 검토한 적용 기준일(YYYY-MM-DD)', 'kind':'date'},
]
KEYS = {x['key'] for x in INPUT_FIELDS}
DECISIONS = ('미검토','적정(담당자 확인)','보완 필요','추가 확인','비적용(담당자 확인)')


def number(value):
    try:
        if value is None or isinstance(value,bool) or not str(value).strip(): return None
        n=Decimal(str(value).strip().replace(',',''))
        return n if n.is_finite() and 0<=n<=Decimal('100000000') else None
    except (ValueError,InvalidOperation): return None


def validate_inputs(data):
    if not isinstance(data,dict) or set(data)-KEYS:raise ValueError('조례 검토 입력항목이 올바르지 않습니다.')
    clean={}
    for spec in INPUT_FIELDS:
        key=spec['key']; val=data.get(key,'')
        if not isinstance(val,str) or len(val)>250:raise ValueError(f"{spec['label']}: 유효하지 않은 입력값입니다.")
        val=val.strip()
        if 'options' in spec and val not in spec['options']:raise ValueError(f"{spec['label']}: 목록에서 선택하세요.")
        if spec.get('kind')=='number' and val and number(val) is None:raise ValueError(f"{spec['label']}: 0 이상의 유효한 수치를 입력하세요.")
        if spec.get('kind')=='date' and val:
            from datetime import date
            try:
                if date.fromisoformat(val).isoformat()!=val:raise ValueError
            except ValueError:raise ValueError('법령 기준일은 YYYY-MM-DD 형식이어야 합니다.')
        clean[key]=val
    return clean


def _row(key,title,reference,criterion,design,result,attention='info',need=''):
    return {'id':key,'title':title,'reference':reference,'criterion':criterion,
            'design_value':design,'result':result,'attention':attention,'needs_confirmation':need,
            'legal_verdict':'담당자 미판단'}


def _fmt(x):
    return str(x.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)).rstrip('0').rstrip('.')


def _zoning(values):
    zone=(values.get('zoning') or '').strip(); use=(values.get('primary_use') or '').strip()
    if zone not in ZONE_NAMES:
        return _row('PZ01','용도지역별 건축제한','도시계획 조례 제31조 및 별표 1~22','용도지역·지구 중첩 여부 확인',zone or '미입력',
                    '용도지역을 21개 기본 분류 중 하나로 확정해야 합니다. 지구·지구단위계획은 별도 확인.',need='용도지역, 용도지구, 계획지침')
    n=ZONE_NAMES.index(zone)+1
    kind='금지 용도 열거' if n in DENY_ANNEXES else '허용 용도 열거'
    ref=f'파주시 도시계획 조례 제31조제{n}호 / 별표 {n} (2025-03-20 자료)'
    if zone=='계획관리지역':
        floors=number(values.get('above_ground_floors'))
        if floors is not None and floors>4:
            return _row('PZ01','용도지역별 건축제한',ref,'별표 19: 4층을 초과하는 건축물 금지',f'{use} / {floors}층',
                        '4층 초과로 별표 19의 기본 금지조건에 해당할 가능성. 예외·다른 법령 확인 필요.', 'warning','건축물 전체 층수, 특례, 지구단위계획')
        if use in ('아파트','공동주택(아파트)'):
            return _row('PZ01','용도지역별 건축제한',ref,'별표 19: 공동주택 중 아파트 금지',use,
                        '아파트 금지조건에 해당할 가능성. 시행일·용도분류 확인 필요.','warning','정확한 주용도 및 적용일')
        if use=='업무시설':
            return _row('PZ01','용도지역별 건축제한',ref,'별표 19 제6호: 업무시설',use,
                        '업무시설 금지 열거조건에 해당할 가능성. 세부용도·특례 확인 필요.','warning','건축법 시행령 별표 1 용도분류')
    return _row('PZ01','용도지역별 건축제한',ref,f'{zone}은 별표 {n}의 {kind} 방식',use or '용도 미입력',
                '해당 별표의 세부호·단서·상위법령 확인이 필요합니다. 열거 여부만으로 건축 가능 판정하지 않습니다.',
                'info','세부 용도, 용도지구·지구단위계획, 별표 개별조건')


def _coverage_far(values, evidence, criterion):
    zone=(values.get('zoning') or '').strip()
    idx=ZONE_NAMES.index(zone) if zone in ZONE_NAMES else None
    site=number(values.get('site_area_m2'))
    bld=number(values.get('building_area_m2'))
    fararea=number(evidence.get('far_chargeable_area_m2'))
    kind='건폐율' if criterion=='bcr' else '용적률'
    key='PZ02' if criterion=='bcr' else 'PZ03'
    section='32' if criterion=='bcr' else '33'
    standard=(BCR if criterion=='bcr' else FAR)[idx] if idx is not None else None
    area=bld if criterion=='bcr' else fararea
    ref=f'파주시 도시계획 조례 제{section}조제1항 (2025-03-20 자료)'
    if not site or area is None or standard is None:
        missing='대지면적, 건축면적' if criterion=='bcr' else '대지면적, 용적률 산정용 연면적(설계도서·법령기준 입력)'
        return _row(key,kind,ref,'용도지역 기본 상한(특례·중첩 규제 제외)', '확인자료 부족',
                    '기본 수치 비교 보류. '+('용도지역 확인 필요. ' if standard is None else '')+missing,
                    need=missing)
    rate=area/site*100
    warning=rate>Decimal(standard)
    return _row(key,kind,ref,f'{zone} 기본 상한 {standard}% (상위법·특례·부칙 별도 확인)',
                f'{_fmt(area)}㎡ ÷ {_fmt(site)}㎡ = {_fmt(rate)}%',
                ('기본 상한 초과 의심' if warning else '기본 상한 수치 이내')+' — 적용기준일·완화·산정면적 담당자 확인 필수.',
                'warning' if warning else 'ok','특례/완화, 용도지역 중첩, 적용 기준일')


def _parking(values, data):
    ref='파주시 주차장 설치 및 관리 조례 별표 2 (제공된 2019-12-27 개정 자료 · 현행 검증 전)'
    scenario=data['parking_scenario']; typ=data['parking_type']; size=number(data['parking_area_m2'])
    planned=number(values.get('parking_spaces'))
    if scenario!='신축·단일용도' or values.get('work_type')!='신축':
        return _row('PZ04','부설주차장 산정',ref,'용도별 시설면적·세대별·증축·용도변경 및 비고 확인',
                    f'{typ or "유형 미확정"} / 계획 {values.get("parking_spaces") or "미입력"}대',
                    '참고 산정 보류: 신축 단일용도만 계산. 복합용도·증축·용도변경·기존 주차장은 비고 4~7 등에 따른 개별산정 필요.',
                    need='건축행위, 주차 용도별 면적, 증축 전후 및 세대별 면적')
    if typ not in PARKING_TYPES or size is None:
        return _row('PZ04','부설주차장 산정',ref,'시설물별 주차기준 및 비고 1~16',
                    '세부용도/시설면적 미확인', '참고 산정 보류: 시설용도와 면적을 확인하세요.',need='별표상의 시설물 분류, 시설면적')
    n,den=PARKING_TYPES[typ]
    if den is None:
        if size<=50:raw=Decimal('0')
        elif size<=100:raw=Decimal('1')
        else:raw=Decimal('1')+(size-100)/100
    else: raw=size/Decimal(den)
    # Provisional 2019 annex note 6 for a single-use new facility only.
    spaces=int(raw.to_integral_value(rounding=ROUND_HALF_UP))
    if raw<1 and raw<Decimal('.5'): spaces=0
    result=f'2019년 별표 단순 참고산정 약 {spaces}대 (계산값 {_fmt(raw)}대)'
    if planned is None:
        result+=' · 설계 계획대수 확인 필요'
        severity='info'
    elif planned<spaces:
        result+=f' · 계획 {planned}대: 참고 산정치보다 부족 의심'
        severity='warning'
    else:
        result+=f' · 계획 {planned}대: 참고 산정치 이상'
        severity='ok'
    return _row('PZ04','부설주차장 산정',ref,f'별표 2 제{n}호: {typ} / 단순산식·비고 제6호 참고',
                f'시설면적 {_fmt(size)}㎡, 계획 {planned if planned is not None else "미입력"}대',
                result+' · 2019년 구판이므로 법정대수 확정 금지.',severity,
                '현행 별표·상위법령 및 적용일, 특수시설·완화, 주차 규격/기계식')


def _setback(values, data):
    ref='파주시 건축 조례 제28조 및 별표 3 (2025-03-20 조례, 별표 2024-04-02)'
    use=(values.get('primary_use') or '').strip(); zone=(values.get('zoning') or '').strip()
    road=number(data['building_road_width_m']); front=number(data['building_line_setback_m']); boundary=number(data['boundary_setback_m'])
    # Only a tightly-defined small single-family scope receives a numeric draft.
    if use not in ('단독주택','단독주택(단독)'):
        return _row('PZ05','대지 안의 공지',ref,'별표 3 건축선·인접경계 별도 기준',use or '주용도 미입력',
                    '상세 용도·용도별 면적·층수에 따라 기준이 달라지는 항목. 자동 수치 산정 보류.',need='세부 용도, 부속건축물, 층수, 배치도')
    edge=Decimal('1') if zone in ('제1종 전용주거지역','제2종 전용주거지역') else Decimal('.5')
    frontmin=Decimal('1') if road is not None and road>=6 else None
    bad=(boundary is not None and boundary<edge) or (frontmin is not None and front is not None and front<frontmin)
    desc=f'단독주택 기본 인접대지경계선 {edge}m 이상'
    if frontmin is not None:desc+=' / 너비 6m 이상 도로 접함: 건축선 1m 이상 기본'
    detail=f'인접경계 {boundary if boundary is not None else "미입력"}m / 건축선 {front if front is not None else "미입력"}m'
    return _row('PZ05','대지 안의 공지',ref,desc,detail,
                ('기본 이격거리 부족 의심.' if bad else '기본 이격 조건 비교(불완전) — ')+' 증축 기존건축물 특례·건축선 위치·도면 확인 필요.',
                'warning' if bad else 'info', '배치도, 법정 건축선, 인접대지경계선, 기존건축물 특례')


def assess(values, evidence=None, inputs=None):
    data=validate_inputs(inputs or {})
    return {'version':VERSION,'sources':{'zoning':ZONING_DATE,'building':BUILDING_DATE,'parking':PARKING_DATE},
            'notice':'2025년 도시계획·건축 조례와 2019년 주차장 별표의 제한적 참고 검토입니다. 현행·적용일·부칙 확인 전 자동 법정 적정 판정 금지.',
            'checks':[_zoning(values),_coverage_far(values,evidence or {},'bcr'),
                      _coverage_far(values,evidence or {},'far'),_parking(values,data),_setback(values,data)]}


def validate_decision(value, note, drawing_ref, criteria_ref):
    if value not in DECISIONS: raise ValueError('담당자 검토결과를 선택하세요.')
    if not all(isinstance(x,str) for x in (note,drawing_ref,criteria_ref)):raise ValueError('검토기록이 올바르지 않습니다.')
    if len(note)>2500 or len(drawing_ref)>500 or len(criteria_ref)>500:raise ValueError('검토의견 또는 근거가 너무 깁니다.')
    if value in ('적정(담당자 확인)','보완 필요') and not all(s.strip() for s in (note,drawing_ref,criteria_ref)):
        raise ValueError('적정·보완 판단은 도면근거·확인 법령·검토의견을 입력해야 합니다.')
    if value=='비적용(담당자 확인)' and not (note.strip() and criteria_ref.strip()):
        raise ValueError('비적용 판단에는 근거·사유가 필요합니다.')
    return {'review_result':value,'note':note.strip(),'drawing_ref':drawing_ref.strip(),'criteria_ref':criteria_ref.strip()}
