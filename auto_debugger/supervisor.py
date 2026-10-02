"""전체 복구 루프: 앱 실행 → 오류 감지 → 엔진 수정 → 테스트 → 재실행."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import Config
from .detector import error_signature, extract_tracebacks
from .engines import Engine, EngineError
from .log_watcher import LogWatcher
from .prompt import build_prompt
from .report import Reporter, banner
from .runner import CommandNotFound, ManagedProcess, RunResult, run_command
from .snapshot import Snapshot

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CONFIG = 2


@dataclass
class Failure:
    kind: str  # exit | timeout | traceback | smoke | test
    signature: str
    text: str
    test_text: str = ""


@dataclass
class SessionResult:
    success: bool
    exit_code: int
    message: str
    repairs: int = 0  # 수행한 복구 회차 수
    engine_calls: int = 0
    rolled_back: bool = False
    error_logs: list[str] = field(default_factory=list)
    patch_file: str | None = None


def _format_run(result: RunResult) -> str:
    return (
        f"Return Code:\n{result.returncode}\n\n"
        f"STDOUT:\n{result.stdout}\n\n"
        f"STDERR:\n{result.stderr}\n"
    )


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


class Supervisor:
    def __init__(self, config: Config) -> None:
        self.cfg = config
        self.reporter = Reporter(config.project_dir / config.logs_dir)
        self.engine = Engine(config.engine, config.project_dir, config.timeouts.engine)
        self.snapshot = Snapshot(
            config.project_dir, extra_excludes={Path(config.logs_dir).parts[0]}
        )
        self.engine_calls = 0
        self.repairs = 0
        self.error_logs: list[str] = []

    # ------------------------------------------------------------------ 실행

    def run(self) -> SessionResult:
        try:
            result = self._run()
        except EngineError as exc:
            result = self._result(False, EXIT_CONFIG, str(exc))
        except CommandNotFound as exc:
            result = self._result(
                False, EXIT_CONFIG, f"실행 파일을 찾을 수 없습니다: {exc}"
            )
        banner(("✅ " if result.success else "⛔ ") + result.message)
        if self.error_logs or self.engine_calls:
            summary = self.reporter.save_summary(asdict(result))
            print(f"세션 요약: {summary}")
        return result

    def _result(self, success: bool, exit_code: int, message: str, **extra) -> SessionResult:
        return SessionResult(
            success=success,
            exit_code=exit_code,
            message=message,
            repairs=self.repairs,
            engine_calls=self.engine_calls,
            error_logs=list(self.error_logs),
            **extra,
        )

    def _run(self) -> SessionResult:
        cfg = self.cfg
        history: list[str] = []
        pending_test_failure = ""

        for attempt in range(cfg.max_repairs + 1):
            banner(f"애플리케이션 실행 ({attempt + 1}번째)")
            failure = self._check_app()
            if failure is None and pending_test_failure:
                failure = Failure(
                    kind="test",
                    signature="테스트 실패",
                    text="애플리케이션은 정상 실행되지만 자동 테스트가 실패합니다.",
                    test_text=pending_test_failure,
                )
            if failure is None:
                if attempt == 0:
                    return self._result(True, EXIT_OK, "애플리케이션 정상 실행")
                return self._result(
                    True,
                    EXIT_OK,
                    f"자동 복구 성공 (복구 {self.repairs}회, 엔진 호출 {self.engine_calls}회)",
                    patch_file=self._save_patch("repair"),
                )

            print(f"\n❌ 오류 감지 [{failure.kind}] {failure.signature}")
            error_log = self.reporter.save(
                "error", failure.text + ("\n" + failure.test_text if failure.test_text else "")
            )
            self.error_logs.append(str(error_log))
            print(f"오류 로그: {error_log}")

            prompt = build_prompt(failure.text, failure.test_text, history)
            if cfg.dry_run:
                banner("dry-run: 엔진에 전달될 프롬프트")
                print(prompt)
                return self._result(False, EXIT_FAILED, "dry-run: 오류를 감지했지만 수정하지 않았습니다.")
            if attempt >= cfg.max_repairs:
                break

            if not self.snapshot.created:
                self.engine.check_available()
                print(f"백업 생성: {self.snapshot.create()}")

            self.repairs += 1
            banner(f"🔧 자동 복구 {self.repairs}/{cfg.max_repairs}")
            self._call_engine(prompt)
            pending_test_failure = self._fix_until_tests_pass(failure, history)
            history.append(failure.signature)

        patch_file = self._save_patch("failed")
        rolled_back = False
        if cfg.rollback_on_failure and self.snapshot.created:
            banner("롤백: 수정 전 상태로 복원")
            for action in self.snapshot.restore():
                print(action)
            rolled_back = True
        return self._result(
            False,
            EXIT_FAILED,
            f"자동 수정 최대 횟수 {cfg.max_repairs}회를 초과했습니다."
            + (" 원본으로 롤백했습니다." if rolled_back else ""),
            rolled_back=rolled_back,
            patch_file=patch_file,
        )

    # ------------------------------------------------------------ 엔진/테스트

    def _call_engine(self, prompt: str) -> None:
        self.engine_calls += 1
        print(f"엔진 호출 #{self.engine_calls}: {' '.join(self.engine.command[:2])} ...")
        result = self.engine.repair(prompt)
        self.reporter.save(
            "engine",
            f"[PROMPT]\n{prompt}\n[STDOUT]\n{result.stdout}\n[STDERR]\n{result.stderr}\n",
        )
        if result.timed_out:
            print(f"⚠ 엔진이 {self.cfg.timeouts.engine}초 안에 끝나지 않아 종료했습니다.")
        elif result.returncode != 0:
            print(f"⚠ 엔진이 종료 코드 {result.returncode}(으)로 끝났습니다.")

    def _run_tests(self) -> str:
        """테스트를 실행하고 실패하면 출력 내용을, 통과하면 빈 문자열을 돌려준다."""
        cfg = self.cfg
        banner("자동 테스트 실행")
        result = run_command(
            cfg.test_command, cfg.project_dir, timeout=cfg.timeouts.test, echo=True
        )
        if result.timed_out:
            return f"테스트가 {cfg.timeouts.test}초 안에 끝나지 않았습니다 (타임아웃).\n" + _format_run(result)
        # pytest 종료 코드 5 = 수집된 테스트 없음
        if result.returncode == 0 or (
            result.returncode == 5 and "pytest" in " ".join(cfg.test_command)
        ):
            return ""
        return _format_run(result)

    def _fix_until_tests_pass(self, failure: Failure, history: list[str]) -> str:
        """테스트가 통과할 때까지 엔진을 다시 부른다. 끝내 실패하면 그 출력을 돌려준다."""
        cfg = self.cfg
        if not cfg.test_command:
            return ""
        test_text = ""
        for i in range(cfg.max_test_fixes + 1):
            test_text = self._run_tests()
            if not test_text:
                print("✅ 테스트 통과")
                return ""
            if i == cfg.max_test_fixes:
                break
            print(f"\n❌ 테스트 실패 → 엔진에 테스트 오류 전달 ({i + 1}/{cfg.max_test_fixes})")
            self._call_engine(build_prompt(failure.text, test_text, history))
        print("\n❌ 테스트가 여전히 실패합니다.")
        return test_text

    def _save_patch(self, prefix: str) -> str | None:
        diff = self.snapshot.diff()
        if not diff:
            return None
        path = self.reporter.save(prefix, diff, ".patch")
        print(f"변경 내역: {path}")
        return str(path)

    # --------------------------------------------------------------- 앱 점검

    def _check_app(self) -> Failure | None:
        if self.cfg.mode == "service":
            return self._check_service()
        return self._check_oneshot()

    def _check_oneshot(self) -> Failure | None:
        cfg = self.cfg
        result = run_command(
            cfg.app_command, cfg.project_dir, timeout=cfg.timeouts.app, echo=True
        )
        if result.timed_out:
            return Failure(
                kind="timeout",
                signature="timeout",
                text=(
                    f"애플리케이션이 {cfg.timeouts.app}초 안에 종료되지 않았습니다 (타임아웃). "
                    "무한 루프나 대기 상태일 수 있습니다.\n\n" + _format_run(result)
                ),
            )
        if result.returncode != 0:
            signature = (
                error_signature(result.stderr)
                or _last_line(result.stderr)
                or f"exit code {result.returncode}"
            )
            return Failure(kind="exit", signature=signature, text=_format_run(result))
        return self._run_smoke()

    def _run_smoke(self) -> Failure | None:
        cfg = self.cfg
        if not cfg.smoke_command:
            return None
        banner("Smoke Test 실행")
        result = run_command(
            cfg.smoke_command, cfg.project_dir, timeout=cfg.timeouts.test, echo=True
        )
        if result.ok:
            return None
        signature = error_signature(result.stderr) or "smoke test 실패"
        return Failure(
            kind="smoke",
            signature=signature,
            text="Smoke Test가 실패했습니다.\n\n" + _format_run(result),
        )

    def _check_service(self) -> Failure | None:
        """앱을 띄워 두고 stderr와 로그 파일에서 Traceback을 감시한다."""
        cfg, svc = self.cfg, self.cfg.service
        # 재시작 전에 쌓인 오류는 무시하고 이번 실행분만 본다
        watcher = LogWatcher(cfg.project_dir / svc.log_file) if svc.log_file else None
        proc = ManagedProcess(cfg.app_command, cfg.project_dir, echo=True)
        started = time.monotonic()
        log_text = ""
        try:
            while True:
                time.sleep(svc.poll_interval)
                if watcher:
                    log_text += watcher.read_new()
                if extract_tracebacks(proc.stderr) or extract_tracebacks(log_text):
                    time.sleep(svc.poll_interval)  # 이어지는 출력까지 수집
                    if watcher:
                        log_text += watcher.read_new()
                    return self._service_failure("traceback", proc, log_text)
                returncode = proc.poll()
                if returncode is not None:
                    proc.finish()
                    if returncode == 0:
                        return None
                    return self._service_failure("exit", proc, log_text, returncode)
                if not svc.keep_running and time.monotonic() - started >= svc.healthy_after:
                    print(f"\n{svc.healthy_after}초 동안 오류 없음 → 정상으로 판정")
                    return self._run_smoke()
        finally:
            proc.stop()
            proc.finish()

    def _service_failure(
        self, kind: str, proc: ManagedProcess, log_text: str, returncode: int | None = None
    ) -> Failure:
        stderr = proc.stderr
        head = (
            "애플리케이션 실행 중 예외가 기록되었습니다 (프로세스는 계속 실행 중이었음)."
            if kind == "traceback"
            else f"애플리케이션이 종료 코드 {returncode}(으)로 종료되었습니다."
        )
        text = f"{head}\n\nSTDOUT:\n{proc.stdout}\n\nSTDERR:\n{stderr}\n"
        if log_text:
            text += f"\nLOG ({self.cfg.service.log_file}):\n{log_text}\n"
        signature = (
            error_signature(log_text)
            or error_signature(stderr)
            or _last_line(stderr)
            or f"exit code {returncode}"
        )
        return Failure(kind=kind, signature=signature, text=text)
