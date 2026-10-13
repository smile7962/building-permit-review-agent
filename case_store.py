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
            return {
                'case_id': row['case_id'],
                'values': json.loads(row['values_json']),
                'sources': json.loads(row['sources_json']),
                'confirmed_at': row['confirmed_at'],
                'created_at': row['created_at'],
                'updated_at': row['updated_at'],
                'master_version': master_version,
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

    def add_application(self, filename, sha256, mime, content, lines, extracted, sources, method):
        with self.lock, self._connect() as con:
            t = now()
            con.execute("INSERT INTO documents(filename,sha256,mime,content,extracted_lines_json,uploaded_at) VALUES (?,?,?,?,?,?)",
                        (filename, sha256, mime, content, json.dumps(lines, ensure_ascii=False), t))
            docid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
            # Store values separately from immutable original bytes; explicit replacement is recorded.
            for source in sources.values():
                source['document_id'] = docid
                source['filename'] = filename
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
