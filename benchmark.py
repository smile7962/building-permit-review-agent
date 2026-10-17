"""Read-only, synthetic-only 16-field extraction benchmark.

Rule-based mode never contacts a network. AI mode requires explicit user opt-in
and evaluates only the four bundled synthetic TXT fixtures, never active cases.
The result is not a legal-compliance assessment.
"""
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from ai_review import ai_config, compare_ai
from parser import parse_application
from synthetic_gate import require_bundled_fixture_integrity

ROOT = Path(__file__).resolve().parent
BENCHMARK_DIR = ROOT / 'benchmarks'
GOLD_FILE = BENCHMARK_DIR / 'gold.json'
NUMERIC_KEYS = frozenset({
    'site_area_m2', 'building_area_m2', 'total_floor_area_m2',
    'building_coverage_percent', 'floor_area_ratio_percent',
    'above_ground_floors', 'underground_floors', 'building_count',
    'parking_spaces'
})


def equivalent(key, actual, expected):
    if actual is None or expected is None:
        return actual == expected
    if key in NUMERIC_KEYS:
        try:
            a = Decimal(str(actual).replace(',', '').strip())
            b = Decimal(str(expected).replace(',', '').strip())
            return a.is_finite() and b.is_finite() and a == b
        except InvalidOperation:
            return False
    return ' '.join(str(actual).split()).casefold() == ' '.join(str(expected).split()).casefold()


def grade(expected, candidate, allowed_keys, *, evidence=None):
    """Scores every allowed field; a value with invalid evidence cannot count as correct."""
    rows = []
    counters = dict(correct=0, wrong=0, missing=0, extra=0, unverified=0, empty_correct=0)
    for key in sorted(allowed_keys):
        gold = expected.get(key)
        observed = candidate.get(key)
        observed = None if observed is None or str(observed).strip() == '' else str(observed)
        grounded = True if evidence is None else bool(evidence.get(key, False))
        if observed is None:
            status = 'missing' if gold is not None else 'empty_correct'
        elif not grounded:
            status = 'unverified'
        elif gold is None:
            status = 'extra'
        elif equivalent(key, observed, gold):
            status = 'correct'
        else:
            status = 'wrong'
        counters[status] += 1
        rows.append({'field': key, 'expected': gold, 'observed': observed,
                     'evidence_verified': grounded if observed is not None else None,
                     'status': status})
    expected_n = len(expected)
    assert sum(counters.values()) == len(allowed_keys)
    return {'expected_fields': expected_n, 'counts': counters,
            'accuracy': round(counters['correct']/expected_n * 100, 2) if expected_n else 100.0,
            'fields': rows}


def _combine(case_results):
    total = dict(correct=0, wrong=0, missing=0, extra=0, unverified=0, empty_correct=0)
    expected = 0
    for case in case_results:
        expected += case['score']['expected_fields']
        for key, amount in case['score']['counts'].items():
            total[key] += amount
    return {'cases': len(case_results), 'expected_fields': expected,
            'counts': total, 'accuracy': round(total['correct']/expected * 100, 2) if expected else 0.0,
            'note': ('정답 항목 대비, 원문 근거가 확인된 정확한 추출 비율입니다. '
                     '실제 세움터 서식 전체의 정확도나 법령 적합률을 뜻하지 않습니다.')}


def run_benchmark(mode='rules', *, consent=False, allowed_keys=None, transport=None, config=None):
    if mode not in ('rules', 'ai'):
        raise ValueError('벤치마크 모드는 rules 또는 ai만 허용합니다.')
    if mode == 'ai' and consent is not True:
        raise ValueError('AI 평가에서는 합성자료 외부 전송에 대한 별도 동의가 필요합니다.')
    manifest = json.loads(GOLD_FILE.read_text(encoding='utf-8'))
    keys = set(allowed_keys or manifest['cases'][0]['expected'].keys())
    keys.update({'building_count', 'zoning'})
    if mode == 'ai':
        require_bundled_fixture_integrity()
        config = config or ai_config()
        if not config['available']:
            raise ValueError('실제 AI 평가를 실행하려면 모델 설정이 필요합니다. 규칙 기반 평가는 별도로 가능합니다.')
    rules_cases, ai_cases = [], []
    for item in manifest['cases']:
        # Files are selected exclusively from a hardcoded allowlisted manifest,
        # never from HTTP request paths, uploaded documents or workspace.
        filename = item['file']
        if Path(filename).name != filename or not filename.endswith('.txt'):
            raise ValueError('벤치마크 파일 구성이 올바르지 않습니다.')
        content = (BENCHMARK_DIR / filename).read_bytes()
        lines, values, sources, _, _ = parse_application(filename, content, keys, False)
        expected = item['expected']
        base = {'id': item['id'], 'description': item['description']}
        rules_cases.append({**base, 'score': grade(expected, values, keys)})
        if mode == 'ai':
            # No original bytes. compare_ai includes synthetic-marker and PII gates.
            draft = compare_ai(lines, values, keys, transport=transport, config=config)
            suggestions = draft['suggestions']
            ai_values = {key: suggestion['value'] for key, suggestion in suggestions.items()}
            evidence = {key: suggestion['verified'] for key, suggestion in suggestions.items()}
            ai_cases.append({**base, 'score': grade(expected, ai_values, keys, evidence=evidence),
                             'model': draft['model'], 'sent_lines': draft['sent_lines']})
    report = {'benchmark_version': manifest['version'], 'mode': mode,
              'data_classification': '합성 테스트 전용',
              'real_document_used': False, 'active_case_modified': False,
              'rules': {'summary': _combine(rules_cases), 'cases': rules_cases},
              'notice': '합성문서 4건의 추출 성능 평가이며 법적 적합성 또는 실제 신청서 정확도 보증이 아닙니다.'}
    if mode == 'ai':
        report['ai'] = {'model': config['model'], 'summary': _combine(ai_cases), 'cases': ai_cases}
        report['requests_to_model'] = len(ai_cases)
    else:
        report['requests_to_model'] = 0
    return report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='건축ON AI 합성자료 추출 성능 벤치마크')
    parser.add_argument('--mode', choices=['rules','ai'], default='rules')
    parser.add_argument('--confirm-synthetic-send', action='store_true')
    parser.add_argument('--output', help='선택한 경로에 보고서 JSON 저장')
    args = parser.parse_args()
    report = run_benchmark(args.mode, consent=args.confirm_synthetic_send)
    formatted = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(formatted, encoding='utf-8')
    else:
        print(formatted)
