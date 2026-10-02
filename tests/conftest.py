import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from auto_debugger.config import Config, EngineConfig, Timeouts  # noqa: E402

EXAMPLES = ROOT / "examples"
FAKE_ENGINE = ROOT / "tests" / "fake_engine.py"


class FakeEngine:
    def __init__(self, state_dir: Path, monkeypatch) -> None:
        self.state_dir = state_dir
        self.command = [sys.executable, str(FAKE_ENGINE)]
        self._monkeypatch = monkeypatch
        monkeypatch.setenv("FAKE_ENGINE_STATE", str(state_dir))
        self.script("fix")

    def script(self, *actions: str) -> None:
        self._monkeypatch.setenv("FAKE_ENGINE_SCRIPT", ",".join(actions))

    def prompts(self) -> list[str]:
        calls = self.state_dir / "calls.json"
        if not calls.exists():
            return []
        return json.loads(calls.read_text(encoding="utf-8"))


@pytest.fixture
def fake_engine(tmp_path, monkeypatch):
    # 같은 초 안에 소스가 바뀌어도 오래된 .pyc가 쓰이지 않게 한다
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    return FakeEngine(tmp_path / "engine_state", monkeypatch)


@pytest.fixture
def crash_project(tmp_path):
    return Path(shutil.copytree(EXAMPLES / "crash_app", tmp_path / "crash_app"))


@pytest.fixture
def server_project(tmp_path):
    return Path(shutil.copytree(EXAMPLES / "server_app", tmp_path / "server_app"))


@pytest.fixture
def make_config(fake_engine):
    def factory(project: Path, **overrides) -> Config:
        options = dict(
            project_dir=project,
            app_command=[sys.executable, "app.py"],
            test_command=[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            engine=EngineConfig(type="custom", command=list(fake_engine.command)),
            timeouts=Timeouts(app=20, test=120, engine=60),
        )
        options.update(overrides)
        return Config(**options)

    return factory
