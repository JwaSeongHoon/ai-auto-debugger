"""AI 엔진에 보낼 수정 요청 프롬프트."""

from __future__ import annotations

MAX_ERROR_CHARS = 15000
MAX_TEST_CHARS = 10000

RULES = """작업 규칙:

1. traceback을 기준으로 근본 원인을 분석한다.
2. 관련된 프로젝트 파일을 직접 확인한다.
3. 필요한 소스만 최소한으로 수정한다.
4. 기존 정상 기능을 임의로 제거하지 않는다.
5. .env, API Key, 비밀번호 등 보안정보를 변경하지 않는다.
6. 임시방편으로 예외를 숨기지 않는다.
7. 오류의 근본 원인을 해결한다.
8. 수정 후 가능한 테스트를 실행한다.
9. 기존 코드 구조를 최대한 유지한다.
10. 작업 완료 후 무엇을 수정했는지 요약한다."""


def tail(text: str, limit: int) -> str:
    """너무 긴 로그는 뒤쪽만 남긴다 (오류는 보통 끝에 있다)."""
    return text if len(text) <= limit else text[-limit:]


def build_prompt(
    error_text: str,
    test_text: str = "",
    history: list[str] | None = None,
) -> str:
    """history는 이전 시도들에서 발생했던 오류 시그니처 목록이다."""
    parts = [
        "현재 Python 프로젝트를 자동 복구하고 있습니다.",
        "",
        "프로젝트 전체 소스를 분석하고 아래 오류의 근본 원인을 찾아 수정하세요.",
        "",
        "[애플리케이션 오류]",
        "",
        tail(error_text, MAX_ERROR_CHARS).strip(),
        "",
    ]
    if test_text.strip():
        parts += [
            "[추가 테스트 오류]",
            "",
            tail(test_text, MAX_TEST_CHARS).strip(),
            "",
        ]
    if history:
        parts += ["[이전 시도]", ""]
        parts += [
            f"- 이전 시도 {n}: `{signature}` 오류를 수정했으나 문제가 해결되지 않았습니다."
            for n, signature in enumerate(history, start=1)
        ]
        parts += ["", "이전과 같은 수정을 반복하지 말고 다른 원인을 검토하세요.", ""]
    parts.append(RULES)
    return "\n".join(parts) + "\n"
