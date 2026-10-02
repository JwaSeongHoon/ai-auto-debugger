"""서버형 오류 예제: 종료되지 않고 예외를 error.log에만 기록한다."""

import logging
import time

from worker import process

logging.basicConfig(
    filename="error.log",
    level=logging.ERROR,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8",
)

JOBS = [
    {"id": 1, "total": 10, "count": 2},
    {"id": 2, "total": 9, "count": 3},
    {"id": 3, "total": 5, "count": 0},
]


def main():
    print("서버 시작", flush=True)
    while True:
        for job in JOBS:
            try:
                print(f"job {job['id']} 평균 = {process(job)}", flush=True)
            except Exception:
                logging.exception("job %s 처리 실패", job["id"])
            time.sleep(0.2)


if __name__ == "__main__":
    main()
