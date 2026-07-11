"""STEP3 검증: strategy_x 로깅 + cooccur 슬라이스 + API 무간섭."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.lotto4.cooccur_walkforward import aggregate_cooccur_before
from app.lotto4.models import LOTTO_DB_PATH
from app.lotto4.strategy_x_logging import (
    STRATEGY_X_BRAIN_TAGS,
    generate_and_save_recommend,
)
from app.lotto4.brains.coordinator_brain import generate_recommend_sets
from app.lotto4.brains.popularity_freq_brain import generate_popularity_sets
from app.lotto4.brains.popularity_pair_brain import generate_pair_sets
from app.lotto4.brains.shape_brain import generate_shape_sets

TEST_DRAW = 19999


def main() -> None:
    out: dict = {"test_draw": TEST_DRAW}

    # (1) recommend + logging
    result = generate_and_save_recommend(TEST_DRAW)
    out["recommend_sets"] = len(result.get("sets") or [])
    out["logging"] = result.get("prediction_logging")

    conn = sqlite3.connect(str(LOTTO_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT brain_tag, method, num1, num2, num3, num4, num5, num6,
                   reasoning, created_at
            FROM lotto_predictions_army4
            WHERE target_draw_no = ?
            ORDER BY brain_tag, method
            """,
            (TEST_DRAW,),
        ).fetchall()
        out["db_rows"] = len(rows)
        out["db_by_tag"] = {}
        for r in rows:
            tag = r["brain_tag"]
            out["db_by_tag"].setdefault(tag, 0)
            out["db_by_tag"][tag] += 1
        out["db_sample"] = [
            {
                "brain_tag": r["brain_tag"],
                "nums": [r[f"num{i}"] for i in range(1, 7)],
                "method": r["method"],
                "created_at": r["created_at"],
                "reasoning_len": len(r["reasoning"] or ""),
            }
            for r in rows[:3]
        ]

        # predict DELETE collision check (simulate v13_engine_v2 wipe)
        before = conn.execute(
            "SELECT COUNT(*) FROM lotto_predictions_army4 WHERE target_draw_no=?",
            (TEST_DRAW,),
        ).fetchone()[0]
        conn.execute(
            "DELETE FROM lotto_predictions_army4 WHERE target_draw_no=? AND brain_tag LIKE 'v13_%'",
            (TEST_DRAW,),
        )
        after = conn.execute(
            "SELECT COUNT(*) FROM lotto_predictions_army4 WHERE target_draw_no=?",
            (TEST_DRAW,),
        ).fetchone()[0]
        conn.rollback()
        out["predict_collision"] = {
            "before_v13_delete": before,
            "after_v13_delete_sim": after,
            "strategy_x_survives": before == after,
        }
    finally:
        conn.close()

    # (2) cooccur slice
    slice_500 = aggregate_cooccur_before(500, top_n=3)
    slice_1229 = aggregate_cooccur_before(1229, top_n=3)
    out["cooccur_slice"] = {
        "N500": {
            "draw_count": slice_500["draw_count"],
            "max_draw_no": slice_500["max_draw_no"],
            "top2": slice_500["cooccur_2"][:2],
        },
        "N1229": {
            "draw_count": slice_1229["draw_count"],
            "max_draw_no": slice_1229["max_draw_no"],
            "top2": slice_1229["cooccur_2"][:2],
        },
        "r13_ok": slice_500["max_draw_no"] < 500 and slice_1229["max_draw_no"] < 1229,
    }

    # (3) 4뇌 API 함수 OK
    apis = {}
    for name, fn in [
        ("popularity", lambda: generate_popularity_sets(TEST_DRAW)),
        ("pair", lambda: generate_pair_sets(TEST_DRAW)),
        ("shape", lambda: generate_shape_sets(TEST_DRAW)),
        ("recommend", lambda: generate_recommend_sets(TEST_DRAW)),
    ]:
        try:
            r = fn()
            apis[name] = {"ok": True, "sets": len(r.get("sets") or [])}
        except Exception as e:
            apis[name] = {"ok": False, "error": str(e)}
    out["api_checks"] = apis

    print(json.dumps(out, ensure_ascii=False, indent=2))

    # cleanup test rows
    conn = sqlite3.connect(str(LOTTO_DB_PATH))
    try:
        ph = ",".join("?" for _ in STRATEGY_X_BRAIN_TAGS)
        conn.execute(
            f"DELETE FROM lotto_predictions_army4 WHERE target_draw_no=? AND brain_tag IN ({ph})",
            (TEST_DRAW, *STRATEGY_X_BRAIN_TAGS),
        )
        conn.commit()
        print("cleanup_ok", TEST_DRAW)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
