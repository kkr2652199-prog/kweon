"""v13_anti_popular — 단독수령 최적화 뇌 (anti-popular 조합 선호)."""

from __future__ import annotations

import random

from app.lotto4.brains._utils import (
    generate_sets_with_filters,
    jaccard,
    load_draws_before,
)

NUM_SETS = 5
MAX_RETRIES = 200
JACCARD_LIMIT = 0.5
SUM_RANGE = (100, 175)
MAX_RETRY_GEN = 120
POP_THRESHOLD = 4.0

POPULAR_NUMBERS = {
    1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17, 21, 22, 24, 25, 31, 33,
}
UNPOPULAR_BONUS = {32, 34, 35, 36, 38, 39, 40, 42, 43, 44, 45}


def _popularity_score(nums: list[int]) -> float:
    score = 0.0
    for n in nums:
        if n in POPULAR_NUMBERS:
            score += 2.0
        elif n in UNPOPULAR_BONUS:
            score -= 1.0
        if n <= 31:
            score += 0.5
        if n % 7 == 0:
            score += 0.3
    return score


def predict(draw_no: int, db_path: str) -> list[list[int]]:
    draws = load_draws_before(db_path, draw_no)
    if not draws or len(draws) < 30:
        rng = random.Random(draw_no * 501_013 + 41)
        out: list[list[int]] = []
        seen: set[tuple[int, ...]] = set()
        guard = 0
        while len(out) < NUM_SETS and guard < 8000:
            guard += 1
            batch = generate_sets_with_filters(
                {i: 1.0 for i in range(1, 46)},
                n_sets=1,
                n_pick=6,
                sum_range=SUM_RANGE,
                jaccard_limit=JACCARD_LIMIT,
                max_retry=80,
                rng=rng,
                odd_range=(2, 4),
            )
            if not batch:
                continue
            cand = list(batch[0])
            if _popularity_score(cand) >= POP_THRESHOLD:
                continue
            t = tuple(cand)
            if t in seen:
                continue
            if any(jaccard(set(cand), set(x)) >= JACCARD_LIMIT for x in out):
                continue
            seen.add(t)
            out.append(cand)
        while len(out) < NUM_SETS:
            batch = generate_sets_with_filters(
                {i: 1.0 for i in range(1, 46)},
                n_sets=1,
                n_pick=6,
                sum_range=SUM_RANGE,
                jaccard_limit=JACCARD_LIMIT,
                max_retry=200,
                rng=rng,
                odd_range=(2, 4),
            )
            if not batch:
                break
            cand = list(batch[0])
            t = tuple(cand)
            if t in seen:
                continue
            seen.add(t)
            out.append(cand)
        return [sorted(list(x)) for x in out[:NUM_SETS]]

    recent = draws[-20:]
    freq: dict[int, int] = {i: 0 for i in range(1, 46)}
    for d in recent:
        for n in d["nums"]:
            ni = int(n)
            if 1 <= ni <= 45:
                freq[ni] = freq.get(ni, 0) + 1

    denom = max(len(recent), 1)
    score_dict: dict[int, float] = {}
    for n in range(1, 46):
        base = freq.get(n, 0) / denom
        pop_penalty = 0.0
        if n in POPULAR_NUMBERS:
            pop_penalty = -0.15
        elif n in UNPOPULAR_BONUS:
            pop_penalty = 0.10
        if n <= 31:
            pop_penalty -= 0.05
        score_dict[n] = max(0.01, base + 0.5 + pop_penalty)

    rng = random.Random(draw_no * 501_013 + 41)
    results: list[list[int]] = []
    seen: set[tuple[int, ...]] = set()
    attempts = 0
    while len(results) < NUM_SETS and attempts < MAX_RETRIES:
        attempts += 1
        batch = generate_sets_with_filters(
            score_dict,
            n_sets=1,
            n_pick=6,
            sum_range=SUM_RANGE,
            jaccard_limit=JACCARD_LIMIT,
            max_retry=MAX_RETRY_GEN,
            rng=rng,
            odd_range=(2, 4),
        )
        if not batch:
            continue
        c = list(batch[0])
        if _popularity_score(c) >= POP_THRESHOLD:
            continue
        t = tuple(c)
        if t in seen:
            continue
        if any(jaccard(set(c), set(r)) >= JACCARD_LIMIT for r in results):
            continue
        seen.add(t)
        results.append(c)

    guard = 0
    while len(results) < NUM_SETS and guard < 5000:
        guard += 1
        batch = generate_sets_with_filters(
            score_dict,
            n_sets=1,
            n_pick=6,
            sum_range=SUM_RANGE,
            jaccard_limit=JACCARD_LIMIT,
            max_retry=MAX_RETRY_GEN,
            rng=rng,
            odd_range=(2, 4),
        )
        if not batch:
            continue
        fb = list(batch[0])
        if _popularity_score(fb) >= POP_THRESHOLD + 1.0:
            continue
        t = tuple(fb)
        if t in seen:
            continue
        if any(jaccard(set(fb), set(r)) >= JACCARD_LIMIT for r in results):
            continue
        seen.add(t)
        results.append(fb)

    while len(results) < NUM_SETS:
        batch = generate_sets_with_filters(
            {i: 1.0 for i in range(1, 46)},
            n_sets=1,
            n_pick=6,
            sum_range=SUM_RANGE,
            jaccard_limit=JACCARD_LIMIT,
            max_retry=250,
            rng=rng,
            odd_range=(2, 4),
        )
        if not batch:
            break
        s = list(batch[0])
        t = tuple(s)
        if t in seen:
            continue
        seen.add(t)
        results.append(s)

    return [sorted(list(x)) for x in results[:NUM_SETS]]
