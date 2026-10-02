"""예제 앱을 임시 폴더에 복사해 자동 복구 과정을 직접 확인한다.

    python run_demo.py --scenario crash  --engine mock
    python run_demo.py --scenario server --engine mock
    python run_demo.py --scenario crash  --engine codex    # 실제 Codex CLI
    python run_demo.py --scenario crash  --engine claude   # 실제 Claude Code CLI

원본 examples/ 폴더는 수정하지 않는다.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from auto_debugger.config import Config, EngineConfig, ServiceConfig
from auto_debugger.report import banner, setup_console
from auto_debugger.supervisor import Supervisor

ROOT = Path(__file__).resolve().parent
SCENARIOS = {"crash": ("crash_app", "oneshot"), "server": ("server_app", "service")}


def main() -> int:
    setup_console()
    parser = argparse.ArgumentParser(description="AI Auto Debugger 데모")
    parser.add_argument("--scenario", choices=SCENARIOS, default="crash")
    parser.add_argument("--engine", choices=["mock", "codex", "claude"], default="mock")
    parser.add_argument(
        "--mock-script",
        default="fix",
        help="mock 엔진 동작 순서 (예: noop,fix / break,fix / vandal)",
    )
    parser.add_argument("--max-repairs", type=int, default=3)
    parser.add_argument(
        "--workdir",
        help="예제를 복사할 상위 폴더 (기본: 시스템 임시 폴더)",
    )
    args = parser.parse_args()

    app_name, mode = SCENARIOS[args.scenario]
    # tempfile.mkdtemp는 Windows에서 소유자 전용 ACL로 폴더를 만들어
    # Codex 샌드박스(제한된 토큰)가 접근하지 못한다. 일반 mkdir로 만든다.
    base = Path(args.workdir) if args.workdir else Path(tempfile.gettempdir())
    workdir = base / f"auto_repair_demo_{datetime.now():%Y%m%d_%H%M%S}_{os.getpid()}"
    workdir.mkdir(parents=True)
    project = Path(shutil.copytree(ROOT / "examples" / app_name, workdir / app_name))

    if args.engine == "mock":
        os.environ["FAKE_ENGINE_SCRIPT"] = args.mock_script
        os.environ["FAKE_ENGINE_STATE"] = str(workdir / "engine_state")
        engine = EngineConfig(
            type="custom", command=[sys.executable, str(ROOT / "tests" / "fake_engine.py")]
        )
    else:
        engine = EngineConfig(type=args.engine)

    config = Config(
        project_dir=project,
        app_command=["python", "app.py"],
        test_command=["python", "-m", "pytest", "-q"],
        mode=mode,
        max_repairs=args.max_repairs,
        service=ServiceConfig(healthy_after=5, poll_interval=0.5),
        engine=engine,
    )

    banner(f"데모 시작: {args.scenario} / 엔진 {args.engine}\n작업 폴더: {project}")
    result = Supervisor(config).run()
    print(f"\n작업 폴더(결과 확인용): {project}")
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
