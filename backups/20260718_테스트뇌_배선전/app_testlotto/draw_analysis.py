"""회차별 분석 그릇 — 쌍수·이월수·연속수·끝수·AC·미출·합계·814만순위 컬럼."""

from __future__ import annotations

import json
import logging
from typing import Any

from collections import Counter

from app.testlotto.data_service import _get_draws_before
from app.testlotto.features.draw_features import (
    build_number_gaps,
    build_pair_freq,
    combo_features,
    consecutive_pairs,
    ending_digits,
    odd_even_ratio,
    sorted_nums,
)
from app.testlotto.models import get_lotto_db

logger = logging.getLogger(__name__)


def _combo_rank_814(nums: list[int]) -> int | None:
    try:
        from app.lotto4.combinadic import combo_to_rank

        return int(combo_to_rank(sorted(nums)))
    except Exception:
        return None


def compute_draw_feature_row(draw_no: int) -> dict[str, Any] | None:
    """해당 회차 당첨번호 기준 분석 (정답 확정 후 저장)."""
    conn = get_lotto_db()
    try:
        row = conn.execute("SELECT * FROM lotto_draws WHERE draw_no = ?", (draw_no,)).fetchone()
        if not row:
            return None
        d = dict(row)
        nums = sorted_nums(d)
        prev_draws = _get_draws_before(draw_no)
        prev = prev_draws[-1] if prev_draws else None
        feats = combo_features(nums, prev_draws)
        gaps = build_number_gaps(prev_draws) if prev_draws else {}
        overdue = sorted([n for n in nums if gaps.get(n, 0) >= 25])
        pair_freq = build_pair_freq(prev_draws) if prev_draws else Counter()
        hot_pairs = sorted(
            [(list(p), c) for p, c in pair_freq.most_common(10)],
            key=lambda x: -x[1],
        )
        odd, even = odd_even_ratio(nums)
        zones = [sum(1 for n in nums if 1 <= n <= 15), sum(1 for n in nums if 16 <= n <= 30), sum(1 for n in nums if 31 <= n <= 45)]
        return {
            "draw_no": draw_no,
            "carry_over_count": len(feats["carry_over"]),
            "carry_over_nums": json.dumps(feats["carry_over"], ensure_ascii=False),
            "consecutive_count": feats["consecutive"],
            "ending_digits": json.dumps(feats["endings"], ensure_ascii=False),
            "ac_value": feats["ac"],
            "gap_overdue_nums": json.dumps(overdue, ensure_ascii=False),
            "sum_total": feats["sum"],
            "odd_count": odd,
            "even_count": even,
            "zone_low_mid_high": json.dumps(zones, ensure_ascii=False),
            "pair_hot_json": json.dumps(hot_pairs, ensure_ascii=False),
            "combo_rank_814": _combo_rank_814(nums),
            "bonus_num": int(d["bonus"]),
        }
    finally:
        conn.close()


def upsert_draw_features(draw_no: int) -> dict[str, Any] | None:
    row = compute_draw_feature_row(draw_no)
    if not row:
        return None
    conn = get_lotto_db()
    try:
        conn.execute(
            """
            INSERT INTO testlotto_draw_features (
                draw_no, carry_over_count, carry_over_nums, consecutive_count,
                ending_digits, ac_value, gap_overdue_nums, sum_total,
                odd_count, even_count, zone_low_mid_high, pair_hot_json,
                combo_rank_814, bonus_num, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?, datetime('now','localtime'))
            ON CONFLICT(draw_no) DO UPDATE SET
                carry_over_count=excluded.carry_over_count,
                carry_over_nums=excluded.carry_over_nums,
                consecutive_count=excluded.consecutive_count,
                ending_digits=excluded.ending_digits,
                ac_value=excluded.ac_value,
                gap_overdue_nums=excluded.gap_overdue_nums,
                sum_total=excluded.sum_total,
                odd_count=excluded.odd_count,
                even_count=excluded.even_count,
                zone_low_mid_high=excluded.zone_low_mid_high,
                pair_hot_json=excluded.pair_hot_json,
                combo_rank_814=excluded.combo_rank_814,
                bonus_num=excluded.bonus_num,
                updated_at=excluded.updated_at
            """,
            (
                row["draw_no"],
                row["carry_over_count"],
                row["carry_over_nums"],
                row["consecutive_count"],
                row["ending_digits"],
                row["ac_value"],
                row["gap_overdue_nums"],
                row["sum_total"],
                row["odd_count"],
                row["even_count"],
                row["zone_low_mid_high"],
                row["pair_hot_json"],
                row["combo_rank_814"],
                row["bonus_num"],
            ),
        )
        conn.commit()
        return row
    finally:
        conn.close()


def detect_missed_patterns(
    predicted: list[int],
    actual: list[int],
    draws_before: list[dict],
) -> list[str]:
    """오답탐정: 놓친 패턴 태그 목록."""
    missed: list[str] = []
    prev = draws_before[-1] if draws_before else None
    actual_set = set(actual)
    pred_set = set(predicted)

    if prev:
        carry = set(sorted_nums(prev))
        actual_carry = carry & actual_set
        pred_carry = carry & pred_set
        if actual_carry and not pred_carry:
            missed.append("carry_over")

    actual_endings = {n % 10 for n in actual}
    pred_endings = {n % 10 for n in predicted}
    if actual_endings - pred_endings:
        missed.append("ending_digit")

    if consecutive_pairs(actual) > 0 and consecutive_pairs(predicted) == 0:
        missed.append("consecutive")

    gaps = build_number_gaps(draws_before) if draws_before else {}
    actual_overdue = [n for n in actual if gaps.get(n, 0) >= 25]
    if actual_overdue and not any(n in pred_set for n in actual_overdue):
        missed.append("overdue")

    odd_a, _ = odd_even_ratio(actual)
    odd_p, _ = odd_even_ratio(predicted)
    if abs(odd_a - odd_p) >= 2:
        missed.append("odd_even")

    pair_freq = build_pair_freq(draws_before) if draws_before else Counter()
    if pair_freq:
        top_pairs = {p for p, _ in pair_freq.most_common(5)}
        actual_pairs = {(min(a, b), max(a, b)) for i, a in enumerate(actual) for b in actual[i + 1 :]}
        if top_pairs & actual_pairs and not top_pairs & {
            (min(a, b), max(a, b)) for i, a in enumerate(predicted) for b in predicted[i + 1 :]
        }:
            missed.append("pair")

    return missed
