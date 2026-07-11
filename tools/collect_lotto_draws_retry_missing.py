"""등수(tier) 정보가 비어 있는 회차만 재수집.

동행 API 과부하 시 실패한 구간 보완용.
  python tools/collect_lotto_draws_retry_missing.py
  python tools/collect_lotto_draws_retry_missing.py --delay 1.0
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.lotto.data_service import fetch_single_draw, save_draw_full
from app.lotto.models import init_lotto_db

DB = _ROOT / "data" / "lotto4.db"
OUT = _ROOT / "tools" / "_collect_lotto_draws_retry_missing.json"


def _missing_draw_nos() -> list[int]:
    conn = sqlite3.connect(DB)
    try:
        rows = conn.execute(
            """
            SELECT d.draw_no
            FROM lotto_draws d
            WHERE NOT EXISTS (
                SELECT 1 FROM lotto_draw_tiers t
                WHERE t.draw_no = d.draw_no AND t.tier_rank = 2
            )
            ORDER BY d.draw_no DESC
            """
        ).fetchall()
        return [int(r[0]) for r in rows]
    finally:
        conn.close()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--delay", type=float, default=0.8)
    p.add_argument("--limit", type=int, default=0, help="0=전체")
    args = p.parse_args()

    init_lotto_db()
    targets = _missing_draw_nos()
    if args.limit > 0:
        targets = targets[: args.limit]

    saved = 0
    failed = 0
    errors: list[str] = []

    print(f"missing tier draws: {len(targets)}")
    for draw_no in targets:
        draw = fetch_single_draw(draw_no, lt645_only=True)
        if draw and save_draw_full(draw):
            saved += 1
            if saved % 20 == 0:
                print(f"  saved {saved} (last={draw_no})")
        else:
            failed += 1
            errors.append(str(draw_no))
        time.sleep(args.delay)

    result = {
        "targets": len(targets),
        "saved": saved,
        "failed": failed,
        "errors_sample": errors[:30],
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
