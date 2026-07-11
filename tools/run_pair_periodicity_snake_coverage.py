"""쌍 주기성(STEP C) + snake 커버리지(STEP D) 검증."""

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

from app.lotto4.brains._utils import jaccard
from app.lotto4.brains.cooccur_brain_v13 import CooccurState, generate_cooccur_sets
from app.lotto4.brains.coordinator_brain import NUM_SETS, RNG_SEED_MUL, _draw_coordinator_set
from app.lotto4.brains.hyena_coordinator_v13 import SOURCE_TAGS, generate_hyena_sets
from app.lotto4.brains.popularity_freq_brain import generate_popularity_sets
from app.lotto4.brains.popularity_pair_brain import generate_pair_sets
from app.lotto4.brains.shape_brain import (
    _segment_summary,
    extract_shape_metrics,
    generate_shape_sets,
)
from app.lotto4.pair_periodicity_analysis import run_full_analysis

DB = Path(r"d:\3kweon\data\lotto4.db")
OUT = Path(r"d:\3kweon\tools\_pair_periodicity_snake_coverage.json")
PERIOD_JSON = Path(r"d:\3kweon\tools\_pair_periodicity_summary.json")

ERA_C_START = 262
ERA_C_END = 1228
MIN_TRAIN_DRAWS = 80
LOOKBACK = 50
TTEST_ALPHA = 0.05
HYENA_BASELINE_POP = 0.8679
SCHEME = "cooccur_favor"
JACCARD_THRESHOLDS = (0.5, 0.45, 0.4, 0.35)


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
    from collections import Counter

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
    return _segment_summary([extract_shape_metrics(d["nums"]) for d in top30])


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


def _collect_outputs(drw_no: int, wf: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        "strategy_x_popularity_freq": generate_popularity_sets(drw_no),
        "strategy_x_popularity_pair": generate_pair_sets(drw_no),
        "strategy_x_shape": generate_shape_sets(drw_no),
        "strategy_x_cooccur": generate_cooccur_sets(
            drw_no,
            state=wf["cooccur_state"].copy(),
            draw_count=wf["draw_count"],
        ),
        "strategy_x_coordinator": {
            "sets": [
                {"set_no": i + 1, "numbers": s}
                for i, s in enumerate(
                    _wf_coordinator_sets(
                        drw_no,
                        wf["number_weights"],
                        wf["pair_weights"],
                        wf["shape_profile"],
                    )
                )
            ]
        },
    }


def _sets_from(payload: dict[str, Any]) -> list[list[int]]:
    return [s["numbers"] for s in payload.get("sets") or [] if s.get("numbers")]


def _pop_avg(sets: list[list[int]], nw: dict[int, float]) -> float:
    if not sets:
        return 0.0
    return statistics.mean(
        round(sum(nw.get(int(n), 0.0) for n in s), 4) for s in sets
    )


def _union_coverage(sets: list[list[int]]) -> int:
    u: set[int] = set()
    for s in sets:
        u.update(int(n) for n in s)
    return len(u)


def _avg_pairwise_jaccard(sets: list[list[int]]) -> float:
    if len(sets) < 2:
        return 0.0
    sims: list[float] = []
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            sims.append(jaccard(set(sets[i]), set(sets[j])))
    return round(statistics.mean(sims), 4)


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


def run_snake_coverage() -> dict[str, Any]:
    draws = _load_draws()
    co_state = CooccurState()
    trust_hist: dict[str, list[float]] = {t: [] for t in SOURCE_TAGS}

    baseline_pops: list[float] = []
    metrics: dict[float, dict[str, list[float]]] = {
        j: {"pop": [], "union": [], "jaccard": []} for j in JACCARD_THRESHOLDS
    }

    evaluated = 0
    for drw_no in range(ERA_C_START, ERA_C_END + 1):
        draw_by_no = {d["drw_no"]: d for d in draws}
        if drw_no not in draw_by_no:
            continue
        train = [d for d in draws if d["drw_no"] < drw_no]
        if len(train) < MIN_TRAIN_DRAWS:
            co_state.add_draw(draw_by_no[drw_no]["nums"])
            continue

        top30 = _top30_rows(train)
        nw = _build_number_weights(top30)
        wf = {
            "number_weights": nw,
            "pair_weights": _build_pair_weights(top30),
            "shape_profile": _build_shape_profile(top30),
            "cooccur_state": co_state.copy(),
            "draw_count": len(train),
        }
        trust = {
            t: round(statistics.mean(trust_hist[t][-LOOKBACK:]), 4)
            if trust_hist[t]
            else 0.5
            for t in SOURCE_TAGS
        }
        outputs = _collect_outputs(drw_no, wf)

        for jac in JACCARD_THRESHOLDS:
            hy = generate_hyena_sets(
                drw_no,
                wf_context=wf,
                draws=draws,
                use_db_logs=False,
                brain_trust_override=trust,
                brain_outputs_override=outputs,
                weight_scheme=SCHEME,
                jaccard_limit=jac,
            )
            sets = _sets_from(hy)
            metrics[jac]["pop"].append(_pop_avg(sets, nw))
            metrics[jac]["union"].append(float(_union_coverage(sets)))
            metrics[jac]["jaccard"].append(_avg_pairwise_jaccard(sets))

        baseline_pops.append(metrics[0.5]["pop"][-1])

        for tag, payload in outputs.items():
            for nums in _sets_from(payload):
                trust_hist[tag].append(
                    round(sum(nw.get(int(n), 0.0) for n in nums), 4)
                )

        evaluated += 1
        co_state.add_draw(draw_by_no[drw_no]["nums"])

    base_pop = round(statistics.mean(baseline_pops), 4)
    rows = []
    for jac in JACCARD_THRESHOLDS:
        pop = round(statistics.mean(metrics[jac]["pop"]), 4)
        union = round(statistics.mean(metrics[jac]["union"]), 2)
        jac_avg = round(statistics.mean(metrics[jac]["jaccard"]), 4)
        ttest = _paired_ttest(metrics[jac]["pop"], baseline_pops)
        rows.append(
            {
                "jaccard_limit": jac,
                "popularity_sum": pop,
                "delta_vs_0.5": round(pop - base_pop, 4),
                "union_coverage_avg": union,
                "avg_pairwise_jaccard": jac_avg,
                "paired_ttest_pop_vs_0.5": ttest,
            }
        )

    best_union = max(rows, key=lambda r: r["union_coverage_avg"])
    best_tradeoff = None
    for r in rows:
        if r["union_coverage_avg"] > rows[0]["union_coverage_avg"] and r["popularity_sum"] >= base_pop - 0.005:
            best_tradeoff = r

    return {
        "evaluated_draws": evaluated,
        "baseline_jaccard_0.5_pop": base_pop,
        "rows": rows,
        "best_union": best_union,
        "verdict_d": (
            f"채택 검토 — jaccard={best_tradeoff['jaccard_limit']} "
            f"union {best_tradeoff['union_coverage_avg']} 인기 {best_tradeoff['popularity_sum']}"
            if best_tradeoff
            else "보류 — union 상승 시 인기적합도 trade-off 또는 미미"
        ),
        "snake_reference": {
            "source": "My_Library/app/lotto3/v12_snake.py",
            "threshold": 0.4,
            "logic": "1군 30세트 대비 Jaccard<0.4 + 5005 전수",
        },
    }


def run() -> dict[str, Any]:
    print("STEP C - pair periodicity...", flush=True)
    period = run_full_analysis(str(DB), json_out=PERIOD_JSON)

    print("STEP D - snake coverage...", flush=True)
    snake = run_snake_coverage()

    base_union = snake["rows"][0]["union_coverage_avg"]
    adopt_jac = None
    for r in snake["rows"]:
        if r["jaccard_limit"] < 0.5 and r["union_coverage_avg"] > base_union and r["popularity_sum"] >= snake["baseline_jaccard_0.5_pop"] - 0.003:
            adopt_jac = r["jaccard_limit"]

    result = {
        "step_c_periodicity": period,
        "step_d_snake_coverage": snake,
        "step_e_summary": {
            "periodicity_real": period["step_c4_verdict"],
            "coverage_improved": any(
                r["union_coverage_avg"] > base_union + 0.3 for r in snake["rows"]
            ),
            "adopt_periodicity_6brain": "periodicity" in period["step_c4_verdict"],
            "adopt_jaccard_limit": adopt_jac,
            "discard_periodicity": "폐기" in period["step_c4_verdict"],
            "next_benchmark": "1군 5005 전수 (인기적합도 상한)",
            "second_benchmark": "1군 fusion 벡터 융합",
        },
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    r = run()
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(r, ensure_ascii=False, indent=2))
