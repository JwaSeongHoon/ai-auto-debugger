"""oneshot 모드 전체 흐름 테스트 (가짜 엔진 사용)."""

import time
from pathlib import Path

import yaml

import auto_repair
from auto_debugger.config import EngineConfig, Timeouts
from auto_debugger.supervisor import Supervisor


def test_healthy_app_never_calls_engine(crash_project, fake_engine, make_config):
    service = crash_project / "service.py"
    service.write_text(
        service.read_text(encoding="utf-8").replace('user["email"]', 'user.get("email", "-")'),
        encoding="utf-8",
    )

    result = Supervisor(make_config(crash_project)).run()

    assert result.exit_code == 0
    assert result.engine_calls == 0
    assert fake_engine.prompts() == []
    assert not (crash_project / "logs").exists()


def test_crash_is_repaired_in_one_call(crash_project, fake_engine, make_config):
    fake_engine.script("fix")

    result = Supervisor(make_config(crash_project)).run()

    assert result.success and result.exit_code == 0
    assert result.repairs == 1 and result.engine_calls == 1
    prompts = fake_engine.prompts()
    assert len(prompts) == 1
    assert "KeyError: 'email'" in prompts[0]
    assert "작업 규칙" in prompts[0]

    error_logs = list((crash_project / "logs").glob("error_*.log"))
    assert len(error_logs) == 1
    assert "KeyError" in error_logs[0].read_text(encoding="utf-8")
    patch = Path(result.patch_file).read_text(encoding="utf-8")
    assert "service.py" in patch and '+    email = user.get("email"' in patch
    assert list((crash_project / "logs").glob("session_*.json"))


def test_fix_that_breaks_tests_is_sent_back_with_test_output(
    crash_project, fake_engine, make_config
):
    fake_engine.script("break", "fix")

    result = Supervisor(make_config(crash_project)).run()

    assert result.exit_code == 0
    assert result.repairs == 1 and result.engine_calls == 2
    prompts = fake_engine.prompts()
    assert "[추가 테스트 오류]" not in prompts[0]
    assert "[추가 테스트 오류]" in prompts[1]
    assert "test_service" in prompts[1]


def test_ineffective_fix_is_retried_with_history(crash_project, fake_engine, make_config):
    fake_engine.script("noop", "fix")

    result = Supervisor(make_config(crash_project)).run()

    assert result.exit_code == 0
    assert result.repairs == 2 and result.engine_calls == 2
    prompts = fake_engine.prompts()
    assert "이전 시도" not in prompts[0]
    assert "이전 시도 1" in prompts[1]
    assert "KeyError: 'email'" in prompts[1]


def test_unfixable_app_is_rolled_back(crash_project, fake_engine, make_config):
    fake_engine.script("vandal")
    original = (crash_project / "service.py").read_text(encoding="utf-8")

    result = Supervisor(make_config(crash_project, max_repairs=2)).run()

    assert not result.success and result.exit_code == 1
    assert result.engine_calls == 2
    assert result.rolled_back
    assert (crash_project / "service.py").read_text(encoding="utf-8") == original
    assert not (crash_project / "junk.py").exists()
    assert list((crash_project / ".auto_repair" / "rolled_back").rglob("junk.py"))
    assert "쓸모없는 수정" in Path(result.patch_file).read_text(encoding="utf-8")


def test_rollback_can_be_disabled(crash_project, fake_engine, make_config):
    fake_engine.script("vandal")

    result = Supervisor(
        make_config(crash_project, max_repairs=1, rollback_on_failure=False)
    ).run()

    assert result.exit_code == 1 and not result.rolled_back
    assert (crash_project / "junk.py").exists()


def test_hanging_app_is_detected_by_timeout(crash_project, fake_engine, make_config):
    (crash_project / "app.py").write_text("import time\ntime.sleep(120)\n", encoding="utf-8")
    fake_engine.script("unhang")
    config = make_config(crash_project, timeouts=Timeouts(app=2, test=120, engine=60))

    started = time.monotonic()
    result = Supervisor(config).run()

    assert result.exit_code == 0
    assert time.monotonic() - started < 60
    assert "타임아웃" in fake_engine.prompts()[0]


def test_missing_engine_exits_with_config_error(crash_project, fake_engine, make_config):
    original = (crash_project / "service.py").read_text(encoding="utf-8")
    config = make_config(
        crash_project, engine=EngineConfig(type="custom", command=["no-such-engine-xyz"])
    )

    result = Supervisor(config).run()

    assert result.exit_code == 2
    assert "no-such-engine-xyz" in result.message
    assert (crash_project / "service.py").read_text(encoding="utf-8") == original
    assert not (crash_project / ".auto_repair").exists()


def test_failing_smoke_command_triggers_repair(crash_project, fake_engine, make_config):
    """앱은 정상 종료하지만 smoke 명령이 실패하는 경우."""
    (crash_project / "app.py").write_text('print("ok")\n', encoding="utf-8")
    (crash_project / "smoke.py").write_text(
        "from service import start_app\nstart_app()\n", encoding="utf-8"
    )
    fake_engine.script("fix")
    config = make_config(crash_project, smoke_command=["python", "smoke.py"])

    result = Supervisor(config).run()

    assert result.exit_code == 0 and result.engine_calls == 1
    assert "Smoke Test" in fake_engine.prompts()[0]


def _write_yaml(project: Path, fake_engine, **extra) -> Path:
    data = {
        "project_dir": ".",
        "app_command": ["python", "app.py"],
        "test_command": ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        "engine": {"type": "custom", "command": fake_engine.command},
        **extra,
    }
    path = project / "config.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_cli_dry_run_changes_nothing(crash_project, fake_engine, capsys):
    config_path = _write_yaml(crash_project, fake_engine)
    original = (crash_project / "service.py").read_text(encoding="utf-8")

    exit_code = auto_repair.main(["--config", str(config_path), "--dry-run"])

    assert exit_code == 1
    assert fake_engine.prompts() == []
    assert (crash_project / "service.py").read_text(encoding="utf-8") == original
    assert not (crash_project / ".auto_repair").exists()
    out = capsys.readouterr().out
    assert "dry-run" in out and "KeyError: 'email'" in out


def test_cli_repairs_using_yaml_config(crash_project, fake_engine):
    config_path = _write_yaml(crash_project, fake_engine, max_repairs=1)

    assert auto_repair.main(["--config", str(config_path)]) == 0
    assert len(fake_engine.prompts()) == 1


def test_cli_missing_config_returns_2(tmp_path, capsys):
    assert auto_repair.main(["--config", str(tmp_path / "none.yaml")]) == 2
    assert "설정 오류" in capsys.readouterr().err
