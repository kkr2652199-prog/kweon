"""전략 X recommend → lotto_predictions_army4 적재 (하이에나 miss 학습 전제).

brain_tag는 strategy_x_* 접두사 — predict 파이프라인의 DELETE v13_% 와 충돌 방지.
R2: 당첨 확률 향상 문구 금지.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.lotto4.brains.coordinator_brain import generate_recommend_sets
from app.lotto4.brains.cooccur_brain_v13 import (
    BRAIN_TAG as COOCCUR_BRAIN_TAG,
    generate_cooccur_sets,
)
from app.lotto4.brains.hyena_coordinator_v13 import (
    BRAIN_TAG as HYENA_BRAIN_TAG,
    generate_hyena_sets,
)
from app.lotto4.brains.popularity_freq_brain import generate_popularity_sets
from app.lotto4.brains.popularity_pair_brain import generate_pair_sets
from app.lotto4.brains.shape_brain import generate_shape_sets
from app.lotto4.models import get_lotto4_db

STRATEGY_X_BRAIN_TAGS: tuple[str, ...] = (
    "strategy_x_coordinator",
    "strategy_x_popularity_freq",
    "strategy_x_popularity_pair",
    "strategy_x_shape",
)

_COORDINATOR_TAG = "strategy_x_coordinator"
_FREQ_TAG = "strategy_x_popularity_freq"
_PAIR_TAG = "strategy_x_popularity_pair"
_SHAPE_TAG = "strategy_x_shape"
_COOCCUR_TAG = COOCCUR_BRAIN_TAG  # strategy_x_cooccur
_HYENA_TAG = HYENA_BRAIN_TAG  # strategy_x_hyena

STRATEGY_X_FIVE_BRAIN_TAGS: tuple[str, ...] = (
    _FREQ_TAG,
    _PAIR_TAG,
    _SHAPE_TAG,
    _COOCCUR_TAG,
    _HYENA_TAG,
)

STRATEGY_X_BRAIN_LABEL_UI: dict[str, str] = {
    _FREQ_TAG: "1뇌 인기빈도",
    _PAIR_TAG: "2뇌 인기쌍",
    _SHAPE_TAG: "3뇌 형태",
    _COOCCUR_TAG: "5뇌 cooccur",
    _HYENA_TAG: "하이에나",
}


def _delete_brain_rows(
    conn: sqlite3.Connection, target_draw_no: int, tags: tuple[str, ...]
) -> None:
    placeholders = ",".join("?" for _ in tags)
    conn.execute(
        f"""
        DELETE FROM lotto_predictions_army4
        WHERE target_draw_no = ? AND brain_tag IN ({placeholders})
        """,
        (int(target_draw_no), *tags),
    )


def _delete_strategy_x_rows(conn: sqlite3.Connection, target_draw_no: int) -> None:
    _delete_brain_rows(conn, target_draw_no, STRATEGY_X_BRAIN_TAGS)


def _insert_set_row(
    conn: sqlite3.Connection,
    *,
    target_draw_no: int,
    brain_tag: str,
    nums: list[int],
    method: str,
    reasoning: str,
    confidence: float = 0.5,
) -> None:
    sorted_nums = sorted(int(n) for n in nums)
    if len(sorted_nums) != 6:
        return
    conn.execute(
        """
        INSERT INTO lotto_predictions_army4
            (target_draw_no, method, num1, num2, num3, num4, num5, num6,
             confidence, reasoning, brain_tag, matched_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(target_draw_no),
            method,
            sorted_nums[0],
            sorted_nums[1],
            sorted_nums[2],
            sorted_nums[3],
            sorted_nums[4],
            sorted_nums[5],
            float(confidence),
            reasoning,
            brain_tag,
            -1,
        ),
    )


def _save_brain_sets(
    conn: sqlite3.Connection,
    target_draw_no: int,
    brain_tag: str,
    payload: dict[str, Any],
    method_prefix: str,
) -> int:
    saved = 0
    for item in payload.get("sets") or []:
        nums = item.get("numbers")
        if not nums or len(nums) != 6:
            continue
        set_no = int(item.get("set_no") or (saved + 1))
        reasoning = json.dumps(
            {
                "set_no": set_no,
                "brain": payload.get("brain"),
                "disclaimer": payload.get("disclaimer"),
            },
            ensure_ascii=False,
        )
        _insert_set_row(
            conn,
            target_draw_no=target_draw_no,
            brain_tag=brain_tag,
            nums=nums,
            method=f"{method_prefix}_set_{set_no}",
            reasoning=reasoning,
        )
        saved += 1
    return saved


def save_strategy_x_recommend(
    target_draw_no: int,
    coordinator_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """recommend 5세트 + 1~3뇌 각 5세트를 lotto_predictions_army4에 저장."""
    td = int(target_draw_no)
    coord = coordinator_result or generate_recommend_sets(td)
    freq = generate_popularity_sets(td)
    pair = generate_pair_sets(td)
    shape = generate_shape_sets(td)

    conn = get_lotto4_db()
    try:
        _delete_strategy_x_rows(conn, td)

        counts: dict[str, int] = {}
        for item in coord.get("sets") or []:
            nums = item.get("numbers")
            if not nums or len(nums) != 6:
                continue
            set_no = int(item.get("set_no") or 0)
            reasoning = json.dumps(
                {
                    "set_no": set_no,
                    "combined_score": item.get("combined_score"),
                    "brain_contributions": item.get("brain_contributions"),
                    "shape_metrics": item.get("shape_metrics"),
                    "top_pairs_present": item.get("top_pairs_present"),
                    "source_brain": coord.get("brain"),
                },
                ensure_ascii=False,
            )
            conf = float(item.get("combined_score") or 0.5)
            _insert_set_row(
                conn,
                target_draw_no=td,
                brain_tag=_COORDINATOR_TAG,
                nums=nums,
                method=f"strategy_x_recommend_set_{set_no}",
                reasoning=reasoning,
                confidence=conf,
            )
            counts[_COORDINATOR_TAG] = counts.get(_COORDINATOR_TAG, 0) + 1

        counts[_FREQ_TAG] = _save_brain_sets(
            conn, td, _FREQ_TAG, freq, "strategy_x_popularity"
        )
        counts[_PAIR_TAG] = _save_brain_sets(
            conn, td, _PAIR_TAG, pair, "strategy_x_pair"
        )
        counts[_SHAPE_TAG] = _save_brain_sets(
            conn, td, _SHAPE_TAG, shape, "strategy_x_shape"
        )

        conn.commit()
    finally:
        conn.close()

    return {
        "target_draw_no": td,
        "saved_counts": counts,
        "total_rows": sum(counts.values()),
        "brain_tags": list(STRATEGY_X_BRAIN_TAGS),
        "coordinator_sets": len(coord.get("sets") or []),
    }


def save_strategy_x_popularity_freq(
    target_draw_no: int,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """1뇌 5세트 → lotto_predictions_army4."""
    td = int(target_draw_no)
    data = payload or generate_popularity_sets(td)
    conn = get_lotto4_db()
    try:
        _delete_brain_rows(conn, td, (_FREQ_TAG,))
        saved = _save_brain_sets(conn, td, _FREQ_TAG, data, "strategy_x_popularity")
        conn.commit()
    finally:
        conn.close()
    return {"target_draw_no": td, "saved_counts": {_FREQ_TAG: saved}, "total_rows": saved}


def save_strategy_x_pair(
    target_draw_no: int,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """2뇌 5세트 → lotto_predictions_army4."""
    td = int(target_draw_no)
    data = payload or generate_pair_sets(td)
    conn = get_lotto4_db()
    try:
        _delete_brain_rows(conn, td, (_PAIR_TAG,))
        saved = _save_brain_sets(conn, td, _PAIR_TAG, data, "strategy_x_pair")
        conn.commit()
    finally:
        conn.close()
    return {"target_draw_no": td, "saved_counts": {_PAIR_TAG: saved}, "total_rows": saved}


def save_strategy_x_shape(
    target_draw_no: int,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """3뇌 5세트 → lotto_predictions_army4."""
    td = int(target_draw_no)
    data = payload or generate_shape_sets(td)
    conn = get_lotto4_db()
    try:
        _delete_brain_rows(conn, td, (_SHAPE_TAG,))
        saved = _save_brain_sets(conn, td, _SHAPE_TAG, data, "strategy_x_shape")
        conn.commit()
    finally:
        conn.close()
    return {"target_draw_no": td, "saved_counts": {_SHAPE_TAG: saved}, "total_rows": saved}


def generate_and_save_recommend(target_draw_no: int) -> dict[str, Any]:
    """API용: 조합 생성 후 DB 적재, 응답에 logging 메타 포함."""
    result = generate_recommend_sets(int(target_draw_no))
    log_meta = save_strategy_x_recommend(int(target_draw_no), result)
    result["prediction_logging"] = log_meta
    return result


def save_strategy_x_cooccur(
    target_draw_no: int,
    cooccur_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """cooccur 5뇌 5세트 → lotto_predictions_army4."""
    td = int(target_draw_no)
    payload = cooccur_result or generate_cooccur_sets(td)
    conn = get_lotto4_db()
    saved = 0
    try:
        _delete_brain_rows(conn, td, (_COOCCUR_TAG,))
        for item in payload.get("sets") or []:
            nums = item.get("numbers")
            if not nums or len(nums) != 6:
                continue
            set_no = int(item.get("set_no") or (saved + 1))
            reasoning = json.dumps(
                {
                    "set_no": set_no,
                    "cooccur_score": item.get("cooccur_score"),
                    "brain": payload.get("brain"),
                    "disclaimer": payload.get("disclaimer"),
                },
                ensure_ascii=False,
            )
            _insert_set_row(
                conn,
                target_draw_no=td,
                brain_tag=_COOCCUR_TAG,
                nums=nums,
                method=f"strategy_x_cooccur_set_{set_no}",
                reasoning=reasoning,
                confidence=float(item.get("cooccur_score") or 0.5),
            )
            saved += 1
        conn.commit()
    finally:
        conn.close()
    return {
        "target_draw_no": td,
        "saved_counts": {_COOCCUR_TAG: saved},
        "total_rows": saved,
        "brain_tags": [_COOCCUR_TAG],
    }


def generate_and_save_cooccur(target_draw_no: int) -> dict[str, Any]:
    """API용: cooccur 생성 + DB 적재."""
    result = generate_cooccur_sets(int(target_draw_no))
    log_meta = save_strategy_x_cooccur(int(target_draw_no), result)
    result["prediction_logging"] = log_meta
    return result


def save_strategy_x_hyena(
    target_draw_no: int,
    hyena_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """하이에나 5세트 → lotto_predictions_army4."""
    td = int(target_draw_no)
    payload = hyena_result or generate_hyena_sets(td)
    conn = get_lotto4_db()
    saved = 0
    try:
        _delete_brain_rows(conn, td, (_HYENA_TAG,))
        for item in payload.get("sets") or []:
            nums = item.get("numbers")
            if not nums or len(nums) != 6:
                continue
            set_no = int(item.get("set_no") or (saved + 1))
            reasoning = json.dumps(
                {
                    "set_no": set_no,
                    "brain_trust": payload.get("brain_trust"),
                    "popularity_score": item.get("popularity_score"),
                    "pool_consensus_max": item.get("pool_consensus_max"),
                    "mode": payload.get("mode"),
                    "brain": payload.get("brain"),
                    "disclaimer": payload.get("disclaimer"),
                },
                ensure_ascii=False,
            )
            _insert_set_row(
                conn,
                target_draw_no=td,
                brain_tag=_HYENA_TAG,
                nums=nums,
                method=f"strategy_x_hyena_set_{set_no}",
                reasoning=reasoning,
                confidence=float(item.get("popularity_score") or 0.5),
            )
            saved += 1
        conn.commit()
    finally:
        conn.close()
    return {
        "target_draw_no": td,
        "saved_counts": {_HYENA_TAG: saved},
        "total_rows": saved,
        "brain_tags": [_HYENA_TAG],
    }


def generate_and_save_hyena(target_draw_no: int) -> dict[str, Any]:
    """API용: 하이에나 walk-forward 생성 + DB 적재."""
    result = generate_hyena_sets(int(target_draw_no))
    log_meta = save_strategy_x_hyena(int(target_draw_no), result)
    result["prediction_logging"] = log_meta
    return result
