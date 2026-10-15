"""Conservative BIFF8 Excel picture/checkbox position recognizer."""
import re
import struct
from xls_legacy import _OLE, _records, read_xls_cells

OPTIONS = ('신축', '증축', '개축', '재축', '이전', '대수선')


def _sheets(records):
    out=[]
    for _,kind,buf in records:
        if kind==0x85 and len(buf)>=8:
            off,vis,typ,count,flags=struct.unpack_from('<IBBBB',buf)
            if typ==0:
                end=8+count*(2 if flags&1 else 1)
                name=buf[8:end].decode('utf-16le' if flags&1 else 'latin-1','replace')
                out.append((off,name))
    return out


def _anchors(raw,offset):
    pending=None
    for _,kind,buf in _records(raw,offset):
        if kind==0x0A: break
        if kind==0x00EC:
            pending=None
            marker=b'\x10\xf0\x12\x00\x00\x00'
            n=buf.find(marker)
            if n>=0 and n+24<=len(buf):
                flags,col1,dx1,row1,dy1,col2,dx2,row2,dy2=struct.unpack_from('<9H',buf,n+6)
                if 0<=col1<=col2<=256 and 0<=row1<=row2<65536:
                    pending=(col1,col2,row1,row2)
        elif kind==0x005D:
            if pending is not None and len(buf)>=8 and buf[:4]==b'\x15\x00\x12\x00':
                if struct.unpack_from('<H',buf,4)[0]==8:
                    yield pending
            pending=None
        else:
            pending=None


def _option_for_anchor(cells,anchor):
    start,end,_,_=anchor
    names=[]
    for i,cell in enumerate(cells):
        if not re.fullmatch(r'\[\s*\]',cell['text']):
            continue
        nxt=next((x for x in cells[i+1:] if x['text'].strip()),None)
        if nxt and nxt['text'].strip() in OPTIONS:
            if cell['col']<start<=end<nxt['col']:
                names.append(nxt['text'].strip())
    return names


def checked_work_type(data):
    """Trust a unique first-page picture anchored in one checkbox slot only."""
    if len(data)>15*1024*1024: raise ValueError('XLS 크기 제한 초과')
    raw=_OLE(data).workbook()
    records=list(_records(raw))
    table={}
    for sheet,row,col,value in read_xls_cells(data):
        if row<=30:
            table.setdefault((sheet,row),[]).append({'col':col,'text':value})
    selected=[]
    for offset,name in _sheets(records):
        if not re.fullmatch(r'Page\s*1',name,flags=re.IGNORECASE):
            continue
        headers=[(row,sorted(cells,key=lambda c:c['col']))
                 for (sheet,row),cells in table.items()
                 if sheet==name and any('건축구분' in c['text'].replace(' ','') for c in cells)]
        for anchor in _anchors(raw,offset):
            for row,cells in headers:
                if min(abs(anchor[2]-row),abs(anchor[2]+1-row))>1:
                    continue
                for choice in _option_for_anchor(cells,anchor):
                    selected.append((choice,anchor))
    if len(selected)!=1: return None
    choice,anchor=selected[0]
    return {'value':choice,
            'evidence':f'XLS Page 1 건축구분 선택 도형 셀 위치: 열 {anchor[0]}~{anchor[1]}, 행 {anchor[2]}~{anchor[3]}'}
