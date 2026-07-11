"""미출현 간격(gap) 신호 walk-forward 타임머신 검증 (era_C, R13)."""

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
from app.lotto4.gap_signal_walkforward import GapState, generate_gap_sets

DB = Path(r"d:\3kweon\data\lotto4.db")
OUT = Path(r"d:\3kweon\tools\_strategy_x_gap_timemachine.json")

ERA_C_START = 262
ERA_C_END = 1228
MIN_TRAIN_DRAWS = 80
LOOKBACK = 50
TTEST_ALPHA = 0.05
HYENA_BASELINE_POP = 0.8679
HYENA_BASELINE_HIT = 0.7916
RANDOM_POP = 0.7988
RANDOM_HIT = 0.81
SCHEME = "cooccur_favor"
GAP_BLENDS = (0.1, 0.15, 0.2, 0.25, 0.3)
ACCUM_EARLY = (262, 600)
ACCUM_LATE = (601, 1228)


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


def run() -> dict[str, Any]:
    draws = _load_draws()
    draw_by_no = {d["drw_no"]: d for d in draws}
    co_state = CooccurState()
    gap_state = GapState()
    trust_hist: dict[str, list[float]] = {t: [] for t in SOURCE_TAGS}

    hyena_pops: list[float] = []
    hyena_hits: list[float] = []
    gap_only_pops: list[float] = []
    gap_only_hits: list[float] = []
    blend_pops: dict[float, list[float]] = {b: [] for b in GAP_BLENDS}
    blend_hits: dict[float, list[float]] = {b: [] for b in GAP_BLENDS}
    blend_early: dict[float, list[float]] = {b: [] for b in GAP_BLENDS}
    blend_late: dict[float, list[float]] = {b: [] for b in GAP_BLENDS}
    hyena_early: list[float] = []
    hyena_late: list[float] = []
    gap_early: list[float] = []
    gap_late: list[float] = []

    evaluated = 0
    skipped = 0

    for drw_no in range(ERA_C_START, ERA_C_END + 1):
        if drw_no not in draw_by_no:
            continue
        train = [d for d in draws if d["drw_no"] < drw_no]
        actual = draw_by_no[drw_no]["nums"]
        if len(train) < MIN_TRAIN_DRAWS:
            skipped += 1
            co_state.add_draw(actual)
            gap_state.add_draw(drw_no, actual)
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
        gaps = gap_state.gaps_at(drw_no)

        hyena = generate_hyena_sets(
            drw_no,
            wf_context=wf,
            draws=draws,
            use_db_logs=False,
            brain_trust_override=trust,
            brain_outputs_override=outputs,
            weight_scheme=SCHEME,
            gap_blend=0.0,
        )
        hsets = _sets_from(hyena)
        hyena_pops.append(_pop_avg(hsets, nw))
        hyena_hits.append(_hit_avg(hsets, actual))

        gap_out = generate_gap_sets(drw_no, gaps=gaps)
        gsets = _sets_from(gap_out)
        gap_only_pops.append(_pop_avg(gsets, nw))
        gap_only_hits.append(_hit_avg(gsets, actual))

        for blend in GAP_BLENDS:
            hg = generate_hyena_sets(
                drw_no,
                wf_context=wf,
                draws=draws,
                use_db_logs=False,
                brain_trust_override=trust,
                brain_outputs_override=outputs,
                weight_scheme=SCHEME,
                gap_blend=blend,
            )
            bsets = _sets_from(hg)
            pop = _pop_avg(bsets, nw)
            blend_pops[blend].append(pop)
            blend_hits[blend].append(_hit_avg(bsets, actual))

        if ACCUM_EARLY[0] <= drw_no <= ACCUM_EARLY[1]:
            hyena_early.append(hyena_pops[-1])
            gap_early.append(gap_only_pops[-1])
            for blend in GAP_BLENDS:
                blend_early[blend].append(blend_pops[blend][-1])
        if ACCUM_LATE[0] <= drw_no <= ACCUM_LATE[1]:
            hyena_late.append(hyena_pops[-1])
            gap_late.append(gap_only_pops[-1])
            for blend in GAP_BLENDS:
                blend_late[blend].append(blend_pops[blend][-1])

        for tag, payload in outputs.items():
            for nums in _sets_from(payload):
                trust_hist[tag].append(
                    round(sum(nw.get(int(n), 0.0) for n in nums), 4)
                )

        evaluated += 1
        co_state.add_draw(actual)
        gap_state.add_draw(drw_no, actual)

    hyena_pop = round(statistics.mean(hyena_pops), 4)
    hyena_hit = round(statistics.mean(hyena_hits), 4)
    gap_pop = round(statistics.mean(gap_only_pops), 4)
    gap_hit = round(statistics.mean(gap_only_hits), 4)

    blend_summary = []
    best_blend = None
    best_blend_pop = -1.0
    for blend in GAP_BLENDS:
        pop = round(statistics.mean(blend_pops[blend]), 4)
        hit = round(statistics.mean(blend_hits[blend]), 4)
        ttest = _paired_ttest(blend_pops[blend], hyena_pops)
        beats_hyena = pop > hyena_pop
        blend_summary.append(
            {
                "gap_blend": blend,
                "popularity_sum": pop,
                "hit_avg": hit,
                "delta_vs_hyena_baseline": round(pop - hyena_pop, 4),
                "beats_hyena_0.8679": beats_hyena,
                "paired_ttest_vs_hyena": ttest,
            }
        )
        if pop > best_blend_pop:
            best_blend_pop = pop
            best_blend = blend

    best_hg = next(x for x in blend_summary if x["gap_blend"] == best_blend)
    gap_vs_hyena_ttest = _paired_ttest(gap_only_pops, hyena_pops)
    hyena_vs_random_hit = abs(hyena_hit - RANDOM_HIT) <= 0.05

    early_h = round(statistics.mean(hyena_early), 4) if hyena_early else None
    late_h = round(statistics.mean(hyena_late), 4) if hyena_late else None
    early_g = round(statistics.mean(gap_early), 4) if gap_early else None
    late_g = round(statistics.mean(gap_late), 4) if gap_late else None

    accum_blend = []
    for blend in GAP_BLENDS:
        e = round(statistics.mean(blend_early[blend]), 4) if blend_early[blend] else None
        l = round(statistics.mean(blend_late[blend]), 4) if blend_late[blend] else None
        accum_blend.append(
            {
                "gap_blend": blend,
                "early_262_600": e,
                "late_601_1228": l,
                "delta_late_minus_early": round(l - e, 4)
                if e is not None and l is not None
                else None,
            }
        )

    best_accum = max(
        (x for x in accum_blend if x["delta_late_minus_early"] is not None),
        key=lambda x: x["delta_late_minus_early"],
        default=None,
    )

    pop_improves = best_hg["beats_hyena_0.8679"] and (
        best_hg["paired_ttest_vs_hyena"]["p_value"] < TTEST_ALPHA
        and best_hg["delta_vs_hyena_baseline"] > 0
    )
    gap_only_improves = gap_pop > hyena_pop

    if pop_improves:
        verdict_6brain = "6뇌 후보 ✅ (hyena+gap 인기 상승)"
    elif gap_only_improves:
        verdict_6brain = "6뇌 후보 검토 (gap 단독만 상승, hyena 혼합 미달)"
    else:
        verdict_6brain = "폐기 — gap 신호 인기적합도 미상승"

    accum_improves = (
        late_h is not None
        and early_h is not None
        and late_h > early_h
        and best_accum is not None
        and best_accum["delta_late_minus_early"] > 0
    )

    result = {
        "evaluated_draws": evaluated,
        "skipped_draws": skipped,
        "era": "C",
        "range": f"{ERA_C_START}~{ERA_C_END}",
        "r13": "draw_no < N 만 gap·trust·cooccur 산출",
        "baseline_hyena_cooccur_favor": {
            "popularity_sum": hyena_pop,
            "hit_avg": hyena_hit,
            "reference_json": HYENA_BASELINE_POP,
        },
        "gap_only": {
            "popularity_sum": gap_pop,
            "hit_avg": gap_hit,
            "delta_vs_hyena": round(gap_pop - hyena_pop, 4),
            "paired_ttest_vs_hyena": gap_vs_hyena_ttest,
        },
        "hyena_plus_gap_blends": blend_summary,
        "best_hyena_gap_blend": best_blend,
        "best_hyena_gap_pop": best_blend_pop,
        "random_reference": {
            "popularity_sum": RANDOM_POP,
            "hit_avg": RANDOM_HIT,
        },
        "accumulation": {
            "hyena_early_262_600": early_h,
            "hyena_late_601_1228": late_h,
            "hyena_delta": round(late_h - early_h, 4)
            if early_h is not None and late_h is not None
            else None,
            "gap_only_early": early_g,
            "gap_only_late": late_g,
            "gap_only_delta": round(late_g - early_g, 4)
            if early_g is not None and late_g is not None
            else None,
            "hyena_plus_gap_by_blend": accum_blend,
            "data_accum_improves_popularity": accum_improves,
        },
        "verdict": {
            "gap_signal_popularity_improves": pop_improves or gap_only_improves,
            "hyena_plus_gap_beats_baseline": pop_improves,
            "six_brain_candidate": verdict_6brain,
            "hit_honest_random_level": hyena_vs_random_hit
            and abs(gap_hit - RANDOM_HIT) <= 0.05
            and abs(best_hg["hit_avg"] - RANDOM_HIT) <= 0.05,
            "accumulation_helps": accum_improves,
        },
        "r2_honest": (
            "gap·hyena+gap 모두 추첨 예측 아님. 인기적합도는 사람 행동(인기) 적합. "
            "적중률은 무작위 수준. 당첨확률 향상 주장 없음."
        ),
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    r = run()
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(r, ensure_ascii=False, indent=2))
