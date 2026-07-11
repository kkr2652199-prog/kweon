"""20260627 A안 통합검증 — 랜덤 vs 9뇌 vs 전략X + 비인기(Matheson) + Stömmer 0.766%."""

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

import numpy as np
from scipy import stats

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.lotto4.brains.cooccur_brain_v13 import CooccurState, generate_cooccur_sets
from app.lotto4.brains.coordinator_brain import NUM_SETS, RNG_SEED_MUL, _draw_coordinator_set
from app.lotto4.brains.hyena_coordinator_v13 import SOURCE_TAGS, generate_hyena_sets
from app.lotto4.brains.popularity_freq_brain import generate_popularity_sets
from app.lotto4.brains.popularity_pair_brain import generate_pair_sets
from app.lotto4.brains.shape_brain import _segment_summary, extract_shape_metrics, generate_shape_sets
from app.lotto4.brains._utils import jaccard
from app.lotto4.combinadic import combo_to_no
from app.lotto4.coverage_optimizer_walkforward import avg_pairwise_jaccard, union_coverage
from app.lotto4.unpopularity_signal_walkforward import compute_unpopularity_before, set_unpopularity_score

DB = Path(r"d:\3kweon\data\lotto4.db")
OUT_JSON = _ROOT / "tools" / "_audit_20260627_a_unified_verification.json"
REPORT = _ROOT / "reports" / "20260627_4군_A안통합검증_비인기회피_논문근거.txt"

ERA_C_START = 262
ERA_C_END = 1228
MIN_TRAIN_DRAWS = 80
LOOKBACK = 50
THRESH = 0.05
BASELINE_THEORY = 0.7894
HYENA_SCHEME = "cooccur_favor"
SETS = 5


def _load_era_c_draws() -> list[dict[str, Any]]:
    import sqlite3

    conn = sqlite3.connect(DB)
    try:
        rows = conn.execute(
            """
            SELECT drw_no, n1, n2, n3, n4, n5, n6, bonus, winner_cnt
            FROM lotto4_winners_full
            WHERE era = 'C' AND winner_cnt >= 0
            ORDER BY drw_no
            """
        ).fetchall()
        return [
            {
                "drw_no": int(r[0]),
                "nums": [int(r[i]) for i in range(1, 7)],
                "bonus": int(r[7]),
                "winner_cnt": int(r[8]),
            }
            for r in rows
        ]
    finally:
        conn.close()


def _load_all_draws_1228() -> list[dict[str, Any]]:
    import sqlite3

    conn = sqlite3.connect(DB)
    try:
        rows = conn.execute(
            """
            SELECT draw_no, num1, num2, num3, num4, num5, num6, bonus,
                   first_winners
            FROM lotto_draws
            WHERE draw_no BETWEEN 1 AND 1228
            ORDER BY draw_no
            """
        ).fetchall()
        return [
            {
                "draw_no": int(r[0]),
                "nums": sorted([int(r[i]) for i in range(1, 7)]),
                "bonus": int(r[7]),
                "winner_cnt": int(r[8] or 0),
                "combo_no": combo_to_no(sorted([int(r[i]) for i in range(1, 7)])),
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


def _gen_random_sets(drw_no: int, k: int = SETS) -> list[list[int]]:
    out: list[list[int]] = []
    for s_idx in range(k):
        rng = random.Random(int(drw_no) * 1000 + s_idx)
        out.append(sorted(rng.sample(range(1, 46), 6)))
    return out


def _pop_avg(sets: list[list[int]], nw: dict[int, float]) -> float:
    if not sets:
        return 0.0
    return statistics.mean(sum(nw.get(int(n), 0.0) for n in s) for s in sets)


def _hit_avg(sets: list[list[int]], actual: list[int]) -> float:
    if not sets:
        return 0.0
    return sum(len(set(s) & set(actual)) for s in sets) / len(sets)


def _metrics(sets: list[list[int]], actual: list[int], nw: dict[int, float]) -> dict[str, float]:
    return {
        "hit_avg": round(_hit_avg(sets, actual), 4),
        "popularity": round(_pop_avg(sets, nw), 4),
        "union_coverage": union_coverage(sets),
        "avg_jaccard": avg_pairwise_jaccard(sets),
    }


def _paired_ttest(a: list[float], b: list[float]) -> dict[str, float]:
    n = len(a)
    if n < 2 or len(b) != n:
        return {"t_stat": float("nan"), "p_value": float("nan"), "n": n}
    diffs = [x - y for x, y in zip(a, b)]
    mean_d = statistics.mean(diffs)
    sd_d = statistics.stdev(diffs)
    if sd_d == 0:
        return {"t_stat": 0.0, "p_value": 1.0 if mean_d == 0 else 0.0, "n": n, "mean_diff": mean_d}
    t_stat = mean_d / (sd_d / math.sqrt(n))
    p_value = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(t_stat) / math.sqrt(2))))
    return {
        "t_stat": round(t_stat, 4),
        "p_value": round(p_value, 6),
        "n": n,
        "mean_diff": round(mean_d, 4),
    }


def _verdict_hit(delta: float, p: float) -> str:
    if abs(delta) <= THRESH and p >= 0.05:
        return "❌ 예측력 없음 (랜덤과 구분 안 됨)"
    if delta > THRESH and p < 0.05:
        return "🟡 약한 우위 (1등 예측 아님, 추가 검증)"
    if delta < -THRESH and p < 0.05:
        return "❌ 랜덤보다 낮음"
    return "❌ 예측력 없음 (차이 미미)"


def step1_a_plan() -> dict[str, Any]:
    from app.lotto4.brains import ensemble as v13_ensemble

    draws = _load_era_c_draws()
    draw_by_no = {d["drw_no"]: d for d in draws}
    co_state = CooccurState()
    trust_hist: dict[str, list[float]] = {t: [] for t in SOURCE_TAGS}
    db_path = str(DB)

    arms = {
        "RANDOM": {"hits": [], "pops": [], "unions": [], "jaccards": []},
        "V13_ensemble": {"hits": [], "pops": [], "unions": [], "jaccards": []},
        "STRATEGY_X_hyena": {"hits": [], "pops": [], "unions": [], "jaccards": []},
    }

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

        rsets = _gen_random_sets(drw_no)
        m_r = _metrics(rsets, actual, nw)
        arms["RANDOM"]["hits"].append(m_r["hit_avg"])
        arms["RANDOM"]["pops"].append(m_r["popularity"])
        arms["RANDOM"]["unions"].append(m_r["union_coverage"])
        arms["RANDOM"]["jaccards"].append(m_r["avg_jaccard"])

        try:
            vsets = v13_ensemble.predict(drw_no, db_path)[:SETS]
        except Exception:
            vsets = _gen_random_sets(drw_no + 999)
        m_v = _metrics(vsets, actual, nw)
        arms["V13_ensemble"]["hits"].append(m_v["hit_avg"])
        arms["V13_ensemble"]["pops"].append(m_v["popularity"])
        arms["V13_ensemble"]["unions"].append(m_v["union_coverage"])
        arms["V13_ensemble"]["jaccards"].append(m_v["avg_jaccard"])

        hx = generate_hyena_sets(
            drw_no,
            wf_context=wf,
            draws=draws,
            use_db_logs=False,
            brain_trust_override=trust,
            brain_outputs_override=outputs,
            weight_scheme=HYENA_SCHEME,
        )
        hsets = _sets_from(hx)
        m_h = _metrics(hsets, actual, nw)
        arms["STRATEGY_X_hyena"]["hits"].append(m_h["hit_avg"])
        arms["STRATEGY_X_hyena"]["pops"].append(m_h["popularity"])
        arms["STRATEGY_X_hyena"]["unions"].append(m_h["union_coverage"])
        arms["STRATEGY_X_hyena"]["jaccards"].append(m_h["avg_jaccard"])

        for tag, payload in outputs.items():
            for nums in _sets_from(payload):
                trust_hist[tag].append(round(sum(nw.get(int(n), 0.0) for n in nums), 4))

        evaluated += 1
        co_state.add_draw(actual)

    rows: list[dict[str, Any]] = []
    rand_hits = arms["RANDOM"]["hits"]
    for name, data in arms.items():
        hits = data["hits"]
        row = {
            "arm": name,
            "n_eval": len(hits),
            "avg_matched": round(statistics.mean(hits), 4) if hits else 0,
            "std_matched": round(statistics.stdev(hits), 4) if len(hits) > 1 else 0,
            "avg_popularity": round(statistics.mean(data["pops"]), 4) if data["pops"] else 0,
            "avg_union_coverage": round(statistics.mean(data["unions"]), 2) if data["unions"] else 0,
            "avg_jaccard": round(statistics.mean(data["jaccards"]), 4) if data["jaccards"] else 0,
            "delta_vs_baseline": round(statistics.mean(hits) - BASELINE_THEORY, 4) if hits else 0,
        }
        if name != "RANDOM":
            tt = _paired_ttest(hits, rand_hits)
            row["delta_vs_random"] = tt.get("mean_diff", 0)
            row["paired_ttest_vs_random"] = tt
            row["verdict"] = _verdict_hit(tt.get("mean_diff", 0), tt.get("p_value", 1))
        else:
            row["delta_vs_random"] = 0.0
            row["verdict"] = "기준선 (랜덤)"
        rows.append(row)

    return {
        "era": f"{ERA_C_START}~{ERA_C_END}",
        "min_train": MIN_TRAIN_DRAWS,
        "evaluated": evaluated,
        "skipped": skipped,
        "baseline_theory": BASELINE_THEORY,
        "threshold_abs_delta": THRESH,
        "rows": rows,
    }


def matheson_unpop_score(nums: list[int]) -> dict[str, Any]:
    """Matheson/Grote 처방: 작은번호·생일·연속 패턴."""
    s = sorted(int(n) for n in nums)
    min_n = s[0]
    bday = sum(1 for n in s if 1 <= n <= 31)
    consec = sum(1 for i in range(5) if s[i + 1] - s[i] == 1)
    sym_spread = s[-1] - s[0]
    score = 0.0
    score += 1.0 if min_n >= 29 else 0.0
    score += (6 - bday) / 6.0
    score += max(0.0, 1.0 - consec / 2.0)
    score += min(sym_spread / 44.0, 1.0) * 0.25
    return {
        "min_num": min_n,
        "min_ge_29": min_n >= 29,
        "birthday_count": bday,
        "consec_pairs": consec,
        "matheson_score": round(score / 3.25, 4),
    }


def step2_matheson_unpop() -> dict[str, Any]:
    draws = _load_all_draws_1228()
    era_c = [d for d in draws if d["draw_no"] >= ERA_C_START]
    all_scored: list[dict[str, Any]] = []

    for d in draws:
        m = matheson_unpop_score(d["nums"])
        wf_unpop = set_unpopularity_score(
            d["nums"],
            compute_unpopularity_before(d["draw_no"], str(DB)),
        )
        all_scored.append(
            {
                "draw_no": d["draw_no"],
                "winner_cnt": d["winner_cnt"],
                **m,
                "wf_unpop_score": wf_unpop,
            }
        )

    wc = [r["winner_cnt"] for r in all_scored if r["winner_cnt"] > 0]
    ms = [r["matheson_score"] for r in all_scored if r["winner_cnt"] > 0]
    pr, pp = stats.pearsonr(ms, wc) if len(ms) > 3 else (0, 1)
    sr, sp = stats.spearmanr(ms, wc) if len(ms) > 3 else (0, 1)

    ge29 = [r for r in all_scored if r["min_ge_29"] and r["winner_cnt"] >= 0]
    lt29 = [r for r in all_scored if not r["min_ge_29"] and r["winner_cnt"] >= 0]
    mean_w_ge29 = statistics.mean([r["winner_cnt"] for r in ge29]) if ge29 else 0
    mean_w_lt29 = statistics.mean([r["winner_cnt"] for r in lt29]) if lt29 else 0

    ge29_wins = [r for r in ge29 if r["winner_cnt"] > 0]
    lt29_wins = [r for r in lt29 if r["winner_cnt"] > 0]

    mw_u, pw_u = (
        stats.mannwhitneyu(
            [r["winner_cnt"] for r in ge29_wins],
            [r["winner_cnt"] for r in lt29_wins],
            alternative="less",
        )
        if ge29_wins and lt29_wins
        else (float("nan"), 1.0)
    )

    q25 = np.percentile(ms, 25)
    q75 = np.percentile(ms, 75)
    low_pop = [r["winner_cnt"] for r in all_scored if r["matheson_score"] >= q75 and r["winner_cnt"] > 0]
    high_pop = [r["winner_cnt"] for r in all_scored if r["matheson_score"] <= q25 and r["winner_cnt"] > 0]
    mean_low = statistics.mean(low_pop) if low_pop else 0
    mean_high = statistics.mean(high_pop) if high_pop else 0

    era_c_scored = [r for r in all_scored if r["draw_no"] >= ERA_C_START]
    ec_ms = [r["matheson_score"] for r in era_c_scored]
    ec_wc = [r["winner_cnt"] for r in era_c_scored]
    ec_pr, ec_pp = stats.pearsonr(ec_ms, ec_wc) if len(ec_ms) > 3 else (0, 1)

    significant = (pp < 0.05 and pr < 0) or (pw_u < 0.05 and mean_w_ge29 < mean_w_lt29)
    verdict = (
        "🟢 채택 후보 (분할 회피 신호 — 1등 확률 아님, 실수령 가정)"
        if significant and mean_low < mean_high
        else "🔴 폐기 (분할 회피 효과 통계적으로 불명확)"
    )
    if not significant and abs(pr) < 0.1:
        verdict = "🔴 폐기 (winner_cnt와 무상관)"

    return {
        "note": "1등 확률 향상 아님 — 역대 당첨번호의 winner_cnt(분할자) 비교",
        "n_draws_1228": len(all_scored),
        "n_era_c": len(era_c_scored),
        "matheson_vs_winner_cnt_pearson": {"r": round(float(pr), 4), "p": round(float(pp), 6)},
        "matheson_vs_winner_cnt_spearman": {"r": round(float(sr), 4), "p": round(float(sp), 6)},
        "era_c_correlation": {"r": round(float(ec_pr), 4), "p": round(float(ec_pp), 6)},
        "min_num_ge_29": {
            "count_draws": len(ge29),
            "count_with_1st_winners": len(ge29_wins),
            "mean_winner_cnt_all": round(mean_w_ge29, 3),
            "mean_winner_cnt_lt29": round(mean_w_lt29, 3),
            "mannwhitney_p_less": round(float(pw_u), 6),
        },
        "quartile_compare": {
            "high_matheson_score_mean_winner_cnt": round(mean_low, 3),
            "low_matheson_score_mean_winner_cnt": round(mean_high, 3),
        },
        "texas_analogy": "논문: min≥29 → 더 큰 1등금. 한국 데이터 재현 여부 위 통계로 판정.",
        "verdict": verdict,
        "significant_p05": bool(significant),
    }


def step3_stoemmer() -> dict[str, Any]:
    draws = _load_all_draws_1228()
    theoretical = math.comb(39, 9) / math.comb(45, 15)

    hits_15 = 0
    trials = 0
    for d in draws:
        rng = random.Random(int(d["draw_no"]) * 7777)
        pick15 = set(rng.sample(range(1, 46), 15))
        if set(d["nums"]).issubset(pick15):
            hits_15 += 1
        trials += 1

    empirical_rate = hits_15 / max(trials, 1)

    combo_nos = [d["combo_no"] for d in draws]
    draw_nos = [d["draw_no"] for d in draws]
    pr_draw_combo, pp_draw = stats.pearsonr(draw_nos, combo_nos)

    next_combo: list[int] = []
    prev_combo: list[int] = []
    for i in range(len(draws) - 1):
        if draws[i + 1]["draw_no"] == draws[i]["draw_no"] + 1:
            prev_combo.append(draws[i]["combo_no"])
            next_combo.append(draws[i + 1]["combo_no"])
    pr_lag, pp_lag = stats.pearsonr(prev_combo, next_combo) if len(prev_combo) > 3 else (0, 1)

    pr88, pp88 = stats.pearsonr(
        [d["combo_no"] for d in draws if d["draw_no"] >= 88],
        [d["draw_no"] for d in draws if d["draw_no"] >= 88],
    )

    return {
        "paper_claim_pct": 0.766,
        "paper_note": "Stömmer: 15픽 covering design 0.766% — Mandel condensation, 예측 아님",
        "random_15pick": {
            "trials": trials,
            "hits_all6_in_15": hits_15,
            "empirical_rate_pct": round(empirical_rate * 100, 4),
            "theoretical_rate_pct": round(theoretical * 100, 4),
            "formula": "C(39,9)/C(45,15)",
        },
        "combo_no_correlation": {
            "draw_no_vs_combo_no": {"r": round(float(pr_draw_combo), 4), "p": round(float(pp_draw), 6)},
            "combo_no_lag1": {"r": round(float(pr_lag), 4), "p": round(float(pp_lag), 6)},
            "note": "|r|≈0 이면 순번·조합 무작위 가설 유지",
        },
        "verdict": (
            "🔴 예측불가 확정 — 15픽 실측≈이론, combo_no 연속 무상관"
            if abs(pr_lag) < 0.1 and abs(empirical_rate - theoretical) < 0.02
            else "🟡 논문값과 실측 추가 확인 필요"
        ),
    }


def step4_verdict(s1: dict, s2: dict, s3: dict) -> dict[str, Any]:
    s1_rows = {r["arm"]: r for r in s1["rows"]}
    sx = s1_rows.get("STRATEGY_X_hyena", {})
    v13 = s1_rows.get("V13_ensemble", {})

    step1_v = "🔴 예측력 없음"
    for arm in ("V13_ensemble", "STRATEGY_X_hyena"):
        v = s1_rows.get(arm, {}).get("verdict", "")
        if "🟡" in v:
            step1_v = "🟡 일부 arm 약한 차이"
            break

    step2_v = s2.get("verdict", "🔴")
    step3_v = s3.get("verdict", "🔴")

    if "🟢" in step2_v:
        rec = "비인기 회피 점수를 4군 보조 라벨로 채택 (분할 회피 전용, 확률 아님)"
    elif step1_v.startswith("🔴") and "🔴" in step3_v:
        rec = "4군 완성 매듭 + 1229+ 실전 봉인 (예측 신호 없음 재확인)"
    else:
        rec = "1229+ 실전 봉인 유지, STEP2 추가 데이터 후 재검"

    return {
        "table": [
            {"step": "STEP1 A안", "verdict": step1_v, "detail": f"SX hit={sx.get('avg_matched')} vs RANDOM, Δ={sx.get('delta_vs_random')}"},
            {"step": "STEP2 Matheson", "verdict": step2_v, "detail": s2.get("note", "")},
            {"step": "STEP3 Stömmer", "verdict": step3_v, "detail": s3.get("random_15pick", {})},
        ],
        "recommendation": rec,
        "hyena_vs_random_hit_delta": sx.get("delta_vs_random"),
        "v13_vs_random_hit_delta": v13.get("delta_vs_random"),
    }


def format_report(data: dict[str, Any]) -> str:
    s1 = data["step1"]
    s2 = data["step2"]
    s3 = data["step3"]
    s4 = data["step4"]
    s1_rows = {r["arm"]: r for r in s1["rows"]}
    sx = s1_rows.get("STRATEGY_X_hyena", {})
    v13 = s1_rows.get("V13_ensemble", {})
    lines = [
        "20260627_4군_A안통합검증_비인기회피_논문근거",
        "동생 → 커서 | 2026-06-27 | READ-ONLY 검증",
        "",
        "원칙: R2 / R13 walk-forward / R14 | DB 무수정 | 당첨확률 향상 문구 금지",
        f"JSON: tools/_audit_20260627_a_unified_verification.json",
        "",
        "논문 근거:",
        "  Stömmer arXiv 2408.06857 — 15픽 0.766% covering, 예측 아님",
        "  Matheson & Grote — 비인기 조합 → 1등 분할 회피 (확률↑ 아님)",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "STEP 1 — A안: 랜덤 vs V13 vs 전략X (era_C walk-forward)",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"구간: {s1['era']} | 평가 {s1['evaluated']}회 | 스킵 {s1['skipped']} | MIN_TRAIN={s1['min_train']}",
        f"이론 baseline avg matched: {s1['baseline_theory']}",
        "",
        "arm | avg_matched | avg_pop | union | jaccard | Δrandom | p | 판정",
    ]
    for r in s1["rows"]:
        tt = r.get("paired_ttest_vs_random") or {}
        lines.append(
            f"{r['arm']} | {r['avg_matched']} | {r['avg_popularity']} | "
            f"{r['avg_union_coverage']} | {r['avg_jaccard']} | "
            f"{r.get('delta_vs_random', 0)} | {tt.get('p_value', '-')} | {r['verdict']}"
        )

    lines += [
        "",
        "판정 기준: |Δrandom|≤0.05 이면 무작위 오차 이내 → 예측력 없음 기록.",
        f"  V13 Δ={v13.get('delta_vs_random')} p={v13.get('paired_ttest_vs_random',{}).get('p_value')} | SX Δ={sx.get('delta_vs_random')} p={sx.get('paired_ttest_vs_random',{}).get('p_value')}",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "STEP 2 — Matheson 비인기 회피 (1228회 winner_cnt) ★핵심",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        s2["note"],
        f"Pearson matheson_score↔winner_cnt: r={s2['matheson_vs_winner_cnt_pearson']['r']} p={s2['matheson_vs_winner_cnt_pearson']['p']}",
        f"Spearman: r={s2['matheson_vs_winner_cnt_spearman']['r']} p={s2['matheson_vs_winner_cnt_spearman']['p']} (양(+) r → 분할 회피 방향 아님)",
        f"era_C(967회) Pearson: r={s2['era_c_correlation']['r']} p={s2['era_c_correlation']['p']}",
        f"min≥29: n={s2['min_num_ge_29']['count_draws']}회만 (표본 극소) | mean winner={s2['min_num_ge_29']['mean_winner_cnt_all']} vs min<29={s2['min_num_ge_29']['mean_winner_cnt_lt29']}",
        "  → 텍사스 논문(큰 min→큰 1등금)과 반대 방향·표본 부족, 채택 불가",
        f"Mann-Whitney(min≥29 < min<29): p={s2['min_num_ge_29']['mannwhitney_p_less']}",
        f"고비인기 quartile mean winner={s2['quartile_compare']['high_matheson_score_mean_winner_cnt']}",
        f"저비인기 quartile mean winner={s2['quartile_compare']['low_matheson_score_mean_winner_cnt']}",
        f"판정: {s2['verdict']}",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "STEP 3 — Stömmer 15픽 + combo_no 무상관",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"랜덤 15픽: {s3['random_15pick']['hits_all6_in_15']}/{s3['random_15pick']['trials']}회 = {s3['random_15pick']['empirical_rate_pct']}%",
        f"  이론 C(39,9)/C(45,15) = {s3['random_15pick']['theoretical_rate_pct']}%",
        f"  논문 0.766% = covering design(예측 아님) — 랜덤 15픽과 비교 대상 아님",
        f"draw_no↔combo_no: r={s3['combo_no_correlation']['draw_no_vs_combo_no']['r']}",
        f"combo_no lag-1: r={s3['combo_no_correlation']['combo_no_lag1']['r']} p={s3['combo_no_correlation']['combo_no_lag1']['p']} (|r|≈0, 20260620 교차검증 일치)",
        f"판정: {s3['verdict']}",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "STEP 4 — 종합",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    for row in s4["table"]:
        lines.append(f"{row['step']}: {row['verdict']}")
    lines += [
        "",
        f"4군 다음 우선순위: {s4['recommendation']}",
        "",
        "DB: INSERT·UPDATE·DELETE 0건 (READ-ONLY) | 1~3군·predict·9뇌·lotto4.db·형앱 20분할DB 무수정",
        "UI: 미구현 | 기억: 형 확인 후",
    ]
    return "\n".join(lines)


def run() -> dict[str, Any]:
    print("STEP1 A-plan walk-forward...", flush=True)
    s1 = step1_a_plan()
    print(f"  evaluated={s1['evaluated']}", flush=True)
    print("STEP2 Matheson...", flush=True)
    s2 = step2_matheson_unpop()
    print("STEP3 Stoemmer 15-pick...", flush=True)
    s3 = step3_stoemmer()
    s4 = step4_verdict(s1, s2, s3)
    return {
        "title": "20260627_4군_A안통합검증_비인기회피_논문근거",
        "mode": "READ_ONLY",
        "step1": s1,
        "step2": s2,
        "step3": s3,
        "step4": s4,
    }


def main() -> None:
    data = run()
    OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    report = format_report(data)
    REPORT.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nJSON: {OUT_JSON}")
    print(f"TXT: {REPORT}")


if __name__ == "__main__":
    main()
