"""One active case in a local SQLite .bcase; no central case database."""
import json
import os
import sqlite3
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
APPLICATION_ID = 0x42434153  # BCAS: distinguish our SQLite file


def now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class CaseStore:
    def __init__(self, workspace, field_keys, master_version):
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.path = self.workspace / "active.bcase"
        self.field_keys = set(field_keys)
        self.master_version = master_version
        self.lock = threading.RLock()
        if not self.path.exists():
            self.new_case()
        else:
            self._check_file(self.path)

    @contextmanager
    def _connect(self, path=None, readonly=False):
        path = Path(path or self.path)
        if readonly:
            con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        else:
            con = sqlite3.connect(str(path))
            con.execute("PRAGMA synchronous=FULL")
        con.row_factory = sqlite3.Row
        try:
            yield con
            if not readonly:
                con.commit()
        except Exception:
            if not readonly:
                con.rollback()
            raise
        finally:
            con.close()

    def _check_file(self, path):
        try:
            with self._connect(path, readonly=True) as con:
                appid = con.execute("PRAGMA application_id").fetchone()[0]
                check = con.execute("PRAGMA quick_check").fetchone()[0]
                if appid != APPLICATION_ID or check != 'ok':
                    raise ValueError("유효한 .bcase 사건파일이 아닙니다.")
                row = con.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
                if not row or int(row[0]) != SCHEMA_VERSION:
                    raise ValueError("지원하지 않는 사건파일 버전입니다.")
                required = {'case_data', 'documents', 'history', 'records', 'metadata'}
                tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not required.issubset(tables):
                    raise ValueError("필수 사건정보가 누락되었습니다.")
                if con.execute("SELECT COUNT(*) FROM case_data WHERE id=1").fetchone()[0] != 1:
                    raise ValueError("사건 기초정보가 올바르지 않습니다.")
        except (sqlite3.DatabaseError, TypeError) as e:
            raise ValueError("손상되었거나 지원하지 않는 사건파일입니다.") from e

    def new_case(self):
        with self.lock:
            fd, tmp_name = tempfile.mkstemp(suffix=".bcase", dir=self.workspace)
            os.close(fd)
            temp = Path(tmp_name)
            try:
                with self._connect(temp) as con:
                    con.executescript("""
                        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                        CREATE TABLE case_data (
                          id INTEGER PRIMARY KEY CHECK(id = 1),
                          case_id TEXT NOT NULL,
                          values_json TEXT NOT NULL,
                          sources_json TEXT NOT NULL,
                          confirmed_at TEXT,
                          created_at TEXT NOT NULL,
                          updated_at TEXT NOT NULL
                        );
                        CREATE TABLE documents (
                          id INTEGER PRIMARY KEY AUTOINCREMENT,
                          filename TEXT NOT NULL,
                          sha256 TEXT NOT NULL,
                          mime TEXT NOT NULL,
                          content BLOB NOT NULL,
                          extracted_lines_json TEXT NOT NULL,
                          uploaded_at TEXT NOT NULL
                        );
                        CREATE TABLE history (
                          id INTEGER PRIMARY KEY AUTOINCREMENT,
                          happened_at TEXT NOT NULL,
                          action TEXT NOT NULL,
                          detail TEXT NOT NULL
                        );
                        CREATE TABLE records (
                          id INTEGER PRIMARY KEY AUTOINCREMENT,
                          category TEXT NOT NULL,
                          cycle INTEGER,
                          payload_json TEXT NOT NULL,
                          created_at TEXT NOT NULL
                        );
                    """)
                    con.execute(f"PRAGMA application_id={APPLICATION_ID}")
                    con.executemany("INSERT INTO metadata VALUES (?, ?)", [
                        ('schema_version', str(SCHEMA_VERSION)),
                        ('master_version', self.master_version),
                        ('app_version', '0.1.0')
                    ])
                    t = now()
                    con.execute("INSERT INTO case_data VALUES (1, ?, ?, ?, NULL, ?, ?)",
                                (str(uuid.uuid4()), '{}', '{}', t, t))
                    con.execute("INSERT INTO history(happened_at,action,detail) VALUES (?,?,?)",
                                (t, 'new', '새 사건 생성'))
                    con.commit()
                os.replace(temp, self.path)
            finally:
                temp.unlink(missing_ok=True)
            return self.state()

    def state(self):
        with self.lock, self._connect(readonly=True) as con:
            row = con.execute("SELECT * FROM case_data WHERE id=1").fetchone()
            documents = con.execute("SELECT id,filename,sha256,uploaded_at FROM documents ORDER BY id DESC").fetchall()
            history = con.execute("SELECT happened_at,action,detail FROM history ORDER BY id DESC LIMIT 12").fetchall()
            master_version = con.execute("SELECT value FROM metadata WHERE key='master_version'").fetchone()[0]
            detail_row = con.execute("SELECT payload_json FROM records WHERE category='application_details' ORDER BY id DESC LIMIT 1").fetchone()
            ai_row = con.execute("SELECT payload_json FROM records WHERE category='ai_review' ORDER BY id DESC LIMIT 1").fetchone()
            ai = json.loads(ai_row[0]) if ai_row else None
            if not documents or (ai and ai.get('document_id') != documents[0]['id']):
                ai = None
            return {
                'ai_review': ai,
                'case_id': row['case_id'],
                'values': json.loads(row['values_json']),
                'sources': json.loads(row['sources_json']),
                'confirmed_at': row['confirmed_at'],
                'created_at': row['created_at'],
                'updated_at': row['updated_at'],
                'master_version': master_version,
                'application_details': json.loads(detail_row[0]) if detail_row else None,
                'documents': [dict(x) for x in documents],
                'history': [dict(x) for x in history]
            }

    def save_values(self, values, actor='user'):
        with self.lock:
            if not isinstance(values, dict) or not set(values).issubset(self.field_keys):
                raise ValueError("허용되지 않은 건축개요 항목입니다.")
            sanitized = {}
            for key, value in values.items():
                if not isinstance(value, str) or len(value) > 1500:
                    raise ValueError(f"{key}: 문자열 최대 1,500자만 입력할 수 있습니다.")
                sanitized[key] = value.strip()
            with self._connect() as con:
                old = con.execute("SELECT values_json,sources_json FROM case_data WHERE id=1").fetchone()
                previous = json.loads(old['values_json'])
                sources = json.loads(old['sources_json'])
                if previous != sanitized:
                    for key in sanitized:
                        if sanitized.get(key) != previous.get(key):
                            sources[key] = {**sources.get(key, {}), 'edited_by_user': True}
                    t = now()
                    con.execute("UPDATE case_data SET values_json=?,sources_json=?,confirmed_at=NULL,updated_at=? WHERE id=1",
                                (json.dumps(sanitized, ensure_ascii=False), json.dumps(sources, ensure_ascii=False), t))
                    con.execute("INSERT INTO history(happened_at,action,detail) VALUES (?,?,?)",
                                (t, 'edit', '건축개요 수정 · 검토확정 해제'))
                    con.commit()
            return self.state()

    def add_application(self, filename, sha256, mime, content, lines, extracted, sources, method, details=None):
        with self.lock, self._connect() as con:
            t = now()
            con.execute("INSERT INTO documents(filename,sha256,mime,content,extracted_lines_json,uploaded_at) VALUES (?,?,?,?,?,?)",
                        (filename, sha256, mime, content, json.dumps(lines, ensure_ascii=False), t))
            docid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
            # Store values separately from immutable original bytes; explicit replacement is recorded.
            for source in sources.values():
                source['document_id'] = docid
                source['filename'] = filename
            if details is not None:
                # Drafts are stored separately from the 16 authoritative summary fields.
                # Each cited source is linked to the immutable original document.
                def attach_source(obj):
                    if isinstance(obj, dict):
                        if 'line' in obj and 'where' in obj and 'evidence' in obj:
                            obj['document_id'] = docid
                            obj['filename'] = filename
                        for val in obj.values(): attach_source(val)
                    elif isinstance(obj, list):
                        for val in obj: attach_source(val)
                attach_source(details)
                con.execute("INSERT INTO records(category,cycle,payload_json,created_at) VALUES ('application_details',NULL,?,?)",
                            (json.dumps(details, ensure_ascii=False), t))
            con.execute("UPDATE case_data SET values_json=?,sources_json=?,confirmed_at=NULL,updated_at=? WHERE id=1",
                        (json.dumps(extracted, ensure_ascii=False), json.dumps(sources, ensure_ascii=False), t))
            con.execute("INSERT INTO history(happened_at,action,detail) VALUES (?,?,?)",
                        (t, 'upload', f'{filename} · 추출 방식: {method}'))
            con.commit()
        return self.state()

    def confirm(self, required_fields):
        with self.lock, self._connect() as con:
            row = con.execute("SELECT values_json FROM case_data WHERE id=1").fetchone()
            values = json.loads(row[0])
            missing = [k for k in required_fields if not values.get(k, '').strip()]
            if missing:
                raise ValueError('필수값 누락: ' + ', '.join(missing))
            t = now()
            con.execute("UPDATE case_data SET confirmed_at=?,updated_at=? WHERE id=1", (t, t))
            con.execute("INSERT INTO history(happened_at,action,detail) VALUES (?,?,?)",
                        (t, 'confirm', '담당자 건축개요 확인'))
            con.commit()
        return self.state()

    def patch_detail(self, section, index, part, field, value):
        """Whitelisted edit of one extracted draft value; citations stay immutable."""
        allowed = {
            'buildings': {'existing': {'building_name','main_use','structure','building_area_m2','floor_area_m2','height_m'},
                          'proposed': {'main_use','structure','building_area_m2','floor_area_m2','height_m'},
                          'meta': {'building_name'}},
            'floors': {'existing': {'area_m2'},
                       'proposed': {'area_m2','structure','use'},
                       'meta': {'building_name','floor','work_type'}}
        }
        if section not in allowed or part not in allowed[section] or field not in allowed[section][part]:
            raise ValueError('허용되지 않은 상세항목입니다.')
        if not isinstance(index,int) or not isinstance(value,str) or len(value)>500:
            raise ValueError('상세항목 입력값이 올바르지 않습니다.')
        value=value.strip()
        with self.lock, self._connect() as con:
            rec=con.execute("SELECT id,payload_json FROM records WHERE category='application_details' ORDER BY id DESC LIMIT 1").fetchone()
            if not rec:raise ValueError('저장된 상세정보가 없습니다.')
            payload=json.loads(rec['payload_json'])
            rows=payload[section]
            if not 0<=index<len(rows):raise ValueError('상세항목 번호가 올바르지 않습니다.')
            row=rows[index]
            if part=='meta':
                previous=row.get(field,'')
                if value!=previous:
                    row[field]=value
                    row.setdefault('user_edits',{})[field]=True
            elif section=='buildings':
                obj=row[part]
                prior=obj.get(field,{}).get('value','')
                if prior!=value:
                    old_source=obj.get(field,{}).get('source')
                    obj[field]={'value':value,'source':old_source,'edited_by_user':True}
            else:
                obj=row[part]
                prior=obj.get(field,'')
                if prior!=value:
                    obj[field]=value
                    row.setdefault('user_edits',{})[part+'.'+field]=True
            t=now()
            con.execute('UPDATE records SET payload_json=? WHERE id=?',
                        (json.dumps(payload,ensure_ascii=False),rec['id']))
            con.execute('UPDATE case_data SET confirmed_at=NULL,updated_at=? WHERE id=1',(t,))
            con.execute('INSERT INTO history(happened_at,action,detail) VALUES (?,?,?)',
                        (t,'detail_edit',f'{section}[{index}] {part}.{field} 담당자 수정'))
            con.commit()
        return self.state()

    def record_ai_review(self, result, document_id):
        """Keep model output as a separate, unapproved draft in the case file."""
        with self.lock, self._connect() as con:
            latest = con.execute('SELECT id,filename FROM documents ORDER BY id DESC LIMIT 1').fetchone()
            if not latest or latest['id'] != document_id:
                raise ValueError('최근 업로드한 신청서에서만 AI 분석을 실행할 수 있습니다.')
            payload = {**result, 'document_id': document_id}
            for candidate in payload['suggestions'].values():
                src = candidate['source']
                src['document_id'] = document_id
                src['filename'] = latest['filename']
            t = now()
            con.execute("INSERT INTO records(category,cycle,payload_json,created_at) VALUES ('ai_review',NULL,?,?)",
                        (json.dumps(payload,ensure_ascii=False),t))
            con.execute('INSERT INTO history(happened_at,action,detail) VALUES (?,?,?)',
                        (t,'ai_review',f"{'모의 비교' if payload.get('mode') == 'demo' else 'AI 비교'} 초안 생성 ({len(payload['suggestions'])}항목, 자동반영 없음)"))
        return self.state()

    def apply_ai_review(self, run_id, keys):
        """Only specifically selected, source-verified AI candidates can be applied."""
        if not isinstance(keys,list) or not keys or len(keys)>len(self.field_keys):
            raise ValueError('반영할 AI 제안 항목을 선택하세요.')
        if len(keys)!=len(set(keys)) or not set(keys).issubset(self.field_keys):
            raise ValueError('AI 반영 항목이 올바르지 않습니다.')
        with self.lock, self._connect() as con:
            row=con.execute("SELECT payload_json FROM records WHERE category='ai_review' ORDER BY id DESC LIMIT 1").fetchone()
            latest=con.execute('SELECT id FROM documents ORDER BY id DESC LIMIT 1').fetchone()
            if not row or not latest:
                raise ValueError('AI 분석 결과가 없습니다.')
            ai=json.loads(row[0])
            if ai.get('run_id')!=run_id or ai.get('document_id')!=latest['id']:
                raise ValueError('AI 결과가 현재 신청서와 일치하지 않습니다. 다시 분석하세요.')
            selections={k:ai['suggestions'].get(k) for k in keys}
            if any(not entry or not entry['verified'] for entry in selections.values()):
                raise ValueError('원문 근거가 확인된 AI 제안만 반영할 수 있습니다.')
            before=con.execute('SELECT values_json,sources_json FROM case_data WHERE id=1').fetchone()
            values=json.loads(before['values_json']); sources=json.loads(before['sources_json'])
            for key,candidate in selections.items():
                values[key]=candidate['value']
                sources[key]=candidate['source']
            t=now()
            con.execute('UPDATE case_data SET values_json=?,sources_json=?,confirmed_at=NULL,updated_at=? WHERE id=1',
                        (json.dumps(values,ensure_ascii=False),json.dumps(sources,ensure_ascii=False),t))
            con.execute('INSERT INTO history(happened_at,action,detail) VALUES (?,?,?)',
                        (t,'ai_apply',('담당자 선택 모의 항목 반영: ' if ai.get('mode') == 'demo' else '담당자 선택 AI 항목 반영: ')+', '.join(keys)))
        return self.state()

    def document(self, docid):
        with self.lock, self._connect(readonly=True) as con:
            row = con.execute("SELECT * FROM documents WHERE id=?", (docid,)).fetchone()
            if not row:
                raise KeyError('원본 문서를 찾을 수 없습니다.')
            return dict(row)

    def open_case(self, content):
        if len(content) > 40 * 1024 * 1024:
            raise ValueError('사건파일 크기는 40MB 이하여야 합니다.')
        with self.lock:
            fd, tmp_name = tempfile.mkstemp(suffix=".bcase", dir=self.workspace)
            os.close(fd)
            temp = Path(tmp_name)
            try:
                temp.write_bytes(content)
                self._check_file(temp)
                os.replace(temp, self.path)
            finally:
                temp.unlink(missing_ok=True)
            return self.state()

    def export_bytes(self):
        with self.lock:
            with self._connect(readonly=True) as source:
                buffer = sqlite3.connect(':memory:')
                source.backup(buffer)
                fd, tmp_name = tempfile.mkstemp(suffix=".bcase", dir=self.workspace)
                os.close(fd)
                try:
                    disk = sqlite3.connect(tmp_name)
                    buffer.backup(disk)
                    disk.close()
                    data = Path(tmp_name).read_bytes()
                finally:
                    buffer.close()
                    Path(tmp_name).unlink(missing_ok=True)
                return data
