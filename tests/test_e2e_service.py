"""service 모드 전체 흐름 테스트: 앱은 종료되지 않고 error.log에만 예외를 남긴다."""

from auto_debugger.config import ServiceConfig
from auto_debugger.supervisor import Supervisor

FAST = dict(log_file="error.log", healthy_after=2, poll_interval=0.2)


def test_logged_exception_is_detected_and_repaired(server_project, fake_engine, make_config):
    fake_engine.script("fix")
    config = make_config(server_project, mode="service", service=ServiceConfig(**FAST))

    result = Supervisor(config).run()

    assert result.success and result.exit_code == 0
    assert result.repairs == 1 and result.engine_calls == 1
    prompt = fake_engine.prompts()[0]
    assert "ZeroDivisionError" in prompt
    assert "error.log" in prompt
    assert "return 0.0" in (server_project / "worker.py").read_text(encoding="utf-8")


def test_old_log_entries_are_ignored_after_restart(server_project, fake_engine, make_config):
    """수정 전 실행이 남긴 error.log의 Traceback 때문에 다시 실패로 판정하면 안 된다."""
    fake_engine.script("fix")
    config = make_config(
        server_project, mode="service", max_repairs=1, service=ServiceConfig(**FAST)
    )

    result = Supervisor(config).run()

    assert result.exit_code == 0
    assert "ZeroDivisionError" in (server_project / "error.log").read_text(encoding="utf-8")


def test_unfixable_service_fails_and_rolls_back(server_project, fake_engine, make_config):
    fake_engine.script("vandal")
    original = (server_project / "worker.py").read_text(encoding="utf-8")
    config = make_config(
        server_project, mode="service", max_repairs=1, service=ServiceConfig(**FAST)
    )

    result = Supervisor(config).run()

    assert result.exit_code == 1 and result.rolled_back
    assert (server_project / "worker.py").read_text(encoding="utf-8") == original


def test_service_crash_on_startup_is_detected(server_project, fake_engine, make_config):
    """service 모드에서도 앱이 바로 죽으면 stderr의 Traceback으로 감지한다."""
    (server_project / "app.py").write_text(
        'from worker import process\nprocess({"total": 1, "count": 0})\n', encoding="utf-8"
    )
    fake_engine.script("fix")
    config = make_config(server_project, mode="service", service=ServiceConfig(**FAST))

    result = Supervisor(config).run()

    assert result.exit_code == 0 and result.engine_calls == 1
    assert "ZeroDivisionError" in fake_engine.prompts()[0]
