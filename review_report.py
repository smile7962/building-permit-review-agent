"""Read-only review sheet preview: only explicit human decisions and outstanding alerts."""
from review_guidance import guidance

def preview(case):
    legal=case.get('legal_review')
    if not legal:
        return {'status':'검토 전','rows':[],'summary':{},'notice':'STEP 02 검토항목을 먼저 생성하세요.'}
    outdated=bool(legal.get('outdated') or legal.get('screening_needs_refresh') or not case.get('confirmed_at'))
    rows=[]
    for item in legal.get('items',[]):
        if item.get('level')=='대표항목':continue
        signal=item.get('screening',{})
        check=signal.get('check') or {}
        is_alert=check.get('attention')=='warning'
        verdict=item.get('review_result') or '미검토'
        if verdict=='미검토' and item.get('progress')=='미착수' and not is_alert:continue
        g=guidance(item)
        rows.append({'id':item['id'],'title':item['title'],'group':item['group'],
            'law':g['law'],'criterion':g['rule'],'comparison':check.get('result',''),
            'drawing_value':item.get('drawing_value',''),'drawing_ref':item.get('drawing_ref',''),
            'criteria_ref':item.get('criteria_ref',''),'review_result':verdict,
            'note':item.get('note',''),'attention':is_alert,'reviewed_at':item.get('reviewed_at')})
    summary={'적정':sum(x['review_result']=='적정(담당자 확인)' for x in rows),
        '보완':sum(x['review_result']=='보완 필요' for x in rows),
        '추가 확인':sum(x['review_result']=='추가 확인' for x in rows),
        '비적용':sum(x['review_result']=='비적용(담당자 확인)' for x in rows),
        '미검토·경고':sum(x['review_result']=='미검토' for x in rows)}
    return {'status':'재검토 필요' if outdated else ('기록 확정' if legal.get('confirmed_at') else '검토 초안'),
        'case_id':case.get('case_id'),'values':case.get('values',{}),
        'rows':rows,'summary':summary,
        'notice':'검토조서 미리보기 · 확정된 법적 적합성 판단이 아닙니다. 법령 시행일, 적용조건 및 도면 원문은 담당자가 확인하세요.'}
