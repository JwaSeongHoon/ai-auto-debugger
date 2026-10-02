"""모듈별 단위 테스트."""

import sys
import time

import pytest

from auto_debugger.config import Config, ConfigError, load_config
from auto_debugger.detector import error_signature, extract_tracebacks
from auto_debugger.engines import Engine, EngineError
from auto_debugger.config import EngineConfig
from auto_debugger.log_watcher import LogWatcher
from auto_debugger.prompt import MAX_ERROR_CHARS, build_prompt
from auto_debugger.runner import CommandNotFound, run_command
from auto_debugger.snapshot import Snapshot

TRACEBACK = """Traceback (most recent call last):
  File "app.py", line 83, in <module>
    start_app()
  File "C:\\work\\service.py", line 42, in start_app
    result = user["email"]
             ~~~~^^^^^^^^^
KeyError: 'email'
"""

# ---------------------------------------------------------------- detector


def test_extract_traceback_from_noisy_output():
    text = "서버 시작\n" + TRACEBACK + "다음 줄\n"
    blocks = extract_tracebacks(text)
    assert len(blocks) == 1
    assert blocks[0].startswith("Traceback")
    assert blocks[0].endswith("KeyError: 'email'")


def test_extract_traceback_from_logging_output():
    text = "2026-10-02 10:23:01 ERROR job 3 처리 실패\n" + TRACEBACK
    assert len(extract_tracebacks(text)) == 1


def test_incomplete_traceback_is_not_reported():
    partial = TRACEBACK[: TRACEBACK.index("KeyError")]
    assert extract_tracebacks(partial) == []


def test_multiple_tracebacks():
    assert len(extract_tracebacks(TRACEBACK + "\n" + TRACEBACK)) == 2


def test_signature_ignores_line_numbers():
    moved = TRACEBACK.replace("line 42", "line 57")
    assert error_signature(TRACEBACK) == error_signature(moved)
    assert error_signature(TRACEBACK) == "KeyError: 'email' @ service.py:start_app"
    assert error_signature("그냥 출력") is None


# ------------------------------------------------------------------ config


def test_config_normalizes_python_and_string_commands(tmp_path):
    config = Config(project_dir=tmp_path, app_command="python app.py --port 80")
    assert config.app_command == [sys.executable, "app.py", "--port", "80"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"mode": "daemon"},
        {"max_repairs": -1},
        {"engine": EngineConfig(type="gpt")},
        {"engine": EngineConfig(type="custom")},
        {"app_command": []},
    ],
)
def test_config_rejects_invalid_values(tmp_path, overrides):
    options = {"project_dir": tmp_path, "app_command": ["python", "app.py"], **overrides}
    with pytest.raises(ConfigError):
        Config(**options)


def test_config_rejects_missing_project_dir(tmp_path):
    with pytest.raises(ConfigError):
        Config(project_dir=tmp_path / "none", app_command=["python", "app.py"])


def test_load_config_resolves_project_dir_relative_to_file(tmp_path):
    (tmp_path / "proj").mkdir()
    path = tmp_path / "config.yaml"
    path.write_text(
        "project_dir: proj\n"
        "mode: service\n"
        "app_command: [python, app.py]\n"
        "timeouts: {app: 5}\n"
        "service: {healthy_after: 3}\n"
        "engine: {type: claude}\n",
        encoding="utf-8",
    )
    config = load_config(path, overrides={"max_repairs": 7, "engine": None})
    assert config.project_dir == (tmp_path / "proj").resolve()
    assert config.mode == "service"
    assert config.timeouts.app == 5 and config.timeouts.test == 300
    assert config.service.healthy_after == 3
    assert config.engine.type == "claude"
    assert config.max_repairs == 7


def test_load_config_cli_engine_override(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "app_command: [python, app.py]\nengine: {type: custom, command: [x]}\n",
        encoding="utf-8",
    )
    config = load_config(path, overrides={"engine": "claude"})
    assert config.engine.type == "claude" and config.engine.command is None


@pytest.mark.parametrize(
    "body",
    [
        "app_command: [python, app.py]\nunknown_key: 1\n",
        "app_command: [python, app.py]\ntimeouts: {apps: 1}\n",
        "mode: oneshot\n",
        "- just\n- a list\n",
    ],
)
def test_load_config_rejects_bad_files(tmp_path, body):
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_repo_config_template_is_valid_yaml_but_points_to_placeholder():
    from conftest import ROOT

    with pytest.raises(ConfigError, match="project_dir"):
        load_config(ROOT / "config.yaml")


@pytest.mark.parametrize("name", ["crash_app", "server_app"])
def test_example_configs_load(name):
    from conftest import EXAMPLES

    config = load_config(EXAMPLES / name / "config.yaml")
    assert config.project_dir == (EXAMPLES / name).resolve()


# ------------------------------------------------------------------ runner


def test_run_command_captures_utf8_output_and_exit_code(tmp_path):
    script = tmp_path / "s.py"
    script.write_text(
        'import sys\nprint("한글 ✅")\nprint("오류", file=sys.stderr)\nsys.exit(3)\n',
        encoding="utf-8",
    )
    result = run_command([sys.executable, str(script)], tmp_path)
    assert result.returncode == 3 and not result.ok
    assert "한글 ✅" in result.stdout
    assert "오류" in result.stderr


def test_run_command_passes_stdin(tmp_path):
    result = run_command(
        [sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"],
        tmp_path,
        input_text="hello 프롬프트\n여러 줄",
    )
    assert result.ok
    assert "HELLO 프롬프트" in result.stdout and "여러 줄" in result.stdout


def test_run_command_timeout_kills_process_tree(tmp_path):
    marker = tmp_path / "child_alive.txt"
    child = f"import time; time.sleep(3); open(r'{marker}', 'w').write('x')"
    parent = (
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
        "time.sleep(60)\n"
    )
    started = time.monotonic()
    result = run_command([sys.executable, "-c", parent], tmp_path, timeout=1)
    assert result.timed_out and result.returncode is None
    assert time.monotonic() - started < 20
    time.sleep(4)
    assert not marker.exists(), "자식 프로세스가 종료되지 않았습니다"


def test_run_command_missing_executable(tmp_path):
    with pytest.raises(CommandNotFound):
        run_command(["no-such-command-xyz"], tmp_path)


def test_engine_check_available(tmp_path):
    Engine(EngineConfig("custom", [sys.executable]), tmp_path, 10).check_available()
    with pytest.raises(EngineError, match="no-such-engine"):
        Engine(EngineConfig("custom", ["no-such-engine"]), tmp_path, 10).check_available()


# ------------------------------------------------------------- log watcher


def test_log_watcher_reads_only_new_content(tmp_path):
    log = tmp_path / "error.log"
    log.write_text("이전 내용\n", encoding="utf-8")
    watcher = LogWatcher(log)
    assert watcher.read_new() == ""

    with open(log, "a", encoding="utf-8") as fh:
        fh.write("새 오류\n")
    assert watcher.read_new() == "새 오류\n"
    assert watcher.read_new() == ""


def test_log_watcher_handles_missing_and_truncated_file(tmp_path):
    log = tmp_path / "error.log"
    watcher = LogWatcher(log)
    assert watcher.read_new() == ""

    log.write_text("첫 번째 긴 내용\n", encoding="utf-8")
    assert watcher.read_new() == "첫 번째 긴 내용\n"

    log.write_text("짧음\n", encoding="utf-8")  # 로테이션
    assert watcher.read_new() == "짧음\n"


# ---------------------------------------------------------------- snapshot


def test_snapshot_diff_and_restore(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "pkg" / "b.py").write_text("y = 1\n", encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "old.txt").write_text("log", encoding="utf-8")

    snapshot = Snapshot(tmp_path, extra_excludes={"logs"})
    assert snapshot.diff() == ""
    snapshot.create()
    assert snapshot.diff() == ""

    (tmp_path / "a.py").write_text("x = 2\n", encoding="utf-8")
    (tmp_path / "pkg" / "b.py").unlink()
    (tmp_path / "new.py").write_text("z = 1\n", encoding="utf-8")
    (tmp_path / "logs" / "new.txt").write_text("log", encoding="utf-8")
    (tmp_path / "app.log").write_text("log", encoding="utf-8")

    diff = snapshot.diff()
    assert "-x = 1" in diff and "+x = 2" in diff
    assert "+z = 1" in diff and "-y = 1" in diff
    assert "logs" not in diff and "app.log" not in diff

    snapshot.restore()
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x = 1\n"
    assert (tmp_path / "pkg" / "b.py").read_text(encoding="utf-8") == "y = 1\n"
    assert not (tmp_path / "new.py").exists()
    assert (tmp_path / "logs" / "new.txt").exists()
    assert (tmp_path / "app.log").exists()
    assert snapshot.diff() == ""


# ------------------------------------------------------------------ prompt


def test_prompt_contains_sections_and_truncates_long_logs():
    error = "앞부분" + "x" * (MAX_ERROR_CHARS * 2) + "KeyError: 'email'"
    prompt = build_prompt(error, test_text="FAILED test_a", history=["sig-1", "sig-2"])
    assert "[애플리케이션 오류]" in prompt
    assert "KeyError: 'email'" in prompt and "앞부분" not in prompt
    assert "[추가 테스트 오류]" in prompt and "FAILED test_a" in prompt
    assert "이전 시도 2: `sig-2`" in prompt
    assert len(prompt) < MAX_ERROR_CHARS + 2000


def test_prompt_omits_empty_sections():
    prompt = build_prompt("오류")
    assert "[추가 테스트 오류]" not in prompt
    assert "[이전 시도]" not in prompt
