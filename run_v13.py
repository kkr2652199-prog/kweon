"""4군 서버 진입점: sys.path 에 d:\\3kweon 루트만 추가 (외부 lotto 트리 미포함)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--mini-backtest":
        from app.lotto4.v13_engine_v2 import run_v13_mini_backtest

        print(json.dumps(run_v13_mini_backtest(), ensure_ascii=False, indent=2))
        sys.exit(0)

    import uvicorn

    host = "127.0.0.1"
    port = 6124
    print(
        "[4군] 서버 기동 중… (이 창을 닫지 마세요. 중지: Ctrl+C)\n"
        f"  브라우저: http://{host}:{port}/\n"
        f"  API 예시: http://{host}:{port}/api/lotto4/v13/brain/status\n",
        flush=True,
    )
    try:
        uvicorn.run(
            "app.main_v13:app",
            host=host,
            port=port,
            reload=False,
            log_level="info",
        )
    except OSError as e:
        winerr = getattr(e, "winerror", None)
        if winerr == 10048 or e.errno == 98:
            print(
                "[4군] 오류: 포트 6124 가 이미 사용 중입니다.\n"
                "  - 다른 터미널의 run_v13.py 를 종료하거나, 작업 관리자에서 python/uvicorn 을 확인하세요.\n"
                "  PowerShell: Get-NetTCPConnection -LocalPort 6124 | Format-Table OwningProcess\n",
                flush=True,
            )
        raise
