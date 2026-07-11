"""v13_coordinator — 전략 X 4뇌 조율뇌 (1~3뇌 신호 종합).

신호 강도 근거(정찰·측정 결과):
  - 2뇌 pair CV=0.49 → 최강 → 가중치 0.5
  - 1뇌 number |r|=0.017 → 약함 → 가중치 0.3
  - 3뇌 shape 약함(필터) → shape_pass 0.2

combined_score = 0.5*pair_score + 0.3*popularity_score + 0.2*shape_pass
R2: 미래 예측·당첨 확률 향상 주장 금지.
"""

from __future__ import annotations

import random
from typing import Any

from app.lotto4.brains._utils import _weighted_draw_without_replacement, jaccard
from app.lotto4.brains.popularity_freq_brain import (
    avg_popularity_score,
    load_popularity_weights,
)
from app.lotto4.brains.popularity_pair_brain import (
    _pair_key,
    avg_pair_score,
    load_pair_weights,
)
from app.lotto4.brains.shape_brain import (
    _matches_shape,
    extract_shape_metrics,
    load_shape_profile,
)

NUM_SETS = 5
DISCLAIMER = (
    "1~3 신호(인기번호·인기쌍·형태)를 종합한 조합입니다. "
    "당첨 확률은 모든 조합이 동일하며 미래를 예측하지 않습니다."
)
BRAIN_TAG = "v13_coordinator"
RNG_SEED_MUL = 20260620

# 신호 강도 반영 가중치 (보고서·정찰 근거)
W_PAIR = 0.5       # 2뇌 CV=0.49 최강
W_POPULARITY = 0.3  # 1뇌 |r|=0.017 약함
W_SHAPE = 0.2       # 3뇌 필터 통과 시 1.0, 미통과 0.0

TOP_PAIRS_CHECK = [
    (6, 12), (7, 12), (27, 38), (7, 19), (13, 45),
]


def _first_number_pick(
    rng: random.Random,
    number_weights: dict[int, float],
    picked: list[int],
) -> int | None:
    """1뇌: 시작 번호만 number_popularity 가중 추출."""
    available = [n for n in range(1, 46) if n not in picked]
    if not available:
        return None
    weights = {n: max(number_weights.get(n, 0.01), 0.001) for n in available}
    one = _weighted_draw_without_replacement(rng, weights, 1)
    return one[0] if one else None


def _pair_chain_pick(
    rng: random.Random,
    picked: list[int],
    number_weights: dict[int, float],
    pair_weights: dict[tuple[int, int], float],
) -> int | None:
    """2뇌: 직전 번호들과의 pair_popularity 체인 가중 추출."""
    available = [n for n in range(1, 46) if n not in picked]
    if not available:
        return None
    weights: dict[int, float] = {}
    for c in available:
        w = sum(pair_weights.get(_pair_key(c, p), 0.001) for p in picked)
        if w <= 0:
            w = number_weights.get(c, 0.01)
        weights[c] = max(float(w), 0.001)
    one = _weighted_draw_without_replacement(rng, weights, 1)
    return one[0] if one else None


def calc_combined_score(
    nums: list[int],
    number_weights: dict[int, float],
    pair_weights: dict[tuple[int, int], float],
    shape_profile: dict[str, Any],
) -> dict[str, Any]:
    pop_score = avg_popularity_score(nums, number_weights)
    pair_score = avg_pair_score(nums, pair_weights)
    metrics = extract_shape_metrics(nums)
    shape_pass = 1.0 if _matches_shape(metrics, shape_profile) else 0.0
    combined = round(
        W_PAIR * pair_score + W_POPULARITY * pop_score + W_SHAPE * shape_pass,
        4,
    )
    return {
        "popularity_score": pop_score,
        "pair_score": pair_score,
        "shape_pass": shape_pass,
        "combined_score": combined,
        "shape_metrics": metrics,
    }


def _count_top_pairs_in_set(nums: list[int]) -> list[str]:
    s = set(nums)
    found: list[str] = []
    for a, b in TOP_PAIRS_CHECK:
        if a in s and b in s:
            found.append(f"{a}-{b}")
    return found


def _draw_coordinator_set(
    rng: random.Random,
    number_weights: dict[int, float],
    pair_weights: dict[tuple[int, int], float],
    shape_profile: dict[str, Any],
    existing: list[list[int]],
    jaccard_limit: float = 0.5,
) -> list[int] | None:
    for _ in range(300):
        picked: list[int] = []
        n1 = _first_number_pick(rng, number_weights, picked)
        if n1 is None:
            continue
        picked.append(n1)
        ok = True
        for _step in range(5):
            n = _pair_chain_pick(rng, picked, number_weights, pair_weights)
            if n is None:
                ok = False
                break
            picked.append(n)
        if not ok or len(picked) != 6:
            continue
        nums = sorted(picked)
        metrics = extract_shape_metrics(nums)
        if not _matches_shape(metrics, shape_profile):
            continue
        st = set(nums)
        if any(jaccard(st, set(prev)) >= jaccard_limit for prev in existing):
            continue
        return nums
    return None


def generate_recommend_sets(
    target_draw_no: int,
    n_sets: int = NUM_SETS,
) -> dict[str, Any]:
    """3뇌 신호 종합 최종 5세트 생성."""
    number_weights = load_popularity_weights()
    pair_weights = load_pair_weights()
    shape_profile = load_shape_profile()
    sets: list[dict[str, Any]] = []
    existing: list[list[int]] = []

    for set_no in range(1, n_sets + 1):
        seed = int(target_draw_no) * RNG_SEED_MUL + set_no * 211
        rng = random.Random(seed)
        nums = _draw_coordinator_set(
            rng, number_weights, pair_weights, shape_profile, existing
        )
        if nums is None:
            continue
        existing.append(nums)
        scores = calc_combined_score(
            nums, number_weights, pair_weights, shape_profile
        )
        sets.append(
            {
                "set_no": set_no,
                "numbers": nums,
                "combined_score": scores["combined_score"],
                "brain_contributions": {
                    "v13_popularity_freq": scores["popularity_score"],
                    "v13_popularity_pair": scores["pair_score"],
                    "v13_shape": scores["shape_pass"],
                },
                "shape_metrics": scores["shape_metrics"],
                "top_pairs_present": _count_top_pairs_in_set(nums),
            }
        )

    return {
        "target_draw_no": int(target_draw_no),
        "brain": BRAIN_TAG,
        "disclaimer": DISCLAIMER,
        "score_weights": {
            "pair": W_PAIR,
            "popularity": W_POPULARITY,
            "shape_pass": W_SHAPE,
            "rationale": "2뇌 CV=0.49 최강, 1뇌 |r|=0.017 약, 3뇌 필터",
        },
        "source_tables": [
            "number_popularity",
            "pair_popularity",
            "shape_profile",
        ],
        "sets": sets,
    }


def generate(target_draw_no: int) -> dict[str, Any]:
    """API·테스트용 진입점."""
    return generate_recommend_sets(target_draw_no)
