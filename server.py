"""Local-only Phase 1 server, using only the Python standard library.

Run: python server.py   →   http://127.0.0.1:8765
"""
import hashlib
import io
import json
import mimetypes
import os
import re
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse, quote

from case_store import CaseStore
from parser import ai_available, parse_application
from seumteo_details import extract_details
from ai_review import ai_config, compare_ai, test_ai_connection
from demo_review import compare_synthetic_demo, DEMO_FILE
from benchmark import run_benchmark
from realform_benchmark import run_realform_benchmark
from practical_benchmark import run_practical_benchmark
from synthetic_gate import require_approved_fixture, require_bundled_fixture_integrity
from legal_review import MASTER as LEGAL_MASTER

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get('APP_PORT', '8765'))
DEMO_SHA256 = hashlib.sha256(DEMO_FILE.read_bytes()).hexdigest()
MAX_UPLOAD = 15 * 1024 * 1024
MAX_CASE = 40 * 1024 * 1024
with open(ROOT / 'masters' / 'fields.json', 'r', encoding='utf-8') as f:
    MASTER = json.load(f)
FIELDS = MASTER['fields']
FIELD_KEYS = {f['key'] for f in FIELDS}
REQUIRED_KEYS = [f['key'] for f in FIELDS if f.get('required')]
STORE = None


def store():
    global STORE
    if STORE is None:
        workspace = Path(os.environ.get('BCASE_WORKSPACE', str(ROOT / 'workspace')))
        STORE = CaseStore(workspace, FIELD_KEYS, MASTER['version'])
    return STORE


class Handler(BaseHTTPRequestHandler):
    server_version = 'BuildingPermitReview/0.2.0'

    def _headers(self, status, mime='application/json; charset=utf-8', size=None, more=None):
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if size is not None:
            self.send_header('Content-Length', str(size))
        for key, val in (more or {}).items():
            self.send_header(key, val)
        self.end_headers()

    def _json(self, status, obj):
        data = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self._headers(status, size=len(data))
        self.wfile.write(data)

    def _binary(self, data, mime, filename=None):
        headers = {}
        if filename:
            # Use RFC 5987. Never place raw untrusted file names in a header.
            headers['Content-Disposition'] = "attachment; filename*=UTF-8''" + quote(filename, safe='')
        self._headers(200, mime, len(data), headers)
        self.wfile.write(data)

    def _read(self, maximum):
        length = int(self.headers.get('Content-Length', '0'))
        if length <= 0 or length > maximum:
            raise ValueError(f'파일 또는 요청 본문은 최대 {maximum // (1024*1024)}MB입니다.')
        data = self.rfile.read(length)
        if len(data) != length:
            raise ValueError('입력 파일을 모두 읽지 못했습니다.')
        return data

    def _allow_request(self):
        host = self.headers.get('Host', '').split(':')[0].lower()
        if host not in ('127.0.0.1', 'localhost'):
            self._json(403, {'error': '로컬 PC에서만 접근할 수 있습니다.'})
            return False
        origin = self.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{PORT}', f'http://localhost:{PORT}'):
            self._json(403, {'error': '외부 웹페이지의 접근은 허용하지 않습니다.'})
            return False
        return True

    def _call(self, method):
        try:
            if not self._allow_request():
                return
            getattr(self, method)()
        except (ValueError, KeyError, UnicodeError) as e:
            self._json(400, {'error': str(e)})
        except Exception as e:
            # Internal errors are logged locally; do not leak paths or secrets to UI.
            traceback.print_exc()
            self._json(500, {'error': '프로그램 처리 중 오류가 발생했습니다. 실행창의 오류 내용을 확인하세요.'})

    def do_GET(self):
        self._call('_get')

    def do_POST(self):
        self._call('_post')

    def _get(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/state':
            self._json(200, {'case': store().state(), 'fields': FIELDS,
                             'ai_available': ai_config()['available'], 'ai_mode': ai_config()['mode'],
                             'ai_model': ai_config()['model'], 'ai_provider': ai_config()['provider'],
                             'demo_sha256': DEMO_SHA256, 'legal_master': LEGAL_MASTER, 'supported': ['.txt','.csv','.pdf','.docx','.xls','.xlsx']})
        elif parsed.path == '/api/export':
            state = store().state()
            filename = f"{state['case_id'][:8]}_건축인허가.bcase"
            self._binary(store().export_bytes(), 'application/octet-stream', filename)
        elif parsed.path in ('/api/document', '/api/document-lines'):
            qs = parse_qs(parsed.query)
            doc_id = int(qs.get('id', ['0'])[0])
            doc = store().document(doc_id)
            if parsed.path == '/api/document-lines':
                self._json(200, {'filename': doc['filename'], 'lines': json.loads(doc['extracted_lines_json'])})
            else:
                self._binary(doc['content'], doc['mime'], doc['filename'])
        elif parsed.path == '/' or parsed.path in ('/static/app.js','/static/styles.css'):
            asset = ROOT / ('index.html' if parsed.path == '/' else parsed.path.lstrip('/'))
            mime = 'text/html; charset=utf-8' if parsed.path == '/' else ('text/javascript; charset=utf-8' if asset.suffix == '.js' else 'text/css; charset=utf-8')
            self._binary(asset.read_bytes(), mime)
        else:
            self._json(404, {'error': '페이지를 찾을 수 없습니다.'})

    def _post(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if parsed.path == '/api/new':
            self._json(200, {'case': store().new_case()})
        elif parsed.path == '/api/open':
            content = self._read(MAX_CASE)
            self._json(200, {'case': store().open_case(content)})
        elif parsed.path == '/api/save':
            obj = json.loads(self._read(100 * 1024))
            self._json(200, {'case': store().save_values(obj.get('values'))})
        elif parsed.path == '/api/legal-build':
            self._read(1024)
            self._json(200, {'case': store().build_legal()})
        elif parsed.path == '/api/legal-update':
            obj=json.loads(self._read(8*1024))
            self._json(200, {'case':store().update_legal(obj.get('id'),obj.get('applicability'),obj.get('progress'),obj.get('note'))})
        elif parsed.path == '/api/legal-confirm':
            self._read(1024)
            self._json(200, {'case': store().confirm_legal()})
        elif parsed.path == '/api/detail-update':
            obj = json.loads(self._read(16 * 1024))
            self._json(200, {'case': store().patch_detail(obj.get('section'), obj.get('index'),
                obj.get('part'), obj.get('field'), obj.get('value'))})
        elif parsed.path == '/api/ai-connect-test':
            obj = json.loads(self._read(4 * 1024))
            if obj.get('consent') is not True:
                raise ValueError('API 연결시험(유료 1회 호출 가능)에 명시적으로 동의해야 합니다.')
            # Sends only a hard-coded PING prompt; never touches workspace or documents.
            self._json(200, {'result': test_ai_connection()})
        elif parsed.path == '/api/ai-review':
            obj = json.loads(self._read(4 * 1024))
            if obj.get('consent') is not True:
                raise ValueError('AI 전송에 대한 명시적 동의가 필요합니다.')
            doc_id = obj.get('document_id')
            if not isinstance(doc_id,int):
                raise ValueError('분석할 신청서가 없습니다.')
            state = store().state()
            if not state['documents'] or doc_id != state['documents'][0]['id']:
                raise ValueError('가장 최근 신청서를 분석해야 합니다.')
            doc = store().document(doc_id)
            if ai_config()['mode'] == 'external':
                require_approved_fixture(doc['content'])
            lines = json.loads(doc['extracted_lines_json'])
            draft = compare_ai(lines, state['values'], FIELD_KEYS)
            self._json(200, {'case': store().record_ai_review(draft, doc_id)})
        elif parsed.path == '/api/demo-review':
            obj = json.loads(self._read(4 * 1024))
            doc_id = obj.get('document_id')
            if not isinstance(doc_id, int) or isinstance(doc_id, bool):
                raise ValueError('분석할 모의 신청서를 선택하세요.')
            state = store().state()
            if not state['documents'] or doc_id != state['documents'][0]['id']:
                raise ValueError('가장 최근 신청서를 선택하세요.')
            doc = store().document(doc_id)
            lines = json.loads(doc['extracted_lines_json'])
            draft = compare_synthetic_demo(doc['content'], lines, state['values'], FIELD_KEYS)
            case = store().record_ai_review(draft, doc_id)
            self._json(200, {'case': case})
        elif parsed.path == '/api/realform-benchmark':
            self._json(200, run_realform_benchmark(FIELD_KEYS))
        elif parsed.path == '/api/benchmark':
            obj = json.loads(self._read(4 * 1024))
            mode = obj.get('mode')
            if mode not in ('rules', 'ai'):
                raise ValueError('rules 또는 ai 평가 모드를 선택하세요.')
            # The benchmark *never* reads the current active case, documents,
            # uploaded filenames or user-supplied data. Only bundled fixtures.
            if mode == 'ai':
                require_bundled_fixture_integrity()
            report = run_benchmark(mode, consent=obj.get('consent') is True,
                                   allowed_keys=FIELD_KEYS)
            self._json(200, report)
        elif parsed.path == '/api/practical-benchmark':
            obj = json.loads(self._read(4 * 1024))
            mode = obj.get('mode')
            if mode not in ('rules', 'ai'):
                raise ValueError('rules 또는 ai 평가 모드를 선택하세요.')
            # Read-only: only built-in hashed, synthetic PDF/XLSX cases.
            # Neither active case nor its uploaded documents are read.
            report = run_practical_benchmark(mode, consent=obj.get('consent') is True,
                                             allowed_keys=FIELD_KEYS)
            self._json(200, report)
        elif parsed.path == '/api/ai-apply':
            obj = json.loads(self._read(4 * 1024))
            self._json(200, {'case': store().apply_ai_review(obj.get('run_id'),obj.get('keys'))})
        elif parsed.path == '/api/confirm':
            self._json(200, {'case': store().confirm(REQUIRED_KEYS)})
        elif parsed.path == '/api/upload':
            name = qs.get('name', [''])[0].replace('\\', '/').split('/')[-1].strip()
            if not name or len(name) > 150 or '\n' in name or '\r' in name:
                raise ValueError('파일 이름을 확인하세요.')
            ext = Path(name).suffix.lower()
            if ext not in {'.txt','.csv','.pdf','.docx','.xls','.xlsx'}:
                raise ValueError('지원 형식은 TXT, CSV, 텍스트 PDF, DOCX, XLS, XLSX입니다.')
            content = self._read(MAX_UPLOAD)
            # Upload is always local; AI analysis requires a separate opt-in request.
            lines, values, sources, method, warning = parse_application(name, content, FIELD_KEYS, False)
            # Structured detail extraction applies only to recognisable Seumteo forms.
            is_seumteo = ext in ('.pdf','.xls','.xlsx','.docx') and any(('허가신청서' in x['text'].replace(' ','') or
                '(변경)신고서' in x['text'].replace(' ','') or '동별 개요' in x['text']) for x in lines[:100])
            details = extract_details(lines) if is_seumteo else None
            # Never trust the unchecked multi-choice form heading or an LLM guess.
            if details and details['work_type']:
                values['work_type'] = details['work_type']['value']
                sources['work_type'] = {**details['work_type']['source'],
                    'method':'명시적 체크표시', 'edited_by_user':False}
            elif details and any('건축구분' in x['text'].replace(' ','') for x in lines[:30]):
                values.pop('work_type', None)
                sources.pop('work_type', None)
            sha = hashlib.sha256(content).hexdigest()
            mime = mimetypes.guess_type(name)[0] or 'application/octet-stream'
            case = store().add_application(name, sha, mime, content, lines, values, sources, method, details)
            self._json(200, {'case': case, 'method': method, 'warning': warning, 'found': len(values)})
        else:
            self._json(404, {'error': '지원하지 않는 API입니다.'})


def main():
    store()
    httpd = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    print(f'건축인허가 AI 지원 v0.2.0 실행: http://127.0.0.1:{PORT}', flush=True)
    print('로컬 PC에서만 접근 가능합니다. 종료: Ctrl+C', flush=True)
    if os.environ.get('APP_NO_BROWSER') != '1':
        threading.Timer(0.8, lambda: webbrowser.open(f'http://127.0.0.1:{PORT}')).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n프로그램을 종료합니다.')
    finally:
        httpd.server_close()


if __name__ == '__main__':
    main()
