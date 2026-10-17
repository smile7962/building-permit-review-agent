"""Fail-closed allowlist for external-API trials. Fixtures are synthetic and hashed.

Never accept a user's 'synthetic' label or uploaded bytes not matching these
shipped reference fixture digests as proof that remote transfer is appropriate.
"""
import hashlib
from pathlib import Path

EXPECTED_SHA256 = frozenset({
    'df4e3e99dba76122a3c3da18735600e66388b5db47195b8c043219a0ef76db3a',  # bundled sample
    '4ed74a627a7b4d73f464d59983e47f46367939bc36eeb00e7aabb05b994e1d67',  # synthetic extension
    'f005741acc2b6716f06561f6f54e9b893136db2f84dc80ff354173e2e37c439e',  # synthetic shop
    'e9aabc205a2bfc60e7b6ff7d73dcd14074b7c8b5a7095e5adc855e8b913b2a51',  # synthetic house
    '1780fb4f42b0f183eb200282c5e112f8ef9d944d117818e0b31183e9feefb5e1',  # synthetic parking
})


def is_approved_fixture(content):
    return isinstance(content, bytes) and hashlib.sha256(content).hexdigest() in EXPECTED_SHA256


def require_approved_fixture(content):
    if not is_approved_fixture(content):
        raise ValueError('외부 AI 전송 차단: 배포본에 포함된 검증용 합성 TXT 파일만 사용할 수 있습니다. 실제 민원자료는 전송할 수 없습니다.')


def require_bundled_fixture_integrity():
    root = Path(__file__).resolve().parent
    paths = [root / 'samples' / 'sample_application.txt', *sorted((root / 'benchmarks').glob('*.txt'))]
    if len(paths) != 5 or not all(is_approved_fixture(x.read_bytes()) for x in paths):
        raise ValueError('배포된 합성 시험자료가 변조되었거나 누락되어 AI 평가를 차단했습니다.')
