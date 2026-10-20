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
from legal_review import build as build_legal, snapshot as legal_hash, MASTER as LEGAL_MASTER, validate_edit as validate_legal_edit, refresh_screen
from screening import evidence_values, SCREEN_VERSION, screen_item, summarize_screen
from review_guidance import validate_verification
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
            legal_row = con.execute("SELECT payload_json FROM records WHERE category='legal_checklist' ORDER BY id DESC LIMIT 1").fetchone()
            legal = json.loads(legal_row[0]) if legal_row else None
            if legal:
                latest_doc_sha = documents[0]['sha256'] if documents else None
                legal['outdated'] = (legal['values_sha256'] != legal_hash(json.loads(row['values_json']))
                    or legal['master_version'] != LEGAL_MASTER['version']
                    or legal.get('document_sha256') != latest_doc_sha)
                refresh_screen(legal, json.loads(row['values_json']))
                legal['screening_needs_refresh'] = legal.get('screening_version') != SCREEN_VERSION
            ai_row = con.execute("SELECT payload_json FROM records WHERE category='ai_review' ORDER BY id DESC LIMIT 1").fetchone()
            ai = json.loads(ai_row[0]) if ai_row else None
            if not documents or (ai and ai.get('document_id') != documents[0]['id']):
                ai = None
            return {
                'ai_review': ai,
                'legal_review': legal,
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

    def build_legal(self):
        """Take a new snapshot; never preserve prior manual decisions on changed facts."""
        with self.lock, self._connect() as con:
            data=con.execute('SELECT values_json,confirmed_at FROM case_data WHERE id=1').fetchone()
            if not data['confirmed_at']:
                raise ValueError('STEP 01 건축개요를 담당자가 먼저 검토 확정하세요.')
            last=con.execute("SELECT payload_json FROM records WHERE category='legal_checklist' ORDER BY id DESC LIMIT 1").fetchone()
            prior=json.loads(last['payload_json']).get('design_evidence',{}) if last else {}
            payload=build_legal(json.loads(data['values_json']),prior)
            newest_doc=con.execute('SELECT sha256 FROM documents ORDER BY id DESC LIMIT 1').fetchone()
            payload['document_sha256']=newest_doc['sha256'] if newest_doc else None
            t=now()
            con.execute("INSERT INTO records(category,cycle,payload_json,created_at) VALUES ('legal_checklist',NULL,?,?)",
                        (json.dumps(payload,ensure_ascii=False),t))
            con.execute("INSERT INTO history(happened_at,action,detail) VALUES (?,?,?)",
                        (t,'legal_build','건축법 검토항목 후보 생성 · 담당자 판단 미실시'))
        return self.state()

    def update_design_evidence(self, data):
        """Save verified design drawing measurements; never invent a statutory cutoff."""
        ev=evidence_values(data)
        with self.lock,self._connect() as con:
            row=con.execute("SELECT id,payload_json FROM records WHERE category='legal_checklist' ORDER BY id DESC LIMIT 1").fetchone()
            if not row:raise ValueError('먼저 사건별 법령 검토를 생성하세요.')
            review=json.loads(row['payload_json'])
            application=con.execute('SELECT values_json,confirmed_at FROM case_data WHERE id=1').fetchone()
            docs=con.execute('SELECT sha256 FROM documents ORDER BY id DESC LIMIT 1').fetchone()
            document_sha=docs['sha256'] if docs else None
            if not application['confirmed_at'] or review['values_sha256']!=legal_hash(json.loads(application['values_json'])) or review['master_version']!=LEGAL_MASTER['version'] or review.get('document_sha256')!=document_sha:
                raise ValueError('STEP 01 신청정보를 최신 도면 기준으로 확정한 뒤 재생성하세요.')
            if review.get('design_evidence',{})==ev:
                return self.state()
            review['design_evidence']=ev
            review['screening_version']=SCREEN_VERSION
            application_values=json.loads(application['values_json'])
            for item in review['items']:
                item['screening']=screen_item(item,application_values,ev)
                # Changed inputs invalidate every recorded verdict; preserve comment and drawing evidence.
                item['review_result']='미검토'
                if item.get('progress')=='검토기록완료':
                    item['progress']='검토중'
                    item['applicability']='미확인'
            review['screening_summary']=summarize_screen(review['items'])
            review['confirmed_at']=None
            con.execute('UPDATE records SET payload_json=? WHERE id=?',(json.dumps(review,ensure_ascii=False),row['id']))
            con.execute('INSERT INTO history(happened_at,action,detail) VALUES (?,?,?)',
                        (now(),'design_evidence','설계도서 수치 및 사건별 법령 스크리닝 재계산 · 기록확정 해제'))
        return self.state()

    def update_legal(self,item_id,applicability,progress,note):
        update=validate_legal_edit(item_id,applicability,progress,note)
        with self.lock, self._connect() as con:
            row=con.execute("SELECT id,payload_json FROM records WHERE category='legal_checklist' ORDER BY id DESC LIMIT 1").fetchone()
            if not row:raise ValueError('먼저 건축법 검토 체크리스트를 생성하세요.')
            review=json.loads(row['payload_json'])
            vals=con.execute('SELECT values_json,confirmed_at FROM case_data WHERE id=1').fetchone()
            newest_doc=con.execute('SELECT sha256 FROM documents ORDER BY id DESC LIMIT 1').fetchone()
            newest_sha=newest_doc['sha256'] if newest_doc else None
            if (review['values_sha256']!=legal_hash(json.loads(vals['values_json'])) or review['master_version']!=LEGAL_MASTER['version']
                or review.get('document_sha256')!=newest_sha or not vals['confirmed_at']):
                raise ValueError('건축개요 변경 또는 미확정 상태입니다. 1단계 확인 후 체크리스트를 다시 생성하세요.')
            item=next((x for x in review['items'] if x['id']==item_id),None)
            if not item:raise ValueError('해당 검토항목을 찾지 못했습니다.')
            previous={k:item[k] for k in update}
            if previous!=update:
                item.update(update);item['reviewed_at']=now();review['confirmed_at']=None
                con.execute('UPDATE records SET payload_json=? WHERE id=?',
                            (json.dumps(review,ensure_ascii=False),row['id']))
                con.execute('INSERT INTO history(happened_at,action,detail) VALUES (?,?,?)',
                            (now(),'legal_edit',f'건축법 검토 {item_id}: 담당자 기록 수정, 확정 해제'))
        return self.state()

    def save_legal_verification(self, item_id, applicability, progress, note,
                                review_result, drawing_value, drawing_ref, criteria_ref):
        """Save a reviewer decision only; do not infer legal approval."""
        edit=validate_legal_edit(item_id,applicability,progress,note)
        extra=validate_verification(review_result,drawing_value,drawing_ref,criteria_ref,edit['note'])
        if review_result=='비적용(담당자 확인)' and applicability!='비적용':
            raise ValueError('비적용 결과는 적용 여부도 비적용으로 표시해야 합니다.')
        if review_result in ('적정(담당자 확인)','보완 필요') and applicability!='적용':
            raise ValueError('적정·보완 결과는 적용 여부를 적용으로 선택해야 합니다.')
        with self.lock,self._connect() as con:
            row=con.execute("SELECT id,payload_json FROM records WHERE category='legal_checklist' ORDER BY id DESC LIMIT 1").fetchone()
            if not row:raise ValueError('먼저 사건별 검토항목을 생성하세요.')
            review=json.loads(row['payload_json'])
            case=con.execute('SELECT values_json,confirmed_at FROM case_data WHERE id=1').fetchone()
            latest=con.execute('SELECT sha256 FROM documents ORDER BY id DESC LIMIT 1').fetchone()
            sha=latest['sha256'] if latest else None
            if (not case['confirmed_at'] or
                review['values_sha256']!=legal_hash(json.loads(case['values_json'])) or
                review['master_version']!=LEGAL_MASTER['version'] or
                review.get('document_sha256')!=sha or
                review.get('screening_version')!=SCREEN_VERSION):
                raise ValueError('건축개요·도면·마스터 버전이 변경됐습니다. 확인 후 다시 생성하세요.')
            item=next((x for x in review['items'] if x['id']==item_id),None)
            if not item:raise ValueError('유효하지 않은 검토항목입니다.')
            update={**edit,**extra}
            if any(item.get(k)!=v for k,v in update.items()):
                item.update(update)
                item['reviewed_at']=now()
                review['confirmed_at']=None
                con.execute('UPDATE records SET payload_json=? WHERE id=?',
                            (json.dumps(review,ensure_ascii=False),row['id']))
                con.execute('INSERT INTO history(happened_at,action,detail) VALUES (?,?,?)',
                            (now(),'legal_verification',f'{item_id}: 담당자 도면·법령 대조 및 검토결과 저장'))
        return self.state()

    def confirm_legal(self):
        with self.lock, self._connect() as con:
            row=con.execute("SELECT id,payload_json FROM records WHERE category='legal_checklist' ORDER BY id DESC LIMIT 1").fetchone()
            if not row:raise ValueError('건축법 검토 체크리스트가 없습니다.')
            review=json.loads(row['payload_json'])
            data=con.execute('SELECT values_json,confirmed_at FROM case_data WHERE id=1').fetchone()
            newest_doc=con.execute('SELECT sha256 FROM documents ORDER BY id DESC LIMIT 1').fetchone()
            newest_sha=newest_doc['sha256'] if newest_doc else None
            if (not data['confirmed_at'] or review['values_sha256']!=legal_hash(json.loads(data['values_json']))
                or review['master_version']!=LEGAL_MASTER['version'] or review.get('screening_version')!=SCREEN_VERSION or review.get('document_sha256')!=newest_sha):
                raise ValueError('건축개요가 변경되었거나 미확정입니다. 1단계를 확정하고 체크리스트를 다시 생성하세요.')
            pending=[x['id'] for x in review['items'] if x['progress']!='검토기록완료' or x['applicability']=='미확인' or not x['note'].strip()]
            if pending:raise ValueError('담당자 검토 기록이 미완료인 항목: '+', '.join(pending))
            t=now();review['confirmed_at']=t
            con.execute('UPDATE records SET payload_json=? WHERE id=?',(json.dumps(review,ensure_ascii=False),row['id']))
            con.execute('INSERT INTO history(happened_at,action,detail) VALUES (?,?,?)',
                        (t,'legal_confirm','담당자 건축법 체크리스트 검토기록 확정 (적법성 자동판정 아님)'))
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
