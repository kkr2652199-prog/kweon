"""V9 2군 엔진: 1군 미수정, 2군 6뇌 호출 + DB INSERT."""
from __future__ import annotations

import logging
import math
import sqlite3
from collections import Counter

from app.lotto2.models import get_lotto2_db, get_miss_draws_for_army2

logger = logging.getLogger(__name__)

SETS_PER_BRAIN_ARMY2 = 5


def _score_army2_predictions(target_draw_no: int) -> None:
    """채점: lotto_draws에서 실제 당첨 읽어 matched_count/bonus_matched 갱신."""
    conn = get_lotto2_db()
    try:
        actual = conn.execute(
            """
            SELECT num1, num2, num3, num4, num5, num6, bonus
            FROM lotto_draws WHERE draw_no = ?
            """,
            (target_draw_no,),
        ).fetchone()
        if not actual:
            return

        actual_set = {actual["num1"], actual["num2"], actual["num3"], actual["num4"], actual["num5"], actual["num6"]}
        bonus = actual["bonus"]

        rows = conn.execute(
            """
            SELECT id, num1, num2, num3, num4, num5, num6
            FROM lotto_predictions_army2 WHERE target_draw_no = ?
            """,
            (target_draw_no,),
        ).fetchall()
        for r in rows:
            pred_set = {r["num1"], r["num2"], r["num3"], r["num4"], r["num5"], r["num6"]}
            matched = len(pred_set & actual_set)
            bonus_m = 1 if bonus in pred_set else 0
            conn.execute(
                """
                UPDATE lotto_predictions_army2
                SET matched_count = ?, bonus_matched = ? WHERE id = ?
                """,
                (matched, bonus_m, r["id"]),
            )
        conn.commit()
    finally:
        conn.close()


def run_prediction_army2(target_draw_no: int) -> dict:
    """2군 6뇌 예측 실행."""
    from app.lotto2.fusion import army2_fusion_predict
    from app.lotto2.predict_combo import army2_combo_predict
    from app.lotto2.predict_hyena import army2_hyena_predict
    from app.lotto2.predict_lstm import army2_lstm_predict
    from app.lotto2.predict_markov import army2_markov_predict
    from app.lotto2.predict_stat import army2_stat_predict

    conn = get_lotto2_db()
    try:
        existing = conn.execute(
            """
            SELECT brain_tag FROM lotto_predictions_army2
            WHERE target_draw_no = ?
            """,
            (target_draw_no,),
        ).fetchall()
    finally:
        conn.close()

    if existing and len(existing) >= 30:
        return {
            "status": "cached",
            "target_draw_no": target_draw_no,
            "total_sets": len(existing),
        }

    miss_draws = get_miss_draws_for_army2(target_draw_no)
    if len(miss_draws) < 5:
        return {
            "status": "error",
            "reason": "insufficient_miss_data",
            "miss_count": len(miss_draws),
        }

    fresh: list[dict] = []
    fresh.extend(army2_stat_predict(miss_draws, SETS_PER_BRAIN_ARMY2))
    fresh.extend(army2_markov_predict(miss_draws, SETS_PER_BRAIN_ARMY2))
    fresh.extend(army2_combo_predict(miss_draws, SETS_PER_BRAIN_ARMY2))
    fresh.extend(army2_lstm_predict(miss_draws, SETS_PER_BRAIN_ARMY2))
    fresh.extend(army2_fusion_predict(miss_draws, SETS_PER_BRAIN_ARMY2))

    hyena_sets = army2_hyena_predict(fresh, SETS_PER_BRAIN_ARMY2)
    fresh.extend(hyena_sets)

    conn = get_lotto2_db()
    try:
        conn.execute(
            "DELETE FROM lotto_predictions_army2 WHERE target_draw_no = ?",
            (target_draw_no,),
        )
        for r in fresh:
            nums = r.get("nums", [])
            if len(nums) != 6:
                continue
            conn.execute(
                """
                INSERT INTO lotto_predictions_army2
                (target_draw_no, method, num1, num2, num3, num4, num5, num6,
                 confidence, reasoning, brain_tag)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target_draw_no,
                    r.get("method", "?"),
                    nums[0],
                    nums[1],
                    nums[2],
                    nums[3],
                    nums[4],
                    nums[5],
                    r.get("confidence", 0.5),
                    r.get("reasoning", ""),
                    r.get("brain_tag", "legacy"),
                ),
            )
        conn.commit()
    finally:
        conn.close()

    _score_army2_predictions(target_draw_no)

    return {
        "status": "ok",
        "target_draw_no": target_draw_no,
        "total_sets": len(fresh),
    }


def update_army2_weights(target_draw_no: int, last_n: int = 50, eta: float = 1.5) -> None:
    """2군 가중치 Hedge 갱신."""
    conn = get_lotto2_db()
    try:
        rows = conn.execute(
            """
            SELECT brain_tag, AVG(matched_count) AS avg_m,
                   COUNT(*) AS n, SUM(matched_count) AS sum_m
            FROM lotto_predictions_army2
            WHERE target_draw_no <= ? AND target_draw_no > ?
              AND matched_count >= 0
            GROUP BY brain_tag
            """,
            (target_draw_no, target_draw_no - last_n),
        ).fetchall()

        if not rows:
            return

        seeds = {
            "army2_stat": 1.5,
            "army2_markov": 1.0,
            "army2_combo": 2.5,
            "army2_lstm": 2.0,
            "army2_fusion": 2.0,
            "army2_hyena": 2.0,
        }

        for r in rows:
            tag = r["brain_tag"]
            if tag not in seeds:
                continue
            avg_m = r["avg_m"] or 0
            base = seeds[tag]
            new_w = base * math.exp(eta * float(avg_m) / 6.0)
            n_pred = r["n"] or 0
            sum_m = r["sum_m"] if r["sum_m"] is not None else 0
            conn.execute(
                """
                UPDATE lotto_brain_weights_army2
                SET current_weight = ?, recent_avg_match = ?,
                    total_predictions = ?, total_matches = ?,
                    last_updated_draw = ?, updated_at = datetime('now','localtime')
                WHERE brain_tag = ?
                """,
                (new_w, avg_m, n_pred, int(sum_m), target_draw_no, tag),
            )
        conn.commit()
    finally:
        conn.close()


def run_backtest_army2(start_draw: int, end_draw: int) -> dict:
    """2군 백테스트(회차별 예측 + 가중치 갱신)."""
    n_ok = 0
    status_counts: Counter[str] = Counter()

    for draw_no in range(start_draw, end_draw + 1):
        try:
            result = run_prediction_army2(draw_no)
            st = str(result.get("status", ""))
            status_counts[st] += 1
            if st == "ok":
                n_ok += 1
                update_army2_weights(draw_no)
        except (OSError, sqlite3.Error, ValueError, TypeError, RuntimeError) as e:
            logger.warning("army2 backtest skip %s: %s", draw_no, e)
            continue

    return {
        "total_ok": n_ok,
        "status_histogram": dict(status_counts),
        "range": f"{start_draw}~{end_draw}",
    }
