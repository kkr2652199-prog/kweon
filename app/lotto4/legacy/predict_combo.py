"""V9 2군 combo: 조합 패턴 학습(LLM 자리, 미당첨 회차 조합 특성)."""
import logging
import random
from itertools import combinations

from app.lotto.filters import tier1_filter

logger = logging.getLogger(__name__)


def _analyze_combo_patterns(miss_draws: list[dict]) -> dict:
    """미당첨 회차 당첨번호의 조합 패턴 추출."""
    if not miss_draws:
        return {"pair_scores": {}, "consec_target": 0.5, "sum_target": 138}

    pair_count: dict[tuple[int, int], int] = {}
    sum_list: list[int] = []
    consec_list: list[int] = []

    for d in miss_draws:
        nums = sorted(
            [d["num1"], d["num2"], d["num3"], d["num4"], d["num5"], d["num6"]]
        )
        sum_list.append(sum(nums))
        consec = sum(1 for i in range(5) if nums[i + 1] - nums[i] == 1)
        consec_list.append(consec)
        for pair in combinations(nums, 2):
            pair_count[pair] = pair_count.get(pair, 0) + 1

    n = len(miss_draws)
    return {
        "pair_scores": {k: v / n for k, v in pair_count.items()},
        "consec_target": sum(consec_list) / n,
        "sum_target": sum(sum_list) / n,
        "count": n,
    }


def army4_combo_predict(miss_draws: list[dict], n_sets: int = 5) -> list[dict]:
    """미당첨 조합 패턴 기반 세트 생성."""
    patterns = _analyze_combo_patterns(miss_draws)
    pair_scores = patterns["pair_scores"]
    sum_target = patterns["sum_target"]

    sets: list[dict] = []
    attempts = 0
    while len(sets) < n_sets and attempts < 200:
        attempts += 1
        cand = sorted(random.sample(range(1, 46), 6))
        if abs(sum(cand) - sum_target) > 25:
            continue
        try:
            if not tier1_filter(cand):
                continue
        except (TypeError, ValueError) as e:
            logger.debug("역전조합 tier1_filter 스킵: %s", e)
            continue
        score = sum(pair_scores.get(p, 0) for p in combinations(cand, 2))
        sets.append(
            {
                "nums": cand,
                "confidence": min(0.6, 0.3 + score),
                "reasoning": (
                    f"역전조합 sum={sum(cand)} target≈{sum_target:.0f} score={score:.2f}"
                ),
                "brain_tag": "army4_combo",
                "method": "역전조합두뇌",
                "source": "army4_combo",
            }
        )
    return sets


def army4_combo_prob_vector(miss_draws: list[dict]) -> dict[int, float]:
    """조합 패턴 기반 PMF."""
    patterns = _analyze_combo_patterns(miss_draws)
    pair_scores = patterns.get("pair_scores", {})

    num_score = {n: 0.0 for n in range(1, 46)}
    for (a, b), s in pair_scores.items():
        num_score[a] += s
        num_score[b] += s

    total = sum(num_score.values()) or 1.0
    return {n: v / total for n, v in num_score.items()}
