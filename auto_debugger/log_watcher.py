"""로그 파일에 새로 추가된 내용을 폴링으로 읽는다."""

from __future__ import annotations

from pathlib import Path


class LogWatcher:
    def __init__(self, path: Path, start_at_end: bool = True) -> None:
        self.path = Path(path)
        self._offset = self._size() if start_at_end else 0

    def _size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    def read_new(self) -> str:
        """마지막으로 읽은 위치 이후의 내용을 돌려준다."""
        size = self._size()
        if size < self._offset:
            self._offset = 0  # 로그가 잘리거나 로테이션됨
        if size == self._offset:
            return ""
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self._offset)
                data = fh.read()
        except OSError:
            return ""
        self._offset += len(data)
        return data.decode("utf-8", errors="replace").replace("\r\n", "\n")
