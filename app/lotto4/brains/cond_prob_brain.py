"""v13_cond_prob — 같은 회차 내 조건부확률 P(B|A), P(C|A,B) + 탐욕 순차 샘플.

1군 markov(회차 간 전이)와 달리, 동일 드로우 내 번호 공출현에 시간 감쇠 가중을 준다.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from itertools import combinations
from typing import Any, Optional

from app.lotto4.brains._utils import (
    generate_sets_with_filters,
    jaccard,
    load_draws_before,
    smart_filter_relaxed,
)

NUM_BALLS = 45
PICK = 6
DECAY_LAMBDA = 0.005
LAPLACE_SMOOTH = 0.1
TOP_PAIRS_FOR_2ND = 200
N_SETS = 5
JACCARD_LIMIT = 0.5
SUM_RANGE = (100, 175)
MAX_RETRY_GREEDY = 400
MAX_RETRY_FILL = 200
TEMPS = (0.5, 0.8, 1.0, 1.2, 1.5)


def _build_marginal_prob(draws: list[dict[str, Any]]) -> list[float]:
    count = [0.0] * (NUM_BALLS + 1)
    total_draws = len(draws)
    if total_draws == 0:
        p = 1.0 / NUM_BALLS
        return [0.0] + [p] * NUM_BALLS
    for d in draws:
        for n in d["nums"]:
            ni = int(n)
            if 1 <= ni <= NUM_BALLS:
                count[ni] += 1.0
    prob = [0.0] * (NUM_BALLS + 1)
    denom = total_draws + LAPLACE_SMOOTH * NUM_BALLS
    for i in range(1, NUM_BALLS + 1):
        prob[i] = (count[i] + LAPLACE_SMOOTH) / denom
    return prob


def _build_cond_prob_matrix(draws: list[dict[str, Any]]) -> list[list[float]]:
    if not draws:
        uniform = 1.0 / NUM_BALLS
        mat = [[0.0] * (NUM_BALLS + 1) for _ in range(NUM_BALLS + 1)]
        for a in range(1, NUM_BALLS + 1):
            for b in range(1, NUM_BALLS + 1):
                if a != b:
                    mat[a][b] = uniform
        return mat

    max_draw = int(draws[-1]["draw_no"])
    co_occur = [[0.0] * (NUM_BALLS + 1) for _ in range(NUM_BALLS + 1)]
    single_occur = [0.0] * (NUM_BALLS + 1)

    for d in draws:
        w = math.exp(-DECAY_LAMBDA * (max_draw - int(d["draw_no"])))
        nums = sorted({int(x) for x in d["nums"] if 1 <= int(x) <= NUM_BALLS})
        for n in nums:
            single_occur[n] += w
        for a, b in combinations(nums, 2):
            co_occur[a][b] += w
            co_occur[b][a] += w

    cond = [[0.0] * (NUM_BALLS + 1) for _ in range(NUM_BALLS + 1)]
    for a in range(1, NUM_BALLS + 1):
        denom = single_occur[a] + LAPLACE_SMOOTH * NUM_BALLS
        for b in range(1, NUM_BALLS + 1):
            if a == b:
                cond[a][b] = 0.0
            else:
                cond[a][b] = (co_occur[a][b] + LAPLACE_SMOOTH) / denom
    return cond


def _build_2nd_order_cond(
    draws: list[dict[str, Any]], top_pairs: int = TOP_PAIRS_FOR_2ND
) -> dict[tuple[int, int], dict[int, float]]:
    if not draws:
        return {}

    max_draw = int(draws[-1]["draw_no"])
    pair_count: dict[tuple[int, int], float] = defaultdict(float)
    triple_count: dict[tuple[int, int], dict[int, float]] = defaultdict(
        lambda: defaultdict(float)
    )

    for d in draws:
        w = math.exp(-DECAY_LAMBDA * (max_draw - int(d["draw_no"])))
        nums = sorted({int(x) for x in d["nums"] if 1 <= int(x) <= NUM_BALLS})
        for a, b in combinations(nums, 2):
            pair_key = (a, b)
            pair_count[pair_key] += w
            for c in nums:
                if c != a and c != b:
                    triple_count[pair_key][c] += w

    sorted_pairs = sorted(pair_count.items(), key=lambda x: -x[1])[:top_pairs]
    result: dict[tuple[int, int], dict[int, float]] = {}
    for (a, b), pair_w in sorted_pairs:
        denom = pair_w + LAPLACE_SMOOTH * NUM_BALLS
        c_probs: dict[int, float] = {}
        for c in range(1, NUM_BALLS + 1):
            if c == a or c == b:
                continue
            c_probs[c] = (triple_count[(a, b)].get(c, 0.0) + LAPLACE_SMOOTH) / denom
        result[(a, b)] = c_probs
    return result


def _pow_weight(p: float, temperature: float) -> float:
    t = max(temperature, 0.05)
    return max(float(p) ** (1.0 / t), 1e-15)


def _greedy_select(
    marginal: list[float],
    cond: list[list[float]],
    cond2: dict[tuple[int, int], dict[int, float]],
    existing: list[tuple[int, ...]],
    *,
    temperature: float,
    rng: random.Random,
) -> Optional[tuple[int, ...]]:
    numbers = list(range(1, NUM_BALLS + 1))

    for _ in range(MAX_RETRY_GREEDY):
        chosen: list[int] = []

        weights_1 = [_pow_weight(marginal[i], temperature) for i in numbers]
        s1 = sum(weights_1)
        if s1 <= 0:
            break
        weights_1 = [w / s1 for w in weights_1]
        first = rng.choices(numbers, weights=weights_1, k=1)[0]
        chosen.append(first)

        weights_2 = [
            0.0 if j in chosen else _pow_weight(cond[first][j], temperature)
            for j in numbers
        ]
        s2 = sum(weights_2)
        if s2 <= 0:
            continue
        weights_2 = [w / s2 for w in weights_2]
        second = rng.choices(numbers, weights=weights_2, k=1)[0]
        chosen.append(second)

        pair_key = tuple(sorted((first, second)))
        weights_3 = []
        for k in numbers:
            if k in chosen:
                weights_3.append(0.0)
            elif pair_key in cond2 and k in cond2[pair_key]:
                weights_3.append(_pow_weight(cond2[pair_key][k], temperature))
            else:
                avg_p = (cond[first][k] + cond[second][k]) / 2.0
                weights_3.append(_pow_weight(avg_p, temperature))
        s3 = sum(weights_3)
        if s3 <= 0:
            continue
        weights_3 = [w / s3 for w in weights_3]
        third = rng.choices(numbers, weights=weights_3, k=1)[0]
        chosen.append(third)

        failed_mid = False
        for __ in range(3):
            weights_n = []
            for m in numbers:
                if m in chosen:
                    weights_n.append(0.0)
                else:
                    avg_cond = sum(cond[c][m] for c in chosen) / len(chosen)
                    weights_n.append(_pow_weight(avg_cond, temperature))
            s = sum(weights_n)
            if s <= 0:
                failed_mid = True
                break
            weights_n = [w / s for w in weights_n]
            pick = rng.choices(numbers, weights=weights_n, k=1)[0]
            chosen.append(pick)
        if failed_mid or len(chosen) != PICK:
            continue

        combo = tuple(sorted(chosen))
        if len(set(combo)) != PICK:
            continue
        if not smart_filter_relaxed(list(combo)):
            continue
        st = set(combo)
        if any(jaccard(st, set(ex)) >= JACCARD_LIMIT for ex in existing):
            continue
        return combo

    return None


def predict_detailed(draw_no: int, db_path: str) -> list[dict[str, Any]]:
    """단위 테스트용: nums, brain_tag, confidence, reasoning 포함."""
    draws = load_draws_before(db_path, draw_no)
    if len(draws) < 10:
        return []

    marginal = _build_marginal_prob(draws)
    cond = _build_cond_prob_matrix(draws)
    cond2 = _build_2nd_order_cond(draws)
    rng = random.Random(draw_no * 707_011 + 4242)

    existing: list[tuple[int, ...]] = []
    results: list[dict[str, Any]] = []

    for i in range(N_SETS):
        t = TEMPS[i] if i < len(TEMPS) else 1.0
        combo = _greedy_select(
            marginal, cond, cond2, existing, temperature=t, rng=rng
        )
        if combo is None:
            break
        existing.append(combo)
        pair_scores = [cond[a][b] for a, b in combinations(combo, 2)]
        avg_pair_score = sum(pair_scores) / len(pair_scores) if pair_scores else 0.0
        results.append(
            {
                "nums": list(combo),
                "brain_tag": "v13_cond_prob",
                "brain_name": "조건부확률 네트워크",
                "confidence": round(avg_pair_score, 4),
                "reasoning": (
                    f"P(B|A)+P(C|A,B) decay={DECAY_LAMBDA} temp={t} pairs2={len(cond2)}"
                ),
            }
        )

    score_dict = {i: max(marginal[i], 1e-9) for i in range(1, NUM_BALLS + 1)}
    guard = 0
    while len(results) < N_SETS and guard < MAX_RETRY_FILL:
        guard += 1
        batch = generate_sets_with_filters(
            score_dict,
            n_sets=1,
            n_pick=PICK,
            sum_range=SUM_RANGE,
            jaccard_limit=JACCARD_LIMIT,
            max_retry=MAX_RETRY_FILL,
            rng=rng,
            smart_filter_mode="relaxed",
        )
        if not batch:
            continue
        cand = tuple(sorted(batch[0]))
        if cand in existing:
            continue
        if any(jaccard(set(cand), set(ex)) >= JACCARD_LIMIT for ex in existing):
            continue
        if not smart_filter_relaxed(list(cand)):
            continue
        existing.append(cand)
        pair_scores = [cond[a][b] for a, b in combinations(cand, 2)]
        avg_pair_score = sum(pair_scores) / len(pair_scores) if pair_scores else 0.0
        results.append(
            {
                "nums": list(cand),
                "brain_tag": "v13_cond_prob",
                "brain_name": "조건부확률 네트워크",
                "confidence": round(avg_pair_score, 4),
                "reasoning": "fallback marginal+filters",
            }
        )

    return results[:N_SETS]


def predict(draw_no: int, db_path: str) -> list[list[int]]:
    """엔진 규약."""
    return [list(x["nums"]) for x in predict_detailed(draw_no, db_path)]


def get_top_pairs(db_path: str, target_draw_no: int, top_n: int = 10) -> list[dict]:
    draws = load_draws_before(db_path, target_draw_no)
    if not draws:
        return []
    cond = _build_cond_prob_matrix(draws)
    pairs: list[dict] = []
    for a in range(1, NUM_BALLS + 1):
        for b in range(a + 1, NUM_BALLS + 1):
            pairs.append(
                {
                    "pair": (a, b),
                    "p_b_given_a": round(cond[a][b], 4),
                    "p_a_given_b": round(cond[b][a], 4),
                    "avg": round((cond[a][b] + cond[b][a]) / 2.0, 4),
                }
            )
    pairs.sort(key=lambda x: -x["avg"])
    return pairs[:top_n]
