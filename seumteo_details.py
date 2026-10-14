"""Extract *draft* building/floor details from Seumteo forms.

Never infer unchecked boxes; do not confuse the overall summary with areas
per building, increased area, or per-floor areas. Source line is mandatory.
"""
import re

WORKS = ('신축', '증축', '개축', '재축', '이전', '대수선', '용도변경', '허가사항 변경', '신고사항 변경')
NUM = r'\d[\d,]*(?:\.\d+)?'


def normal(s):
    return re.sub(r'\s+', '', str(s))


def src(line):
    return {'line': line['n'], 'where': line['where'], 'evidence': line['text'][:400]}


def item(value, line):
    return {'value': str(value).strip(), 'source': src(line)}


def normalize_number(s):
    if re.fullmatch(NUM, str(s).strip()):
        return str(s).strip().replace(',', '')
    return ''


def selected_work_type(lines):
    """Trust only a recognizable checked mark in the building-type control.

    The plain title '건축구분' + unmarked options does not identify selection.
    The check may be a PDF vector drawing and therefore invisible to text parsing.
    """
    first = [x for x in lines if x['where'].startswith(('1쪽', 'Page 1 '))]
    matched = []
    for row in first:
        t = row['text']
        if re.search(r'^\s*건축\s*구분\s*[:：]\s*', t):
            m = re.search(r'건축\s*구분\s*[:：]\s*(' + '|'.join(WORKS) + r')\s*$', t)
            if m:
                matched.append((m.group(1), row))
        # Only accept an explicit marked checkbox immediately before its label.
        for m in re.finditer(r'(?:\[\s*[√✓✔xX]\s*\]|☑|☒)\s*(' + '|'.join(WORKS) + r')(?=\s|$|\|)', t):
            # The explanatory '√ 표시' sentence does not contain a checkbox.
            if '해당하는 곳' not in t:
                matched.append((m.group(1), row))
    if len(matched) == 1:
        value, line = matched[0]
        return {'value': value, 'source': src(line)}
    return None


def page_of(line):
    place = line['where']
    m = re.match(r'(?:Page\s+)?(\d+)(?:쪽|\s)', place)
    return int(m.group(1)) if m else None


def building_xls(lines):
    buildings = []
    grouped = {}
    for line in lines:
        page = page_of(line)
        if page is not None:
            grouped.setdefault(page, []).append(line)
    for page, page_lines in grouped.items():
        if not any('동별개요' in normal(l['text']) for l in page_lines):
            continue
        # One BIFF8 page normally represents one building, but honor repeated headings.
        current = None
        for line in page_lines:
            cells = line.get('cells') or []
            mid = next((k for k, c in enumerate(cells) if re.search('동명칭및번호', normal(c['text']))), None)
            if mid is not None:
                label_col = cells[mid]['col']
                proposed = next((c['text'].strip() for c in cells[mid+1:] if c['text'].strip()), '')
                prev = next((c['text'].strip() for c in reversed(cells[:mid]) if c['text'].strip()), '')
                if not proposed: continue
                current = {'building_name': proposed, 'existing': {}, 'proposed': {},
                           'source': src(line), 'notes': ['동별 표의 신청 건축물(우측)과 기존 건축물(좌측)을 분리했습니다.']}
                if prev: current['existing']['building_name'] = item(prev,line)
                buildings.append(current)
                continue
            if current is None: continue
            labels = {'주용도':'main_use','주구조':'structure','※건축면적(㎡)':'building_area_m2',
                      '※연면적(㎡)':'floor_area_m2','높이(m)':'height_m'}
            for k,cell in enumerate(cells):
                key = labels.get(normal(cell['text']))
                if not key: continue
                main_col = cell['col']
                prev = [c for c in cells[:k] if c['text'].strip() and c['col'] < main_col]
                nexts = [c for c in cells[k+1:] if c['text'].strip() and c['col'] > main_col]
                if prev:
                    candidate = prev[-1]['text'].strip()
                    if key not in ('building_area_m2','floor_area_m2','height_m') or normalize_number(candidate):
                        current['existing'][key] = item(normalize_number(candidate) if key.endswith('_m2') or key=='height_m' else candidate,line)
                if nexts:
                    candidate = nexts[0]['text'].strip()
                    if key not in ('building_area_m2','floor_area_m2','height_m') or normalize_number(candidate):
                        current['proposed'][key] = item(normalize_number(candidate) if key.endswith('_m2') or key=='height_m' else candidate,line)
    return buildings


def building_pdf(lines):
    grouped = {}
    for line in lines:
        page=page_of(line)
        if page is not None:
            grouped.setdefault(page, []).append(line)
    buildings=[]
    for page,rows in grouped.items():
        if not any('동별개요' in normal(r['text']) for r in rows): continue
        current=None
        for line in rows:
            t=line['text']; s=normal(t)
            if '동명칭및번호' in s and '주건축물제' in s:
                names=re.findall(r'주건축물제\d+동',s)
                if not names: continue
                current={'building_name':names[-1], 'existing':{}, 'proposed':{},
                         'source':src(line), 'notes':['※ 표시는 증축 시 증가부분만 기재할 수 있으므로 전체 개요와 합산하지 않습니다.']}
                if len(names)>1: current['existing']['building_name']=item(names[0],line)
                buildings.append(current)
                continue
            if not current: continue
            labels=[('※건축면적(㎡)','building_area_m2'),('※연면적(㎡)','floor_area_m2'),
                    ('주구조','structure'),('주용도','main_use'),('높이(m)','height_m')]
            for label,key in labels:
                if label not in s: continue
                # Split using original text: whitespace tolerated between label symbols.
                label_regex=re.escape(label).replace(r'\※',r'\s*※\s*').replace(r'\ ',r'\s*')
                # Instead, normalized string has one unique label.
                left,right=s.split(label,1)
                if key.endswith('_m2') or key=='height_m':
                    x=re.search(r'(' + NUM + r')$',left)
                    y=re.match(r'^(' + NUM + r')',right)
                    if x: current['existing'][key]=item(normalize_number(x.group(1)),line)
                    if y: current['proposed'][key]=item(normalize_number(y.group(1)),line)
                else:
                    if left and not any(k in left for k in ('※','⑦','⑩')) and not left.endswith(']'):
                        current['existing'][key]=item(left,line)
                    if right and not right.startswith(('※','⑦','⑩')):
                        current['proposed'][key]=item(right,line)
                break
    return buildings


def _floor_key(cells, label):
    return next((c['col'] for c in cells if normal(c['text'])==label),None)


def floors_xls(lines):
    rows=[]; active=False; building_name=''
    for line in lines:
        text=line['text']; compact=normal(text)
        if '층별개요' in compact and ('Ⅲ' in text or text.strip().startswith('III')):
            active=True;continue
        if active and '대수선개요' in compact:
            active=False;continue
        if not active:continue
        name=re.search(r'주건축물제\d+동',text)
        if name and '동명칭' in compact:
            building_name=name.group(0)
        cells=line.get('cells') or []
        # These columns are identified by Ⅲ.층별개요 table headings in Seumteo XLS;
        # we still require both an explicit operation and floor to avoid a guess.
        for i,c in enumerate(cells):
            if c['text'].strip() not in WORKS[:6]:continue
            if i==0 or i+1>=len(cells):continue
            floor=cells[i-1]['text'].strip()
            if not re.fullmatch(r'-?\d+',floor):continue
            following=cells[i+1:]
            if len(following)<3: continue
            candidate=normalize_number(following[-1]['text'])
            if not candidate:continue
            proposed={'structure':following[0]['text'].strip(),
                      'use':following[1]['text'].strip(),
                      'area_m2':candidate}
            existing={}
            # For existing parts, only capture values in explicit left cells.
            prior=cells[:i-1]
            if prior:
                old_area=normalize_number(prior[-1]['text'])
                if old_area:existing['area_m2']=old_area
            rows.append({'building_name':building_name,'floor':floor,
                         'work_type':c['text'].strip(), 'existing':existing,
                         'proposed':proposed,'source':src(line), 'review_required':False})
    return rows


def floors_pdf(lines):
    rows=[];active=False;building_name=''; block=[]
    def commit():
        if not block: return
        start=block[0]
        t=start['text']
        m=re.search(r'(?<!\d)(?:(' + NUM + r')\s+)?(-\s*\d+|\d+)\s+(신축|증축|개축|재축|이전|대수선)\s+(.*)',t)
        if not m:return
        existing_area=normalize_number(m.group(1)) if m.group(1) else ''
        floor=m.group(2).replace(' ','')
        body=' '.join(x['text'] for x in block)
        numbers=[]
        for num in re.finditer(r'(?<![가-힣A-Za-z0-9])(' + NUM + r')(?![가-힣A-Za-z0-9])',body):
            numbers.append(num.group(1))
        # Proposed area is accepted only when it is at the end of the last record
        # or on a final isolated numeric line, not when another descriptor follows.
        area=''
        area_line=None
        for trial in block[1:]:
            end_match=re.search(r'(?<![가-힣A-Za-z0-9])(' + NUM + r')\s*$',trial['text'].strip())
            if end_match:
                area=normalize_number(end_match.group(1))
                area_line=trial
        # Last numeric token is a draft only; never infer an entire floor subtotal.
        prop={'area_m2':area} if area else {}
        existing={'area_m2':existing_area} if existing_area else {}
        rows.append({'building_name':building_name,'floor':floor,'work_type':m.group(3),
                     'existing':existing,'proposed':prop,'source':src(start),
                     'review_required':True,
                     'area_source':src(area_line) if area_line else None})
    for line in lines:
        compact=normal(line['text'])
        if '층별개요' in compact and 'Ⅲ' in line['text']:
            commit();block=[];active=True; continue
        if active and ('대수선개요' in compact or 'Ⅳ.' in line['text']):
            commit();block=[];active=False;continue
        if not active:continue
        if '동명칭및번호' in compact:
            match=re.search(r'주건축물제\d+동',line['text'])
            if match:building_name=match.group(0)
        if re.search(r'(?<!\d)(?:(?:' + NUM + r')\s+)?(?:-\s*\d+|\d+)\s+(?:신축|증축|개축|재축|이전|대수선)\s',line['text']):
            commit();block=[line]
        elif block:
            if len(block)<25:block.append(line)
    commit()
    return rows


def extract_details(lines):
    is_xls=any('cells' in l for l in lines)
    buildings=building_xls(lines) if is_xls else building_pdf(lines)
    floors=floors_xls(lines) if is_xls else floors_pdf(lines)
    work=selected_work_type(lines)
    return {'schema_version':1, 'work_type':work,
            'work_type_status':'evidence' if work else 'confirm_required',
            'buildings':buildings[:80], 'floors':floors[:300],
            'warnings': ([] if work else ['건축구분 선택표시를 텍스트로 확인하지 못했습니다. 담당자가 신청서 원본을 보고 직접 선택해야 합니다.'])
              + (['PDF 층별 정보는 줄바꿈과 좌우 열 혼재 가능성이 있으므로 행별 원문 대조가 필요합니다.'] if not is_xls and floors else [])}
