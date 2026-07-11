"""전략 X 하이에나 조율뇌 walk-forward 백테스트 (era_C, R13)."""

from __future__ import annotations

import json
import math
import random
import statistics
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.lotto4.brains.cooccur_brain_v13 import CooccurState, generate_cooccur_sets
from app.lotto4.brains.coordinator_brain import (
    NUM_SETS,
    RNG_SEED_MUL,
    _draw_coordinator_set,
)
from app.lotto4.brains.hyena_coordinator_v13 import (
    SOURCE_TAGS,
    analyze_union_hits_lookahead,
    generate_hyena_sets,
)
from app.lotto4.brains.popularity_freq_brain import generate_popularity_sets
from app.lotto4.brains.popularity_pair_brain import generate_pair_sets
from app.lotto4.brains.shape_brain import (
    _segment_summary,
    extract_shape_metrics,
    generate_shape_sets,
)

DB = Path(r"d:\3kweon\data\lotto4.db")
OUT = Path(r"d:\3kweon\tools\_strategy_x_hyena_backtest.json")

ERA_C_START = 262
ERA_C_END = 1228
MIN_TRAIN_DRAWS = 80
LOOKBACK = 50
TTEST_ALPHA = 0.05
COOCCUR_POP_BASELINE = 0.861
COORD_POP_BASELINE = 0.8514


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
    from collections import Counter

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


def _wf_coordinator_sets(
    drw_no: int,
    nw: dict[int, float],
    pw: dict[tuple[int, int], float],
    sp: dict[str, Any],
) -> list[list[int]]:
    sets: list[list[int]] = []
    existing: list[list[int]] = []
    for set_no in range(1, NUM_SETS + 1):
        seed = int(drw_no) * RNG_SEED_MUL + set_no * 211
        rng = random.Random(seed)
        nums = _draw_coordinator_set(rng, nw, pw, sp, existing)
        if nums is None:
            nums = sorted(rng.sample(range(1, 46), 6))
        existing.append(nums)
        sets.append(nums)
    return sets


def _random_sets(drw_no: int) -> list[list[int]]:
    out: list[list[int]] = []
    for set_no in range(1, NUM_SETS + 1):
        seed = int(drw_no) * 99991 + set_no * 37
        out.append(sorted(random.Random(seed).sample(range(1, 46), 6)))
    return out


def _match_avg(sets: list[list[int]], actual: list[int]) -> float:
    if not sets:
        return 0.0
    return sum(len(set(s) & set(actual)) for s in sets) / len(sets)


def _pop_avg(sets: list[list[int]], weights: dict[int, float]) -> float:
    if not sets:
        return 0.0
    return statistics.mean(
        round(sum(weights.get(int(n), 0.0) for n in s), 4) for s in sets
    )


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


def _collect_all_outputs(
    drw_no: int,
    wf_ctx: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return {
        "strategy_x_popularity_freq": generate_popularity_sets(drw_no),
        "strategy_x_popularity_pair": generate_pair_sets(drw_no),
        "strategy_x_shape": generate_shape_sets(drw_no),
        "strategy_x_cooccur": generate_cooccur_sets(
            drw_no,
            state=wf_ctx["cooccur_state"].copy(),
            draw_count=wf_ctx["draw_count"],
        ),
        "strategy_x_coordinator": {
            "sets": [
                {"set_no": i + 1, "numbers": s}
                for i, s in enumerate(
                    _wf_coordinator_sets(
                        drw_no,
                        wf_ctx["number_weights"],
                        wf_ctx["pair_weights"],
                        wf_ctx["shape_profile"],
                    )
                )
            ]
        },
    }


def _sets_from_output(payload: dict[str, Any]) -> list[list[int]]:
    return [s["numbers"] for s in payload.get("sets") or [] if s.get("numbers")]


def run_backtest() -> dict[str, Any]:
    draws = _load_draws()
    draw_by_no = {d["drw_no"]: d for d in draws}
    co_state = CooccurState()
    trust_hist: dict[str, list[float]] = {t: [] for t in SOURCE_TAGS}

    hyena_hits: list[float] = []
    hyena_pops: list[float] = []
    rnd_hits: list[float] = []
    rnd_pops: list[float] = []
    brain_hits: dict[str, list[float]] = {t: [] for t in SOURCE_TAGS}
    brain_pops: dict[str, list[float]] = {t: [] for t in SOURCE_TAGS}

    union_hits: list[int] = []
    union_hit_nums: list[float] = []
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
        nw = _build_number_weights(top30)
        pw = _build_pair_weights(top30)
        sp = _build_shape_profile(top30)
        wf_ctx = {
            "number_weights": nw,
            "pair_weights": pw,
            "shape_profile": sp,
            "cooccur_state": co_state.copy(),
            "draw_count": len(train),
        }

        trust = {
            t: round(statistics.mean(trust_hist[t][-LOOKBACK:]), 4)
            if trust_hist[t]
            else 0.5
            for t in SOURCE_TAGS
        }

        outputs = _collect_all_outputs(drw_no, wf_ctx)
        hyena = generate_hyena_sets(
            drw_no,
            wf_context=wf_ctx,
            draws=draws,
            use_db_logs=False,
            brain_trust_override=trust,
            brain_outputs_override=outputs,
        )

        actual = draw_by_no[drw_no]["nums"]
        hyena_sets = _sets_from_output(hyena)
        rnd_sets = _random_sets(drw_no)

        hyena_hits.append(_match_avg(hyena_sets, actual))
        hyena_pops.append(_pop_avg(hyena_sets, nw))
        rnd_hits.append(_match_avg(rnd_sets, actual))
        rnd_pops.append(_pop_avg(rnd_sets, nw))

        for tag, payload in outputs.items():
            s = _sets_from_output(payload)
            brain_hits[tag].append(_match_avg(s, actual))
            brain_pops[tag].append(_pop_avg(s, nw))
            for nums in s:
                trust_hist[tag].append(
                    round(sum(nw.get(int(n), 0.0) for n in nums), 4)
                )

        analysis = analyze_union_hits_lookahead(
            drw_no, actual, wf_context=wf_ctx
        )
        union_hits.append(int(analysis["union_hit_count"]))
        union_hit_nums.append(
            int(analysis["union_hit_count"]) / max(int(analysis["union_unique_numbers"]), 1)
        )

        evaluated += 1
        co_state.add_draw(actual)

    hyena_hit = round(statistics.mean(hyena_hits), 4)
    hyena_pop = round(statistics.mean(hyena_pops), 4)
    rnd_hit = round(statistics.mean(rnd_hits), 4)
    rnd_pop = round(statistics.mean(rnd_pops), 4)

    ttest_pop = _paired_ttest(hyena_pops, rnd_pops)
    ttest_hit = _paired_ttest(hyena_hits, rnd_hits)
    pop_delta = round(hyena_pop - rnd_pop, 4)
    hit_delta = round(hyena_hit - rnd_hit, 4)

    best_brain_pop = max(
        round(statistics.mean(v), 4) for v in brain_pops.values() if v
    )
    pop_vs_5brain = hyena_pop > best_brain_pop

    pop_vs_random_ok = ttest_pop["p_value"] < TTEST_ALPHA and pop_delta > 0
    hit_honest = abs(hit_delta) <= 0.05

    if pop_vs_5brain and pop_vs_random_ok and hit_honest:
        verdict = "하이에나 정식 채택"
    elif pop_vs_random_ok:
        verdict = "보조 조율 (5뇌 대비 인기 우위 미달)"
    else:
        verdict = "폐기 검토"

    comparison = [
        {
            "metric": "평균 적중수",
            "hyena": hyena_hit,
            "random": rnd_hit,
            "cooccur_5뇌_hit": round(
                statistics.mean(brain_hits["strategy_x_cooccur"]), 4
            ),
            "coordinator_4뇌_hit": round(
                statistics.mean(brain_hits["strategy_x_coordinator"]), 4
            ),
        },
        {
            "metric": "평균 인기적합도",
            "hyena": hyena_pop,
            "random": rnd_pop,
            "cooccur_5뇌": round(statistics.mean(brain_pops["strategy_x_cooccur"]), 4),
            "coordinator_4뇌": round(
                statistics.mean(brain_pops["strategy_x_coordinator"]), 4
            ),
            "5뇌최고": best_brain_pop,
        },
        {
            "metric": "인기 t-test p (hyena vs random)",
            "hyena": ttest_pop["p_value"],
            "random": None,
            "cooccur_5뇌": None,
            "coordinator_4뇌": None,
        },
    ]

    per_brain_pop = {
        t: round(statistics.mean(brain_pops[t]), 4) for t in SOURCE_TAGS
    }

    return {
        "evaluated_draws": evaluated,
        "skipped_draws": skipped,
        "hyena_hit": {
            "avg": hyena_hit,
            "random_avg": rnd_hit,
            "delta": hit_delta,
            "ttest": ttest_hit,
            "honest_random_level": hit_honest,
        },
        "hyena_popularity": {
            "avg": hyena_pop,
            "random_avg": rnd_pop,
            "delta": pop_delta,
            "ttest": ttest_pop,
            "vs_random_significant": pop_vs_random_ok,
            "vs_5brain_best": best_brain_pop,
            "beats_5brain_best": pop_vs_5brain,
        },
        "per_brain_popularity": per_brain_pop,
        "analysis_lookahead": {
            "label": "analysis_lookahead_only_NOT_PREDICTION",
            "avg_union_hit_count": round(statistics.mean(union_hits), 4),
            "avg_union_hit_ratio": round(statistics.mean(union_hit_nums), 4),
            "note": "이론적 union 적중 — 예측 아님, 5뇌 보완성 참고용",
        },
        "comparison_table": comparison,
        "adoption_verdict": verdict,
        "r2_honest": (
            "하이에나도 예측 엔진 아님. 인기적합도는 조합기 성격. "
            "6개 적중·당첨확률 향상 보장 없음."
        ),
    }


def main() -> None:
    result = run_backtest()
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {OUT}")
    print(f"verdict={result['adoption_verdict']}")
    print(
        f"hyena_pop={result['hyena_popularity']['avg']} "
        f"best_5brain={result['hyena_popularity']['vs_5brain_best']}"
    )


if __name__ == "__main__":
    main()
