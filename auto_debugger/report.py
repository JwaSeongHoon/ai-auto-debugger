"""콘솔 출력과 logs/ 폴더 기록."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def setup_console() -> None:
    """Windows 콘솔(cp949)에서도 한글/기호가 깨지거나 예외가 나지 않게 한다."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def banner(title: str) -> None:
    print("\n====================================")
    print(title)
    print("====================================", flush=True)


class Reporter:
    def __init__(self, logs_dir: Path) -> None:
        self.logs_dir = Path(logs_dir)

    def save(self, prefix: str, text: str, suffix: str = ".log") -> Path:
        """logs/<prefix>_YYYYMMDD_HHMMSS<suffix>로 저장한다."""
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.logs_dir / f"{prefix}_{stamp}{suffix}"
        n = 2
        while path.exists():
            path = self.logs_dir / f"{prefix}_{stamp}_{n}{suffix}"
            n += 1
        path.write_text(text, encoding="utf-8")
        return path

    def save_summary(self, summary: dict[str, Any]) -> Path:
        return self.save(
            "session", json.dumps(summary, ensure_ascii=False, indent=2), ".json"
        )
