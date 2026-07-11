#!/usr/bin/env python3
"""testlotto archive gap 검증 (READ-ONLY)."""
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "lotto_testlotto.db"
START, END = 1, 1231


def main() -> None:
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row

    detail_cnt = c.execute("SELECT COUNT(*) FROM testlotto_draw_detail").fetchone()[0]
    tier_cnt = c.execute(
        "SELECT COUNT(DISTINCT draw_no) FROM testlotto_draw_prize_tiers"
    ).fetchone()[0]
    tier5_cnt = c.execute(
        "SELECT COUNT(DISTINCT draw_no) FROM testlotto_draw_prize_tiers WHERE tier_rank=5"
    ).fetchone()[0]
    store_cnt = c.execute(
        "SELECT COUNT(DISTINCT draw_no) FROM testlotto_draw_win_stores"
    ).fetchone()[0]
    store_ok_cnt = c.execute(
        "SELECT COUNT(*) FROM testlotto_draw_detail WHERE store_fetch_status='ok'"
    ).fetchone()[0]
    store_pending_cnt = c.execute(
        "SELECT COUNT(*) FROM testlotto_draw_detail WHERE store_fetch_status='pending'"
    ).fetchone()[0]
    store_skipped_cnt = c.execute(
        "SELECT COUNT(*) FROM testlotto_draw_detail WHERE store_fetch_status='skipped'"
    ).fetchone()[0]

    have_detail = {
        r[0]
        for r in c.execute(
            "SELECT draw_no FROM testlotto_draw_detail WHERE draw_no BETWEEN ? AND ?",
            (START, END),
        )
    }
    have_tiers = {
        r[0]
        for r in c.execute(
            "SELECT DISTINCT draw_no FROM testlotto_draw_prize_tiers WHERE draw_no BETWEEN ? AND ?",
            (START, END),
        )
    }
    have_stores = {
        r[0]
        for r in c.execute(
            "SELECT DISTINCT draw_no FROM testlotto_draw_win_stores WHERE draw_no BETWEEN ? AND ?",
            (START, END),
        )
    }
    pending_draws = [
        r[0]
        for r in c.execute(
            "SELECT draw_no FROM testlotto_draw_detail WHERE store_fetch_status='pending' ORDER BY draw_no"
        )
    ]

    all_range = set(range(START, END + 1))
    detail_gaps = sorted(all_range - have_detail)
    tier_gaps = sorted(all_range - have_tiers)

    print("=== archive 검증 (1~1231) ===")
    print(f"draw_detail rows: {detail_cnt}")
    print(f"등수(prize_tiers) 채움 회차: {tier_cnt} (5등 포함: {tier5_cnt})")
    print(f"판매점(win_stores) 채움 회차: {store_cnt}")
    print(f"store_status ok: {store_ok_cnt}, pending: {store_pending_cnt}, skipped: {store_skipped_cnt}")
    print(f"detail gap ({len(detail_gaps)}): {detail_gaps[:50]}{'...' if len(detail_gaps)>50 else ''}")
    print(f"tier gap ({len(tier_gaps)}): {tier_gaps[:50]}{'...' if len(tier_gaps)>50 else ''}")
    print(f"pending 판매점 회차 ({len(pending_draws)}): {pending_draws[:30]}{'...' if len(pending_draws)>30 else ''}")


if __name__ == "__main__":
    main()
