"""죽은 데이터 부활 A/B 검증 — 비인기회피 + 튄쌍이상치 (era_C, R13)."""

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

from app.lotto4.anomaly_pair_signal_walkforward import (
    compute_anomaly_pairs_before,
    precision_at_k,
)
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
from app.lotto4.unpopularity_signal_walkforward import (
    compute_unpopularity_before,
    set_unpopularity_score,
    winner_dispersion_score,
)

DB = Path(r"d:\3kweon\data\lotto4.db")
OUT = Path(r"d:\3kweon\tools\_strategy_x_dead_data_ab.json")

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
BLENDS = (0.1, 0.15, 0.2)
ANOMALY_TOP_K = 50


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


def _summarize(
    label: str,
    pops: list[float],
    hits: list[float],
    baseline_pops: list[float],
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pop = round(statistics.mean(pops), 4) if pops else 0.0
    hit = round(statistics.mean(hits), 4) if hits else 0.0
    base_pop = round(statistics.mean(baseline_pops), 4) if baseline_pops else 0.0
    ttest = _paired_ttest(pops, baseline_pops) if pops and baseline_pops else {}
    row = {
        "label": label,
        "popularity_sum": pop,
        "hit_avg": hit,
        "delta_vs_baseline": round(pop - base_pop, 4),
        "beats_baseline_0.8679": pop > HYENA_BASELINE_POP,
        "paired_ttest_vs_baseline": ttest,
        "significant_improve": (
            pop > base_pop
            and ttest.get("p_value", 1.0) < TTEST_ALPHA
            and ttest.get("t_stat", 0) > 0
        ),
    }
    if extra:
        row.update(extra)
    return row


def run() -> dict[str, Any]:
    draws = _load_draws()
    draw_by_no = {d["drw_no"]: d for d in draws}
    co_state = CooccurState()
    trust_hist: dict[str, list[float]] = {t: [] for t in SOURCE_TAGS}

    baseline_pops: list[float] = []
    baseline_hits: list[float] = []

    unpop_pops: dict[float, list[float]] = {b: [] for b in BLENDS}
    unpop_hits: dict[float, list[float]] = {b: [] for b in BLENDS}
    unpop_disp: dict[float, list[float]] = {b: [] for b in BLENDS}
    unpop_avoid: dict[float, list[float]] = {b: [] for b in BLENDS}

    anom_pops: dict[float, list[float]] = {b: [] for b in BLENDS}
    anom_hits: dict[float, list[float]] = {b: [] for b in BLENDS}
    anom_prec: dict[float, list[float]] = {b: [] for b in BLENDS}

    combo_pops: dict[float, list[float]] = {b: [] for b in BLENDS}
    combo_hits: dict[float, list[float]] = {b: [] for b in BLENDS}

    random_prec_baseline: list[float] = []
    RANDOM_PAIR_PREC = round(15 / 990, 4)  # C(6,2)/C(45,2) 기대값

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
        unpop_profile = compute_unpopularity_before(drw_no, str(DB))
        anomaly_data = compute_anomaly_pairs_before(
            drw_no, str(DB), top_k=ANOMALY_TOP_K
        )

        baseline = generate_hyena_sets(
            drw_no,
            wf_context=wf,
            draws=draws,
            use_db_logs=False,
            brain_trust_override=trust,
            brain_outputs_override=outputs,
            weight_scheme=SCHEME,
        )
        bsets = _sets_from(baseline)
        baseline_pops.append(_pop_avg(bsets, nw))
        baseline_hits.append(_hit_avg(bsets, actual))

        for blend in BLENDS:
            hu = generate_hyena_sets(
                drw_no,
                wf_context=wf,
                draws=draws,
                use_db_logs=False,
                brain_trust_override=trust,
                brain_outputs_override=outputs,
                weight_scheme=SCHEME,
                unpop_blend=blend,
                unpop_profile=unpop_profile,
            )
            usets = _sets_from(hu)
            unpop_pops[blend].append(_pop_avg(usets, nw))
            unpop_hits[blend].append(_hit_avg(usets, actual))
            unpop_disp[blend].append(winner_dispersion_score(usets, unpop_profile))
            unpop_avoid[blend].append(
                statistics.mean(
                    set_unpopularity_score(s, unpop_profile) for s in usets
                )
                if usets
                else 0.0
            )

            ha = generate_hyena_sets(
                drw_no,
                wf_context=wf,
                draws=draws,
                use_db_logs=False,
                brain_trust_override=trust,
                brain_outputs_override=outputs,
                weight_scheme=SCHEME,
                anomaly_blend=blend,
                anomaly_data=anomaly_data,
            )
            asets = _sets_from(ha)
            anom_pops[blend].append(_pop_avg(asets, nw))
            anom_hits[blend].append(_hit_avg(asets, actual))
            anom_prec[blend].append(
                precision_at_k(anomaly_data["top_pairs"], actual, ANOMALY_TOP_K)
            )

            hc = generate_hyena_sets(
                drw_no,
                wf_context=wf,
                draws=draws,
                use_db_logs=False,
                brain_trust_override=trust,
                brain_outputs_override=outputs,
                weight_scheme=SCHEME,
                unpop_blend=blend,
                anomaly_blend=blend,
                unpop_profile=unpop_profile,
                anomaly_data=anomaly_data,
            )
            csets = _sets_from(hc)
            combo_pops[blend].append(_pop_avg(csets, nw))
            combo_hits[blend].append(_hit_avg(csets, actual))

        for tag, payload in outputs.items():
            for nums in _sets_from(payload):
                trust_hist[tag].append(
                    round(sum(nw.get(int(n), 0.0) for n in nums), 4)
                )

        evaluated += 1
        co_state.add_draw(actual)

    base_pop = round(statistics.mean(baseline_pops), 4)
    base_hit = round(statistics.mean(baseline_hits), 4)

    unpop_rows = []
    for blend in BLENDS:
        unpop_rows.append(
            _summarize(
                f"unpop_blend={blend}",
                unpop_pops[blend],
                unpop_hits[blend],
                baseline_pops,
                extra={
                    "winner_dispersion_avg": round(
                        statistics.mean(unpop_disp[blend]), 4
                    ),
                    "crowd_avoidance_avg": round(
                        statistics.mean(unpop_avoid[blend]), 4
                    ),
                },
            )
        )

    anom_rows = []
    for blend in BLENDS:
        prec = round(statistics.mean(anom_prec[blend]), 4)
        anom_rows.append(
            _summarize(
                f"anomaly_blend={blend}",
                anom_pops[blend],
                anom_hits[blend],
                baseline_pops,
                extra={
                    f"precision_at_{ANOMALY_TOP_K}": prec,
                    "random_pair_precision_ref": RANDOM_PAIR_PREC,
                },
            )
        )

    combo_rows = [
        _summarize(
            f"A+B_blend={blend}",
            combo_pops[blend],
            combo_hits[blend],
            baseline_pops,
        )
        for blend in BLENDS
    ]

    best_unpop = max(unpop_rows, key=lambda r: r["popularity_sum"])
    best_anom = max(anom_rows, key=lambda r: r["popularity_sum"])
    best_combo = max(combo_rows, key=lambda r: r["popularity_sum"])

    def _verdict(rows: list[dict], name: str) -> str:
        if any(r["significant_improve"] for r in rows):
            return f"채택 검토 — {name} 인기적합도 유의 상승"
        if any(r["beats_baseline_0.8679"] for r in rows):
            return f"보류 — {name} 절대값은 baseline 초과하나 유의성 없음"
        return f"폐기 — {name} 인기적합도 미상승 (gap 신호 전례)"

    anom_prec_mean = round(
        statistics.mean(
            r[f"precision_at_{ANOMALY_TOP_K}"] for r in anom_rows
        ),
        4,
    )
    random_prec_mean = RANDOM_PAIR_PREC

    result = {
        "evaluated_draws": evaluated,
        "skipped_draws": skipped,
        "era": "C",
        "range": f"{ERA_C_START}~{ERA_C_END}",
        "r13": "draw_no < N 만 tiers·cooccur·trust 산출",
        "baseline_cooccur_favor": {
            "popularity_sum": base_pop,
            "hit_avg": base_hit,
            "reference": HYENA_BASELINE_POP,
        },
        "step_a_unpopularity": unpop_rows,
        "step_b_anomaly_pair": anom_rows,
        "step_ab_combo": combo_rows,
        "best": {
            "unpop": best_unpop,
            "anomaly": best_anom,
            "combo": best_combo,
        },
        "random_reference": {
            "popularity_sum": RANDOM_POP,
            "hit_avg": RANDOM_HIT,
        },
        "verdict": {
            "step_a": _verdict(unpop_rows, "비인기회피"),
            "step_b": _verdict(
                anom_rows,
                "튄쌍이상치",
            ),
            "step_b_precision_honest": (
                f"precision@{ANOMALY_TOP_K}={anom_prec_mean} "
                f"vs random_top{ANOMALY_TOP_K}_ref={random_prec_mean} — "
                + (
                    "무작위 수준(미래 예측력 없음)"
                    if abs(anom_prec_mean - random_prec_mean) < 0.02
                    else "무작위 대비 소폭 차이(정직 재검증 필요)"
                )
            ),
            "step_ab_combo": _verdict(combo_rows, "A+B"),
            "hit_random_level": all(
                abs(r["hit_avg"] - RANDOM_HIT) <= 0.05
                for r in unpop_rows + anom_rows + combo_rows
            ),
        },
        "priority": {
            "adopt_signal": None,
            "discard_signals": [],
            "benchmark_123_next": "2·3군 snake (Jaccard<0.4 차별화)",
        },
        "r2_honest": (
            "비인기·이상치·혼합 모두 추첨 예측 아님. 인기적합도=사람 행동 적합. "
            "적중률 무작위 수준. 당첨확률 향상 주장 없음."
        ),
    }

    if best_unpop["significant_improve"]:
        result["priority"]["adopt_signal"] = "A_unpopularity"
    elif best_anom["significant_improve"]:
        result["priority"]["adopt_signal"] = "B_anomaly_pair"
    elif best_combo["significant_improve"]:
        result["priority"]["adopt_signal"] = "A+B_combo"
    else:
        result["priority"]["discard_signals"] = [
            "A_unpopularity",
            "B_anomaly_pair",
            "A+B_combo",
        ]

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    r = run()
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(r, ensure_ascii=False, indent=2))
