"""테스트용 가짜 수정 엔진.

실제 엔진처럼 프로젝트 폴더(cwd)에서 실행되고 stdin으로 프롬프트를 받는다.
FAKE_ENGINE_SCRIPT에 호출 순서별 동작을 쉼표로 적는다 (마지막 동작은 반복).

    fix     올바르게 수정
    break   앱은 실행되지만 기존 테스트를 깨뜨리는 잘못된 수정
    noop    아무것도 하지 않음
    vandal  오류는 그대로 두고 파일을 건드리고 새 파일을 만듦
    unhang  app.py를 즉시 종료하는 코드로 교체

받은 프롬프트는 FAKE_ENGINE_STATE 폴더의 calls.json에 기록한다.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

REWRITES = {
    "service.py": {
        "buggy": '    email = user["email"]\n',
        "broken": '    email = user.get("email", "이메일 없음").upper()\n',
        "fixed": '    email = user.get("email", "이메일 없음")\n',
    },
    "worker.py": {
        "buggy": '    return job["total"] / job["count"]\n',
        "broken": None,
        "fixed": (
            '    if job["count"] == 0:\n'
            "        return 0.0\n"
            '    return job["total"] / job["count"]\n'
        ),
    },
}


def rewrite(target: str) -> None:
    for name, variants in REWRITES.items():
        path = Path(name)
        if not path.exists() or variants[target] is None:
            continue
        text = path.read_text(encoding="utf-8")
        if variants[target] in text:
            continue
        for source in ("buggy", "broken", "fixed"):
            old = variants[source]
            if source != target and old and old in text:
                path.write_text(text.replace(old, variants[target]), encoding="utf-8")
                break


def vandalize() -> None:
    for name in REWRITES:
        path = Path(name)
        if path.exists():
            with open(path, "a", encoding="utf-8") as fh:
                fh.write("# 쓸모없는 수정\n")
    Path("junk.py").write_text("JUNK = True\n", encoding="utf-8")


def main() -> int:
    prompt = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    state_dir = Path(
        os.environ.get("FAKE_ENGINE_STATE")
        or Path(tempfile.gettempdir()) / "fake_engine_state"
    )
    state_dir.mkdir(parents=True, exist_ok=True)
    calls_file = state_dir / "calls.json"
    calls = json.loads(calls_file.read_text(encoding="utf-8")) if calls_file.exists() else []

    actions = os.environ.get("FAKE_ENGINE_SCRIPT", "fix").split(",")
    action = actions[min(len(calls), len(actions) - 1)].strip()

    calls.append(prompt)
    calls_file.write_text(json.dumps(calls, ensure_ascii=False), encoding="utf-8")

    print(f"[fake-engine] 호출 {len(calls)}회차, 동작: {action}")
    if action == "fix":
        rewrite("fixed")
    elif action == "break":
        rewrite("broken")
    elif action == "vandal":
        vandalize()
    elif action == "unhang":
        Path("app.py").write_text('print("정상 종료")\n', encoding="utf-8")
    elif action != "noop":
        print(f"[fake-engine] 알 수 없는 동작: {action}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
