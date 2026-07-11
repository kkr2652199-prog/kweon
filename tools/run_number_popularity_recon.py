"""4군 개별번호/쌍 인기도 분석 — 비인기 엔진 v2 정찰."""
from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from itertools import combinations
from pathlib import Path

DB = Path(r"d:\3kweon\data\lotto4.db")
OUT = Path(r"d:\3kweon\tools\_number_popularity_recon.json")


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


def spearman_from_values(a: list[float], b: list[float]) -> float:
    ra, rb = rankdata(a), rankdata(b)
    n = len(a)
    if n < 2:
        return float("nan")
    ma = sum(ra) / n
    mb = sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den_a = math.sqrt(sum((x - ma) ** 2 for x in ra))
    den_b = math.sqrt(sum((y - mb) ** 2 for y in rb))
    if den_a == 0 or den_b == 0:
        return float("nan")
    return num / (den_a * den_b)


def load_draws(conn: sqlite3.Connection, draw_min: int = 1, draw_max: int = 1225) -> list[dict]:
    rows = conn.execute(
        """
        SELECT draw_no, num1, num2, num3, num4, num5, num6, winner_count
        FROM lotto4_winners
        WHERE draw_no BETWEEN ? AND ?
          AND winner_count > 0
        ORDER BY draw_no
        """,
        (draw_min, draw_max),
    ).fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "draw_no": r[0],
                "nums": [r[1], r[2], r[3], r[4], r[5], r[6]],
                "winner_count": r[7],
            }
        )
    return out


def number_stats(draws: list[dict], global_avg: float) -> list[dict]:
    winners_by_num: dict[int, list[int]] = defaultdict(list)
    for d in draws:
        for n in d["nums"]:
            winners_by_num[n].append(d["winner_count"])
    rows = []
    for num in range(1, 46):
        wc = winners_by_num.get(num, [])
        appear = len(wc)
        avg_w = sum(wc) / appear if appear else float("nan")
        rows.append(
            {
                "number": num,
                "appear_count": appear,
                "avg_winner": round(avg_w, 4) if appear else None,
                "deviation": round(avg_w - global_avg, 4) if appear else None,
            }
        )
    return rows


def pair_stats(draws: list[dict], min_appear: int = 5) -> list[dict]:
    pair_winners: dict[tuple[int, int], list[int]] = defaultdict(list)
    for d in draws:
        for a, b in combinations(sorted(d["nums"]), 2):
            pair_winners[(a, b)].append(d["winner_count"])
    rows = []
    for (a, b), wc in pair_winners.items():
        if len(wc) < min_appear:
            continue
        rows.append(
            {
                "pair": f"{a}-{b}",
                "a": a,
                "b": b,
                "appear_count": len(wc),
                "pair_avg_winner": round(sum(wc) / len(wc), 4),
            }
        )
    return rows


def step1(conn: sqlite3.Connection) -> dict:
    draws = load_draws(conn)
    global_avg = sum(d["winner_count"] for d in draws) / len(draws)
    nums = number_stats(draws, global_avg)
    by_avg = sorted(
        [n for n in nums if n["avg_winner"] is not None],
        key=lambda x: x["avg_winner"],
        reverse=True,
    )
    low_group = [n for n in nums if 1 <= n["number"] <= 31 and n["avg_winner"] is not None]
    high_group = [n for n in nums if 32 <= n["number"] <= 45 and n["avg_winner"] is not None]
    low_avg = sum(n["avg_winner"] for n in low_group) / len(low_group)
    high_avg = sum(n["avg_winner"] for n in high_group) / len(high_group)
    return {
        "global_avg_winner": round(global_avg, 4),
        "analysis_draws": len(draws),
        "all_numbers": nums,
        "top_by_avg_winner": by_avg[:15],
        "bottom_by_avg_winner": by_avg[-15:],
        "birthday_1_31_avg": round(low_avg, 4),
        "high_32_45_avg": round(high_avg, 4),
        "birthday_minus_high": round(low_avg - high_avg, 4),
    }


def step2(conn: sqlite3.Connection) -> dict:
    draws = load_draws(conn)
    pairs = pair_stats(draws, min_appear=5)
    by_avg = sorted(pairs, key=lambda x: x["pair_avg_winner"], reverse=True)
    return {
        "eligible_pairs": len(pairs),
        "total_possible_pairs": 990,
        "min_appear_threshold": 5,
        "top20_popular_pairs": by_avg[:20],
        "bottom20_unpopular_pairs": by_avg[-20:],
    }


def step4(conn: sqlite3.Connection) -> dict:
    first = load_draws(conn, 1, 612)
    second = load_draws(conn, 613, 1225)
    g1 = sum(d["winner_count"] for d in first) / len(first)
    g2 = sum(d["winner_count"] for d in second) / len(second)
    n1 = number_stats(first, g1)
    n2 = number_stats(second, g2)
    m1 = {r["number"]: r["avg_winner"] for r in n1 if r["avg_winner"] is not None}
    m2 = {r["number"]: r["avg_winner"] for r in n2 if r["avg_winner"] is not None}
    nums = sorted(set(m1) & set(m2))
    v1 = [m1[n] for n in nums]
    v2 = [m2[n] for n in nums]
    rho = spearman_from_values(v1, v2)
    # deviation stability
    d1 = {r["number"]: r["deviation"] for r in n1 if r["deviation"] is not None}
    d2 = {r["number"]: r["deviation"] for r in n2 if r["deviation"] is not None}
    dv1 = [d1[n] for n in nums]
    dv2 = [d2[n] for n in nums]
    rho_dev = spearman_from_values(dv1, dv2)
    # pair stability (eligible in both halves separately)
    p1 = {p["pair"]: p["pair_avg_winner"] for p in pair_stats(first, 3)}
    p2 = {p["pair"]: p["pair_avg_winner"] for p in pair_stats(second, 3)}
    common_pairs = sorted(set(p1) & set(p2))
    pair_rho = (
        spearman_from_values([p1[k] for k in common_pairs], [p2[k] for k in common_pairs])
        if len(common_pairs) >= 2
        else float("nan")
    )
    return {
        "first_half": {"draws": len(first), "global_avg": round(g1, 4), "range": "1~612"},
        "second_half": {"draws": len(second), "global_avg": round(g2, 4), "range": "613~1225"},
        "number_avg_winner_spearman": round(rho, 4),
        "number_deviation_spearman": round(rho_dev, 4),
        "common_pairs_for_stability": len(common_pairs),
        "pair_avg_winner_spearman_min3": round(pair_rho, 4),
        "first_half_top5": sorted(n1, key=lambda x: x["avg_winner"], reverse=True)[:5],
        "second_half_top5": sorted(n2, key=lambda x: x["avg_winner"], reverse=True)[:5],
    }


def compare_to_combo_signal(step1_data: dict) -> dict:
    """조합특징 최대 |r|=0.097 대비 번호 avg_winner 편차 범위."""
    devs = [abs(n["deviation"]) for n in step1_data["all_numbers"] if n["deviation"] is not None]
    avgs = [n["avg_winner"] for n in step1_data["all_numbers"] if n["avg_winner"] is not None]
    return {
        "number_avg_winner_min": round(min(avgs), 4),
        "number_avg_winner_max": round(max(avgs), 4),
        "number_avg_winner_spread": round(max(avgs) - min(avgs), 4),
        "max_abs_deviation": round(max(devs), 4),
        "combo_feature_max_abs_r_prior": 0.097,
    }


def main() -> None:
    conn = sqlite3.connect(DB)
    try:
        s1 = step1(conn)
        s2 = step2(conn)
        s4 = step4(conn)
        cmp_ = compare_to_combo_signal(s1)
        out = {
            "step1": s1,
            "step2": s2,
            "step3_note": {
                "appear_count_min": min(n["appear_count"] for n in s1["all_numbers"]),
                "appear_count_max": max(n["appear_count"] for n in s1["all_numbers"]),
                "unstable_threshold": 150,
                "caveat_future": "과거 avg_winner가 미래에도 유지된다는 보장 없음",
                "caveat_bias": "인기도는 인간 선택 편향 대리지표 — 번호 무작위성과 다를 수 있음",
            },
            "step4": s4,
            "signal_compare": cmp_,
        }
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(out, ensure_ascii=False, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
