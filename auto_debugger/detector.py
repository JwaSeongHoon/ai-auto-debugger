"""출력/로그에서 Python Traceback을 찾아낸다."""

from __future__ import annotations

import re
from pathlib import PurePath

TRACEBACK_HEADER = "Traceback (most recent call last):"
_FRAME = re.compile(r'File "(.+?)", line \d+, in (\S+)')


def extract_tracebacks(text: str) -> list[str]:
    """완결된 Traceback 블록만 돌려준다.

    예외 줄(들여쓰기 없는 마지막 줄)까지 기록된 것만 완결로 본다.
    로그 파일에 아직 쓰이는 중인 Traceback은 포함하지 않는다.
    """
    lines = text.splitlines()
    blocks: list[str] = []
    i = 0
    while i < len(lines):
        if TRACEBACK_HEADER not in lines[i]:
            i += 1
            continue
        block = [lines[i]]
        j = i + 1
        while j < len(lines) and (
            lines[j].startswith((" ", "\t")) or not lines[j].strip()
        ):
            block.append(lines[j])
            j += 1
        if j >= len(lines):
            break  # 예외 줄이 아직 없음
        block.append(lines[j])
        blocks.append("\n".join(block))
        i = j + 1
    return blocks


def error_signature(text: str) -> str | None:
    """같은 오류의 반복 여부를 판단하기 위한 시그니처.

    수정 과정에서 줄 번호가 바뀌므로 예외 줄 + 마지막 프레임의 파일/함수만 쓴다.
    """
    blocks = extract_tracebacks(text)
    if not blocks:
        return None
    last = blocks[-1]
    exception_line = last.splitlines()[-1].strip()
    frames = _FRAME.findall(last)
    if not frames:
        return exception_line
    file_name, func = frames[-1]
    return f"{exception_line} @ {PurePath(file_name).name}:{func}"
