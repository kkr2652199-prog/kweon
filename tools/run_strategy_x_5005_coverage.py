"""5005 전수 커버리지 최적화 walk-forward 검증 (era_C, R13)."""

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
from app.lotto4.coverage_optimizer_walkforward import (
    COMBO_TOTAL,
    covering_guarantee_analysis,
    generate_coverage_sets,
    pool_hit_count,
    select_top_pool,
    union_coverage,
)

DB = Path(r"d:\3kweon\data\lotto4.db")
OUT = Path(r"d:\3kweon\tools\_strategy_x_5005_coverage.json")

ERA_C_START = 262
ERA_C_END = 1228
MIN_TRAIN_DRAWS = 80
LOOKBACK = 50
TTEST_ALPHA = 0.05
HYENA_BASELINE_POP = 0.8679
HYENA_BASELINE_UNION = 18.75
SCHEME = "cooccur_favor"
RANDOM_HIT = 0.81


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


def run() -> dict[str, Any]:
    draws = _load_draws()
    draw_by_no = {d["drw_no"]: d for d in draws}
    co_state = CooccurState()
    trust_hist: dict[str, list[float]] = {t: [] for t in SOURCE_TAGS}

    base_union: list[float] = []
    base_pop: list[float] = []
    base_hit: list[float] = []
    base_pool_hit: list[float] = []

    cov_union: list[float] = []
    cov_pop: list[float] = []
    cov_hit: list[float] = []
    cov_pool_hit: list[float] = []

    guarantee_samples: list[dict[str, Any]] = []

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
        pool15 = select_top_pool(_hyena_pool_weight(outputs, trust))

        base_union.append(float(union_coverage(hsets)))
        base_pop.append(_pop_avg(hsets, nw))
        base_hit.append(_hit_avg(hsets, actual))
        base_pool_hit.append(float(pool_hit_count(pool15, actual)))

        cov = generate_coverage_sets(
            _hyena_pool_weight(outputs, trust),
            nw,
            wf["shape_profile"],
        )
        csets = _sets_from(cov)
        cov_union.append(float(cov["union_coverage"]))
        cov_pop.append(_pop_avg(csets, nw))
        cov_hit.append(_hit_avg(csets, actual))
        cov_pool_hit.append(float(pool_hit_count(cov["pool_15"], actual)))

        if evaluated < 20 or evaluated % 100 == 0:
            guarantee_samples.append(
                covering_guarantee_analysis(csets, cov["pool_15"])
            )

        for tag, payload in outputs.items():
            for nums in _sets_from(payload):
                trust_hist[tag].append(
                    round(sum(nw.get(int(n), 0.0) for n in nums), 4)
                )

        evaluated += 1
        co_state.add_draw(actual)

    bu = round(statistics.mean(base_union), 2)
    cu = round(statistics.mean(cov_union), 2)
    bp = round(statistics.mean(base_pop), 4)
    cp = round(statistics.mean(cov_pop), 4)
    bh = round(statistics.mean(base_hit), 4)
    ch = round(statistics.mean(cov_hit), 4)
    bph = round(statistics.mean(base_pool_hit), 2)
    cph = round(statistics.mean(cov_pool_hit), 2)

    union_ttest = _paired_ttest(cov_union, base_union)
    pop_ttest = _paired_ttest(cov_pop, base_pop)

    avg_guarantee = {
        "min_guarantee_match_avg": round(
            statistics.mean(
                g["min_guarantee_match"] for g in guarantee_samples
            ),
            2,
        ),
        "rate_4plus_avg": round(
            statistics.mean(
                g["rate_4plus_if_all6_in_pool"] for g in guarantee_samples
            ),
            4,
        ),
        "rate_3plus_avg": round(
            statistics.mean(
                g["rate_3plus_if_all6_in_pool"] for g in guarantee_samples
            ),
            4,
        ),
        "sample_n": len(guarantee_samples),
    }

    union_pct_base = round(100.0 * bu / 45.0, 1)
    union_pct_cov = round(100.0 * cu / 45.0, 1)
    union_lift = round(cu - bu, 2)
    pop_delta = round(cp - bp, 4)

    union_sig = (
        union_lift > 0.5
        and union_ttest.get("p_value", 1.0) < TTEST_ALPHA
        and union_ttest.get("t_stat", 0) > 0
    )
    pop_ok = cp >= bp - 0.005

    if union_sig and pop_ok:
        verdict = "채택 — union 커버리지 유의 상승 + 인기적합도 유지"
    elif union_lift > 0.3 and pop_ok:
        verdict = "보류 — union 소폭 상승, 유의성/형 확인 필요"
    elif union_lift > 0 and not pop_ok:
        verdict = f"trade-off — union +{union_lift} but 인기 {pop_delta}"
    else:
        verdict = "폐기 — union·인기 개선 미달, 현 상태 유지"

    result = {
        "evaluated_draws": evaluated,
        "skipped_draws": skipped,
        "era": "C",
        "step1_army1_readonly": {
            "pool": "합의 점수 상위 15번호 (_select_candidate_pool)",
            "score": "5005 각 조합 consensus 가중 합",
            "selection": "1세트 tier1 통과 최고점, 2~5세트 top50 가중 랜덤+tier1",
            "jaccard": "snake만 0.4 (hyena 5005는 중복회피만)",
            "source": "My_Library/app/lotto/predict_hyena.py, v12_engine.py",
        },
        "step2_coverage_optimizer": {
            "module": "coverage_optimizer_walkforward.py",
            "pool": "5뇌 pool_weight 상위 15",
            "eval": f"15C6={COMBO_TOTAL} 인기적합도 전수",
            "pick": "greedy union 최대화 + 인기 tie-break + shape + Jaccard<0.5",
        },
        "comparison": {
            "baseline_hyena": {
                "union_coverage_avg": bu,
                "union_pct": union_pct_base,
                "popularity_sum": bp,
                "hit_avg": bh,
                "pool15_hit_avg": bph,
            },
            "coverage_5005": {
                "union_coverage_avg": cu,
                "union_pct": union_pct_cov,
                "popularity_sum": cp,
                "hit_avg": ch,
                "pool15_hit_avg": cph,
                "delta_union": union_lift,
                "delta_popularity": pop_delta,
                "delta_pool15_hit": round(cph - bph, 2),
            },
            "paired_ttest_union": union_ttest,
            "paired_ttest_popularity": pop_ttest,
        },
        "step4_covering_guarantee": avg_guarantee,
        "verdict": {
            "summary": verdict,
            "union_significant": union_sig,
            "popularity_maintained": pop_ok,
            "hit_random_level": abs(bh - RANDOM_HIT) <= 0.05
            and abs(ch - RANDOM_HIT) <= 0.05,
        },
        "r2_honest": (
            "5005 greedy는 조합 최적화(덮기)이며 추첨 예측 아님. "
            "적중률 무작위 수준. covering 보장은 15풀⊇당첨6 가정 하 조합론."
        ),
        "next_if_discard": "4군 현 상태 완성, 1229 실전 대기",
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    r = run()
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(r, ensure_ascii=False, indent=2))
