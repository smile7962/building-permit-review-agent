"""Explicit legal/drawing review guidance. No automatic legal compliance findings."""
EXAMPLES = {
    'D019': {'title':'대지 접도 길이','law':'「건축법」 제44조 및 관련 시행령',
        'rule':'도로에 2m 이상 접하는 것이 원칙입니다. 단서·제2항·시행령상 예외와 실제 도로의 법적 지위 확인 필요.',
        'drawing':'배치도: 도로의 법적 지위, 대지 접도길이(m), 해당 도면번호','unit':'m'},
    'D038': {'title':'건폐율','law':'「건축법」 제55조, 「국토계획법」 제77조 및 위임 조례',
        'rule':'건축면적 / 대지면적 × 100. 필지에 적용되는 상한은 지역·특례·시행일 검증 후 입력해야 합니다.',
        'drawing':'건축개요 및 면적산출표: 산정 건축면적, 대지면적, 산정 제외·완화 근거','unit':'%'},
    'D039': {'title':'용적률','law':'「건축법」 제56조, 「국토계획법」 제78조 및 위임 조례',
        'rule':'용적률 산정용 연면적 / 대지면적 × 100. 용적률 산정 제외면적과 적용 상한 확인 필요.',
        'drawing':'면적산출표: 용적률 산정용 연면적과 제외면적 내역','unit':'%'},
    'D070': {'title':'부설주차장 필요 대수','law':'「주차장법」 제19조, 같은 법 시행령 및 파주시 관련 조례',
        'rule':'필요 대수는 용도·면적·증축/용도변경·기존 대수에 따라 별도 산정합니다. 자동 법정대수 산정은 미구현입니다.',
        'drawing':'주차계획도·주차대수 산정서: 계획 대수·규격·기존 대수','unit':'대'},
    'D041': {'title':'정북방향 일조 이격','law':'「건축법」 제61조제1항 및 「건축법 시행령」 제86조',
        'rule':'전용·일반주거지역 여부 확인이 선행돼야 합니다. 높이별 이격기준·예외는 현행 시행령 원문 검증 필요.',
        'drawing':'배치도·입면도·단면도: 정북 이격, 건축물 높이·대지 고저','unit':'m'},
    'D044': {'title':'구조안전','law':'「건축법」 제48조 및 관계 하위 법령',
        'rule':'구조·층수·규모·용도에 따른 구조안전 확인 대상과 제출서류 조건을 현행 원문으로 확인해야 합니다.',
        'drawing':'구조도·구조안전확인서·구조계산서(해당 시)','unit':''},
    'D051': {'title':'피난계단 등','law':'「건축법」 제49조, 시행령 및 피난·방화구조 기준 규칙',
        'rule':'용도·층수·규모와 피난구조 요건에 따라 세부 기준이 달라집니다. 정량 기준을 임의 생성하지 않습니다.',
        'drawing':'각 층 평면도·피난계획도·계단상세도','unit':''},
}
def guidance(item):
    rule = EXAMPLES.get(item['id'])
    if rule:
        return {**rule,'verification':'기본 법령 근거 후보 · 현행 시행일·예외·지자체 기준 담당자 확인 필요'}
    return {'title':item['title'],'law':item['basis'],
            'rule':'개별 법정 수치 및 적용조건 검증 전: 관련 원문·별표·예외를 담당자가 확인하세요.',
            'drawing':'확인자료: '+', '.join(item.get('required_docs') or ['신청서','설계도서']),
            'unit':'','verification':'세부 기준 미검증(자동 적정 판정 금지)'}

def validate_verification(review_result,drawing_value,drawing_ref,criteria_ref,note):
    options=('미검토','적정(담당자 확인)','보완 필요','추가 확인','비적용(담당자 확인)')
    if review_result not in options:
        raise ValueError('담당자 검토결과를 올바르게 선택하세요.')
    for name,val,limit in [('설계 확인값',drawing_value,250),('도면 근거',drawing_ref,500),
                           ('법령 기준 출처',criteria_ref,500)]:
        if not isinstance(val,str) or len(val)>limit:
            raise ValueError(f'{name}은 {limit}자 이하의 문자열이어야 합니다.')
    if review_result in ('적정(담당자 확인)','보완 필요'):
        if not drawing_ref.strip() or not criteria_ref.strip() or not note.strip():
            raise ValueError('담당자 적정·보완 판단에는 도면 근거, 법령 기준 출처, 검토의견이 필요합니다.')
    if review_result=='비적용(담당자 확인)' and (not criteria_ref.strip() or not note.strip()):
        raise ValueError('비적용 판단에는 법령 기준 근거와 비적용 사유가 필요합니다.')
    return {'review_result':review_result,'drawing_value':drawing_value.strip(),
            'drawing_ref':drawing_ref.strip(),'criteria_ref':criteria_ref.strip()}
