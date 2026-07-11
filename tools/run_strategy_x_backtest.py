"""전략 X 정직성·적합도 walk-forward 백테스트 (era_C, R13).

적중률 무작위 수준 확인 + 인기영역 적합도 측정.
커닝 금지: 회차 N 예측 시 drw_no < N 데이터만 사용.
"""

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

from app.lotto4.brains.coordinator_brain import (
    NUM_SETS,
    RNG_SEED_MUL,
    _draw_coordinator_set,
)
from app.lotto4.brains.shape_brain import (
    _segment_summary,
    extract_shape_metrics,
)

DB = Path(r"d:\3kweon\data\lotto4.db")
OUT = Path(r"d:\3kweon\tools\_strategy_x_backtest.json")

ERA_C_START = 262
ERA_C_END = 1228
TOP30_WINNER_MIN = 11
THEORY_AVG_MATCH = 0.7894
MIN_TRAIN_DRAWS = 80
HIT_DELTA_THRESHOLD = 0.05
TTEST_ALPHA = 0.05
TOP_POPULAR_N = 15


def _load_draws() -> list[dict[str, Any]]:
    import sqlite3

    conn = sqlite3.connect(DB)
    try:
        rows = conn.execute(
            """
            SELECT drw_no, n1, n2, n3, n4, n5, n6, winner_cnt, era
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
                "era": r[8],
            }
            for r in rows
        ]
    finally:
        conn.close()


def _top30_rows(train: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not train:
        return []
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


def _generate_strategy_sets(
    target_draw_no: int,
    number_weights: dict[int, float],
    pair_weights: dict[tuple[int, int], float],
    shape_profile: dict[str, Any],
) -> list[list[int]]:
    sets: list[list[int]] = []
    existing: list[list[int]] = []
    for set_no in range(1, NUM_SETS + 1):
        seed = int(target_draw_no) * RNG_SEED_MUL + set_no * 211
        rng = random.Random(seed)
        nums = _draw_coordinator_set(
            rng, number_weights, pair_weights, shape_profile, existing
        )
        if nums is None:
            nums = sorted(rng.sample(range(1, 46), 6))
        existing.append(nums)
        sets.append(nums)
    return sets


def _generate_random_sets(target_draw_no: int) -> list[list[int]]:
    sets: list[list[int]] = []
    for set_no in range(1, NUM_SETS + 1):
        seed = int(target_draw_no) * 99991 + set_no * 37
        rng = random.Random(seed)
        sets.append(sorted(rng.sample(range(1, 46), 6)))
    return sets


def _match_count(pred: list[int], actual: list[int]) -> int:
    return len(set(pred) & set(actual))


def _pop_score_sum(nums: list[int], weights: dict[int, float]) -> float:
    return round(sum(weights.get(n, 0.0) for n in nums), 4)


def _top_popular_numbers(weights: dict[int, float], n: int = TOP_POPULAR_N) -> set[int]:
    ranked = sorted(weights.items(), key=lambda x: (-x[1], x[0]))
    return {num for num, _ in ranked[:n]}


def _popular_overlap(nums: list[int], popular: set[int]) -> int:
    return len(set(nums) & popular)


def _paired_ttest(a: list[float], b: list[float]) -> dict[str, float]:
    """paired t-test (a vs b), manual implementation."""
    n = len(a)
    if n < 2 or len(b) != n:
        return {"t_stat": float("nan"), "p_value": float("nan"), "n": n}
    diffs = [x - y for x, y in zip(a, b)]
    mean_d = statistics.mean(diffs)
    sd_d = statistics.stdev(diffs)
    if sd_d == 0:
        return {"t_stat": 0.0, "p_value": 1.0 if mean_d == 0 else 0.0, "n": n}
    t_stat = mean_d / (sd_d / math.sqrt(n))
    # two-tailed p approx via normal for large n
    p_value = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(t_stat) / math.sqrt(2))))
    return {"t_stat": round(t_stat, 4), "p_value": round(p_value, 6), "n": n}


def run_backtest() -> dict[str, Any]:
    draws = _load_draws()
    draw_by_no = {d["drw_no"]: d for d in draws}

    sx_matches: list[float] = []
    rnd_matches: list[float] = []
    sx_pop_avgs: list[float] = []
    rnd_pop_avgs: list[float] = []
    sx_overlap_top30: list[float] = []
    rnd_overlap_top30: list[float] = []

    hit4_plus_sx = 0
    hit6_sx = 0
    hit4_plus_rnd = 0
    hit6_rnd = 0
    evaluated = 0
    skipped = 0

    target_draws = [n for n in range(ERA_C_START, ERA_C_END + 1) if n in draw_by_no]

    for drw_no in target_draws:
        train = [d for d in draws if d["drw_no"] < drw_no]
        if len(train) < MIN_TRAIN_DRAWS:
            skipped += 1
            continue

        top30 = _top30_rows(train)
        number_weights = _build_number_weights(top30)
        pair_weights = _build_pair_weights(top30)
        shape_profile = _build_shape_profile(top30)
        popular_nums = _top_popular_numbers(number_weights)

        actual = draw_by_no[drw_no]["nums"]
        sx_sets = _generate_strategy_sets(drw_no, number_weights, pair_weights, shape_profile)
        rnd_sets = _generate_random_sets(drw_no)

        sx_mc = [_match_count(s, actual) for s in sx_sets]
        rnd_mc = [_match_count(s, actual) for s in rnd_sets]
        sx_matches.append(sum(sx_mc) / len(sx_mc))
        rnd_matches.append(sum(rnd_mc) / len(rnd_mc))

        for mc in sx_mc:
            if mc >= 4:
                hit4_plus_sx += 1
            if mc == 6:
                hit6_sx += 1
        for mc in rnd_mc:
            if mc >= 4:
                hit4_plus_rnd += 1
            if mc == 6:
                hit6_rnd += 1

        sx_pop = [_pop_score_sum(s, number_weights) for s in sx_sets]
        rnd_pop = [_pop_score_sum(s, number_weights) for s in rnd_sets]
        sx_pop_avgs.append(sum(sx_pop) / len(sx_pop))
        rnd_pop_avgs.append(sum(rnd_pop) / len(rnd_pop))

        if draw_by_no[drw_no]["winner_cnt"] >= TOP30_WINNER_MIN:
            sx_ov = [_popular_overlap(s, popular_nums) for s in sx_sets]
            rnd_ov = [_popular_overlap(s, popular_nums) for s in rnd_sets]
            sx_overlap_top30.append(sum(sx_ov) / len(sx_ov))
            rnd_overlap_top30.append(sum(rnd_ov) / len(rnd_ov))

        evaluated += 1

    sx_avg = round(statistics.mean(sx_matches), 4) if sx_matches else 0.0
    rnd_avg = round(statistics.mean(rnd_matches), 4) if rnd_matches else 0.0
    hit_delta = round(sx_avg - rnd_avg, 4)

    if abs(hit_delta) <= HIT_DELTA_THRESHOLD:
        hit_verdict = "적중률 무작위 수준 = 정직 확인"
    else:
        hit_verdict = f"적중률 Δ={hit_delta} (|Δ|>{HIT_DELTA_THRESHOLD}, 무작위와 차이 있음 — 우위 주장 금지)"

    ttest = _paired_ttest(sx_pop_avgs, rnd_pop_avgs)
    pop_delta = round(statistics.mean(sx_pop_avgs) - statistics.mean(rnd_pop_avgs), 4)
    if ttest["p_value"] < TTEST_ALPHA and pop_delta > 0:
        pop_verdict = "✅ 인기영역 적합도 우위 = 전략X의 과학적 근거 확보"
    else:
        pop_verdict = "❌ 인기 선호 외 차이 없음"

    sx_ov_avg = round(statistics.mean(sx_overlap_top30), 4) if sx_overlap_top30 else 0.0
    rnd_ov_avg = round(statistics.mean(rnd_overlap_top30), 4) if rnd_overlap_top30 else 0.0

    summary_table = [
        {
            "metric": "평균 적중수",
            "strategy_x": sx_avg,
            "random": rnd_avg,
            "theory": THEORY_AVG_MATCH,
            "delta": hit_delta,
            "verdict": hit_verdict,
        },
        {
            "metric": "평균 인기점수합",
            "strategy_x": round(statistics.mean(sx_pop_avgs), 4),
            "random": round(statistics.mean(rnd_pop_avgs), 4),
            "theory": None,
            "delta": pop_delta,
            "verdict": pop_verdict,
        },
        {
            "metric": "hit4+ 건수",
            "strategy_x": hit4_plus_sx,
            "random": hit4_plus_rnd,
            "theory": None,
            "delta": hit4_plus_sx - hit4_plus_rnd,
            "verdict": "보조",
        },
        {
            "metric": "hit6 건수",
            "strategy_x": hit6_sx,
            "random": hit6_rnd,
            "theory": None,
            "delta": hit6_sx - hit6_rnd,
            "verdict": "보조",
        },
        {
            "metric": "당첨자多 회차 인기번호 겹침",
            "strategy_x": sx_ov_avg,
            "random": rnd_ov_avg,
            "theory": None,
            "delta": round(sx_ov_avg - rnd_ov_avg, 4),
            "verdict": "보조",
        },
    ]

    return {
        "step1_hit_rate": {
            "era": "C",
            "range": f"{ERA_C_START}~{ERA_C_END}",
            "evaluated_draws": evaluated,
            "skipped_draws": skipped,
            "min_train": MIN_TRAIN_DRAWS,
            "strategy_x_avg_match": sx_avg,
            "random_avg_match": rnd_avg,
            "theory_avg_match": THEORY_AVG_MATCH,
            "delta": hit_delta,
            "hit4_plus": {"strategy_x": hit4_plus_sx, "random": hit4_plus_rnd},
            "hit6": {"strategy_x": hit6_sx, "random": hit6_rnd},
            "verdict": hit_verdict,
        },
        "step2_popularity_fit": {
            "strategy_x_avg_pop_sum": round(statistics.mean(sx_pop_avgs), 4),
            "random_avg_pop_sum": round(statistics.mean(rnd_pop_avgs), 4),
            "delta": pop_delta,
            "paired_ttest": ttest,
            "verdict": pop_verdict,
        },
        "step3_top30_winner_overlap": {
            "high_winner_draws_n": len(sx_overlap_top30),
            "strategy_x_avg_overlap": sx_ov_avg,
            "random_avg_overlap": rnd_ov_avg,
            "delta": round(sx_ov_avg - rnd_ov_avg, 4),
            "top_popular_n": TOP_POPULAR_N,
        },
        "step4_summary_table": summary_table,
        "conclusion": {
            "hit_rate": hit_verdict,
            "popularity_fit": pop_verdict,
            "identity": "예측 엔진 아님, 인기영역 조합 생성기",
        },
    }


def main() -> None:
    result = run_backtest()
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {OUT} evaluated={result['step1_hit_rate']['evaluated_draws']}")


if __name__ == "__main__":
    main()
