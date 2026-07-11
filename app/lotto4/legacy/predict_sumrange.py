"""4군 번호합 범위 뇌 — v13_offset 슬롯 교체(M-1).

워크포워드 전제: 호출자가 `training`만 전달. `brain_tag`는 **v13_offset** 유지(R15).
"""

from __future__ import annotations

import logging
import random
from typing import Any

import numpy as np

from app.lotto.filters import tier1_filter
from app.lotto4.legacy.v13_models import (
    V13_WIN_AVOID_N,
    get_recent_winning_sets,
    v13_pass_win_avoid,
    v13_perturb_combo_one_swap,
)

logger = logging.getLogger(__name__)

_FALLBACK_MIN = 21
_FALLBACK_MAX = 255


def _six_from_draw(d: dict) -> list[int] | None:
    try:
        return sorted(int(d[f"num{i}"]) for i in range(1, 7))
    except (KeyError, TypeError, ValueError):
        return None


def _sums_from_training(training: list[dict]) -> list[int]:
    sums: list[int] = []
    for d in training:
        s = _six_from_draw(d)
        if s and len(s) == 6:
            sums.append(sum(s))
    return sums


def _percentile_range(sums: list[int]) -> tuple[int, int]:
    """15~85 백분위(약 70% 커버리지). 표본 없으면 보수적 기본."""
    if not sums:
        return 100, 175
    arr = np.array(sums, dtype=np.float64)
    low = float(np.percentile(arr, 15))
    high = float(np.percentile(arr, 85))
    lo = int(round(low))
    hi = int(round(high))
    lo = max(_FALLBACK_MIN, min(lo, _FALLBACK_MAX - 20))
    hi = min(_FALLBACK_MAX, max(hi, lo + 10))
    return lo, hi


def army4_sumrange_prob_vector(training_draws: list[dict]) -> dict[int, float]:
    """번호별 출현 빈도 PMF (fusion 4뇌 외부 호출·테스트용)."""
    if not training_draws:
        return {n: 1.0 / 45.0 for n in range(1, 46)}
    freq: dict[int, float] = {n: 0.0 for n in range(1, 46)}
    for d in training_draws:
        s = _six_from_draw(d)
        if not s:
            continue
        for n in s:
            if 1 <= n <= 45:
                freq[n] += 1.0
    tot = sum(freq.values())
    if tot <= 0:
        return {n: 1.0 / 45.0 for n in range(1, 46)}
    return {n: freq[n] / tot for n in range(1, 46)}


def _sample_one_set(
    rng: random.Random,
    nums: list[int],
    weights: list[float],
    s_lo: int,
    s_hi: int,
    win_sets: list[set[int]],
    st: dict[str, int | bool],
) -> list[int] | None:
    for _ in range(200):
        cand = sorted(rng.choices(nums, weights=weights, k=6))
        if len(set(cand)) != 6:
            continue
        sm = sum(cand)
        if sm < s_lo or sm > s_hi:
            continue
        try:
            if not tier1_filter(cand):
                continue
        except (TypeError, ValueError):
            continue
        if not v13_pass_win_avoid(cand, win_sets, st):
            continue
        return cand
    return None


def army4_sumrange_predict(
    training_draws: list[dict],
    n_sets: int = 5,
    target_draw_no: int | None = None,
) -> list[dict]:
    """합 분포 백분위 구간 + 번호 빈도 PMF 가중 샘플."""
    if not training_draws or n_sets <= 0:
        return []

    sums = _sums_from_training(training_draws)
    s_lo, s_hi = _percentile_range(sums)

    pmf = army4_sumrange_prob_vector(training_draws)
    nums = list(range(1, 46))
    w = [max(pmf[n], 1e-9) for n in nums]

    win_sets = (
        get_recent_winning_sets(target_draw_no, V13_WIN_AVOID_N) if target_draw_no else []
    )
    st: dict[str, int | bool] = {"fail_count": 0, "bypass": False}

    tail = training_draws[-min(10, len(training_draws)) :]
    key_tuples: list[tuple[int, ...]] = []
    for d in tail:
        dd = int(d.get("draw_no", 0) or 0)
        ns = _six_from_draw(d)
        if ns:
            key_tuples.append((dd, *ns))
    seed = hash(tuple(key_tuples)) % (2**32)
    if seed < 0:
        seed += 2**32
    rng = random.Random(seed)

    out: list[dict[str, Any]] = []
    used: set[tuple[int, ...]] = set()
    pert_lo, pert_hi = s_lo, s_hi

    def fill_with_range(lo: int, hi: int) -> None:
        guard = 0
        while len(out) < n_sets and guard < 5000:
            guard += 1
            cand = _sample_one_set(rng, nums, w, lo, hi, win_sets, st)
            if cand is None:
                continue
            t = tuple(cand)
            if t in used:
                continue
            used.add(t)
            sm = sum(cand)
            out.append(
                {
                    "nums": cand,
                    "brain_tag": "v13_offset",
                    "confidence": round(min(0.99, 0.35 + 0.002 * abs(sm - (lo + hi) // 2)), 2),
                    "method": "📐 번호합범위",
                    "reasoning": f"sumrange p15-p85 [{lo},{hi}] sum={sm}",
                },
            )

    fill_with_range(s_lo, s_hi)

    if len(out) < n_sets:
        lo2 = max(_FALLBACK_MIN, s_lo - 10)
        hi2 = min(_FALLBACK_MAX, s_hi + 10)
        logger.info(
            "sumrange: 확장 재시도 lo=%s hi=%s (기존 %s~%s)",
            lo2,
            hi2,
            s_lo,
            s_hi,
        )
        fill_with_range(lo2, hi2)
        pert_lo, pert_hi = lo2, hi2

    while len(out) < n_sets:
        guard2 = 0
        progressed = False
        while guard2 < 8000 and len(out) < n_sets:
            guard2 += 1
            cand = _sample_one_set(rng, nums, w, pert_lo, pert_hi, win_sets, st)
            if cand is None:
                continue
            st2: dict[str, int | bool] = {"fail_count": 0, "bypass": False}
            nums2 = list(cand)
            rr = random.Random((seed ^ guard2) % (2**32))
            for _ in range(40):
                if v13_pass_win_avoid(nums2, win_sets, st2):
                    break
                nums2 = v13_perturb_combo_one_swap(nums2, rr)
            t = tuple(sorted(nums2))
            if t in used:
                continue
            if sum(nums2) < pert_lo or sum(nums2) > pert_hi:
                continue
            try:
                if not tier1_filter(nums2):
                    continue
            except (TypeError, ValueError):
                continue
            used.add(t)
            out.append(
                {
                    "nums": sorted(nums2),
                    "brain_tag": "v13_offset",
                    "confidence": 0.42,
                    "method": "📐 번호합범위",
                    "reasoning": "sumrange perturb_win_avoid",
                },
            )
            progressed = True
            break
        if not progressed:
            break

    if len(out) < n_sets:
        logger.warning(
            "sumrange: only %d/%d sets (target=%s)",
            len(out),
            n_sets,
            target_draw_no,
        )

    return out[:n_sets]
