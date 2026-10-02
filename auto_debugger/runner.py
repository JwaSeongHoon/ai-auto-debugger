"""프로세스 실행: 출력 캡처, 타임아웃, 프로세스 트리 종료."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path


class CommandNotFound(Exception):
    """실행 파일을 찾을 수 없을 때 발생한다."""


@dataclass
class RunResult:
    returncode: int | None  # 타임아웃이면 None
    stdout: str
    stderr: str
    timed_out: bool
    duration: float

    @property
    def ok(self) -> bool:
        return not self.timed_out and self.returncode == 0


def child_env() -> dict[str, str]:
    """자식 Python 프로세스가 UTF-8로, 버퍼링 없이 출력하도록 한다."""
    env = dict(os.environ)
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    return env


def resolve_command(command: list[str]) -> list[str]:
    """실행 파일 경로를 해석한다. Windows의 npm 셈(codex.cmd 등)도 찾는다."""
    found = shutil.which(command[0])
    if found is None:
        raise CommandNotFound(command[0])
    return [found, *command[1:]]


def kill_tree(proc: subprocess.Popen) -> None:
    """프로세스와 그 자식들을 강제 종료한다."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
        )
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()


class ManagedProcess:
    """출력을 계속 읽어 모으면서(필요하면 화면에도 출력) 실행되는 프로세스."""

    def __init__(
        self,
        command: list[str],
        cwd: Path,
        input_text: str | None = None,
        echo: bool = False,
    ) -> None:
        self._echo = echo
        self._stdout: list[str] = []
        self._stderr: list[str] = []
        kwargs: dict = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        self.proc = subprocess.Popen(
            resolve_command(command),
            cwd=str(cwd),
            stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=child_env(),
            **kwargs,
        )
        self._threads = [
            threading.Thread(
                target=self._pump, args=(self.proc.stdout, self._stdout, False), daemon=True
            ),
            threading.Thread(
                target=self._pump, args=(self.proc.stderr, self._stderr, True), daemon=True
            ),
        ]
        if input_text is not None:
            self._threads.append(
                threading.Thread(target=self._feed, args=(input_text,), daemon=True)
            )
        for thread in self._threads:
            thread.start()

    def _pump(self, stream, sink: list[str], is_err: bool) -> None:
        for line in stream:
            sink.append(line)
            if self._echo:
                out = sys.stderr if is_err else sys.stdout
                try:
                    out.write(line)
                    out.flush()
                except (OSError, ValueError):
                    pass
        stream.close()

    def _feed(self, text: str) -> None:
        try:
            self.proc.stdin.write(text)
            self.proc.stdin.close()
        except (OSError, ValueError):
            pass  # 프로세스가 입력을 다 읽기 전에 종료됨

    @property
    def stdout(self) -> str:
        return "".join(self._stdout)

    @property
    def stderr(self) -> str:
        return "".join(self._stderr)

    def poll(self) -> int | None:
        return self.proc.poll()

    def wait(self, timeout: float | None = None) -> int | None:
        """종료 코드를 돌려준다. 타임아웃이면 None."""
        try:
            return self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def stop(self) -> None:
        kill_tree(self.proc)
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def finish(self) -> None:
        """출력 스레드가 남은 내용을 다 읽을 때까지 기다린다."""
        for thread in self._threads:
            thread.join(timeout=5)


def run_command(
    command: list[str],
    cwd: Path,
    timeout: float | None = None,
    input_text: str | None = None,
    echo: bool = False,
) -> RunResult:
    """명령을 끝까지 실행한다. 타임아웃이면 프로세스 트리를 종료한다."""
    started = time.monotonic()
    proc = ManagedProcess(command, cwd, input_text=input_text, echo=echo)
    returncode = proc.wait(timeout)
    timed_out = returncode is None
    if timed_out:
        proc.stop()
    proc.finish()
    return RunResult(
        returncode=None if timed_out else returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        timed_out=timed_out,
        duration=time.monotonic() - started,
    )
