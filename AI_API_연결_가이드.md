# 건축ON AI v0.1.9 — Gemini 무료 API 기본 연결 가이드

## 기본 선택 (2026-10-17 확인)
- Gemini API 공식 발급: https://aistudio.google.com/api-keys
- 기본 모델: `gemini-3.1-flash-lite` (일부 지역/계정 무료 티어 제공, 사용한도 존재)
- 기본 Chat Completions 호환 엔드포인트: `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions`
- 공식 참고: https://ai.google.dev/gemini-api/docs/openai
- 공식 요금: https://ai.google.dev/gemini-api/docs/pricing

**주의:** Google 무료 티어의 입력내용은 Google 제품 개선에 사용될 수 있습니다. 민원자료·실명·연락처·주소 등 개인정보가 포함된 문서를 외부로 전송하면 안 됩니다. 현재 프로그램은 사전에 검증된 합성 TXT만 API 전송을 허용합니다. 무료 티어는 무제한이 아니며 무료 이용 가능 여부와 결제 연동 상태는 Google AI Studio에서 직접 확인해야 합니다.

## Windows 실행 절차
1. 기존 실행창을 `Ctrl+C`로 종료합니다.
2. 이 버전 ZIP을 새 폴더에 완전히 압축 해제합니다.
3. `start_ai_windows.bat`을 실행합니다.
4. AI 제공자 선택에서 **Enter** 또는 `1` = Gemini, `2` = OpenAI(선택).
5. 모델명 입력에서 **Enter** = `gemini-3.1-flash-lite`.
6. [Google AI Studio](https://aistudio.google.com/api-keys)에서 발급한 Gemini API 키를 검은 창에 입력합니다. 입력 글자는 숨겨지고 파일에 저장되지 않습니다.
7. 브라우저 `http://127.0.0.1:8765` → `외부 AI API 연결 상태`에 Google Gemini와 모델명이 나오는지 확인합니다.
8. `API 연결 테스트 (1회 호출)` → 고정된 시험문장 1회 전송. **사용자 문서 전송 없음.**
9. `추출 정확도 평가 · 합성 시험자료` → `규칙 추출 평가` → 기본 62/62 확인.
10. 합성자료 전송 동의 확인 후 `실제 AI 비교 평가` → 내장 합성 TXT 4건만 외부 모델에 전송해 평가합니다.

## 보안 및 기타 기능
- Gemini 무료 티어: 계정·지역·요금제별 제한이 있으므로 무료 보장이 아닙니다. Google AI Studio에서 사용량과 결제 현황을 확인하세요.
- 외부 전송 차단: 프로그램에 포함된 5개 합성 TXT의 SHA-256이 일치할 때만 문서 분석 허용. 체크박스만 선택한다고 임의 문서가 전송되지는 않습니다.
- API 키: Windows 실행 세션 메모리의 환경변수에서만 유지. GitHub·브라우저·`.bcase` 파일 저장 금지. 실행창을 닫으면 변수는 정리됩니다.
- OpenAI를 사용하려면 `start_ai_windows.bat`의 제공자 선택에서 `2`를 선택합니다. OpenAI API 별도 결제 정책이 적용됩니다.
- 모델 접근 거부 HTTP 404/403 또는 사용한도 HTTP 429가 발생하면 AI Studio에서 모델 지원 여부·무료 티어·프로젝트 사용량을 확인하세요.
- **실제 외부 Gemini API 연결시험은 개발환경에서 수행하지 않았습니다.** 사용자 PC 시험 결과가 필요합니다.
