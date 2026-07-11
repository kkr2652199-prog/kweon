"""990쌍 출현 간격·주기성 분석 (R13/R2 — 예측 주장 금지, 통계 검증 전용)."""

from __future__ import annotations

import json
import math
import random
import sqlite3
import statistics
from itertools import combinations
from pathlib import Path
from typing import Any

from app.lotto4.models import LOTTO_DB_PATH

ANALYSIS_DB_DEFAULT = Path(r"d:\3kweon\tools\pair_periodicity_analysis.db")
RANDOM_SIMS = 1000
MIN_GAPS_FOR_TEST = 2
MIN_APPEAR_FOR_WF = 4
P_ALPHA = 0.05


def _pair_key(a: int, b: int) -> tuple[int, int]:
    x, y = int(a), int(b)
    return (x, y) if x < y else (y, x)


def load_all_draws(db_path: str | Path | None = None) -> list[dict[str, Any]]:
    path = str(db_path or LOTTO_DB_PATH)
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute(
            """
            SELECT draw_no, num1, num2, num3, num4, num5, num6
            FROM lotto_draws
            ORDER BY draw_no ASC
            """
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "draw_no": int(r[0]),
            "nums": sorted(int(r[i]) for i in range(1, 7)),
        }
        for r in rows
    ]


def build_pair_gap_series(
    draws: list[dict[str, Any]],
) -> dict[tuple[int, int], dict[str, Any]]:
    """990쌍 전수 — 출현 회차·간격 시계열."""
    appear: dict[tuple[int, int], list[int]] = {
        (a, b): [] for a in range(1, 46) for b in range(a + 1, 46)
    }
    for d in draws:
        dn = int(d["draw_no"])
        for a, b in combinations(d["nums"], 2):
            appear[(a, b)].append(dn)

    out: dict[tuple[int, int], dict[str, Any]] = {}
    for pair, draws_list in appear.items():
        gaps = [
            draws_list[i] - draws_list[i - 1]
            for i in range(1, len(draws_list))
        ]
        out[pair] = {
            "pair": list(pair),
            "appear_draws": draws_list,
            "appear_count": len(draws_list),
            "gaps": gaps,
        }
    return out


def _gap_cv(gaps: list[int]) -> float | None:
    if len(gaps) < MIN_GAPS_FOR_TEST:
        return None
    mean_g = statistics.mean(gaps)
    if mean_g <= 0:
        return None
    sd = statistics.pstdev(gaps) if len(gaps) > 1 else 0.0
    return round(sd / mean_g, 4)


def _autocorr_lag1(gaps: list[float]) -> float | None:
    if len(gaps) < 3:
        return None
    mean_g = statistics.mean(gaps)
    num = sum((gaps[i] - mean_g) * (gaps[i + 1] - mean_g) for i in range(len(gaps) - 1))
    den = sum((g - mean_g) ** 2 for g in gaps)
    if den <= 0:
        return 0.0
    return round(num / den, 4)


def _dominant_period_fft(gaps: list[float]) -> float | None:
    """간격 시계열 단순 DFT — 우세 주기(회차)."""
    n = len(gaps)
    if n < 4:
        return round(statistics.mean(gaps), 2) if gaps else None
    mean_g = statistics.mean(gaps)
    xs = [g - mean_g for g in gaps]
    best_mag = -1.0
    best_period = statistics.mean(gaps)
    for k in range(1, n // 2 + 1):
        re = sum(xs[t] * math.cos(2 * math.pi * k * t / n) for t in range(n))
        im = sum(xs[t] * math.sin(2 * math.pi * k * t / n) for t in range(n))
        mag = re * re + im * im
        if mag > best_mag:
            best_mag = mag
            best_period = n / k
    return round(best_period, 2)


def _simulate_random_gaps(
    appear_count: int,
    max_draw: int,
    rng: random.Random,
) -> list[int]:
    if appear_count <= 1:
        return []
    picks = sorted(rng.sample(range(1, max_draw + 1), appear_count))
    return [picks[i] - picks[i - 1] for i in range(1, len(picks))]


def random_control_pvalue(
    gaps: list[int],
    max_draw: int,
    *,
    n_sims: int = RANDOM_SIMS,
    seed: int = 42,
) -> float | None:
    """실제 간격 CV가 무작위 배치 대비 유의하게 낮은지 (주기성)."""
    real_cv = _gap_cv(gaps)
    if real_cv is None:
        return None
    k = len(gaps) + 1
    rng = random.Random(seed)
    sim_cvs: list[float] = []
    for _ in range(n_sims):
        sim_gaps = _simulate_random_gaps(k, max_draw, rng)
        cv = _gap_cv(sim_gaps)
        if cv is not None:
            sim_cvs.append(cv)
    if not sim_cvs:
        return None
    lower_or_equal = sum(1 for c in sim_cvs if c <= real_cv)
    return round(lower_or_equal / len(sim_cvs), 4)


def analyze_pair_periodicity(
    pair_data: dict[tuple[int, int], dict[str, Any]],
    max_draw: int,
) -> dict[str, Any]:
    """990쌍 주기 지표 + 무작위 대조군 p값."""
    rows: list[dict[str, Any]] = []
    sig_count = 0
    testable = 0

    for pair, info in sorted(pair_data.items()):
        gaps = info["gaps"]
        cv = _gap_cv(gaps)
        gap_f = [float(g) for g in gaps]
        ac1 = _autocorr_lag1(gap_f)
        dom = _dominant_period_fft(gap_f) if gap_f else None
        pval = random_control_pvalue(gaps, max_draw) if gaps else None
        sig = bool(pval is not None and pval < P_ALPHA)
        if pval is not None:
            testable += 1
            if sig:
                sig_count += 1

        rows.append(
            {
                "pair": list(pair),
                "appear_count": info["appear_count"],
                "gap_count": len(gaps),
                "gap_mean": round(statistics.mean(gaps), 2) if gaps else None,
                "gap_cv": cv,
                "autocorr_lag1": ac1,
                "dominant_period": dom,
                "random_sim_p": pval,
                "significant_vs_random": sig,
            }
        )

    cvs = [r["gap_cv"] for r in rows if r["gap_cv"] is not None]
    return {
        "pairs_total": 990,
        "testable_pairs": testable,
        "significant_pairs_p05": sig_count,
        "significant_rate": round(sig_count / max(testable, 1), 4),
        "expected_false_positive_rate": P_ALPHA,
        "cv_mean": round(statistics.mean(cvs), 4) if cvs else None,
        "cv_median": round(statistics.median(cvs), 4) if cvs else None,
        "exponential_cv_reference": 1.0,
        "pair_rows": rows,
    }


def save_analysis_db(
    pair_data: dict[tuple[int, int], dict[str, Any]],
    analysis: dict[str, Any],
    db_path: Path = ANALYSIS_DB_DEFAULT,
) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            DROP TABLE IF EXISTS pair_gap_series;
            CREATE TABLE pair_gap_series (
                num_a INTEGER NOT NULL,
                num_b INTEGER NOT NULL,
                appear_count INTEGER NOT NULL,
                appear_draws TEXT NOT NULL,
                gaps TEXT NOT NULL,
                gap_mean REAL,
                gap_cv REAL,
                autocorr_lag1 REAL,
                dominant_period REAL,
                random_sim_p REAL,
                significant INTEGER NOT NULL,
                PRIMARY KEY (num_a, num_b)
            );
            """
        )
        row_map = {tuple(r["pair"]): r for r in analysis["pair_rows"]}
        insert_rows = []
        for pair, info in pair_data.items():
            meta = row_map.get(pair, {})
            insert_rows.append(
                (
                    pair[0],
                    pair[1],
                    info["appear_count"],
                    json.dumps(info["appear_draws"]),
                    json.dumps(info["gaps"]),
                    meta.get("gap_mean"),
                    meta.get("gap_cv"),
                    meta.get("autocorr_lag1"),
                    meta.get("dominant_period"),
                    meta.get("random_sim_p"),
                    1 if meta.get("significant_vs_random") else 0,
                )
            )
        conn.executemany(
            """
            INSERT INTO pair_gap_series
            (num_a, num_b, appear_count, appear_draws, gaps,
             gap_mean, gap_cv, autocorr_lag1, dominant_period,
             random_sim_p, significant)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            insert_rows,
        )
        conn.commit()
    finally:
        conn.close()


def walkforward_due_pair_precision(
    draws: list[dict[str, Any]],
    *,
    era_start: int = 262,
    era_end: int = 1228,
    min_train: int = 80,
    top_k: int = 50,
    tolerance_ratio: float = 0.25,
) -> dict[str, Any]:
    """N 이전 mean gap 기반 '곧 돌아올' 쌍 precision (R13)."""
    draw_by_no = {d["draw_no"]: d for d in draws}
    hits = 0
    total_k = 0
    random_hits = 0
    evaluated = 0

    for target in range(era_start, era_end + 1):
        if target not in draw_by_no:
            continue
        train = [d for d in draws if d["draw_no"] < target]
        if len(train) < min_train:
            continue

        sub = build_pair_gap_series(train)
        due: list[tuple[float, tuple[int, int]]] = []
        eligible: list[tuple[int, int]] = []
        for pair, info in sub.items():
            if info["appear_count"] < MIN_APPEAR_FOR_WF:
                continue
            gaps = info["gaps"]
            if not gaps:
                continue
            mean_g = statistics.mean(gaps)
            last = info["appear_draws"][-1]
            elapsed = target - last
            if mean_g <= 0:
                continue
            err = abs(elapsed - mean_g) / mean_g
            due_score = max(0.0, 1.0 - err / max(tolerance_ratio, 0.01))
            if due_score > 0:
                due.append((due_score, pair))
            eligible.append(pair)

        due.sort(key=lambda x: (-x[0], x[1]))
        top_pairs = [p for _, p in due[:top_k]]
        actual = set(draw_by_no[target]["nums"])
        for a, b in top_pairs:
            if a in actual and b in actual:
                hits += 1
        total_k += len(top_pairs)

        if eligible:
            rng = random.Random(target)
            rand_pairs = rng.sample(eligible, min(top_k, len(eligible)))
            for a, b in rand_pairs:
                if a in actual and b in actual:
                    random_hits += 1

        evaluated += 1

    prec = round(hits / max(total_k, 1), 4)
    rand_prec = round(random_hits / max(evaluated * min(top_k, 990), 1), 4)
    random_expect = round(15 / 990, 4)

    return {
        "evaluated_draws": evaluated,
        "top_k": top_k,
        "precision_at_k": prec,
        "random_eligible_precision": rand_prec,
        "random_pair_expect": random_expect,
        "beats_random": prec > random_expect + 0.001,
    }


def run_full_analysis(
    db_path: str | Path | None = None,
    *,
    save_db: Path = ANALYSIS_DB_DEFAULT,
    json_out: Path | None = None,
) -> dict[str, Any]:
    draws = load_all_draws(db_path)
    max_draw = max(d["draw_no"] for d in draws) if draws else 0
    pair_data = build_pair_gap_series(draws)
    analysis = analyze_pair_periodicity(pair_data, max_draw)
    save_analysis_db(pair_data, analysis, save_db)

    wf = walkforward_due_pair_precision(draws)

    sig_pairs = [r for r in analysis["pair_rows"] if r["significant_vs_random"]]
    top_sig = sorted(
        sig_pairs,
        key=lambda r: (r["random_sim_p"] or 1.0, -(r["gap_cv"] or 99)),
    )[:15]

    result = {
        "draw_count": len(draws),
        "max_draw_no": max_draw,
        "analysis_db": str(save_db),
        "step_c2_periodicity": {
            "testable_pairs": analysis["testable_pairs"],
            "significant_pairs_p05": analysis["significant_pairs_p05"],
            "significant_rate": analysis["significant_rate"],
            "expected_false_positive_if_random": P_ALPHA,
            "cv_mean": analysis["cv_mean"],
            "cv_median": analysis["cv_median"],
            "exponential_cv_reference": 1.0,
            "verdict_c2": (
                "유의 쌍 비율이 기대 FP(5%)와 유사 → 주기는 착시"
                if analysis["significant_rate"] <= 0.08
                else "일부 쌍 주기성 유의 — C3 예측력 별도 확인"
            ),
            "top_significant_pairs": top_sig,
        },
        "step_c3_walkforward": wf,
        "step_c4_verdict": _c4_verdict(analysis, wf),
    }

    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return result


def _c4_verdict(analysis: dict[str, Any], wf: dict[str, Any]) -> str:
    sig_rate = analysis["significant_rate"]
    sig_n = analysis["significant_pairs_p05"]
    prec = wf["precision_at_k"]
    rand = wf["random_pair_expect"]

    c2_real = sig_rate > 0.10 and sig_n > 20
    c3_predicts = wf["beats_random"] and prec > rand + 0.002

    if c2_real and c3_predicts:
        return "6뇌 후보 검토 — 주기 실재+walk-forward precision 무작위 초과"
    if sig_rate <= 0.08:
        return "폐기 — 주기는 착시 (유의쌍 비율≈기대 FP, C3 precision 무작위 수준)"
    return "폐기 — C2 일부 유의쌍 있으나 C3 예측력 무작위 (주기≠예측)"
