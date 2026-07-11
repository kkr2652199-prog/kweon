"""4군 sumrange 뇌 — 3군 predict_sumrange.py 독립 이식.

최근 100회 합계 p15~p85 범위 + 빈도 PMF 가중 샘플.
R13: draw_no < target_draw 데이터만 사용.
"""

from __future__ import annotations

import random
from typing import Any

import numpy as np

from app.lotto4.brains._utils import jaccard, load_draws_before

LOOKBACK = 100
NUM_SETS = 5
RNG_MUL = 31
SUM_FALLBACK = (100, 175)
WIN_AVOID_N = 3
WIN_AVOID_THRESH = 0.4


def _tier1_filter(nums: list[int]) -> bool:
    s = sorted(nums)
    if len(s) != 6 or len(set(s)) != 6:
        return False
    total = sum(s)
    if total < 80 or total > 210:
        return False
    odd = sum(1 for n in s if n % 2 == 1)
    if odd < 1 or odd > 5:
        return False
    if len({(n - 1) // 10 for n in s}) < 2:
        return False
    run = consec = 1
    for i in range(1, 6):
        if s[i] == s[i - 1] + 1:
            consec += 1
            run = max(run, consec)
        else:
            consec = 1
    return run < 4


def _recent_draws(target_draw: int, db_path: str) -> list[dict[str, Any]]:
    draws = load_draws_before(db_path, target_draw)
    return draws[-LOOKBACK:] if len(draws) > LOOKBACK else draws


def _sum_range(draws: list[dict[str, Any]]) -> tuple[int, int]:
    sums = [sum(d["nums"]) for d in draws if d.get("nums") and len(d["nums"]) == 6]
    if not sums:
        return SUM_FALLBACK
    arr = np.array(sums, dtype=np.float64)
    lo = int(round(float(np.percentile(arr, 15))))
    hi = int(round(float(np.percentile(arr, 85))))
    lo = max(21, min(lo, 235))
    hi = min(255, max(hi, lo + 10))
    return lo, hi


def _get_recent_wins(target_draw: int, db_path: str) -> list[set[int]]:
    draws = load_draws_before(db_path, target_draw)
    wins: list[set[int]] = []
    for d in reversed(draws):
        nums = d.get("nums")
        if nums and len(nums) == 6:
            wins.append(set(int(x) for x in nums))
        if len(wins) >= WIN_AVOID_N:
            break
    return wins


def _pass_win_avoid(combo: list[int], wins: list[set[int]]) -> bool:
    st = set(combo)
    for w in wins:
        if jaccard(st, w) >= WIN_AVOID_THRESH:
            return False
    return True


class SumrangeBrain:
    """번호합 p15~p85 범위 기반 조합 생성."""

    def get_pmf(self, target_draw: int, db_path: str) -> dict[int, float]:
        """합계 범위 내 회차에서만 집계한 빈도 PMF (stat과 차별화)."""
        draws = _recent_draws(target_draw, db_path)
        if not draws:
            return {n: 1.0 / 45.0 for n in range(1, 46)}
        s_lo, s_hi = _sum_range(draws)
        freq = {n: 0.0 for n in range(1, 46)}
        for d in draws:
            nums = d.get("nums") or []
            if len(nums) != 6:
                continue
            sm = sum(int(x) for x in nums)
            if sm < s_lo or sm > s_hi:
                continue
            for n in nums:
                ni = int(n)
                if 1 <= ni <= 45:
                    freq[ni] += 1.0
        tot = sum(freq.values())
        if tot <= 0:
            base = {n: 0.0 for n in range(1, 46)}
            for d in draws:
                for n in d.get("nums") or []:
                    ni = int(n)
                    if 1 <= ni <= 45:
                        base[ni] += 1.0
            tot2 = sum(base.values())
            if tot2 <= 0:
                return {n: 1.0 / 45.0 for n in range(1, 46)}
            return {n: base[n] / tot2 for n in range(1, 46)}
        return {n: freq[n] / tot for n in range(1, 46)}

    def predict(
        self, target_draw: int, db_path: str, n_sets: int = NUM_SETS
    ) -> list[list[int]]:
        draws = _recent_draws(target_draw, db_path)
        if not draws:
            return []
        s_lo, s_hi = _sum_range(draws)
        pmf = self.get_pmf(target_draw, db_path)
        nums = list(range(1, 46))
        weights = [max(pmf[n], 1e-9) for n in nums]
        rng = random.Random(int(target_draw) * RNG_MUL)
        wins = _get_recent_wins(target_draw, db_path)
        out: list[list[int]] = []
        used: set[tuple[int, ...]] = set()
        guard = 0
        while len(out) < n_sets and guard < 8000:
            guard += 1
            cand = sorted(rng.choices(nums, weights=weights, k=6))
            if len(set(cand)) != 6:
                continue
            sm = sum(cand)
            if sm < s_lo or sm > s_hi:
                continue
            if not _tier1_filter(cand):
                continue
            if not _pass_win_avoid(cand, wins):
                continue
            t = tuple(cand)
            if t in used:
                continue
            used.add(t)
            out.append(cand)
        return out[:n_sets]


def predict(draw_no: int, db_path: str) -> list[list[int]]:
    return SumrangeBrain().predict(draw_no, db_path, NUM_SETS)
