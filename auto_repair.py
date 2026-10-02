"""AI Auto Debugger 진입점.

    python auto_repair.py --config config.yaml

앱을 실행하고, 오류가 나면 AI 엔진(Codex/Claude Code CLI)에 수정을 맡긴 뒤
테스트와 재실행으로 검증한다.
"""

from __future__ import annotations

import argparse
import sys

from auto_debugger.config import ENGINE_TYPES, ConfigError, load_config
from auto_debugger.report import setup_console
from auto_debugger.supervisor import EXIT_CONFIG, EXIT_FAILED, Supervisor


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Python 앱 자동 복구 Supervisor")
    parser.add_argument("--config", default="config.yaml", help="설정 파일 (기본: config.yaml)")
    parser.add_argument("--project-dir", help="대상 프로젝트 폴더 (설정 파일 값 대신 사용)")
    parser.add_argument(
        "--engine",
        choices=[t for t in ENGINE_TYPES if t != "custom"],
        help="AI 엔진 (설정 파일 값 대신 사용)",
    )
    parser.add_argument("--max-repairs", type=int, help="최대 복구 횟수")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="오류 감지와 프롬프트 생성까지만 하고 엔진은 호출하지 않음",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    setup_console()
    args = parse_args(argv)
    try:
        config = load_config(
            args.config,
            overrides={
                "project_dir": args.project_dir,
                "engine": args.engine,
                "max_repairs": args.max_repairs,
                "dry_run": args.dry_run or None,
            },
        )
    except ConfigError as exc:
        print(f"설정 오류: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    try:
        return Supervisor(config).run().exit_code
    except KeyboardInterrupt:
        print("\n사용자가 중단했습니다.", file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
