#!/usr/bin/env python3
"""테스트로또 1~5등 당첨 정보 백필 (lt645)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.testlotto.models import init_testlotto_db
from app.testlotto.prize_tiers import sync_prize_tiers_range


def main() -> None:
    p = argparse.ArgumentParser(description="testlotto prize tiers sync")
    p.add_argument("--start", type=int, default=1220)
    p.add_argument("--end", type=int, default=1231)
    args = p.parse_args()
    init_testlotto_db()
    result = sync_prize_tiers_range(args.start, args.end)
    print(result)


if __name__ == "__main__":
    main()
