"""Phase 2A — 베이지안 CDM 통계 뇌 (3군 predict_cdm.py 4군 독립 포팅).

R13: target_draw 미만 데이터만 사용.
"""

from __future__ import annotations

from itertools import combinations
from typing import Any

from app.lotto4.brains._utils import (
    calc_ac_value,
    count_consecutive,
    load_draws_before,
)

ALPHA_PRIOR = 1.0
RECENT_DRAWS = 100
RECENCY_TAIL = 50
RECENCY_MULTIPLIER = 2.0
POOL_TOP = 15
NUM_SETS = 5
_LAST_CUT = 1223


def _history_cut(draw_no: int) -> int:
    return min(int(draw_no), _LAST_CUT)


def _nums(draw: dict[str, Any]) -> list[int]:
    return [int(x) for x in draw.get("nums", [])]


def _accumulate_counts(draws: list[dict[str, Any]]) -> list[float]:
    """최근 RECENT_DRAWS 회차 Dirichlet count (최근 RECENCY_TAIL 2배 가중)."""
    recent = draws[-RECENT_DRAWS:] if len(draws) >= RECENT_DRAWS else draws
    counts = [0.0] * 46
    tlen = len(recent)
    for idx, d in enumerate(recent):
        nums = _nums(d)
        if len(nums) != 6:
            continue
        wt = RECENCY_MULTIPLIER if idx >= max(0, tlen - RECENCY_TAIL) else 1.0
        for n in nums:
            if 1 <= n <= 45:
                counts[n] += wt
    return counts


def _posterior_pmf(counts: list[float], alpha: float = ALPHA_PRIOR) -> dict[int, float]:
    alphas = {n: alpha + counts[n] for n in range(1, 46)}
    tot = sum(alphas.values())
    if tot <= 0:
        return {n: 1.0 / 45.0 for n in range(1, 46)}
    return {n: alphas[n] / tot for n in range(1, 46)}


def _pass_struct_filter(combo: tuple[int, ...] | list[int]) -> bool:
    nums = sorted(combo)
    if len(nums) != 6 or len(set(nums)) != 6:
        return False
    if not (100 <= sum(nums) <= 175):
        return False
    odd = sum(1 for n in nums if n % 2 == 1)
    if odd < 2 or odd > 4:
        return False
    if calc_ac_value(nums) < 7:
        return False
    if count_consecutive(nums) > 2:
        return False
    return True


class StatCDMBrain:
    """Dirichlet 사후 PMF 기반 통계 뇌."""

    def get_pmf(self, target_draw: int, db_path: str) -> dict[int, float]:
        draws = load_draws_before(db_path, _history_cut(target_draw))
        if not draws:
            return {n: 1.0 / 45.0 for n in range(1, 46)}
        counts = _accumulate_counts(draws)
        return _posterior_pmf(counts, ALPHA_PRIOR)

    def predict(self, target_draw: int, db_path: str, n_sets: int = NUM_SETS) -> list[list[int]]:
        pmf = self.get_pmf(target_draw, db_path)
        ranked = sorted(pmf.items(), key=lambda x: (-x[1], x[0]))
        pool = [n for n, _ in ranked[:POOL_TOP]]
        if len(pool) < 6:
            return []

        scored: list[tuple[tuple[int, ...], float]] = []
        for combo in combinations(pool, 6):
            cand = tuple(sorted(combo))
            if not _pass_struct_filter(cand):
                continue
            score = sum(pmf.get(n, 0.0) for n in cand)
            scored.append((cand, score))
        scored.sort(key=lambda x: (-x[1], x[0]))

        out: list[list[int]] = []
        seen: set[tuple[int, ...]] = set()
        for cand, _ in scored:
            if cand in seen:
                continue
            seen.add(cand)
            out.append(list(cand))
            if len(out) >= n_sets:
                break
        return out[:n_sets]
