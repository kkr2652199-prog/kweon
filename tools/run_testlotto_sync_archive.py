#!/usr/bin/env python3
"""테스트로또 1~N회 정밀 당첨 이력 동행복권 동기화."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.testlotto.draw_archive import sync_draw_archive_range
from app.testlotto.models import init_testlotto_db


def main() -> None:
    p = argparse.ArgumentParser(description="testlotto draw archive sync (lt645)")
    p.add_argument("--start", type=int, default=1)
    p.add_argument("--end", type=int, default=20)
    p.add_argument("--no-stores", action="store_true", help="판매점 조회 생략")
    args = p.parse_args()
    init_testlotto_db()
    result = sync_draw_archive_range(
        args.start,
        args.end,
        fetch_stores=not args.no_stores,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
