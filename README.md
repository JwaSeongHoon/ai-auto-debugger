# AI Auto Debugger

Python 앱을 실행하다 오류가 나면 **오류 수집 → AI 엔진(Codex / Claude Code CLI) 수정 → pytest → 재실행**을 자동으로 반복하는 Supervisor입니다. `docs/chatlog.md`의 구조를 구현했습니다.

## 설치

```bash
pip install -r requirements.txt
```

AI 엔진은 둘 중 하나가 설치되어 있어야 합니다 (테스트와 mock 데모에는 필요 없음).

```bash
npm install -g @openai/codex@latest        # engine.type: codex
npm install -g @anthropic-ai/claude-code   # engine.type: claude
```

## 사용법

1. `config.yaml`을 복사해 `project_dir`, `app_command`, `test_command`를 내 프로젝트에 맞게 고칩니다.
2. `python app.py` 대신 아래처럼 실행합니다.

```bash
python auto_repair.py --config config.yaml
python auto_repair.py --config config.yaml --engine claude --max-repairs 5
python auto_repair.py --config config.yaml --dry-run   # 감지와 프롬프트 확인만
```

종료 코드: `0` 정상(또는 복구 성공), `1` 복구 실패, `2` 설정/환경 오류.

### 모드

| 모드 | 감지 방식 |
|---|---|
| `oneshot` | 앱이 끝날 때까지 기다린 뒤 종료 코드로 판정. `timeouts.app`을 넘기면 멈춘 것으로 간주 |
| `service` | 앱을 띄워 두고 stderr와 `service.log_file`의 Traceback을 감시. `healthy_after`초 동안 오류가 없으면 정상 판정 후 앱을 종료. `keep_running: true`면 계속 감시 |

### 동작 순서

1. 앱 실행 → 오류 감지 → `logs/error_YYYYMMDD_HHMMSS.log` 저장
2. 첫 수정 전에 `.auto_repair/backups/`에 소스 백업
3. 엔진 호출 (프롬프트는 stdin으로 전달)
4. 테스트 실행. 실패하면 테스트 출력을 붙여 엔진 재호출 (`max_test_fixes`회까지)
5. 앱 재실행. 여전히 실패하면 이전 시도 이력을 붙여 반복 (`max_repairs`회까지)
6. 성공하면 변경 내역을 `logs/repair_*.patch`로 저장. 끝내 실패하면 `logs/failed_*.patch`를 남기고 백업으로 롤백 (새로 생긴 파일은 `.auto_repair/rolled_back/`으로 이동)

### 엔진 명령

| type | 실행 명령 |
|---|---|
| `codex` | `codex exec --sandbox workspace-write --skip-git-repo-check -` |
| `claude` | `claude -p --permission-mode acceptEdits` |
| `custom` | `engine.command`에 지정한 명령 |

`engine.command`를 지정하면 type과 상관없이 그 명령을 씁니다. 명령은 프로젝트 폴더에서 실행되고 프롬프트를 stdin으로 받습니다.

> chatlog의 `codex exec --full-auto`는 최신 Codex CLI(0.154 확인)에서 없어진 옵션이라 `--sandbox workspace-write`로 대체했습니다.

## 테스트

```bash
python -m pytest -q
```

실제 AI 엔진 없이 `tests/fake_engine.py`(대본대로 파일을 고치는 가짜 엔진)로 전체 흐름을 검증합니다.

| 파일 | 내용 |
|---|---|
| `tests/test_e2e_oneshot.py` | 정상 앱, 1회 수정, 테스트를 깨는 수정 → 재수정, 효과 없는 수정 → 재시도, 수정 불가 → 롤백, 타임아웃, 엔진 없음, smoke 실패, dry-run, CLI |
| `tests/test_e2e_service.py` | `error.log` Traceback 감지 → 수정 → 재시작, 이전 로그 무시, 롤백, 시작 직후 크래시 |
| `tests/test_units.py` | Traceback 추출, 설정 검증, 프로세스 실행/타임아웃, 로그 감시, 백업/롤백, 프롬프트 |

## 데모

예제를 임시 폴더에 복사해서 실행하므로 `examples/` 원본은 바뀌지 않습니다.

```bash
python run_demo.py --scenario crash  --engine mock                         # 종료형 오류
python run_demo.py --scenario server --engine mock                         # error.log 감시
python run_demo.py --scenario crash  --engine mock --mock-script break,fix # 테스트 실패 후 재수정
python run_demo.py --scenario crash  --engine mock --mock-script vandal    # 수정 실패 → 롤백
python run_demo.py --scenario crash  --engine codex                        # 실제 Codex
python run_demo.py --scenario crash  --engine claude                       # 실제 Claude Code
```

## 주의

- AI 엔진이 프로젝트 소스를 직접 수정합니다. 개발 환경에서만 쓰고, 운영 DB·비밀키·배포 권한이 있는 환경에서는 쓰지 마세요.
- `examples/*/config.yaml`로 예제 폴더에서 직접 실행하면 예제 소스가 수정되어 테스트가 깨집니다. `run_demo.py`를 쓰세요.
- 롤백은 백업 시점(첫 오류 감지 직후)으로 되돌립니다. `.git`, 가상환경, `node_modules`, `logs`, `*.log`는 백업/롤백 대상이 아닙니다.
