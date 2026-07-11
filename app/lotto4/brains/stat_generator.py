"""통계 기반 후보 생성기 — B안 ML 필터 파이프라인 1단계.

최근 100회 빈도 풀 + 1~3군 동일 스마트 필터로 최대 n_candidates 세트 생성.
R13: draw_no < target_draw 데이터만 사용.
"""

from __future__ import annotations

import random
from collections import Counter
from itertools import combinations
from typing import Any, Set

from app.lotto4.brains._utils import (
    calc_ac_value,
    count_consecutive,
    load_draws_before,
)

_LAST_CUT = 1223
SUM_RANGE = (100, 175)
POOL_SIZES = (25, 30)
RNG_SEED_MUL = 20260519


def _history_cut(draw_no: int) -> int:
    return min(int(draw_no), _LAST_CUT)


def _nums(draw: dict[str, Any]) -> list[int]:
    return [int(x) for x in draw["nums"]]


def _freq_pool(draws: list[dict[str, Any]], top_n: int) -> list[int]:
    """최근 100회 빈도 상위 top_n 번호 풀."""
    recent = draws[-100:] if len(draws) >= 100 else draws
    freq: Counter[int] = Counter()
    for d in recent:
        for n in _nums(d):
            if 1 <= n <= 45:
                freq[n] += 1
    ranked = sorted(freq.keys(), key=lambda n: (-freq[n], n))
    for n in range(1, 46):
        if n not in ranked:
            ranked.append(n)
        if len(ranked) >= top_n:
            break
    return ranked[:top_n]


def _tail_max_dup(nums: list[int]) -> int:
    tails = [n % 10 for n in nums]
    return max(Counter(tails).values()) if tails else 0


def _passes_filters(combo: tuple[int, ...] | list[int]) -> bool:
    s = sorted(combo)
    if len(s) != 6 or len(set(s)) != 6:
        return False
    total = sum(s)
    if not (SUM_RANGE[0] <= total <= SUM_RANGE[1]):
        return False
    odd = sum(1 for n in s if n % 2 == 1)
    if not (2 <= odd <= 4):
        return False
    high = sum(1 for n in s if n >= 23)
    if not (2 <= high <= 4):
        return False
    if count_consecutive(s) > 2:
        return False
    if calc_ac_value(s) < 7:
        return False
    if _tail_max_dup(s) > 2:
        return False
    return True


def _collect_from_pool(
    pool: list[int],
    rng: random.Random,
    n_candidates: int,
) -> list[Set[int]]:
    all_combos = list(combinations(pool, 6))
    rng.shuffle(all_combos)
    out: list[Set[int]] = []
    seen: set[frozenset[int]] = set()
    for combo in all_combos:
        if not _passes_filters(combo):
            continue
        key = frozenset(combo)
        if key in seen:
            continue
        seen.add(key)
        out.append(set(combo))
        if len(out) >= n_candidates:
            break
    return out


def get_pmf(target_draw: int, db_path: str) -> dict[int, float]:
    """최근 100회 빈도 기반 45차원 PMF (Fusion 입력용)."""
    cut = _history_cut(target_draw)
    draws = load_draws_before(db_path, cut)
    recent = draws[-100:] if len(draws) >= 100 else draws
    freq: Counter[int] = Counter()
    for d in recent:
        for n in _nums(d):
            if 1 <= n <= 45:
                freq[n] += 1
    raw = {n: float(freq.get(n, 0)) for n in range(1, 46)}
    total = sum(raw.values())
    if total <= 0:
        return {n: 1.0 / 45.0 for n in range(1, 46)}
    return {n: raw[n] / total for n in range(1, 46)}


def generate_candidates(
    target_draw: int,
    db: str,
    n_candidates: int = 200,
) -> list[Set[int]]:
    """통계 필터 통과 조합 최대 n_candidates세트 (결정론적 RNG)."""
    cut = _history_cut(target_draw)
    draws = load_draws_before(db, cut)
    rng = random.Random(int(target_draw) * RNG_SEED_MUL)

    for pool_size in POOL_SIZES:
        pool = _freq_pool(draws, pool_size)
        if len(pool) < 6:
            continue
        found = _collect_from_pool(pool, rng, n_candidates)
        if len(found) >= n_candidates or pool_size == POOL_SIZES[-1]:
            return found[:n_candidates]

    return []
