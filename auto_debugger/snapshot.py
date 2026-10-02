"""수정 전 백업, 변경 diff, 롤백."""

from __future__ import annotations

import difflib
import filecmp
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

STATE_DIR = ".auto_repair"
DEFAULT_EXCLUDES = {
    ".git",
    STATE_DIR,
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".idea",
    ".vscode",
}
MAX_DIFF_BYTES = 1_000_000


class Snapshot:
    def __init__(self, project_dir: Path, extra_excludes: Iterable[str] = ()) -> None:
        self.project_dir = Path(project_dir)
        self.excludes = DEFAULT_EXCLUDES | set(extra_excludes)
        self.backup_dir: Path | None = None
        self.files: set[Path] = set()

    @property
    def created(self) -> bool:
        return self.backup_dir is not None

    def _walk(self) -> Iterator[Path]:
        """백업 대상 파일의 상대 경로. 제외 폴더와 *.log는 건너뛴다."""
        for root, dirs, names in os.walk(self.project_dir):
            dirs[:] = [d for d in dirs if d not in self.excludes]
            for name in names:
                if name.endswith(".log"):
                    continue
                yield (Path(root) / name).relative_to(self.project_dir)

    def create(self) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_dir = self.project_dir / STATE_DIR / "backups" / stamp
        files = set(self._walk())
        for rel in files:
            target = backup_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.project_dir / rel, target)
        backup_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir = backup_dir
        self.files = files
        return backup_dir

    def changes(self) -> tuple[list[Path], list[Path], list[Path]]:
        """백업 이후 (수정됨, 추가됨, 삭제됨) 파일 목록."""
        assert self.backup_dir is not None
        current = set(self._walk())
        modified = sorted(
            rel
            for rel in self.files & current
            if not filecmp.cmp(self.backup_dir / rel, self.project_dir / rel, shallow=False)
        )
        return modified, sorted(current - self.files), sorted(self.files - current)

    @staticmethod
    def _lines(path: Path) -> list[str] | None:
        try:
            if path.stat().st_size > MAX_DIFF_BYTES:
                return None
            return path.read_text(encoding="utf-8").splitlines(keepends=True)
        except (OSError, UnicodeDecodeError):
            return None

    def diff(self) -> str:
        """백업 대비 현재 상태의 unified diff (텍스트 파일만)."""
        if not self.created:
            return ""
        modified, added, deleted = self.changes()
        chunks: list[str] = []
        for rel in modified + added + deleted:
            name = rel.as_posix()
            old = [] if rel in added else self._lines(self.backup_dir / rel)
            new = [] if rel in deleted else self._lines(self.project_dir / rel)
            if old is None or new is None:
                chunks.append(f"Binary or large file changed: {name}\n")
                continue
            chunks.extend(
                difflib.unified_diff(
                    old,
                    new,
                    fromfile="/dev/null" if rel in added else f"a/{name}",
                    tofile="/dev/null" if rel in deleted else f"b/{name}",
                )
            )
        return "".join(chunks)

    def restore(self) -> list[str]:
        """백업 시점으로 되돌린다.

        백업 이후 새로 생긴 파일은 지우지 않고 .auto_repair/rolled_back/으로 옮긴다.
        """
        assert self.backup_dir is not None
        modified, added, deleted = self.changes()
        actions: list[str] = []
        for rel in modified + deleted:
            target = self.project_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.backup_dir / rel, target)
            actions.append(f"복원: {rel.as_posix()}")
        if added:
            trash = self.project_dir / STATE_DIR / "rolled_back" / self.backup_dir.name
            for rel in added:
                target = trash / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(self.project_dir / rel), str(target))
                actions.append(f"이동: {rel.as_posix()} → {STATE_DIR}/rolled_back/")
        return actions
