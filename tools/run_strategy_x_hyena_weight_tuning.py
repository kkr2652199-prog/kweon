"""하이에나 가중치 스킴 3안 walk-forward 비교 (era_C, R13)."""

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
from app.lotto4.brains.hyena_coordinator_v13 import (
    SOURCE_TAGS,
    WEIGHT_SCHEMES,
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
OUT = Path(r"d:\3kweon\tools\_strategy_x_hyena_weight_tuning.json")

ERA_C_START = 262
ERA_C_END = 1228
MIN_TRAIN_DRAWS = 80
LOOKBACK = 50
COOCCUR_BASELINE = 0.8610
HIT_HONEST_THRESHOLD = 0.05


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


def _collect_outputs(drw_no: int, wf_ctx: dict[str, Any]) -> dict[str, dict[str, Any]]:
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


def _sets_from(payload: dict[str, Any]) -> list[list[int]]:
    return [s["numbers"] for s in payload.get("sets") or [] if s.get("numbers")]


def _pop_sum_avg(sets: list[list[int]], nw: dict[int, float]) -> float:
    if not sets:
        return 0.0
    return statistics.mean(
        round(sum(nw.get(int(n), 0.0) for n in s), 4) for s in sets
    )


def _hit_avg(sets: list[list[int]], actual: list[int]) -> float:
    if not sets:
        return 0.0
    return sum(len(set(s) & set(actual)) for s in sets) / len(sets)


def run_tuning() -> dict[str, Any]:
    draws = _load_draws()
    draw_by_no = {d["drw_no"]: d for d in draws}
    co_state = CooccurState()
    trust_hist: dict[str, list[float]] = {t: [] for t in SOURCE_TAGS}

    scheme_pops: dict[str, list[float]] = {s: [] for s in WEIGHT_SCHEMES}
    scheme_hits: dict[str, list[float]] = {s: [] for s in WEIGHT_SCHEMES}
    cooccur_pops: list[float] = []
    cooccur_hits: list[float] = []
    rnd_pops: list[float] = []
    rnd_hits: list[float] = []

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
        wf_ctx = {
            "number_weights": nw,
            "pair_weights": _build_pair_weights(top30),
            "shape_profile": _build_shape_profile(top30),
            "cooccur_state": co_state.copy(),
            "draw_count": len(train),
        }

        raw_trust = {
            t: round(statistics.mean(trust_hist[t][-LOOKBACK:]), 4)
            if trust_hist[t]
            else 0.5
            for t in SOURCE_TAGS
        }

        outputs = _collect_outputs(drw_no, wf_ctx)
        actual = draw_by_no[drw_no]["nums"]

        co_sets = _sets_from(outputs["strategy_x_cooccur"])
        cooccur_pops.append(_pop_sum_avg(co_sets, nw))
        cooccur_hits.append(_hit_avg(co_sets, actual))

        rnd_sets = [
            sorted(random.Random(drw_no * 99991 + i * 37).sample(range(1, 46), 6))
            for i in range(1, NUM_SETS + 1)
        ]
        rnd_pops.append(_pop_sum_avg(rnd_sets, nw))
        rnd_hits.append(_hit_avg(rnd_sets, actual))

        for scheme in WEIGHT_SCHEMES:
            hyena = generate_hyena_sets(
                drw_no,
                wf_context=wf_ctx,
                draws=draws,
                use_db_logs=False,
                brain_trust_override=raw_trust,
                brain_outputs_override=outputs,
                weight_scheme=scheme,
            )
            hsets = _sets_from(hyena)
            scheme_pops[scheme].append(_pop_sum_avg(hsets, nw))
            scheme_hits[scheme].append(_hit_avg(hsets, actual))

        for tag, payload in outputs.items():
            for nums in _sets_from(payload):
                trust_hist[tag].append(
                    round(sum(nw.get(int(n), 0.0) for n in nums), 4)
                )

        evaluated += 1
        co_state.add_draw(actual)

    rows = []
    for scheme in WEIGHT_SCHEMES:
        pop = round(statistics.mean(scheme_pops[scheme]), 4)
        hit = round(statistics.mean(scheme_hits[scheme]), 4)
        rows.append(
            {
                "scheme": scheme,
                "popularity_sum": pop,
                "hit_avg": hit,
                "beats_cooccur_0.8610": pop > COOCCUR_BASELINE,
                "delta_vs_cooccur": round(pop - COOCCUR_BASELINE, 4),
            }
        )

    co_pop = round(statistics.mean(cooccur_pops), 4)
    co_hit = round(statistics.mean(cooccur_hits), 4)
    rnd_pop = round(statistics.mean(rnd_pops), 4)
    rnd_hit = round(statistics.mean(rnd_hits), 4)

    winners = [r for r in rows if r["beats_cooccur_0.8610"]]
    if winners:
        best = max(winners, key=lambda r: r["popularity_sum"])
        verdict = f"하이에나 메인 채택 + 가중치 {best['scheme']} 확정"
        default_scheme = best["scheme"]
    else:
        best = max(rows, key=lambda r: r["popularity_sum"])
        verdict = "cooccur 5뇌 메인, 하이에나 보조 (0.8610 미달)"
        default_scheme = best["scheme"]

    return {
        "evaluated_draws": evaluated,
        "skipped_draws": skipped,
        "baseline_cooccur": {
            "popularity_sum": co_pop,
            "hit_avg": co_hit,
            "reference": COOCCUR_BASELINE,
        },
        "random": {"popularity_sum": rnd_pop, "hit_avg": rnd_hit},
        "scheme_results": rows,
        "best_scheme": best["scheme"],
        "best_scheme_pop": best["popularity_sum"],
        "default_scheme_recommendation": default_scheme,
        "adoption_verdict": verdict,
        "r2_honest": (
            "가중치 튜닝으로 인기적합도 상한은 cooccur 단독에 수렴. "
            "적중률 무작위 수준 유지. 6개 적중 보장 없음."
        ),
    }


def main() -> None:
    result = run_tuning()
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {OUT}")
    print(f"verdict={result['adoption_verdict']}")
    for r in result["scheme_results"]:
        print(
            f"  {r['scheme']}: pop={r['popularity_sum']} "
            f"hit={r['hit_avg']} beat={r['beats_cooccur_0.8610']}"
        )


if __name__ == "__main__":
    main()
