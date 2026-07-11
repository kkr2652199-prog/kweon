#!/usr/bin/env python3
"""테스트로또 walk-forward 복습 루프 (2~N회)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.testlotto.walkforward import run_review_loop
from app.testlotto.models import init_testlotto_db


def main() -> None:
    p = argparse.ArgumentParser(description="testlotto walk-forward review loop")
    p.add_argument("--start", type=int, default=2)
    p.add_argument("--end", type=int, default=1231)
    p.add_argument("--progress-every", type=int, default=50)
    args = p.parse_args()
    init_testlotto_db()
    result = run_review_loop(
        args.start,
        args.end,
        progress_every=args.progress_every,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
