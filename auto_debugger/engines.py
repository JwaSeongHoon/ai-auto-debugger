"""코드를 수정하는 AI 엔진(Codex CLI, Claude Code CLI, 임의 명령) 호출."""

from __future__ import annotations

from pathlib import Path

from .config import EngineConfig
from .runner import CommandNotFound, RunResult, resolve_command, run_command

# 모든 엔진은 프롬프트를 stdin으로 받는다.
PRESETS: dict[str, list[str]] = {
    # 최신 Codex CLI에는 --full-auto가 없다. 프로젝트 폴더 쓰기만 허용하는 샌드박스를 쓴다.
    "codex": ["codex", "exec", "--sandbox", "workspace-write", "--skip-git-repo-check", "-"],
    "claude": ["claude", "-p", "--permission-mode", "acceptEdits"],
}

INSTALL_HINTS = {
    "codex": "npm install -g @openai/codex@latest",
    "claude": "npm install -g @anthropic-ai/claude-code",
}


class EngineError(Exception):
    """엔진을 사용할 수 없을 때 발생한다."""


class Engine:
    def __init__(self, config: EngineConfig, project_dir: Path, timeout: float | None) -> None:
        self.type = config.type
        self.command = config.command or PRESETS[config.type]
        self.project_dir = project_dir
        self.timeout = timeout

    def check_available(self) -> None:
        try:
            resolve_command(self.command)
        except CommandNotFound as exc:
            hint = INSTALL_HINTS.get(self.type)
            message = f"AI 엔진 실행 파일을 찾을 수 없습니다: {exc}"
            if hint:
                message += f"\n설치: {hint}"
            raise EngineError(message) from exc

    def repair(self, prompt: str) -> RunResult:
        """프로젝트 폴더에서 엔진을 실행해 소스를 수정하게 한다."""
        return run_command(
            self.command,
            cwd=self.project_dir,
            timeout=self.timeout,
            input_text=prompt,
            echo=True,
        )
