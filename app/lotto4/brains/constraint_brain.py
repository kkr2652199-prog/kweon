"""4군 constraint 뇌 — 3군 predict_constraint.py 독립 이식.

sum/odd/high/연번 CSP 제약 + PMF 가중 샘플.
R13: draw_no < target_draw 데이터만 사용.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from typing import Any

from app.lotto4.brains._utils import jaccard, load_draws_before

LOOKBACK = 100
NUM_SETS = 5
RNG_MUL = 37
WIN_AVOID_N = 3
WIN_AVOID_THRESH = 0.4
LOW_BOUNDARY = 22


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


def _adj_consec_pairs(nums: list[int]) -> int:
    c = 0
    for i in range(5):
        if nums[i + 1] == nums[i] + 1:
            c += 1
    return c


def _struct_modes(draws: list[dict[str, Any]]) -> tuple[tuple[float, float], int, int, int]:
    """sum bounds (p15,p85), mode odd, mode low, mode consec pairs."""
    sums: list[float] = []
    odds: list[int] = []
    lows: list[int] = []
    consecs: list[int] = []
    for d in draws:
        nums = sorted(int(x) for x in (d.get("nums") or []))
        if len(nums) != 6:
            continue
        sums.append(float(sum(nums)))
        odds.append(sum(1 for n in nums if n % 2 == 1))
        lows.append(sum(1 for n in nums if n <= LOW_BOUNDARY))
        consecs.append(_adj_consec_pairs(nums))
    if len(sums) < 5:
        return (100.0, 170.0), 3, 3, 1
    sums.sort()
    lo = _percentile(sums, 15)
    hi = _percentile(sums, 85)
    if hi <= lo:
        hi = lo + 30.0
    return (lo, hi), Counter(odds).most_common(1)[0][0], Counter(lows).most_common(1)[0][0], Counter(consecs).most_common(1)[0][0]


def _percentile(sorted_vals: list[float], p: float) -> float:
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    idx = (n - 1) * (p / 100.0)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (idx - lo)


def _constraints_ok(
    nums: list[int],
    sum_lo: float,
    sum_hi: float,
    odd_tgt: int,
    low_tgt: int,
    consec_tgt: int,
) -> bool:
    sm = sum(nums)
    if sm < sum_lo or sm > sum_hi:
        return False
    odd_c = sum(1 for x in nums if x % 2 == 1)
    if abs(odd_c - odd_tgt) > 1:
        return False
    low_c = sum(1 for x in nums if x <= LOW_BOUNDARY)
    if abs(low_c - low_tgt) > 1:
        return False
    if abs(_adj_consec_pairs(nums) - consec_tgt) > 1:
        return False
    return True


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


class ConstraintBrain:
    """구조 변수 최빈값 CSP 샘플링."""

    def get_pmf(self, target_draw: int, db_path: str) -> dict[int, float]:
        """구조 조건(odd/low) 일치 회차에서만 번호 빈도."""
        draws = _recent_draws(target_draw, db_path)
        if not draws:
            return {n: 1.0 / 45.0 for n in range(1, 46)}
        _, odd_tgt, low_tgt, _ = _struct_modes(draws)
        freq = {n: 0.0 for n in range(1, 46)}
        for d in draws:
            nums = sorted(int(x) for x in (d.get("nums") or []))
            if len(nums) != 6:
                continue
            odd_c = sum(1 for n in nums if n % 2 == 1)
            low_c = sum(1 for n in nums if n <= LOW_BOUNDARY)
            if abs(odd_c - odd_tgt) > 1 or abs(low_c - low_tgt) > 1:
                continue
            for n in nums:
                if 1 <= n <= 45:
                    freq[n] += 1.0
        tot = sum(freq.values())
        if tot <= 0:
            cnt = {n: 0.0 for n in range(1, 46)}
            for d in draws:
                for n in d.get("nums") or []:
                    ni = int(n)
                    if 1 <= ni <= 45:
                        cnt[ni] += 1.0
            t2 = sum(cnt.values())
            if t2 <= 0:
                return {n: 1.0 / 45.0 for n in range(1, 46)}
            return {n: cnt[n] / t2 for n in range(1, 46)}
        return {n: freq[n] / tot for n in range(1, 46)}

    def predict(
        self, target_draw: int, db_path: str, n_sets: int = NUM_SETS
    ) -> list[list[int]]:
        draws = _recent_draws(target_draw, db_path)
        if not draws:
            return []
        (sum_lo, sum_hi), odd_tgt, low_tgt, consec_tgt = _struct_modes(draws)
        pmf = self.get_pmf(target_draw, db_path)
        pool = list(range(1, 46))
        rng = random.Random(int(target_draw) * RNG_MUL)
        wins = _get_recent_wins(target_draw, db_path)
        out: list[list[int]] = []
        used: set[tuple[int, ...]] = set()
        guard = 0
        while len(out) < n_sets and guard < 12000:
            guard += 1
            wts = [max(pmf[n], 1e-15) for n in pool]
            picked: list[int] = []
            pp = pool.copy()
            pw = wts.copy()
            for _ in range(6):
                s = sum(pw)
                if s <= 0:
                    break
                r = rng.random() * s
                acc = 0.0
                for j, w in enumerate(pw):
                    acc += w
                    if r <= acc:
                        picked.append(pp[j])
                        pp.pop(j)
                        pw.pop(j)
                        break
            if len(picked) != 6:
                continue
            cand = sorted(picked)
            if not _constraints_ok(cand, sum_lo, sum_hi, odd_tgt, low_tgt, consec_tgt):
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
    return ConstraintBrain().predict(draw_no, db_path, NUM_SETS)
