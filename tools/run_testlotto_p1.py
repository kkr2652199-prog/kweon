#!/usr/bin/env python3
"""테스트로또 P1 — 예측이력·가중치 초기화, 당첨정답 보존, 분석 그릇 생성."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.testlotto.draw_analysis import upsert_draw_features
from app.testlotto.models import get_lotto_db, init_testlotto_db


def run_p1(*, seed_features: bool = True, max_draw: int = 1231) -> dict:
    init_testlotto_db()
    conn = get_lotto_db()
    try:
        draw_row = conn.execute(
            "SELECT MIN(draw_no), MAX(draw_no), COUNT(*) FROM lotto_draws"
        ).fetchone()
        min_d, max_d, cnt = int(draw_row[0] or 0), int(draw_row[1] or 0), int(draw_row[2] or 0)

        pred_before = conn.execute("SELECT COUNT(*) FROM lotto_predictions").fetchone()[0]
        conn.execute("DELETE FROM lotto_predictions")
        conn.execute("DELETE FROM testlotto_brain_review")
        conn.execute("DELETE FROM testlotto_brain_learn_state")

        conn.execute(
            """
            UPDATE testlotto_brain_weights SET
                current_weight = CASE brain_tag
                    WHEN 'stat' THEN 1.5
                    WHEN 'markov' THEN 1.0
                    WHEN 'review' THEN 1.2
                    ELSE current_weight
                END,
                recent_avg_match = 0,
                total_predictions = 0,
                total_matches = 0,
                last_updated_draw = 0,
                updated_at = datetime('now','localtime')
            WHERE brain_tag IN ('stat','markov','review')
            """
        )
        conn.execute("DELETE FROM testlotto_brain_weights WHERE brain_tag NOT IN ('stat','markov','review')")
        for tag, w in [("stat", 1.5), ("markov", 1.0), ("review", 1.2)]:
            conn.execute(
                "INSERT OR IGNORE INTO testlotto_brain_weights (brain_tag, current_weight) VALUES (?,?)",
                (tag, w),
            )
        conn.commit()
    finally:
        conn.close()

    feature_count = 0
    if seed_features and max_d > 0:
        end = min(max_draw, max_d)
        for draw_no in range(1, end + 1):
            if upsert_draw_features(draw_no):
                feature_count += 1

    return {
        "preserved_draws": {"min": min_d, "max": max_d, "count": cnt},
        "cleared_predictions": int(pred_before),
        "seeded_features": feature_count,
        "brain_weights": ["stat", "markov", "review"],
        "tables_ready": [
            "testlotto_draw_features",
            "testlotto_brain_review",
            "testlotto_brain_learn_state",
        ],
    }


if __name__ == "__main__":
    result = run_p1()
    print("P1 완료:", result)
