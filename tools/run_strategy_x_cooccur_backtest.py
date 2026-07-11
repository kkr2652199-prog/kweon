"""전략 X 5뇌 cooccur 단독 walk-forward 백테스트 (era_C, R13)."""

from __future__ import annotations

import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.lotto4.brains.cooccur_brain_v13 import (
    CooccurState,
    generate_cooccur_sets,
)
from app.lotto4.brains.coordinator_brain import (
    NUM_SETS,
    RNG_SEED_MUL,
    _draw_coordinator_set,
)
from app.lotto4.brains.shape_brain import _segment_summary, extract_shape_metrics
from app.lotto4.brains._utils import jaccard

DB = Path(r"d:\3kweon\data\lotto4.db")
OUT = Path(r"d:\3kweon\tools\_strategy_x_cooccur_backtest.json")
BASELINE_4 = Path(r"d:\3kweon\tools\_strategy_x_backtest_v2.json")

ERA_C_START = 262
ERA_C_END = 1228
MIN_TRAIN_DRAWS = 80
TTEST_ALPHA = 0.05
TOP_POPULAR_N = 15
COMPLEMENT_JACCARD_MAX = 0.55
BASELINE_HIT = 0.8081
BASELINE_POP = 0.8514


def _load_draws() -> list[dict[str, Any]]:
    import sqlite3

    conn = sqlite3.connect(DB)
    try:
        rows = conn.execute(
            """
            SELECT drw_no, n1, n2, n3, n4, n5, n6, winner_cnt
            FROM lotto4_winners_full
            WHERE era = 'C' AND winner_cnt > 0
            ORDER BY drw_no
            """
        ).fetchall()
        return [
            {
                "drw_no": int(r[0]),
                "nums": [int(r[i]) for i in range(1, 7)],
                "winner_cnt": int(r[7]),
            }
            for r in rows
        ]
    finally:
        conn.close()


def _top30_rows(train: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sorted_by_w = sorted(train, key=lambda d: d["winner_cnt"], reverse=True)
    k = max(1, int(len(sorted_by_w) * 0.30))
    threshold = sorted_by_w[k - 1]["winner_cnt"]
    return [d for d in train if d["winner_cnt"] >= threshold]


def _build_number_weights(top30: list[dict[str, Any]]) -> dict[int, float]:
    if not top30:
        return {n: 1.0 / 45.0 for n in range(1, 46)}
    k = len(top30)
    freq: Counter[int] = Counter()
    for d in top30:
        for n in d["nums"]:
            freq[n] += 1
    return {n: max(freq.get(n, 0) / k, 0.01) for n in range(1, 46)}


def _build_pair_weights(top30: list[dict[str, Any]]) -> dict[tuple[int, int], float]:
    if not top30:
        return {(a, b): 0.001 for a in range(1, 46) for b in range(a + 1, 46)}
    k = len(top30)
    pair_freq: dict[tuple[int, int], int] = defaultdict(int)
    for d in top30:
        for a, b in combinations(sorted(d["nums"]), 2):
            pair_freq[(a, b)] += 1
    return {
        (a, b): max(pair_freq.get((a, b), 0) / k, 0.001)
        for a in range(1, 46)
        for b in range(a + 1, 46)
    }


def _build_shape_profile(top30: list[dict[str, Any]]) -> dict[str, Any]:
    if not top30:
        return {"sum6": {"p5": 100, "p95": 175}}
    shapes = [extract_shape_metrics(d["nums"]) for d in top30]
    return _segment_summary(shapes)


def _generate_coordinator_sets(
    drw_no: int,
    number_weights: dict[int, float],
    pair_weights: dict[tuple[int, int], float],
    shape_profile: dict[str, Any],
) -> list[list[int]]:
    sets: list[list[int]] = []
    existing: list[list[int]] = []
    for set_no in range(1, NUM_SETS + 1):
        seed = int(drw_no) * RNG_SEED_MUL + set_no * 211
        rng = random.Random(seed)
        nums = _draw_coordinator_set(
            rng, number_weights, pair_weights, shape_profile, existing
        )
        if nums is None:
            nums = sorted(rng.sample(range(1, 46), 6))
        existing.append(nums)
        sets.append(nums)
    return sets


def _generate_random_sets(drw_no: int) -> list[list[int]]:
    sets: list[list[int]] = []
    for set_no in range(1, NUM_SETS + 1):
        seed = int(drw_no) * 99991 + set_no * 37
        rng = random.Random(seed)
        sets.append(sorted(rng.sample(range(1, 46), 6)))
    return sets


def _match_count(pred: list[int], actual: list[int]) -> int:
    return len(set(pred) & set(actual))


def _pop_score_sum(nums: list[int], weights: dict[int, float]) -> float:
    return round(sum(weights.get(n, 0.0) for n in nums), 4)


def _union_jaccard(sets_a: list[list[int]], sets_b: list[list[int]]) -> float:
    ua = set()
    ub = set()
    for s in sets_a:
        ua.update(s)
    for s in sets_b:
        ub.update(s)
    if not ua and not ub:
        return 0.0
    return jaccard(ua, ub)


def _paired_ttest(a: list[float], b: list[float]) -> dict[str, float]:
    n = len(a)
    if n < 2 or len(b) != n:
        return {"t_stat": float("nan"), "p_value": float("nan"), "n": n}
    diffs = [x - y for x, y in zip(a, b)]
    mean_d = statistics.mean(diffs)
    sd_d = statistics.stdev(diffs)
    if sd_d == 0:
        return {"t_stat": 0.0, "p_value": 1.0 if mean_d == 0 else 0.0, "n": n}
    t_stat = mean_d / (sd_d / math.sqrt(n))
    p_value = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(t_stat) / math.sqrt(2))))
    return {"t_stat": round(t_stat, 4), "p_value": round(p_value, 6), "n": n}


def run_backtest() -> dict[str, Any]:
    draws = _load_draws()
    draw_by_no = {d["drw_no"]: d for d in draws}

    co_state = CooccurState()

    co_matches: list[float] = []
    rnd_matches: list[float] = []
    co_pop_avgs: list[float] = []
    rnd_pop_avgs: list[float] = []
    co_scores: list[float] = []
    complement_jaccards: list[float] = []

    evaluated = 0
    skipped = 0

    for drw_no in range(ERA_C_START, ERA_C_END + 1):
        if drw_no not in draw_by_no:
            continue

        train = [d for d in draws if d["drw_no"] < drw_no]
        if len(train) < MIN_TRAIN_DRAWS:
            skipped += 1
            co_state.add_draw(draw_by_no[drw_no]["nums"])
            continue

        top30 = _top30_rows(train)
        number_weights = _build_number_weights(top30)

        actual = draw_by_no[drw_no]["nums"]
        co_result = generate_cooccur_sets(
            drw_no, state=co_state.copy(), draw_count=len(train)
        )
        co_sets = [s["numbers"] for s in co_result.get("sets") or []]
        if len(co_sets) < NUM_SETS:
            for set_no in range(len(co_sets) + 1, NUM_SETS + 1):
                seed = drw_no * 20260621 + set_no * 173
                co_sets.append(sorted(random.Random(seed).sample(range(1, 46), 6)))

        rnd_sets = _generate_random_sets(drw_no)
        coord_sets = _generate_coordinator_sets(
            drw_no, number_weights, _build_pair_weights(top30), _build_shape_profile(top30)
        )

        co_mc = [_match_count(s, actual) for s in co_sets]
        rnd_mc = [_match_count(s, actual) for s in rnd_sets]
        co_matches.append(sum(co_mc) / len(co_mc))
        rnd_matches.append(sum(rnd_mc) / len(rnd_mc))

        co_pop = [_pop_score_sum(s, number_weights) for s in co_sets]
        rnd_pop = [_pop_score_sum(s, number_weights) for s in rnd_sets]
        co_pop_avgs.append(sum(co_pop) / len(co_pop))
        rnd_pop_avgs.append(sum(rnd_pop) / len(rnd_pop))

        if co_result.get("sets"):
            co_scores.append(
                statistics.mean(s.get("cooccur_score", 0.0) for s in co_result["sets"])
            )

        complement_jaccards.append(_union_jaccard(co_sets, coord_sets))
        evaluated += 1

        co_state.add_draw(draw_by_no[drw_no]["nums"])

    co_avg_hit = round(statistics.mean(co_matches), 4) if co_matches else 0.0
    rnd_avg_hit = round(statistics.mean(rnd_matches), 4) if rnd_matches else 0.0
    co_avg_pop = round(statistics.mean(co_pop_avgs), 4) if co_pop_avgs else 0.0
    rnd_avg_pop = round(statistics.mean(rnd_pop_avgs), 4) if rnd_pop_avgs else 0.0

    ttest_pop = _paired_ttest(co_pop_avgs, rnd_pop_avgs)
    ttest_hit = _paired_ttest(co_matches, rnd_matches)
    pop_delta = round(co_avg_pop - rnd_avg_pop, 4)
    hit_delta = round(co_avg_hit - rnd_avg_hit, 4)
    avg_complement = round(statistics.mean(complement_jaccards), 4) if complement_jaccards else 1.0

    pop_vs_random_ok = ttest_pop["p_value"] < TTEST_ALPHA and pop_delta > 0
    complement_ok = avg_complement < COMPLEMENT_JACCARD_MAX

    if pop_vs_random_ok and complement_ok:
        adoption = "5뇌 정식 채택"
    elif pop_vs_random_ok:
        adoption = "보조 신호로만 (보완성 부족)"
    else:
        adoption = "폐기"

    comparison_table = [
        {
            "metric": "평균 적중수",
            "cooccur_5뇌": co_avg_hit,
            "random": rnd_avg_hit,
            "strategy_x_4뇌": BASELINE_HIT,
            "delta_vs_random": hit_delta,
        },
        {
            "metric": "평균 인기적합도",
            "cooccur_5뇌": co_avg_pop,
            "random": rnd_avg_pop,
            "strategy_x_4뇌": BASELINE_POP,
            "delta_vs_random": pop_delta,
        },
        {
            "metric": "paired_ttest 인기적합도 p",
            "cooccur_5뇌": ttest_pop["p_value"],
            "random": None,
            "strategy_x_4뇌": None,
            "delta_vs_random": None,
        },
        {
            "metric": "4뇌와 union Jaccard(낮을수록 보완)",
            "cooccur_5뇌": avg_complement,
            "random": None,
            "strategy_x_4뇌": None,
            "delta_vs_random": None,
        },
        {
            "metric": "평균 cooccur_score",
            "cooccur_5뇌": round(statistics.mean(co_scores), 4) if co_scores else 0.0,
            "random": None,
            "strategy_x_4뇌": None,
            "delta_vs_random": None,
        },
    ]

    return {
        "evaluated_draws": evaluated,
        "skipped_draws": skipped,
        "cooccur_hit": {
            "avg": co_avg_hit,
            "random_avg": rnd_avg_hit,
            "delta": hit_delta,
            "ttest": ttest_hit,
        },
        "cooccur_popularity": {
            "avg": co_avg_pop,
            "random_avg": rnd_avg_pop,
            "delta": pop_delta,
            "ttest": ttest_pop,
            "vs_random_significant": pop_vs_random_ok,
        },
        "complementarity": {
            "avg_union_jaccard_vs_4brain": avg_complement,
            "threshold": COMPLEMENT_JACCARD_MAX,
            "complementary": complement_ok,
        },
        "comparison_table": comparison_table,
        "adoption_verdict": adoption,
        "r2_honest": (
            "cooccur 5뇌도 예측 엔진 아님. 인기적합도 우위는 인기영역 조합기 성격. "
            "적중률 무작위 이김 보장 없음."
        ),
    }


def main() -> None:
    result = run_backtest()
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {OUT}")
    print(f"adoption={result['adoption_verdict']}")
    print(f"pop={result['cooccur_popularity']['avg']} random={result['cooccur_popularity']['random_avg']}")
    print(f"jaccard_vs_4brain={result['complementarity']['avg_union_jaccard_vs_4brain']}")


if __name__ == "__main__":
    main()
