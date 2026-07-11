"""전체 데이터 수집·동반출현·전략X 프로파일 재구축 파이프라인."""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.lotto.data_service import collect_draw_range, fetch_single_draw, save_draw_full
from app.lotto.models import init_lotto_db

DB = _ROOT / "data" / "lotto4.db"
OUT = _ROOT / "tools" / "_full_data_pipeline.json"


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


def _collect_missing(delay: float = 0.7) -> dict:
    targets = _missing_draw_nos()
    if not targets:
        return {"saved": 0, "failed": 0, "targets": 0}
    saved = failed = 0
    errors: list[str] = []
    for i, draw_no in enumerate(targets):
        draw = fetch_single_draw(draw_no, lt645_only=True)
        if draw and save_draw_full(draw):
            saved += 1
        else:
            failed += 1
            errors.append(str(draw_no))
        if (i + 1) % 25 == 0:
            print(f"  missing collect {i+1}/{len(targets)} saved={saved}")
        time.sleep(delay)
    return {"targets": len(targets), "saved": saved, "failed": failed, "errors": errors[:30]}


def _rebuild_strategy_x_profiles() -> dict:
    from tools.rebuild_lotto4_winners_full import rebuild as rebuild_winners
    from app.lotto4.brains.popularity_pair_brain import build_pair_popularity_table
    from app.lotto4.brains.shape_brain import build_shape_profile_table

    winners = rebuild_winners()
    pair = build_pair_popularity_table()
    shape = build_shape_profile_table()

    conn = sqlite3.connect(DB)
    try:
        conn.executescript(
            """
            DROP TABLE IF EXISTS number_popularity;
            CREATE TABLE number_popularity (
                number INTEGER PRIMARY KEY,
                top30_freq INTEGER NOT NULL,
                top30_pct REAL NOT NULL,
                era TEXT NOT NULL DEFAULT 'C',
                updated_at TEXT DEFAULT (datetime('now','localtime'))
            );
            """
        )
        rows = conn.execute(
            """
            SELECT n1,n2,n3,n4,n5,n6, winner_cnt
            FROM lotto4_winners_full
            WHERE era='C' AND winner_cnt > 0
            ORDER BY winner_cnt DESC
            """
        ).fetchall()
        k = max(1, int(len(rows) * 0.30))
        top = rows[:k]
        freq = {n: 0 for n in range(1, 46)}
        for r in top:
            for i in range(6):
                freq[int(r[i])] += 1
        conn.executemany(
            "INSERT INTO number_popularity (number, top30_freq, top30_pct, era) VALUES (?,?,?,'C')",
            [(n, freq[n], round(freq[n] / k, 4)) for n in range(1, 46)],
        )
        conn.commit()
        num_top = sorted(
            [{"number": n, "freq": freq[n]} for n in range(1, 46)],
            key=lambda x: x["freq"],
            reverse=True,
        )[:10]
    finally:
        conn.close()

    return {
        "winners_full": winners,
        "number_popularity_top10": num_top,
        "pair_popularity": {
            "top_draws_n": pair.get("top_draws_n"),
            "pairs_n": pair.get("pairs_n"),
            "cv": pair.get("cv"),
        },
        "shape_profile": {
            "top_draws_n": shape.get("top_draws_n"),
            "sum_delta": shape.get("sum_delta"),
        },
    }


def main() -> None:
    init_lotto_db()
    report: dict = {"steps": {}}

    print("STEP1 missing tier collect...")
    report["steps"]["missing_collect"] = _collect_missing(delay=0.7)

    print("STEP2 cooccur rebuild...")
    import subprocess
    subprocess.check_call([sys.executable, str(_ROOT / "tools" / "collect_cooccur.py")])
    report["steps"]["cooccur"] = {"ok": True}

    print("STEP3 cooccur latest export...")
    subprocess.check_call([sys.executable, str(_ROOT / "tools" / "export_cooccur_latest.py")])
    report["steps"]["cooccur_export"] = {"ok": True, "out": str(_ROOT / "tools" / "_cooccur_latest.json")}

    print("STEP4 strategy X profile rebuild...")
    report["steps"]["strategy_x_profiles"] = _rebuild_strategy_x_profiles()

    conn = sqlite3.connect(DB)
    try:
        missing = conn.execute(
            """
            SELECT COUNT(*) FROM lotto_draws d
            WHERE NOT EXISTS (
                SELECT 1 FROM lotto_draw_tiers t
                WHERE t.draw_no=d.draw_no AND t.tier_rank=2
            )
            """
        ).fetchone()[0]
        tiers = conn.execute("SELECT COUNT(DISTINCT draw_no) FROM lotto_draw_tiers").fetchone()[0]
        report["final"] = {
            "missing_tier2": missing,
            "tier_draws": tiers,
            "draws": conn.execute("SELECT COUNT(*) FROM lotto_draws").fetchone()[0],
        }
    finally:
        conn.close()

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
