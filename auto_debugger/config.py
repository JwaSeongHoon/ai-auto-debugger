"""설정 dataclass와 config.yaml 로드/검증."""

from __future__ import annotations

import os
import shlex
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

MODES = ("oneshot", "service")
ENGINE_TYPES = ("codex", "claude", "custom")


class ConfigError(Exception):
    """설정이 잘못되었을 때 발생한다."""


@dataclass
class Timeouts:
    app: float | None = 60  # oneshot 모드 전용. None이면 제한 없음
    test: float | None = 300
    engine: float | None = 900


@dataclass
class ServiceConfig:
    log_file: str | None = "error.log"
    healthy_after: float = 10
    poll_interval: float = 0.5
    keep_running: bool = False  # True면 정상 판정 후에도 계속 감시


@dataclass
class EngineConfig:
    type: str = "codex"
    command: list[str] | None = None  # 지정하면 type의 기본 명령 대신 사용


def normalize_command(value: Any, name: str) -> list[str] | None:
    """문자열/리스트 명령을 리스트로 통일하고 python은 현재 인터프리터로 바꾼다."""
    if value is None:
        return None
    if isinstance(value, str):
        command = shlex.split(value, posix=(os.name != "nt"))
    elif isinstance(value, (list, tuple)):
        command = [str(part) for part in value]
    else:
        raise ConfigError(f"{name}은(는) 문자열 또는 리스트여야 합니다.")
    if not command:
        raise ConfigError(f"{name}이(가) 비어 있습니다.")
    if command[0] in ("python", "python3"):
        command[0] = sys.executable
    return command


@dataclass
class Config:
    project_dir: Path
    app_command: list[str]
    mode: str = "oneshot"
    test_command: list[str] | None = None
    smoke_command: list[str] | None = None
    max_repairs: int = 3
    max_test_fixes: int = 2
    timeouts: Timeouts = field(default_factory=Timeouts)
    service: ServiceConfig = field(default_factory=ServiceConfig)
    engine: EngineConfig = field(default_factory=EngineConfig)
    rollback_on_failure: bool = True
    logs_dir: str = "logs"
    dry_run: bool = False

    def __post_init__(self) -> None:
        self.project_dir = Path(self.project_dir).resolve()
        if not self.project_dir.is_dir():
            raise ConfigError(f"project_dir를 찾을 수 없습니다: {self.project_dir}")

        self.app_command = normalize_command(self.app_command, "app_command")
        if self.app_command is None:
            raise ConfigError("app_command는 필수입니다.")
        self.test_command = normalize_command(self.test_command, "test_command")
        self.smoke_command = normalize_command(self.smoke_command, "smoke_command")
        self.engine.command = normalize_command(self.engine.command, "engine.command")

        if self.mode not in MODES:
            raise ConfigError(f"mode는 {MODES} 중 하나여야 합니다: {self.mode}")
        if self.engine.type not in ENGINE_TYPES:
            raise ConfigError(
                f"engine.type은 {ENGINE_TYPES} 중 하나여야 합니다: {self.engine.type}"
            )
        if self.engine.type == "custom" and not self.engine.command:
            raise ConfigError("engine.type이 custom이면 engine.command가 필요합니다.")
        for name in ("max_repairs", "max_test_fixes"):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0:
                raise ConfigError(f"{name}은(는) 0 이상의 정수여야 합니다: {value}")
        if self.service.poll_interval <= 0:
            raise ConfigError("service.poll_interval은 0보다 커야 합니다.")


def _section(cls: type, data: Any, name: str) -> Any:
    if data is None:
        return cls()
    if not isinstance(data, dict):
        raise ConfigError(f"{name}은(는) 매핑이어야 합니다.")
    allowed = {f.name for f in fields(cls)}
    unknown = set(data) - allowed
    if unknown:
        raise ConfigError(f"{name}에 알 수 없는 항목이 있습니다: {sorted(unknown)}")
    return cls(**data)


def load_config(path: str | Path, overrides: dict[str, Any] | None = None) -> Config:
    """YAML 설정 파일을 읽어 Config를 만든다. overrides는 CLI 인자용이다."""
    import yaml

    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"설정 파일을 찾을 수 없습니다: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"설정 파일을 해석할 수 없습니다: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("설정 파일의 최상위는 매핑이어야 합니다.")

    allowed = {f.name for f in fields(Config)} - {"dry_run"}
    unknown = set(data) - allowed
    if unknown:
        raise ConfigError(f"알 수 없는 설정 항목: {sorted(unknown)}")

    overrides = {k: v for k, v in (overrides or {}).items() if v is not None}

    # project_dir의 상대 경로는 설정 파일 위치 기준
    project_dir = overrides.pop("project_dir", None)
    if project_dir is None:
        project_dir = path.resolve().parent / data.get("project_dir", ".")
    data["project_dir"] = project_dir

    data["timeouts"] = _section(Timeouts, data.get("timeouts"), "timeouts")
    data["service"] = _section(ServiceConfig, data.get("service"), "service")
    data["engine"] = _section(EngineConfig, data.get("engine"), "engine")

    engine_type = overrides.pop("engine", None)
    if engine_type is not None:
        data["engine"] = EngineConfig(type=engine_type)

    data.update(overrides)
    if "app_command" not in data:
        raise ConfigError("app_command는 필수입니다.")
    return Config(**data)
