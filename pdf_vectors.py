"""Conservative Seumteo PDF vector checkbox reader; no OCR or external AI."""
import re

OPTIONS = ('신축', '증축', '개축', '재축', '이전', '대수선')


def _text_positions(page):
    glyphs = []

    def visit(text, cm, tm, font, size):
        if not text or not text.strip():
            return
        if any(abs(float(cm[i])-value)>0.001 for i,value in (
            (0,1),(1,0),(2,0),(3,1),(4,0),(5,0))):
            return
        x,y=float(tm[4]),float(tm[5])
        if 0 <= x <= 1200 and 0 <= y <= 1200:
            glyphs.append((x,y,text))

    page.extract_text(visitor_text=visit)
    rows={}
    for x,y,text in glyphs:
        rows.setdefault(round(y),[]).append((x,text))
    headings=[]
    labels=[]
    for y,parts in rows.items():
        parts.sort(key=lambda item:item[0])
        text=''.join(s for _,s in parts)
        if '건축구분' in text.replace(' ',''):
            headings.append(y)
        for option in OPTIONS:
            start=text.find(option)
            if start<0: continue
            cursor=0
            for x,t in parts:
                if cursor==start:
                    labels.append((option,x,y))
                    break
                cursor+=len(t)
    return [(option,x,y) for option,x,y in labels
            if any(abs(y-h)<=25 for h in headings)]


def _tiny_filled_paths(page):
    from pypdf.generic import ContentStream
    ops=ContentStream(page.get_contents(),page.pdf).operations
    points=[]
    transformed=False
    rectangles=[]
    for args,operator in ops:
        if operator==b'cm':
            if [round(float(v),4) for v in args]!=[1,0,0,1,0,0]:
                transformed=True
        elif operator==b'm':
            points=[(float(args[0]),float(args[1]))] if len(args)==2 else []
        elif operator in (b'l',b'c',b'v',b'y'):
            vals=[float(v) for v in args]
            if len(vals)%2==0:
                points.extend(zip(vals[::2],vals[1::2]))
        elif operator in (b'f',b'f*',b'F'):
            if points and not transformed:
                xx,yy=zip(*points)
                l,r,b,t=min(xx),max(xx),min(yy),max(yy)
                if 2.5 <= r-l <=9 and 2.5 <=t-b<=9:
                    rectangles.append((l,r,b,t))
            points=[]
        elif operator in (b'S',b's',b'B',b'B*',b'b',b'b*',b'n'):
            points=[]
    return rectangles


def checked_work_type(page):
    """Return one geometrically confirmed selection, or None."""
    labels=_text_positions(page)
    if not labels: return None
    shapes=_tiny_filled_paths(page)
    selected={}
    for option,x,y in labels:
        for l,r,b,t in shapes:
            mx,my=(l+r)/2,(b+t)/2
            if 9 <= x-mx <=26 and -1 <=my-y<=15:
                selected[option]=(l,b)
    if len(selected)!=1: return None
    option,(x,y)=next(iter(selected.items()))
    return {'value':option,
            'evidence':f'PDF 첫쪽 건축구분 체크 도형 좌표 ({x:.1f}, {y:.1f})'}
