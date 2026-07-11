"""v13_ev — 배당 기대(비인기) 기대값 뇌 (5단계-B)."""

from __future__ import annotations

import random
from typing import Any

from app.lotto4.brains._utils import (
    count_consecutive,
    jaccard,
    load_draws_before,
    smart_filter_relaxed,
    sum_filter,
    odd_even_filter,
    _weighted_draw_without_replacement,
)

_LAST_CUT = 1223
NUM_SETS = 5
JACCARD_LIMIT = 0.5
SUM_RANGE = (100, 175)


def _history_cut(draw_no: int) -> int:
    return min(int(draw_no), _LAST_CUT)


def _nums(draw: dict[str, Any]) -> list[int]:
    return [int(x) for x in draw["nums"]]


def birthday_factor(n: int) -> float:
    return 1.3 if n <= 31 else 0.7


def popularity_score(
    s: list[int],
    draw_no: int,
    db_path: str,
) -> float:
    """세트 단위 인기도(높을수록 많은 사람이 고를 추정). 곱 모델."""
    st = sorted({int(x) for x in s if 1 <= int(x) <= 45})
    if len(st) != 6:
        return 1.0
    draws = load_draws_before(db_path, _history_cut(draw_no))
    last_n: set[int] = set()
    prev_n: set[int] = set()
    if draws:
        last_n = set(_nums(draws[-1]))
    if len(draws) >= 3:
        for d in draws[-3:-1]:
            prev_n.update(_nums(d))

    pop = 1.0
    for n in st:
        pop *= birthday_factor(n)
        if n % 7 == 0:
            pop *= 1.4
        if n in last_n:
            pop *= 1.5
        elif n in prev_n:
            pop *= 1.2

    c = count_consecutive(st)
    if c >= 3:
        pop *= 1.5
    elif c >= 2:
        pop *= 1.2

    odds = sum(1 for n in st if n % 2 == 1)
    if odds == 6 or odds == 0:
        pop *= 1.3

    return max(pop, 1e-9)


def ev_score_for_set(s: list[int], draw_no: int, db_path: str) -> float:
    p = popularity_score(s, draw_no, db_path)
    return 1.0 / p


def _minmax_normalize(raw: list[float]) -> list[float]:
    if not raw:
        return []
    lo, hi = min(raw), max(raw)
    if hi - lo < 1e-9:
        return [0.5] * len(raw)
    return [(r - lo) / (hi - lo) for r in raw]


def score_combo(combo: set, target_draw: int, db) -> float:
    """기대값 점수 (0~1 정규화)."""
    st = sorted({int(x) for x in combo if 1 <= int(x) <= 45})
    if len(st) != 6:
        return 0.0
    raw = ev_score_for_set(st, target_draw, db)
    return min(1.0, max(0.0, raw / 5.0))


def score_batch(combos: list, target_draw: int, db) -> list[float]:
    """배치 기대값 점수 (min-max 0~1)."""
    raw: list[float] = []
    for combo in combos:
        st = sorted({int(x) for x in combo if 1 <= int(x) <= 45})
        if len(st) != 6:
            raw.append(0.0)
        else:
            raw.append(ev_score_for_set(st, target_draw, db))
    return _minmax_normalize(raw)


def rescore(
    candidate_sets: list[list[int]],
    draw_no: int,
    db_path: str,
) -> list[tuple[list[int], float]]:
    out: list[tuple[list[int], float]] = []
    for raw in candidate_sets:
        st = sorted({int(x) for x in raw if 1 <= int(x) <= 45})
        if len(st) != 6:
            continue
        sc = ev_score_for_set(list(st), draw_no, db_path)
        out.append((list(st), sc))
    out.sort(key=lambda x: -x[1])
    return out


def _sample_weights(draw_no: int, db_path: str) -> dict[int, float]:
    draws = load_draws_before(db_path, _history_cut(draw_no))
    last_n: set[int] = set()
    prev_n: set[int] = set()
    if draws:
        last_n = set(_nums(draws[-1]))
    if len(draws) >= 3:
        for d in draws[-3:-1]:
            prev_n.update(_nums(d))

    w: dict[int, float] = {}
    for n in range(1, 46):
        if n <= 31:
            wt = 0.35
        else:
            wt = 2.4
        if n % 7 == 0:
            wt /= 1.55
        if n in last_n:
            wt /= 1.9
        elif n in prev_n:
            wt /= 1.35
        w[n] = max(wt, 0.08)
    return w


def _geo_mean_birthday(s: list[int]) -> float:
    st = sorted(s)
    pr = 1.0
    for n in st:
        pr *= birthday_factor(n)
    return pr ** (1.0 / 6.0)


def predict(draw_no: int, db_path: str) -> list[list[int]]:
    base_w = _sample_weights(draw_no, db_path)
    rng = random.Random(draw_no * 307_211 + 19_031)
    sets: list[list[int]] = []

    for _ in range(6000):
        if len(sets) >= NUM_SETS:
            break
        cand = _weighted_draw_without_replacement(rng, base_w, 6)
        if len(cand) != 6:
            continue
        cand = sorted(cand)
        if count_consecutive(cand) > 1:
            continue
        if sum(1 for x in cand if x >= 32) < 4:
            continue
        if not sum_filter(cand, SUM_RANGE[0], SUM_RANGE[1]):
            continue
        if not odd_even_filter(cand):
            continue
        if not smart_filter_relaxed(cand):
            continue
        st = set(cand)
        if any(jaccard(st, set(p)) >= JACCARD_LIMIT for p in sets):
            continue
        sets.append(cand)

    while len(sets) < NUM_SETS:
        cand = sorted(rng.sample(range(32, 46), min(6, 15)))
        if len(cand) < 6:
            cand = sorted(rng.sample(range(1, 46), 6))
        if smart_filter_relaxed(cand) and count_consecutive(cand) <= 1:
            if not any(jaccard(set(cand), set(p)) >= JACCARD_LIMIT for p in sets):
                sets.append(cand)
        if rng.random() > 0.999:
            break
    while len(sets) < NUM_SETS:
        sets.append(sorted(rng.sample(range(1, 46), 6)))

    return sets[:NUM_SETS]


def mean_popularity_geo(sessions: list[list[int]], draw_no: int, db_path: str) -> float:
    """진단용: 생일 요소 기하평균의 세트 평균."""
    if not sessions:
        return 1.0
    vals = [_geo_mean_birthday(s) for s in sessions]
    return float(sum(vals) / len(vals))
