"""풀 크기 스윕 + 45공간 직접 커버리지 walk-forward 검증 (era_C, R13)."""

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
from app.lotto4.brains.coordinator_brain import NUM_SETS, RNG_SEED_MUL, _draw_coordinator_set
from app.lotto4.brains.hyena_coordinator_v13 import SOURCE_TAGS, generate_hyena_sets
from app.lotto4.brains.popularity_freq_brain import generate_popularity_sets
from app.lotto4.brains.popularity_pair_brain import generate_pair_sets
from app.lotto4.brains.shape_brain import (
    _segment_summary,
    extract_shape_metrics,
    generate_shape_sets,
)
from app.lotto4.coverage_optimizer_walkforward import (
    avg_pairwise_jaccard,
    generate_coverage_sets,
    generate_full45_coverage_sets,
    union_coverage,
)

DB = Path(r"d:\3kweon\data\lotto4.db")
OUT = Path(r"d:\3kweon\tools\_strategy_x_pool_sweep_coverage.json")

ERA_C_START = 262
ERA_C_END = 1228
MIN_TRAIN_DRAWS = 80
LOOKBACK = 50
POP_BASELINE = 0.8679
UNION_BASELINE = 18.75
RANDOM_HIT = 0.81
SCHEME = "cooccur_favor"
POOL_SIZES = (15, 20, 25, 30)
POP_TOLERANCE = 0.005


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


def _hit_avg(sets: list[list[int]], actual: list[int]) -> float:
    if not sets:
        return 0.0
    return sum(len(set(s) & set(actual)) for s in sets) / len(sets)


def _hyena_pool_weight(outputs: dict[str, dict[str, Any]], trust: dict[str, float]) -> dict[int, float]:
    from collections import defaultdict as dd

    pool: dict[int, float] = dd(float)
    for tag, payload in outputs.items():
        tw = max(float(trust.get(tag, 0.5)), 0.01)
        for item in payload.get("sets") or []:
            for n in item.get("numbers") or []:
                ni = int(n)
                if 1 <= ni <= 45:
                    pool[ni] += tw
    return dict(pool)


def _summarize(label: str, unions: list[float], pops: list[float], hits: list[float], jacs: list[float]) -> dict[str, Any]:
    u = round(statistics.mean(unions), 2)
    p = round(statistics.mean(pops), 4)
    h = round(statistics.mean(hits), 4)
    j = round(statistics.mean(jacs), 4)
    return {
        "label": label,
        "union_avg": u,
        "union_pct": round(100.0 * u / 45.0, 1),
        "popularity_sum": p,
        "delta_pop_vs_baseline": round(p - POP_BASELINE, 4),
        "hit_avg": h,
        "avg_pairwise_jaccard": j,
        "union_vs_baseline": round(u - UNION_BASELINE, 2),
        "pop_maintained": p >= POP_BASELINE - POP_TOLERANCE,
        "union_beats_baseline": u > UNION_BASELINE,
    }


def run() -> dict[str, Any]:
    draws = _load_draws()
    draw_by_no = {d["drw_no"]: d for d in draws}
    co_state = CooccurState()
    trust_hist: dict[str, list[float]] = {t: [] for t in SOURCE_TAGS}

    metrics: dict[str, dict[str, list[float]]] = {
        "baseline_hyena": {"union": [], "pop": [], "hit": [], "jac": []},
        "full45": {"union": [], "pop": [], "hit": [], "jac": []},
    }
    for ps in POOL_SIZES:
        metrics[f"pool_{ps}"] = {"union": [], "pop": [], "hit": [], "jac": []}

    evaluated = 0
    for drw_no in range(ERA_C_START, ERA_C_END + 1):
        if drw_no not in draw_by_no:
            continue
        train = [d for d in draws if d["drw_no"] < drw_no]
        actual = draw_by_no[drw_no]["nums"]
        if len(train) < MIN_TRAIN_DRAWS:
            co_state.add_draw(actual)
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
        pw = _hyena_pool_weight(outputs, trust)

        hyena = generate_hyena_sets(
            drw_no,
            wf_context=wf,
            draws=draws,
            use_db_logs=False,
            brain_trust_override=trust,
            brain_outputs_override=outputs,
            weight_scheme=SCHEME,
        )
        hsets = _sets_from(hyena)
        metrics["baseline_hyena"]["union"].append(float(union_coverage(hsets)))
        metrics["baseline_hyena"]["pop"].append(_pop_avg(hsets, nw))
        metrics["baseline_hyena"]["hit"].append(_hit_avg(hsets, actual))
        metrics["baseline_hyena"]["jac"].append(avg_pairwise_jaccard(hsets))

        for ps in POOL_SIZES:
            cov = generate_coverage_sets(pw, nw, wf["shape_profile"], pool_size=ps)
            csets = _sets_from(cov)
            key = f"pool_{ps}"
            metrics[key]["union"].append(float(cov["union_coverage"]))
            metrics[key]["pop"].append(_pop_avg(csets, nw))
            metrics[key]["hit"].append(_hit_avg(csets, actual))
            metrics[key]["jac"].append(avg_pairwise_jaccard(csets))

        f45 = generate_full45_coverage_sets(pw, nw, wf["shape_profile"])
        fsets = _sets_from(f45)
        metrics["full45"]["union"].append(float(f45["union_coverage"]))
        metrics["full45"]["pop"].append(_pop_avg(fsets, nw))
        metrics["full45"]["hit"].append(_hit_avg(fsets, actual))
        metrics["full45"]["jac"].append(avg_pairwise_jaccard(fsets))

        for tag, payload in outputs.items():
            for nums in _sets_from(payload):
                trust_hist[tag].append(
                    round(sum(nw.get(int(n), 0.0) for n in nums), 4)
                )

        evaluated += 1
        co_state.add_draw(actual)

    rows = [
        _summarize(
            "baseline_hyena",
            metrics["baseline_hyena"]["union"],
            metrics["baseline_hyena"]["pop"],
            metrics["baseline_hyena"]["hit"],
            metrics["baseline_hyena"]["jac"],
        )
    ]
    for ps in POOL_SIZES:
        k = f"pool_{ps}"
        rows.append(
            _summarize(
                f"pool{ps}_greedy",
                metrics[k]["union"],
                metrics[k]["pop"],
                metrics[k]["hit"],
                metrics[k]["jac"],
            )
        )
    rows.append(
        _summarize(
            "full45_greedy",
            metrics["full45"]["union"],
            metrics["full45"]["pop"],
            metrics["full45"]["hit"],
            metrics["full45"]["jac"],
        )
    )

    sweet = [
        r
        for r in rows
        if r["label"] != "baseline_hyena"
        and r["union_beats_baseline"]
        and r["pop_maintained"]
    ]
    tradeoff_curve = [
        {
            "label": r["label"],
            "union_pct": r["union_pct"],
            "popularity_sum": r["popularity_sum"],
        }
        for r in rows
    ]

    if sweet:
        best = max(sweet, key=lambda r: (r["union_avg"], r["popularity_sum"]))
        verdict = f"채택 후보 — {best['label']} (union {best['union_avg']}/45, pop {best['popularity_sum']})"
    else:
        verdict = "폐기 — sweet spot 없음. 커버리지↑는 인기↓ 동반 또는 baseline 미달. 4군 완성+1229 봉인 권고"

    result = {
        "evaluated_draws": evaluated,
        "baseline_reference": {
            "union": UNION_BASELINE,
            "popularity": POP_BASELINE,
        },
        "comparison_table": rows,
        "tradeoff_curve": tradeoff_curve,
        "sweet_spot_candidates": sweet,
        "verdict": verdict,
        "r2_honest": (
            "커버리지=번호 분산도(덮기)이며 당첨 가능성 아님. "
            f"적중률 전 구성 무작위 ~{RANDOM_HIT} 수준."
        ),
        "theoretical_union_cap": "5세트×6=30 (Jaccard<0.5 시 실질 상한)",
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    r = run()
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(r, ensure_ascii=False, indent=2))
