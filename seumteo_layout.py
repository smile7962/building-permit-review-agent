"""Structure-aware, strictly sourced extraction for real Seumteo application forms.

The application form's entire-site summary is authoritative for overall fields.
Building-level and floor-level areas must not overwrite this summary.
No inference of checkbox selections if their marks are not machine-readable.
"""
import re

NUM = r'([0-9][0-9,]*(?:\.[0-9]+)?)'


def norm(s):
    return re.sub(r'\s+', '', str(s)).replace('％', '%').replace('㎥', 'm3')


def is_number(value):
    return bool(re.fullmatch(r'\s*[0-9][0-9,]*(?:\.[0-9]+)?\s*', str(value)))


def _value(key, value):
    value = str(value).strip()
    if key in ('site_area_m2', 'building_area_m2', 'total_floor_area_m2',
               'building_coverage_percent', 'floor_area_ratio_percent',
               'above_ground_floors', 'underground_floors', 'building_count', 'parking_spaces'):
        m = re.search(NUM, value)
        return m.group(1).replace(',', '') if m else ''
    return value[:1500]


def parse_seumteo(lines, allowed_keys):
    values, sources = {}, {}

    def set_value(key, value, line, explanation='세움터 구조 분석'):
        if key not in allowed_keys or key in values or not value:
            return
        clean = _value(key, value)
        if not clean:
            return
        values[key] = clean
        sources[key] = {
            'line': line['n'], 'where': line['where'], 'evidence': line['text'],
            'method': explanation, 'edited_by_user': False
        }

    # Form title, never a file name, determines the submission type.
    first_page = [x for x in lines if x['where'].startswith('1쪽') or
                  x['where'].startswith('Page 1 ')]
    header = norm(' '.join(x['text'] for x in first_page[:18]))
    if re.search(r'\(변경\)허가신청서', header):
        set_value('permit_type', '건축허가', first_page[0])
    elif re.search(r'\(변경\)신고서', header):
        set_value('permit_type', '건축신고', first_page[0])

    # BIFF XLS retains exact cell grid including original column indices.
    for row in first_page:
        cells = row.get('cells', [])
        if not cells:
            continue
        for i, cell in enumerate(cells):
            label = norm(cell['text'])
            for key, labels in {
                'site_area_m2':['대지면적'],
                'building_area_m2':['건축면적'],
                'total_floor_area_m2':['연면적합계'],
                'building_coverage_percent':['건폐율'],
                'floor_area_ratio_percent':['용적률'],
                'primary_use':['⑤주용도', '주용도'],
                'building_count':['주건축물수'],
                'parking_spaces':['총주차대수'],
                'zoning':['용도지역']
            }.items():
                if key in values or label not in labels:
                    continue
                for following in cells[i + 1:]:
                    v = following['text'].strip()
                    if re.fullmatch(r'㎡|m²|동|대|%|％|세대|가구|호|\d*㎡', v):
                        continue
                    if key in ('primary_use', 'zoning'):
                        if len(v) >= 2 and not re.match(r'^(세대/|주건축물|부속건축물|총주차대수|건축면적|건폐율|용적률)', v):
                            set_value(key, v, row)
                        break
                    if re.fullmatch(NUM, v):
                        set_value(key, v, row)
                        break
                    if v and (key == 'building_count' and re.fullmatch(r'\d+\s*동', v)):
                        set_value(key, v, row)
                        break
                    if re.search(r'(면적|용도|건폐율|용적률|주건축물|주차대수|부속건축물)', v):
                        break

    # The site location in an XLS template is a value in the same row as
    # ③대지조건 / 대지위치. Join the cadastral number only when separately labelled.
    if 'site_address' not in values:
        for i, row in enumerate(first_page):
            cells = row.get('cells', [])
            for j, cell in enumerate(cells):
                if norm(cell['text']) != '대지위치':
                    continue
                place = next((c['text'] for c in cells[j + 1:]
                              if re.search(r'(특별시|광역시|경기도|강원|충청|전라|경상|세종|제주)', c['text'])), '')
                number = ''
                if i + 1 < len(first_page):
                    row_after = first_page[i + 1]
                    after_cells = row_after.get('cells', [])
                    for n, following in enumerate(after_cells):
                        if norm(following['text']) == '지번':
                            number = next((c['text'].strip() for c in after_cells[n + 1:]
                                           if re.fullmatch(r'\d+\s*(?:-\s*\d+)?', c['text'].strip())), '')
                            break
                if place:
                    set_value('site_address', place + ((' ' + number) if number else ''), row)
                break

    # XLS building summary (Page 3); text/numeric cells are positioned
    # distinctly. Never treat existing-building left-side columns as proposed.
    for row in lines:
        if not row['where'].startswith('Page 3 '):
            continue
        cells = row.get('cells', [])
        for i, cell in enumerate(cells):
            label = norm(cell['text'])
            if label == '주구조' and 'structure' not in values:
                next_cell = next((c['text'] for c in cells[i + 1:]
                                  if '구조' in c['text'] and c['text'].strip() != '주구조'), '')
                if next_cell:
                    set_value('structure', next_cell, row)
            if label == '층수' and 'above_ground_floors' not in values:
                right = cells[i + 1:]
                for j, c in enumerate(right):
                    if norm(c['text']) == '지상:':
                        val = next((x['text'] for x in right[j + 1:]
                                    if re.fullmatch(r'\d+', x['text'].strip())), '')
                        if val:
                            set_value('above_ground_floors', val, row)
                        break

    # For PDF, only the form page-1 summary is read. Later page floor / building
    # area fragments are intentionally ignored to avoid overwriting total areas.
    page_text = '\n'.join(row['text'] for row in first_page)
    start = re.search(r'Ⅰ\.?\s*전체\s*개요', page_text)
    summary = page_text[start.end():] if start else page_text
    flat = norm(summary)
    for key, labels in {
        'site_area_m2':['대지면적'],
        'building_area_m2':['건축면적'],
        'total_floor_area_m2':['연면적합계'],
        'building_coverage_percent':['건폐율'],
        'floor_area_ratio_percent':['용적률']
    }.items():
        if key in values:
            continue
        for label in labels:
            # For total floor area, exclude '연면적합계(용적률산정용)'.
            pattern = re.escape(label) + r'(?!\()' + NUM
            match = re.search(pattern, flat)
            if match:
                for row in first_page:
                    if label in norm(row['text']):
                        set_value(key, match.group(1), row)
                        break
                break

    # The primary use is often printed directly BELOW ⑤주용도 instead of after
    # a colon. Preserve its own first-page source, not a later building use.
    if 'primary_use' not in values:
        for index, line in enumerate(first_page):
            if re.match(r'^\s*⑤\s*주용도\s*$', line['text']):
                for following in first_page[index + 1:index + 4]:
                    val = following['text'].strip()
                    if val and not re.search('세대/호|총주차|가구수|주택을포함', norm(val)):
                        set_value('primary_use', val, following)
                        break

    # PDF first-page zoning is often printed on the line AFTER its label.
    # Do not read any later-page mentions in legal guidance as zoning values.
    if 'zoning' not in values:
        for i, row in enumerate(first_page):
            if norm(row['text']) == '용도지역':
                if i + 1 < len(first_page):
                    candidate = first_page[i + 1]['text'].strip()
                    if re.fullmatch(r'(?:[가-힣0-9]+지역)(?:/[가-힣0-9]+지역)*', candidate):
                        set_value('zoning', candidate, first_page[i + 1])
                break

    # Total planned parking on the form summary (not by individual parking
    # section or parking area in a floor description).
    if 'parking_spaces' not in values:
        for i, row in enumerate(first_page):
            if '총주차대수' in norm(row['text']):
                tail = first_page[i:i + 6]
                for candidate in tail:
                    m = re.search(NUM + r'\s*대(?:\s|$)', candidate['text'])
                    if m:
                        set_value('parking_spaces', m.group(1), candidate)
                        break
                break

    # XLS: identity/location on a merged cell may be in the following row.
    if 'site_address' not in values:
        for i, row in enumerate(first_page):
            if re.fullmatch(r'\s*대지\s*위치\s*', row['text']):
                for cand in first_page[i+1:i+4]:
                    txt = cand['text'].strip()
                    if re.search(r'(특별시|광역시|경기도|강원|충청|전라|경상|세종|제주)', txt):
                        set_value('site_address', txt, cand)
                        break
                break

    # Proposed structure/floor counts are from II. 동별 개요 and are only
    # recognized if clearly adjacent to the corresponding labels.
    for index, row in enumerate(lines):
        s = norm(row['text'])
        if 'above_ground_floors' in allowed_keys and 'above_ground_floors' not in values:
            m = re.search(r'지하:?\s*(\d+)\s*층?\s*지상:?\s*(\d+)\s*층', s)
            if m:
                set_value('underground_floors', m.group(1), row)
                set_value('above_ground_floors', m.group(2), row)
            else:
                m = re.search(r'지하:\s*층\s*지상:\s*(\d+)층', s)
                if m:
                    set_value('above_ground_floors', m.group(1), row)
    return values, sources
