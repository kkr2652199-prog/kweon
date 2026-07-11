"""4군 제약만족 샘플링 뇌 — v13_contrarian 슬롯 교체(M-4).

합·홀짝·고저·연속번호 제약 + tier1 + 당첨회피. PMF는 번호 출현빈도 정규화.
"""

from __future__ import annotations

import logging
import math
import random
from typing import Any

from app.lotto.filters import tier1_filter
from app.lotto4.legacy.v13_models import (
    V13_WIN_AVOID_N,
    get_recent_winning_sets,
    v13_pass_win_avoid,
    v13_perturb_combo_one_swap,
)

logger = logging.getLogger(__name__)

SUM_PERCENTILE_LO = 15
SUM_PERCENTILE_HI = 85
ODD_MIN = 2
ODD_MAX = 4
LOW_HIGH_BOUNDARY = 22
LOWHI_MIN = 2
LOWHI_MAX = 4
MAX_CONSECUTIVE_PAIRS = 2
MAX_ATTEMPTS = 10000
RELAX_SUM_DELTA = 15


def _six_from_draw(d: dict) -> list[int] | None:
    try:
        return sorted(int(d[f"num{i}"]) for i in range(1, 7))
    except (KeyError, TypeError, ValueError):
        return None


def _percentile_linear(sorted_vals: list[float], p_pct: float) -> float:
    """p_pct: 0~100 구간 선형 보간."""
    if not sorted_vals:
        return 126.0
    n = len(sorted_vals)
    if n == 1:
        return float(sorted_vals[0])
    idx = (n - 1) * (p_pct / 100.0)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    lo = max(0, min(lo, n - 1))
    hi = max(0, min(hi, n - 1))
    if lo == hi:
        return float(sorted_vals[lo])
    return float(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (idx - lo))


def _dynamic_sum_bounds(training_draws: list[dict]) -> tuple[float, float]:
    sums: list[float] = []
    for d in training_draws:
        nums = _six_from_draw(d)
        if nums and len(nums) == 6:
            sums.append(float(sum(nums)))
    if len(sums) < 5:
        return (100.0, 170.0)
    sums.sort()
    lo = _percentile_linear(sums, float(SUM_PERCENTILE_LO))
    hi = _percentile_linear(sums, float(SUM_PERCENTILE_HI))
    if hi <= lo:
        hi = lo + 30.0
    return (lo, hi)


def army4_constraint_prob_vector(training_draws: list[dict]) -> dict[int, float]:
    """번호 출현 빈도 기반 PMF (fusion 호환용)."""
    if not training_draws:
        return {n: 1.0 / 45.0 for n in range(1, 46)}
    cnt = [0.0] * 46
    for d in training_draws:
        nums = _six_from_draw(d)
        if not nums:
            continue
        for x in nums:
            if 1 <= x <= 45:
                cnt[x] += 1.0
    tot = sum(cnt[1:46])
    if tot <= 0:
        return {n: 1.0 / 45.0 for n in range(1, 46)}
    return {n: cnt[n] / tot for n in range(1, 46)}


def _weighted_sample_six_without_replacement(
    pmf: dict[int, float],
    rng: random.Random,
) -> list[int]:
    pool = list(range(1, 46))
    out: list[int] = []
    for _ in range(6):
        wts = [max(float(pmf.get(n, 0.0)), 1e-15) for n in pool]
        pick = rng.choices(pool, weights=wts, k=1)[0]
        out.append(pick)
        pool.remove(pick)
    return sorted(out)


def _consecutive_adj_edges(nums: list[int]) -> int:
    """정렬된 6개에서 인접 연속쌍 개수 (예: 3-4-5 → 2)."""
    if len(nums) != 6:
        return 99
    c = 0
    for i in range(5):
        if nums[i + 1] == nums[i] + 1:
            c += 1
    return c


def _constraints_ok(
    nums: list[int],
    sum_lo: float,
    sum_hi: float,
    odd_min: int,
    odd_max: int,
    low_min: int,
    low_max: int,
    max_pairs: int,
) -> bool:
    sm = sum(nums)
    if sm < sum_lo or sm > sum_hi:
        return False
    odd_c = sum(1 for x in nums if x % 2 == 1)
    if odd_c < odd_min or odd_c > odd_max:
        return False
    low_c = sum(1 for x in nums if x <= LOW_HIGH_BOUNDARY)
    if low_c < low_min or low_c > low_max:
        return False
    if _consecutive_adj_edges(nums) > max_pairs:
        return False
    return True


def _fill_sets(
    _td: list[dict],
    pmf: dict[int, float],
    sum_lo: float,
    sum_hi: float,
    odd_min: int,
    odd_max: int,
    low_min: int,
    low_max: int,
    max_pairs: int,
    n_sets: int,
    target_draw_no: int | None,
    rng: random.Random,
    max_attempts: int,
    used_start: set[tuple[int, ...]] | None,
) -> tuple[list[dict[str, Any]], set[tuple[int, ...]]]:
    win_sets = (
        get_recent_winning_sets(target_draw_no, V13_WIN_AVOID_N) if target_draw_no else []
    )
    out: list[dict[str, Any]] = []
    used: set[tuple[int, ...]] = set(used_start) if used_start else set()
    st: dict[str, int | bool] = {"fail_count": 0, "bypass": False}
    attempts = 0
    while len(out) < n_sets and attempts < max_attempts:
        attempts += 1
        cand = _weighted_sample_six_without_replacement(pmf, rng)
        if not _constraints_ok(
            cand, sum_lo, sum_hi, odd_min, odd_max, low_min, low_max, max_pairs,
        ):
            continue
        try:
            if not tier1_filter(cand):
                continue
        except (TypeError, ValueError):
            continue
        if not v13_pass_win_avoid(cand, win_sets, st):
            continue
        t = tuple(cand)
        if t in used:
            continue
        used.add(t)
        out.append(
            {
                "nums": cand,
                "brain_tag": "v13_contrarian",
                "confidence": round(min(0.92, 0.44 + 0.06 * (len(out) % 3)), 2),
                "method": "🎯 제약만족샘플러",
                "reasoning": "constraint_sat_sum_odd_lowhi_run",
            },
        )
    return out, used


def _perturb_fallback(
    _td: list[dict],
    target_draw_no: int | None,
    n_need: int,
    seed: int,
    pmf: dict[int, float],
    sum_lo: float,
    sum_hi: float,
    odd_min: int,
    odd_max: int,
    low_min: int,
    low_max: int,
    max_pairs: int,
    used_global: set[tuple[int, ...]],
    out: list[dict[str, Any]],
) -> None:
    win_sets = (
        get_recent_winning_sets(target_draw_no, V13_WIN_AVOID_N)
        if target_draw_no
        else []
    )
    guard = 0
    while len(out) < n_need and guard < 8000:
        guard += 1
        rr = random.Random((seed ^ guard) % (2**32))
        cand = _weighted_sample_six_without_replacement(pmf, rr)
        if not _constraints_ok(
            cand, sum_lo, sum_hi, odd_min, odd_max, low_min, low_max, max_pairs,
        ):
            continue
        st2: dict[str, int | bool] = {"fail_count": 0, "bypass": False}
        nums2 = list(cand)
        for _ in range(50):
            if v13_pass_win_avoid(nums2, win_sets, st2):
                break
            nums2 = v13_perturb_combo_one_swap(nums2, rr)
        nums2 = sorted(nums2)
        if not _constraints_ok(
            nums2, sum_lo, sum_hi, odd_min, odd_max, low_min, low_max, max_pairs,
        ):
            continue
        try:
            if not tier1_filter(nums2):
                continue
        except (TypeError, ValueError):
            continue
        t = tuple(nums2)
        if t in used_global:
            continue
        used_global.add(t)
        out.append(
            {
                "nums": nums2,
                "brain_tag": "v13_contrarian",
                "confidence": 0.46,
                "method": "🎯 제약만족샘플러",
                "reasoning": "constraint_perturb_fallback",
            },
        )


def _rng_seed(training_draws: list[dict]) -> int:
    tail = training_draws[-min(10, len(training_draws)) :]
    key_tuples: list[tuple[int, ...]] = []
    for d in tail:
        dd = int(d.get("draw_no", 0) or 0)
        ns = _six_from_draw(d)
        if ns:
            key_tuples.append((dd, *ns))
    seed = hash(tuple(key_tuples)) % (2**32)
    return seed + (2**32 if seed < 0 else 0)


def _relaxed_and_perturb(
    training_draws: list[dict],
    n_sets: int,
    target_draw_no: int | None,
    seed: int,
    pmf: dict[int, float],
    sum_lo: float,
    sum_hi: float,
    out: list[dict[str, Any]],
    used_g: set[tuple[int, ...]],
) -> None:
    if len(out) >= n_sets:
        return
    logger.warning("constraint: strict 부족 (%d/%d), 완화 재시도", len(out), n_sets)
    rng2 = random.Random((seed ^ 0xC04104) % (2**32))
    slo, shi = sum_lo - RELAX_SUM_DELTA, sum_hi + RELAX_SUM_DELTA
    extra, used2 = _fill_sets(
        training_draws,
        pmf,
        slo,
        shi,
        1,
        5,
        1,
        5,
        MAX_CONSECUTIVE_PAIRS + 1,
        n_sets - len(out),
        target_draw_no,
        rng2,
        MAX_ATTEMPTS,
        used_g,
    )
    out.extend(extra)
    used_g.clear()
    used_g.update(used2)
    if len(out) < n_sets:
        slo, shi = sum_lo - RELAX_SUM_DELTA, sum_hi + RELAX_SUM_DELTA
        _perturb_fallback(
            training_draws,
            target_draw_no,
            n_sets,
            seed,
            pmf,
            slo,
            shi,
            1,
            5,
            1,
            5,
            MAX_CONSECUTIVE_PAIRS + 1,
            used_g,
            out,
        )


def army4_constraint_predict(
    training_draws: list[dict],
    n_sets: int = 5,
    target_draw_no: int | None = None,
) -> list[dict]:
    if not training_draws or n_sets <= 0:
        return []

    pmf = army4_constraint_prob_vector(training_draws)
    sum_lo, sum_hi = _dynamic_sum_bounds(training_draws)
    seed = _rng_seed(training_draws)
    rng = random.Random(seed)

    out, used_g = _fill_sets(
        training_draws,
        pmf,
        sum_lo,
        sum_hi,
        ODD_MIN,
        ODD_MAX,
        LOWHI_MIN,
        LOWHI_MAX,
        MAX_CONSECUTIVE_PAIRS,
        n_sets,
        target_draw_no,
        rng,
        MAX_ATTEMPTS,
        None,
    )

    _relaxed_and_perturb(
        training_draws,
        n_sets,
        target_draw_no,
        seed,
        pmf,
        sum_lo,
        sum_hi,
        out,
        used_g,
    )

    if len(out) < n_sets:
        logger.warning(
            "constraint: only %d/%d sets (target=%s)",
            len(out),
            n_sets,
            target_draw_no,
        )

    return out[:n_sets]
