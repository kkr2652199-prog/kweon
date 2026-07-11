"""4군 비인기 전략 기반분석 정찰 — lotto4_winners 적재 + 상관 분석."""
from __future__ import annotations

import json
import math
import sqlite3
import statistics
from pathlib import Path

DB = Path(r"d:\3kweon\data\lotto4.db")
OUT = Path(r"d:\3kweon\tools\_unpopular_recon_result.json")


def _decade_bucket(n: int) -> int:
    if n <= 9:
        return 0
    if n <= 19:
        return 1
    if n <= 29:
        return 2
    if n <= 39:
        return 3
    return 4


def extract_features(nums: list[int]) -> dict:
    s = sorted(nums)
    low_count = sum(1 for n in s if n <= 31)
    high_count = 6 - low_count
    odd_count = sum(1 for n in s if n % 2 == 1)
    sum6 = sum(s)
    decades = len({_decade_bucket(n) for n in s})
    tails = [n % 10 for n in s]
    tail_dup = 6 - len(set(tails))
    gaps = [s[i + 1] - s[i] for i in range(5)]
    gap_var = statistics.pvariance(gaps) if len(gaps) > 1 else 0.0
    consec_max = 1
    run = 1
    for i in range(1, 6):
        if s[i] == s[i - 1] + 1:
            run += 1
            consec_max = max(consec_max, run)
        else:
            run = 1
    return {
        "low_count": low_count,
        "high_count": high_count,
        "consec_max": consec_max,
        "sum6": sum6,
        "odd_count": odd_count,
        "decade_spread": decades,
        "tail_dup": tail_dup,
        "gap_var": round(gap_var, 4),
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


def step0(conn: sqlite3.Connection) -> dict:
    conn.executescript(
        """
        DROP TABLE IF EXISTS lotto4_winners;
        CREATE TABLE lotto4_winners (
            draw_no INTEGER PRIMARY KEY,
            draw_date TEXT,
            num1 INTEGER NOT NULL,
            num2 INTEGER NOT NULL,
            num3 INTEGER NOT NULL,
            num4 INTEGER NOT NULL,
            num5 INTEGER NOT NULL,
            num6 INTEGER NOT NULL,
            bonus INTEGER NOT NULL,
            winner_count INTEGER NOT NULL,
            prize_per_game INTEGER NOT NULL,
            total_sales INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        """
    )
    conn.execute(
        """
        INSERT INTO lotto4_winners (
            draw_no, draw_date, num1, num2, num3, num4, num5, num6, bonus,
            winner_count, prize_per_game, total_sales
        )
        SELECT draw_no, draw_date, num1, num2, num3, num4, num5, num6, bonus,
               first_winners, first_prize, total_sales
        FROM lotto_draws
        WHERE draw_no BETWEEN 1 AND 1225
        ORDER BY draw_no
        """
    )
    conn.commit()
    cnt = conn.execute("SELECT COUNT(*) FROM lotto4_winners").fetchone()[0]
    mn, mx = conn.execute(
        "SELECT MIN(draw_no), MAX(draw_no) FROM lotto4_winners"
    ).fetchone()
    zero_rows = conn.execute(
        "SELECT draw_no FROM lotto4_winners WHERE winner_count = 0 ORDER BY draw_no"
    ).fetchall()
    return {
        "count": cnt,
        "min_draw": mn,
        "max_draw": mx,
        "zero_winner_draws": [r[0] for r in zero_rows],
        "zero_winner_count": len(zero_rows),
    }


def step1(conn: sqlite3.Connection) -> tuple[list[dict], list[dict]]:
    rows = conn.execute(
        """
        SELECT draw_no, num1, num2, num3, num4, num5, num6, bonus,
               winner_count, prize_per_game
        FROM lotto4_winners
        ORDER BY draw_no
        """
    ).fetchall()
    enriched: list[dict] = []
    for r in rows:
        nums = [r[1], r[2], r[3], r[4], r[5], r[6]]
        feat = extract_features(nums)
        enriched.append(
            {
                "draw_no": r[0],
                "nums": nums,
                "bonus": r[7],
                "winner_count": r[8],
                "prize_per_game": r[9],
                **feat,
            }
        )
    return enriched, enriched[:10]


def step2(enriched: list[dict]) -> dict:
    features = [
        "low_count",
        "high_count",
        "consec_max",
        "sum6",
        "odd_count",
        "decade_spread",
        "tail_dup",
        "gap_var",
    ]
    valid = [e for e in enriched if e["winner_count"] > 0]
    y = [float(e["winner_count"]) for e in valid]
    corr_rows = []
    for f in features:
        x = [float(e[f]) for e in valid]
        corr_rows.append(
            {
                "feature": f,
                "pearson": round(pearson(x, y), 4),
                "spearman": round(spearman(x, y), 4),
                "n": len(valid),
            }
        )

    sorted_by_w = sorted(valid, key=lambda e: e["winner_count"])
    n = len(sorted_by_w)
    k = max(1, n // 10)
    bottom = sorted_by_w[:k]
    top = sorted_by_w[-k:]

    def avg_group(group: list[dict], key: str) -> float:
        return round(sum(e[key] for e in group) / len(group), 4)

    compare = []
    for f in features:
        compare.append(
            {
                "feature": f,
                "bottom10_avg": avg_group(bottom, f),
                "top10_avg": avg_group(top, f),
                "delta_top_minus_bottom": round(
                    avg_group(top, f) - avg_group(bottom, f), 4
                ),
            }
        )

    return {
        "analysis_n": n,
        "excluded_zero_winner": len(enriched) - n,
        "bottom10_pct_n": k,
        "top10_pct_n": k,
        "bottom10_winner_range": [
            bottom[0]["winner_count"],
            bottom[-1]["winner_count"],
        ],
        "top10_winner_range": [top[0]["winner_count"], top[-1]["winner_count"]],
        "correlations": corr_rows,
        "decile_compare": compare,
    }


def step3(corr_rows: list[dict]) -> dict:
    popularity_weights = []
    unpopularity_weights = []
    for row in corr_rows:
        p = row["pearson"]
        if math.isnan(p):
            continue
        if p > 0.05:
            popularity_weights.append(
                {"feature": row["feature"], "pearson": p, "role": "인기(+)"}
            )
        elif p < -0.05:
            unpopularity_weights.append(
                {"feature": row["feature"], "pearson": p, "role": "비인기(-)"}
            )

    # 초안: pearson 절대값 정규화 가중합 (과거 편향 일치도만)
    pos = [(r["feature"], abs(r["pearson"])) for r in popularity_weights]
    neg = [(r["feature"], abs(r["pearson"])) for r in unpopularity_weights]
    pos_sum = sum(w for _, w in pos) or 1.0
    neg_sum = sum(w for _, w in neg) or 1.0

    formula_terms = []
    for feat, w in pos:
        formula_terms.append(f"+ ({w/pos_sum:.3f}) * z({feat})")
    for feat, w in neg:
        formula_terms.append(f"- ({w/neg_sum:.3f}) * z({feat})")

    formula = (
        "unpopular_bias_score(combo) = "
        + " ".join(formula_terms)
        if formula_terms
        else "unpopular_bias_score = (상관 유의미 특징 없음 — 추가 정찰 필요)"
    )

    return {
        "popularity_features": popularity_weights,
        "unpopularity_features": unpopularity_weights,
        "draft_formula": formula,
        "note": "과거 당첨 조합이 '인기 편향'과 얼마나 일치했는지의 회귀적 점수. 미래 당첨자수 예측 주장 금지.",
    }


def main() -> None:
    conn = sqlite3.connect(DB)
    try:
        s0 = step0(conn)
        enriched, sample10 = step1(conn)
        s2 = step2(enriched)
        s3 = step3(s2["correlations"])
        out = {
            "step0": s0,
            "step1_sample10": sample10,
            "step2": s2,
            "step3": s3,
        }
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(out, ensure_ascii=False, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
