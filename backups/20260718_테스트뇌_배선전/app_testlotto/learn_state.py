"""테스트로또 뇌 학습 상태 — 오답 패턴 기억·가중치 조정 (walk-forward 전용)."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.testlotto.models import get_lotto_db

logger = logging.getLogger(__name__)

DEFAULT_ADJUSTMENTS: dict[str, float] = {
    "carry_over_boost": 0.0,
    "ending_digit_boost": 0.0,
    "pair_boost": 0.0,
    "consecutive_boost": 0.0,
    "overdue_boost": 0.0,
    "odd_even_balance": 0.0,
}

PREDICT_BRAIN_TAGS = ("stat", "markov", "review")


def _empty_state() -> dict[str, Any]:
    return {
        "adjustments": dict(DEFAULT_ADJUSTMENTS),
        "miss_counts": {},
        "review_count": 0,
        "last_draw_no": 0,
        "recent_avg_match": 0.0,
    }


def load_learn_state(brain_tag: str) -> dict[str, Any]:
    conn = get_lotto_db()
    try:
        row = conn.execute(
            "SELECT state_json FROM testlotto_brain_learn_state WHERE brain_tag = ?",
            (brain_tag,),
        ).fetchone()
        if not row:
            return _empty_state()
        data = json.loads(row[0])
        base = _empty_state()
        base.update(data)
        return base
    finally:
        conn.close()


def save_learn_state(brain_tag: str, state: dict[str, Any]) -> None:
    conn = get_lotto_db()
    try:
        conn.execute(
            """
            INSERT INTO testlotto_brain_learn_state (brain_tag, state_json, review_count, last_draw_no, updated_at)
            VALUES (?, ?, ?, ?, datetime('now','localtime'))
            ON CONFLICT(brain_tag) DO UPDATE SET
                state_json = excluded.state_json,
                review_count = excluded.review_count,
                last_draw_no = excluded.last_draw_no,
                updated_at = excluded.updated_at
            """,
            (
                brain_tag,
                json.dumps(state, ensure_ascii=False),
                int(state.get("review_count", 0)),
                int(state.get("last_draw_no", 0)),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_all_learn_states() -> dict[str, dict[str, Any]]:
    return {tag: load_learn_state(tag) for tag in PREDICT_BRAIN_TAGS}


def get_referee_weights() -> dict[str, float]:
    """심판관: 최근 성적 기반 예측뇌 가중치."""
    states = get_all_learn_states()
    weights: dict[str, float] = {}
    for tag in PREDICT_BRAIN_TAGS:
        s = states.get(tag, _empty_state())
        avg = float(s.get("recent_avg_match", 0.0))
        weights[tag] = 1.0 + avg * 0.15
    total = sum(weights.values()) or 1.0
    return {k: v / total for k, v in weights.items()}


def apply_feedback(
    brain_tag: str,
    draw_no: int,
    matched_count: int,
    missed_patterns: list[str],
    *,
    window: int = 20,
) -> dict[str, Any]:
    """오답 패턴 → 조정값 누적 (복습 루프 핵심)."""
    state = load_learn_state(brain_tag)
    adj = state.setdefault("adjustments", dict(DEFAULT_ADJUSTMENTS))
    miss_counts = state.setdefault("miss_counts", {})

    for pattern in missed_patterns:
        miss_counts[pattern] = int(miss_counts.get(pattern, 0)) + 1
        recent = miss_counts[pattern]
        if recent >= 3:
            boost_key = {
                "carry_over": "carry_over_boost",
                "ending_digit": "ending_digit_boost",
                "pair": "pair_boost",
                "consecutive": "consecutive_boost",
                "overdue": "overdue_boost",
                "odd_even": "odd_even_balance",
            }.get(pattern)
            if boost_key:
                adj[boost_key] = min(0.5, float(adj.get(boost_key, 0)) + 0.05)

    rc = int(state.get("review_count", 0)) + 1
    prev_avg = float(state.get("recent_avg_match", 0.0))
    new_avg = ((prev_avg * (rc - 1)) + matched_count) / rc if rc > 0 else float(matched_count)

    state["review_count"] = rc
    state["last_draw_no"] = draw_no
    state["recent_avg_match"] = round(new_avg, 4)
    state["adjustments"] = adj
    state["miss_counts"] = miss_counts

    save_learn_state(brain_tag, state)

    conn = get_lotto_db()
    try:
        conn.execute(
            """
            UPDATE testlotto_brain_weights
            SET current_weight = ?, recent_avg_match = ?, total_predictions = total_predictions + 1,
                total_matches = total_matches + ?, last_updated_draw = ?,
                updated_at = datetime('now','localtime')
            WHERE brain_tag = ?
            """,
            (
                max(0.5, 1.0 + new_avg * 0.1),
                new_avg,
                matched_count,
                draw_no,
                brain_tag,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    logger.info(
        "[학습] %s draw=%d match=%d missed=%s adj_carry=%.2f",
        brain_tag,
        draw_no,
        matched_count,
        missed_patterns,
        adj.get("carry_over_boost", 0),
    )
    return state


def reset_learn_states(conn=None) -> None:
    own = conn is None
    if own:
        conn = get_lotto_db()
    try:
        conn.execute("DELETE FROM testlotto_brain_learn_state")
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()
