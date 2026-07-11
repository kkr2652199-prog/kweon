"""동행 lt645 API — 회차 구간 일괄 수집·갱신 (기본 1228→1 역순).

사용:
  python tools/collect_lotto_draws_bulk.py
  python tools/collect_lotto_draws_bulk.py --from 1228 --to 1 --delay 0.2
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.lotto.data_service import collect_draw_range
from app.lotto.models import init_lotto_db

DB = _ROOT / "data" / "lotto4.db"
OUT = _ROOT / "tools" / "_collect_lotto_draws_bulk.json"


def _summary() -> dict:
    conn = sqlite3.connect(DB)
    try:
        draws = conn.execute(
            "SELECT COUNT(*), MIN(draw_no), MAX(draw_no) FROM lotto_draws"
        ).fetchone()
        tiers = conn.execute(
            "SELECT COUNT(DISTINCT draw_no), COUNT(*) FROM lotto_draw_tiers"
        ).fetchone()
        prize_ok = conn.execute(
            "SELECT COUNT(*) FROM lotto_draws WHERE first_winners > 0 OR first_prize > 0"
        ).fetchone()[0]
        sample = conn.execute(
            """
            SELECT d.draw_no, d.first_winners, d.first_prize,
                   t2.winner_count, t3.winner_count
            FROM lotto_draws d
            LEFT JOIN lotto_draw_tiers t2 ON d.draw_no=t2.draw_no AND t2.tier_rank=2
            LEFT JOIN lotto_draw_tiers t3 ON d.draw_no=t3.draw_no AND t3.tier_rank=3
            WHERE d.draw_no IN (1228, 1)
            ORDER BY d.draw_no DESC
            """
        ).fetchall()
    finally:
        conn.close()
    return {
        "lotto_draws": {"count": draws[0], "min": draws[1], "max": draws[2]},
        "lotto_draw_tiers": {"draws": tiers[0], "rows": tiers[1]},
        "draws_with_1st_prize_data": prize_ok,
        "sample": [
            {
                "draw_no": r[0],
                "first_winners": r[1],
                "first_prize": r[2],
                "tier2_winners": r[3],
                "tier3_winners": r[4],
            }
            for r in sample
        ],
    }


def main() -> None:
    p = argparse.ArgumentParser(description="동행 lt645 일괄 수집")
    p.add_argument("--from", dest="from_draw", type=int, default=1228)
    p.add_argument("--to", dest="to_draw", type=int, default=1)
    p.add_argument("--delay", type=float, default=0.2)
    p.add_argument("--ascending", action="store_true", help="오름차순(기본: 역순)")
    args = p.parse_args()

    init_lotto_db()
    result = collect_draw_range(
        args.from_draw,
        args.to_draw,
        delay=args.delay,
        descending=not args.ascending,
    )
    result["after"] = _summary()
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
