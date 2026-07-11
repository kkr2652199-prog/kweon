"""4군 전략X 인기신호 정밀정찰 — lotto4_winners_full 적재 + 상관/walk-forward."""
from __future__ import annotations

import json
import math
import sqlite3
import statistics
from pathlib import Path

DB = Path(r"d:\3kweon\data\lotto4.db")
OUT = Path(r"d:\3kweon\tools\_strategy_x_popularity_recon.json")

ERA_A = (1, 87)
ERA_B = (88, 261)
ERA_C = (262, 1228)
MIN_TRAIN = 80  # walk-forward 최소 학습 회차 (era_C 내부)


def era_label(drw_no: int) -> str:
    if drw_no <= ERA_A[1]:
        return "A"
    if drw_no <= ERA_B[1]:
        return "B"
    return "C"


def _decade(n: int) -> int:
    return n // 10


def extract_patterns(nums: list[int]) -> dict:
    s = sorted(nums)
    low_cnt = sum(1 for n in s if n <= 22)
    sum6 = sum(s)
    odd_cnt = sum(1 for n in s if n % 2 == 1)
    decades = [_decade(n) for n in s]
    decade_var = statistics.pvariance(decades) if len(decades) > 1 else 0.0
    tails = [n % 10 for n in s]
    tail_dup = 6 - len(set(tails))

    consec_max = 1
    run = 1
    consec_pairs = 0
    for i in range(1, 6):
        if s[i] == s[i - 1] + 1:
            run += 1
            consec_pairs += 1
            consec_max = max(consec_max, run)
        else:
            run = 1

    return {
        "consec_max": consec_max,
        "consec_pairs": consec_pairs,
        "low_cnt": low_cnt,
        "sum6": sum6,
        "odd_cnt": odd_cnt,
        "decade_var": round(decade_var, 4),
        "tail_dup": tail_dup,
    }


def pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return float("nan")
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mx) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - my) ** 2 for y in ys))
    if den_x == 0 or den_y == 0:
        return float("nan")
    return num / (den_x * den_y)


def rankdata(vals: list[float]) -> list[float]:
    indexed = sorted(enumerate(vals), key=lambda t: t[1])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg_rank
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float:
    return pearson(rankdata(xs), rankdata(ys))


def zscore(val: float, mean: float, std: float) -> float:
    if std == 0:
        return 0.0
    return (val - mean) / std


def step1_load(conn: sqlite3.Connection) -> dict:
    conn.executescript(
        """
        DROP TABLE IF EXISTS lotto4_winners_full;
        CREATE TABLE lotto4_winners_full (
            drw_no INTEGER PRIMARY KEY,
            n1 INTEGER NOT NULL,
            n2 INTEGER NOT NULL,
            n3 INTEGER NOT NULL,
            n4 INTEGER NOT NULL,
            n5 INTEGER NOT NULL,
            n6 INTEGER NOT NULL,
            bonus INTEGER NOT NULL,
            winner_cnt INTEGER NOT NULL,
            prize_per INTEGER NOT NULL,
            era TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        """
    )
    rows = conn.execute(
        """
        SELECT draw_no, num1, num2, num3, num4, num5, num6, bonus,
               first_winners, first_prize
        FROM lotto_draws
        WHERE draw_no BETWEEN 1 AND 1228
        ORDER BY draw_no
        """
    ).fetchall()
    conn.executemany(
        """
        INSERT INTO lotto4_winners_full (
            drw_no, n1, n2, n3, n4, n5, n6, bonus, winner_cnt, prize_per, era
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9],
                era_label(r[0]),
            )
            for r in rows
        ],
    )
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM lotto4_winners_full").fetchone()[0]
    era_counts = {
        e: conn.execute(
            "SELECT COUNT(*) FROM lotto4_winners_full WHERE era = ?", (e,)
        ).fetchone()[0]
        for e in ("A", "B", "C")
    }
    return {
        "source": "lotto_draws (1~1228, 엑셀 미발견 → DB raw 동일 소스)",
        "total_rows": total,
        "era_counts": era_counts,
        "min_drw": conn.execute("SELECT MIN(drw_no) FROM lotto4_winners_full").fetchone()[0],
        "max_drw": conn.execute("SELECT MAX(drw_no) FROM lotto4_winners_full").fetchone()[0],
    }


def step2_patterns(conn: sqlite3.Connection) -> tuple[list[dict], list[dict]]:
    rows = conn.execute(
        """
        SELECT drw_no, n1, n2, n3, n4, n5, n6, bonus, winner_cnt, prize_per, era
        FROM lotto4_winners_full
        ORDER BY drw_no
        """
    ).fetchall()
    enriched = []
    for r in rows:
        nums = [r[1], r[2], r[3], r[4], r[5], r[6]]
        pat = extract_patterns(nums)
        enriched.append(
            {
                "drw_no": r[0],
                "nums": nums,
                "bonus": r[7],
                "winner_cnt": r[8],
                "prize_per": r[9],
                "era": r[10],
                **pat,
            }
        )
    return enriched, enriched[:10]


def step3_correlations(enriched: list[dict]) -> dict:
    era_c = [e for e in enriched if e["era"] == "C" and e["winner_cnt"] > 0]
    features = [
        "consec_max",
        "consec_pairs",
        "low_cnt",
        "sum6",
        "odd_cnt",
        "decade_var",
        "tail_dup",
    ]
    y = [float(e["winner_cnt"]) for e in era_c]
    rows = []
    for f in features:
        x = [float(e[f]) for e in era_c]
        p = pearson(x, y)
        s = spearman(x, y)
        rows.append(
            {
                "feature": f,
                "pearson": round(p, 4),
                "spearman": round(s, 4),
                "abs_pearson": round(abs(p), 4) if not math.isnan(p) else None,
                "abs_spearman": round(abs(s), 4) if not math.isnan(s) else None,
            }
        )
    rows.sort(key=lambda r: max(r["abs_pearson"] or 0, r["abs_spearman"] or 0), reverse=True)
    consec_row = next(r for r in rows if r["feature"] == "consec_pairs")
    return {
        "era": "C",
        "drw_range": f"{ERA_C[0]}~{ERA_C[1]}",
        "analysis_n": len(era_c),
        "excluded_zero_winner": len([e for e in enriched if e["era"] == "C"]) - len(era_c),
        "correlations": rows,
        "consec_pairs_priority": consec_row,
    }


def _popularity_score(
    feat: dict,
    train: list[dict],
    r_pairs: float,
    r_max: float,
) -> float:
    cp_vals = [float(e["consec_pairs"]) for e in train]
    cm_vals = [float(e["consec_max"]) for e in train]
    cp_mean = sum(cp_vals) / len(cp_vals)
    cm_mean = sum(cm_vals) / len(cm_vals)
    cp_std = statistics.pstdev(cp_vals) if len(cp_vals) > 1 else 1.0
    cm_std = statistics.pstdev(cm_vals) if len(cm_vals) > 1 else 1.0
    w_pairs = abs(r_pairs) if not math.isnan(r_pairs) else 0.0
    w_max = abs(r_max) if not math.isnan(r_max) else 0.0
    w_sum = w_pairs + w_max or 1.0
    z_cp = zscore(float(feat["consec_pairs"]), cp_mean, cp_std)
    z_cm = zscore(float(feat["consec_max"]), cm_mean, cm_std)
    return (w_pairs / w_sum) * z_cp + (w_max / w_sum) * z_cm


def step4_walkforward(enriched: list[dict]) -> dict:
    era_c = [e for e in enriched if e["era"] == "C"]
    start_n = ERA_C[0] + MIN_TRAIN
    preds: list[float] = []
    actuals: list[float] = []
    details: list[dict] = []

    for target in era_c:
        n = target["drw_no"]
        if n <= start_n:
            continue
        train = [
            e for e in era_c
            if e["drw_no"] < n and e["winner_cnt"] > 0
        ]
        if len(train) < MIN_TRAIN:
            continue
        y = [float(e["winner_cnt"]) for e in train]
        cp = [float(e["consec_pairs"]) for e in train]
        cm = [float(e["consec_max"]) for e in train]
        r_pairs = pearson(cp, y)
        r_max = pearson(cm, y)
        score = _popularity_score(target, train, r_pairs, r_max)
        preds.append(score)
        actuals.append(float(target["winner_cnt"]))
        if len(details) < 5:
            details.append(
                {
                    "predict_drw": n,
                    "train_n": len(train),
                    "r_consec_pairs": round(r_pairs, 4),
                    "r_consec_max": round(r_max, 4),
                    "pred_score": round(score, 4),
                    "actual_winner_cnt": target["winner_cnt"],
                }
            )

    r_pred = pearson(preds, actuals)
    rho_pred = spearman(preds, actuals)
    abs_r = abs(r_pred) if not math.isnan(r_pred) else 0.0
    verdict = "✅ 인기신호 유효" if abs_r > 0.2 else "❌ 약함, 단순참고"

    return {
        "method": "연속수 가중 인기점수 (consec_pairs·consec_max Pearson 가중 z합)",
        "era": "C",
        "walkforward_range": f"{start_n + 1}~{ERA_C[1]}",
        "min_train": MIN_TRAIN,
        "predictions_n": len(preds),
        "pearson_pred_vs_actual": round(r_pred, 4),
        "spearman_pred_vs_actual": round(rho_pred, 4),
        "abs_pearson": round(abs_r, 4),
        "threshold": 0.2,
        "verdict": verdict,
        "sample_details": details,
    }


def step5_number_popularity(conn: sqlite3.Connection, enriched: list[dict]) -> dict:
    era_c = [e for e in enriched if e["era"] == "C" and e["winner_cnt"] > 0]
    sorted_by_w = sorted(era_c, key=lambda e: e["winner_cnt"], reverse=True)
    k = max(1, int(len(sorted_by_w) * 0.30))
    top30 = sorted_by_w[:k]
    top_draws = {e["drw_no"] for e in top30}

    freq: dict[int, int] = {n: 0 for n in range(1, 46)}
    for e in top30:
        for n in e["nums"]:
            freq[n] += 1

    conn.executescript(
        """
        DROP TABLE IF EXISTS number_popularity;
        CREATE TABLE number_popularity (
            number INTEGER PRIMARY KEY,
            top30_freq INTEGER NOT NULL,
            top30_pct REAL NOT NULL,
            era TEXT NOT NULL DEFAULT 'C',
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        """
    )
    conn.executemany(
        """
        INSERT INTO number_popularity (number, top30_freq, top30_pct, era)
        VALUES (?, ?, ?, 'C')
        """,
        [
            (n, freq[n], round(freq[n] / k, 4))
            for n in range(1, 46)
        ],
    )
    conn.commit()

    ranked = sorted(
        [{"number": n, "top30_freq": freq[n], "top30_pct": round(freq[n] / k, 4)} for n in range(1, 46)],
        key=lambda x: x["top30_freq"],
        reverse=True,
    )
    return {
        "era": "C",
        "top30_draws_n": k,
        "total_valid_era_c": len(era_c),
        "winner_cnt_threshold_top30": top30[-1]["winner_cnt"] if top30 else None,
        "top10": ranked[:10],
        "bottom10": ranked[-10:],
    }


def main() -> None:
    conn = sqlite3.connect(DB)
    try:
        s1 = step1_load(conn)
        enriched, sample10 = step2_patterns(conn)
        s3 = step3_correlations(enriched)
        s4 = step4_walkforward(enriched)
        s5 = step5_number_popularity(conn, enriched)
        out = {
            "step1": s1,
            "step2_sample10": sample10,
            "step3": s3,
            "step4": s4,
            "step5": s5,
        }
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(out, ensure_ascii=False, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
