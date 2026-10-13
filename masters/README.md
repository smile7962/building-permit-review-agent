이 폴더는 **사건별 파일과 분리**되는 공통 마스터의 위치입니다.

- `fields.json`: Phase 1 건축개요 공통 데이터 명세
- Phase 2: checklist.json, legal_sources.json (검증된 공식 원문을 확인한 후 추가)
- Phase 3: consultation_rules.json, department_directory.json (업무코드와 현재 부서명을 분리)
- Phase 4~5: 문서 템플릿

마스터가 변경되더라도 기존 `.bcase` 안에 저장된 `master_version`은 유지됩니다.
