"""Read-only BIFF8/OLE2 reader for legacy .xls exports (Python stdlib only).

Scope: textual and numeric worksheet cells, not formulas, styles, macros,
or embedded objects. Rejects unsupported or malformed workbooks.
"""
import struct

END = 0xFFFFFFFE
FREE = 0xFFFFFFFF


def _u16(b, p=0):
    return struct.unpack_from('<H', b, p)[0]


def _u32(b, p=0):
    return struct.unpack_from('<I', b, p)[0]


class _OLE:
    def __init__(self, blob):
        if blob[:8] != bytes.fromhex('d0cf11e0a1b11ae1') or len(blob) < 512:
            raise ValueError('올바른 바이너리 XLS(OLE2) 파일이 아닙니다.')
        self.data = blob
        self.sector_size = 1 << _u16(blob, 30)
        self.mini_size = 1 << _u16(blob, 32)
        if self.sector_size not in (512, 4096) or self.mini_size != 64:
            raise ValueError('지원하지 않는 XLS 섹터 형식입니다.')
        ids = list(struct.unpack_from('<109I', blob, 76))
        next_difat = _u32(blob, 68)
        for _ in range(min(_u32(blob, 72), 100)):
            if next_difat in (END, FREE):
                break
            sector = self.sector(next_difat)
            ids.extend(struct.unpack_from('<%dI' % (self.sector_size // 4 - 1), sector))
            next_difat = _u32(sector, self.sector_size - 4)
        self.fat = []
        for sid in ids:
            if sid != FREE:
                self.fat.extend(struct.unpack('<%dI' % (self.sector_size // 4), self.sector(sid)))
        self.directory = self.chain(_u32(blob, 48))
        self.entries = []
        for p in range(0, len(self.directory), 128):
            entry = self.directory[p:p + 128]
            if len(entry) < 128 or entry[66] not in (2, 5):
                continue
            n = min(_u16(entry, 64), 64)
            name = entry[:max(0, n - 2)].decode('utf-16le', 'replace')
            self.entries.append((name, entry[66], _u32(entry, 116), struct.unpack_from('<Q', entry, 120)[0]))
        roots = [e for e in self.entries if e[1] == 5]
        if not roots:
            raise ValueError('XLS 파일에 Root Entry가 없습니다.')
        self.root = self.chain(roots[0][2])[:roots[0][3]]
        self.mini_fat = []
        mini_start = _u32(blob, 60)
        if mini_start not in (FREE, END) and _u32(blob, 64):
            raw = self.chain(mini_start)
            self.mini_fat = list(struct.unpack('<%dI' % (len(raw) // 4), raw))
        self.cutoff = _u32(blob, 56)

    def sector(self, sid):
        if sid >= (len(self.data) - 512) // self.sector_size:
            raise ValueError('XLS 섹터 위치가 파일 범위를 초과했습니다.')
        start = 512 + sid * self.sector_size
        return self.data[start:start + self.sector_size]

    def chain(self, start):
        visited = set()
        parts = []
        sid = start
        while sid not in (END, FREE):
            if sid in visited or len(visited) > 100000 or sid >= len(self.fat):
                raise ValueError('XLS 섹터 체인이 비정상적입니다.')
            visited.add(sid)
            parts.append(self.sector(sid))
            sid = self.fat[sid]
        return b''.join(parts)

    def workbook(self):
        for name, typ, sid, length in self.entries:
            if name in ('Workbook', 'Book') and typ == 2:
                if length >= self.cutoff:
                    return self.chain(sid)[:length]
                parts = []
                visited = set()
                while sid not in (END, FREE):
                    if sid in visited or sid >= len(self.mini_fat):
                        raise ValueError('XLS 미니섹터가 비정상적입니다.')
                    visited.add(sid)
                    start = sid * self.mini_size
                    parts.append(self.root[start:start + self.mini_size])
                    sid = self.mini_fat[sid]
                return b''.join(parts)[:length]
        raise ValueError('XLS Workbook 스트림을 찾지 못했습니다.')


def _records(raw, pos=0):
    while pos + 4 <= len(raw):
        kind, size = struct.unpack_from('<HH', raw, pos)
        start = pos
        pos += 4
        if pos + size > len(raw):
            return
        yield start, kind, raw[pos:pos + size]
        pos += size


class _SSTReader:
    def __init__(self, segments):
        self.segments = segments
        self.seg = 0
        self.at = 0

    def read(self, n):
        parts = []
        while n:
            if self.seg >= len(self.segments):
                raise ValueError('XLS 공유 문자열(SST)이 중간에 끊겼습니다.')
            seg = self.segments[self.seg]
            if self.at == len(seg):
                self.seg += 1
                self.at = 0
                continue
            take = min(n, len(seg) - self.at)
            parts.append(seg[self.at:self.at + take])
            self.at += take
            n -= take
        return b''.join(parts)

    def string(self):
        nchars = _u16(self.read(2))
        flags = self.read(1)[0]
        is_16bit = bool(flags & 1)
        rich_count = _u16(self.read(2)) if flags & 8 else 0
        ext_count = _u32(self.read(4)) if flags & 4 else 0
        characters = []
        remain = nchars
        while remain:
            if self.seg >= len(self.segments):
                raise ValueError('XLS SST 문자열이 중간에 끊겼습니다.')
            available = len(self.segments[self.seg]) - self.at
            if available == 0:
                self.seg += 1
                self.at = 0
                if self.seg >= len(self.segments):
                    raise ValueError('XLS SST 연속 레코드가 없습니다.')
                is_16bit = bool(self.read(1)[0] & 1)
                continue
            byte_width = 2 if is_16bit else 1
            count = min(remain, available // byte_width)
            if not count:
                raise ValueError('XLS SST 문자열 경계가 유효하지 않습니다.')
            chars = self.read(count * byte_width)
            characters.append(chars.decode('utf-16le' if is_16bit else 'latin-1', 'replace'))
            remain -= count
        if rich_count:
            self.read(rich_count * 4)
        if ext_count:
            self.read(ext_count)
        return ''.join(characters)


def _shared_strings(records):
    for i, (_, kind, data) in enumerate(records):
        if kind != 0xFC:
            continue
        segments = [data]
        for _, subsequent, more in records[i + 1:]:
            if subsequent != 0x3C:
                break
            segments.append(more)
        reader = _SSTReader(segments)
        counts = reader.read(8)
        unique = _u32(counts, 4)
        if unique > 100000:
            raise ValueError('XLS의 공유 문자열 수가 너무 많습니다.')
        return [reader.string() for _ in range(unique)]
    return []


def _rk(n):
    if n & 2:
        val = struct.unpack('<i', struct.pack('<I', n))[0] >> 2
    else:
        val = struct.unpack('<d', struct.pack('<Q', (n & 0xFFFFFFFC) << 32))[0]
    return val / 100 if n & 1 else val


def read_xls_cells(data, limit_rows=10000):
    """Return (sheet name, row number, column index, display value) tuples."""
    if len(data) > 15 * 1024 * 1024:
        raise ValueError('XLS는 최대 15MB까지 읽습니다.')
    raw = _OLE(data).workbook()
    records = list(_records(raw))
    strings = _shared_strings(records)
    sheets = []
    for _, kind, record in records:
        if kind == 0x85 and len(record) >= 8:
            offset, visible, typ, count, flags = struct.unpack_from('<IBBBB', record)
            if typ == 0:
                start = 8
                end = start + count * (2 if flags & 1 else 1)
                name = record[start:end].decode('utf-16le' if flags & 1 else 'latin-1', 'replace')
                sheets.append((offset, name))
    if len(sheets) > 30:
        raise ValueError('XLS 시트 수가 제한을 초과했습니다.')
    for off, name in sheets:
        for _, kind, cell in _records(raw, off):
            if kind == 0x0A:
                break
            try:
                if kind == 0xFD and len(cell) >= 10:
                    row, col, _, idx = struct.unpack_from('<HHHI', cell)
                    value = strings[idx]
                    if row < limit_rows and value.strip():
                        yield name, row + 1, col, value.strip()
                elif kind == 0x203 and len(cell) >= 14:
                    row, col = struct.unpack_from('<HH', cell)
                    value = struct.unpack_from('<d', cell, 6)[0]
                    if row < limit_rows:
                        yield name, row + 1, col, str(int(value) if value.is_integer() else value)
                elif kind == 0x27e and len(cell) >= 10:
                    row, col = struct.unpack_from('<HH', cell)
                    value = _rk(_u32(cell, 6))
                    if row < limit_rows:
                        yield name, row + 1, col, str(int(value) if float(value).is_integer() else value)
                elif kind == 0xBD and len(cell) >= 12:
                    row, first_col = struct.unpack_from('<HH', cell)
                    last_col = _u16(cell, len(cell) - 2)
                    for col in range(first_col, last_col + 1):
                        value = _rk(_u32(cell, 4 + 6 * (col - first_col) + 2))
                        if row < limit_rows:
                            yield name, row + 1, col, str(int(value) if float(value).is_integer() else value)
                elif kind == 0x204 and len(cell) >= 8:
                    row, col, _, size = struct.unpack_from('<HHHH', cell)
                    text = cell[8:8 + size].decode('cp949', 'replace').strip()
                    if text and row < limit_rows:
                        yield name, row + 1, col, text
            except (ValueError, IndexError, struct.error):
                continue
