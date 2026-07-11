"""88~1228회차 수학적 연관성 정찰 (READ-ONLY)."""

from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.lotto4.combinadic import combo_to_no

DB = _ROOT / "data" / "lotto4.db"
OUT_JSON = _ROOT / "tools" / "_audit_88to1228_math_correlation.json"
DRAW_MIN = 88
DRAW_MAX = 1228
EXPECTED_DRAWS = DRAW_MAX - DRAW_MIN + 1  # 1141
TOTAL_COMBOS = 8_145_060


def _sig_label(r: float, p: float, *, strong: float = 0.3) -> str:
    if p >= 0.05:
        return "무의미"
    if abs(r) >= strong:
        return "유의미(강)"
    if abs(r) >= 0.1:
        return "유의미(약)"
    return "유의미(극약)"


def _corr_pair(
    x: np.ndarray,
    y: np.ndarray,
    name: str,
) -> dict[str, Any]:
    mask = np.isfinite(x) & np.isfinite(y)
    xv, yv = x[mask], y[mask]
    n = int(len(xv))
    if n < 3:
        return {"pair": name, "n": n, "error": "insufficient_data"}
    pr, pp = stats.pearsonr(xv, yv)
    sr, sp = stats.spearmanr(xv, yv)
    return {
        "pair": name,
        "n": n,
        "pearson_r": round(float(pr), 6),
        "pearson_p": round(float(pp), 6),
        "spearman_r": round(float(sr), 6),
        "spearman_p": round(float(sp), 6),
        "pearson_sig": _sig_label(pr, pp),
        "spearman_sig": _sig_label(sr, sp),
        "significant_p05": bool(pp < 0.05 or sp < 0.05),
    }


def load_draws(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT d.draw_no, d.draw_date, d.num1, d.num2, d.num3, d.num4, d.num5, d.num6,
               d.bonus, d.total_sales, d.first_prize, d.first_winners
        FROM lotto_draws d
        WHERE d.draw_no BETWEEN ? AND ?
        ORDER BY d.draw_no
        """,
        (DRAW_MIN, DRAW_MAX),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        nums = sorted([int(r[f"num{i}"]) for i in range(1, 7)])
        cno = combo_to_no(nums)
        out.append(
            {
                "draw_no": int(r["draw_no"]),
                "draw_date": r["draw_date"],
                "numbers": nums,
                "bonus": int(r["bonus"]),
                "combo_no": cno,
                "num_sum": sum(nums),
                "total_sales": int(r["total_sales"] or 0),
                "first_prize": int(r["first_prize"] or 0),
                "first_winners": int(r["first_winners"] or 0),
            }
        )
    return out


def step1_raw_audit(conn: sqlite3.Connection, draws: list[dict]) -> dict[str, Any]:
    have = {d["draw_no"] for d in draws}
    expected = set(range(DRAW_MIN, DRAW_MAX + 1))
    missing = sorted(expected - have)

    zero_sales = [d["draw_no"] for d in draws if d["total_sales"] == 0]
    zero_prize = [d["draw_no"] for d in draws if d["first_prize"] == 0]
    zero_winners = [d["draw_no"] for d in draws if d["first_winners"] == 0]

    # tiers coverage
    tier_rows = conn.execute(
        """
        SELECT draw_no, tier_rank, winner_count, prize_per_game, total_prize
        FROM lotto_draw_tiers
        WHERE draw_no BETWEEN ? AND ?
        ORDER BY draw_no, tier_rank
        """,
        (DRAW_MIN, DRAW_MAX),
    ).fetchall()
    tier_by_draw: dict[int, dict[int, dict]] = {}
    for tr in tier_rows:
        dr = int(tr["draw_no"])
        tier_by_draw.setdefault(dr, {})[int(tr["tier_rank"])] = {
            "winner_count": int(tr["winner_count"] or 0),
            "prize_per_game": int(tr["prize_per_game"] or 0),
            "total_prize": int(tr["total_prize"] or 0),
        }

    draws_missing_tiers = sorted(
        dr for dr in have if len(tier_by_draw.get(dr, {})) < 5
    )
    tier_zero_examples: dict[str, list[int]] = {f"tier{t}": [] for t in range(1, 6)}
    for dr, tiers in tier_by_draw.items():
        for t in range(1, 6):
            wc = tiers.get(t, {}).get("winner_count", -1)
            if wc == 0 and len(tier_zero_examples[f"tier{t}"]) < 5:
                tier_zero_examples[f"tier{t}"].append(dr)

    # winners_full
    wf_count = conn.execute(
        """
        SELECT COUNT(*) FROM lotto4_winners_full
        WHERE drw_no BETWEEN ? AND ?
        """,
        (DRAW_MIN, DRAW_MAX),
    ).fetchone()[0]
    wf_missing = sorted(
        dr
        for dr in expected
        if not conn.execute(
            "SELECT 1 FROM lotto4_winners_full WHERE drw_no=? LIMIT 1", (dr,)
        ).fetchone()
    )

    # attach tiers to draws for later
    for d in draws:
        d["tiers"] = tier_by_draw.get(d["draw_no"], {})

    return {
        "draw_range": [DRAW_MIN, DRAW_MAX],
        "expected_count": EXPECTED_DRAWS,
        "actual_count": len(draws),
        "missing_draws": missing,
        "complete": len(missing) == 0 and len(draws) == EXPECTED_DRAWS,
        "zero_total_sales_count": len(zero_sales),
        "zero_total_sales_sample": zero_sales[:15],
        "zero_first_prize_count": len(zero_prize),
        "zero_first_prize_sample": zero_prize[:15],
        "zero_first_winners_count": len(zero_winners),
        "zero_first_winners_sample": zero_winners[:15],
        "zero_first_winners_note": "1등 미당첨(0명) 회차 — 정상 0값",
        "lotto_draw_tiers_rows": len(tier_rows),
        "draws_missing_any_tier": draws_missing_tiers[:20],
        "draws_missing_tier_count": len(draws_missing_tiers),
        "tier_zero_winner_examples": tier_zero_examples,
        "lotto4_winners_full_count": int(wf_count),
        "winners_full_missing": wf_missing[:20],
        "winners_full_missing_count": len(wf_missing),
    }


def step2_correlations(draws: list[dict]) -> dict[str, Any]:
    n = len(draws)
    draw_no = np.array([d["draw_no"] for d in draws], dtype=float)
    combo_no = np.array([d["combo_no"] for d in draws], dtype=float)
    num_sum = np.array([d["num_sum"] for d in draws], dtype=float)
    sales = np.array([d["total_sales"] for d in draws], dtype=float)
    prize = np.array([d["first_prize"] for d in draws], dtype=float)
    winners = np.array([d["first_winners"] for d in draws], dtype=float)

    # tier 2~5 from draws
    t2w = np.array([d["tiers"].get(2, {}).get("winner_count", np.nan) for d in draws], dtype=float)
    t3w = np.array([d["tiers"].get(3, {}).get("winner_count", np.nan) for d in draws], dtype=float)
    t4w = np.array([d["tiers"].get(4, {}).get("winner_count", np.nan) for d in draws], dtype=float)
    t5w = np.array([d["tiers"].get(5, {}).get("winner_count", np.nan) for d in draws], dtype=float)
    t2p = np.array([d["tiers"].get(2, {}).get("prize_per_game", np.nan) for d in draws], dtype=float)

    pairs = [
        _corr_pair(combo_no, winners, "combo_no ↔ 1등당첨자수"),
        _corr_pair(combo_no, prize, "combo_no ↔ 1등당첨금"),
        _corr_pair(combo_no, sales, "combo_no ↔ 총판매량"),
        _corr_pair(num_sum, winners, "본번호합계 ↔ 1등당첨자수"),
        _corr_pair(num_sum, prize, "본번호합계 ↔ 1등당첨금"),
        _corr_pair(sales, winners, "총판매량 ↔ 1등당첨자수"),
        _corr_pair(prize, winners, "1등당첨금 ↔ 1등당첨자수"),
        _corr_pair(draw_no, sales, "회차(시간) ↔ 총판매량"),
        _corr_pair(draw_no, prize, "회차(시간) ↔ 1등당첨금"),
        _corr_pair(draw_no, combo_no, "회차 ↔ combo_no"),
        _corr_pair(num_sum, sales, "본번호합계 ↔ 총판매량"),
        _corr_pair(combo_no, t2w, "combo_no ↔ 2등당첨자수"),
        _corr_pair(sales, t4w, "총판매량 ↔ 4등당첨자수"),
        _corr_pair(sales, t5w, "총판매량 ↔ 5등당첨자수"),
    ]

    structural = {
        "판매량↔1등당첨자수": next(p for p in pairs if p["pair"] == "총판매량 ↔ 1등당첨자수"),
        "당첨금↔당첨자수": next(p for p in pairs if p["pair"] == "1등당첨금 ↔ 1등당첨자수"),
    }

    random_like = [p for p in pairs if "combo_no" in p["pair"] and "회차" not in p["pair"]]

    return {
        "n_draws": n,
        "pairs": pairs,
        "structural_highlight": structural,
        "combo_no_pairs": random_like,
        "combo_no_max_abs_pearson": max(
            abs(p.get("pearson_r", 0)) for p in random_like if "pearson_r" in p
        ),
    }


def step3_distributions(draws: list[dict]) -> dict[str, Any]:
  # Number frequency chi-square (1-45, expected equal)
    freq = Counter()
    for d in draws:
        for n in d["numbers"]:
            freq[n] += 1
    observed = np.array([freq.get(i, 0) for i in range(1, 46)], dtype=float)
    expected = np.full(45, observed.sum() / 45.0)
    chi2_num, p_num = stats.chisquare(observed, expected)

    # Bonus frequency
    bonus_freq = Counter(d["bonus"] for d in draws)
    bonus_obs = np.array([bonus_freq.get(i, 0) for i in range(1, 46)], dtype=float)
    bonus_exp = np.full(45, bonus_obs.sum() / 45.0)
    chi2_bonus, p_bonus = stats.chisquare(bonus_obs, bonus_exp)

    # Sum distribution normality (Shapiro on sample if n large use subsample)
    sums = np.array([d["num_sum"] for d in draws], dtype=float)
    shapiro_stat, shapiro_p = stats.shapiro(sums[:5000] if len(sums) > 5000 else sums)

    # combo_no uniformity on 88-1228 winning combos only (1141 points in 8M space)
    combo_nos = np.array([d["combo_no"] for d in draws], dtype=float)
    # chi-square: divide 8145060 into 45 bins by quantile of equal width
    bin_count = 45
    bin_edges = np.linspace(1, TOTAL_COMBOS + 1, bin_count + 1)
    hist, _ = np.histogram(combo_nos, bins=bin_edges)
    exp_bin = len(combo_nos) / bin_count
    chi2_combo, p_combo = stats.chisquare(hist, np.full(bin_count, exp_bin))

    # Expected chi2 for 44 df ~ 44, user mentioned chi²≈9.6 before
    # Also KS test vs uniform on normalized combo_no
    normed = (combo_nos - 1) / (TOTAL_COMBOS - 1)
    ks_stat, ks_p = stats.kstest(normed, "uniform")

    # Top bonus-main pairs (bonus co-occurrence with main numbers)
    pair_counts: Counter[tuple[int, int]] = Counter()
    for d in draws:
        b = d["bonus"]
        for n in d["numbers"]:
            pair_counts[(min(n, b), max(n, b))] += 1
    top_pairs = [
        {"nums": list(k), "count": v}
        for k, v in pair_counts.most_common(10)
    ]

    # Sum stats
    return {
        "main_number_freq": {
            "chi2": round(float(chi2_num), 4),
            "df": 44,
            "p_value": round(float(p_num), 6),
            "fair_uniform_p05": bool(p_num >= 0.05),
            "interpretation": "p>=0.05면 공평 출현과 통계적으로 양립",
            "min_count": int(observed.min()),
            "max_count": int(observed.max()),
            "expected_per_number": round(float(expected[0]), 2),
        },
        "bonus_number_freq": {
            "chi2": round(float(chi2_bonus), 4),
            "df": 44,
            "p_value": round(float(p_bonus), 6),
            "fair_uniform_p05": bool(p_bonus >= 0.05),
        },
        "num_sum_distribution": {
            "mean": round(float(sums.mean()), 2),
            "std": round(float(sums.std()), 2),
            "min": int(sums.min()),
            "max": int(sums.max()),
            "shapiro_W": round(float(shapiro_stat), 6),
            "shapiro_p": round(float(shapiro_p), 6),
            "normal_like_p05": bool(shapiro_p >= 0.05),
        },
        "combo_no_uniformity_88_1228": {
            "n_winning_draws": len(combo_nos),
            "bins": bin_count,
            "chi2": round(float(chi2_combo), 4),
            "df": bin_count - 1,
            "p_value": round(float(p_combo), 6),
            "ks_stat": round(float(ks_stat), 6),
            "ks_p": round(float(ks_p), 6),
            "uniform_like_p05": bool(p_combo >= 0.05 and ks_p >= 0.05),
            "note": "1141개 당첨 combo_no가 814만 공간에서 균등한지 (무작위 가설)",
        },
        "bonus_main_top_pairs": top_pairs,
    }


def step4_verdict(step2: dict, step3: dict) -> dict[str, Any]:
    pairs = step2["pairs"]

    green = []
    red = []
    yellow = []

    for p in pairs:
        name = p["pair"]
        r = abs(p.get("pearson_r", 0))
        sig = p.get("significant_p05", False)
        if "combo_no" in name and "회차" not in name:
            if sig and r > 0.1:
                yellow.append(f"{name}: r={p['pearson_r']} (우연 유의, 예측 무용)")
            else:
                red.append(f"{name}: |r|≈{r:.4f} — 무작위·무관계")
        elif name in ("총판매량 ↔ 1등당첨자수", "1등당첨금 ↔ 1등당첨자수"):
            green.append(
                f"{name}: r={p['pearson_r']} — 분배·구매 구조상 당연한 관계 (예측 아님)"
            )
        elif name in ("회차(시간) ↔ 총판매량", "회차(시간) ↔ 1등당첨금"):
            if sig:
                green.append(f"{name}: r={p['pearson_r']} — 시대·인플레 추세 (예측 아님)")
        elif "본번호합계" in name:
            if not sig or r < 0.1:
                red.append(f"{name}: 예측 신호 없음")
            else:
                yellow.append(f"{name}: 약한 통계 유의, 인과 해석 불가")

    conclusion = (
        "88~1228 구간에서 combo_no·번호조합은 1등 당첨금/당첨자/판매량과 "
        "예측 가능한 수학 관계가 없음(|r|≈0). "
        "유의하게 보이는 상관은 판매량↔당첨자수·당첨금↔당첨자수(역상관)·회차 추세 등 "
        "복권 분배 구조·시대 효과이며 미래 번호 예측에 쓸 수 없음."
    )

    return {
        "green_structural": green,
        "red_no_signal": red,
        "yellow_caution": yellow,
        "conclusion": conclusion,
        "predictable": False,
    }


def run() -> dict[str, Any]:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        draws = load_draws(conn)
        s1 = step1_raw_audit(conn, draws)
        s2 = step2_correlations(draws)
        s3 = step3_distributions(draws)
        s4 = step4_verdict(s2, s3)
        return {
            "title": "20260620_4군_88to1228_수학적연관성_테스트정찰",
            "mode": "READ-ONLY",
            "db": str(DB),
            "draw_range": [DRAW_MIN, DRAW_MAX],
            "step1_raw": s1,
            "step2_correlations": s2,
            "step3_distributions": s3,
            "step4_verdict": s4,
        }
    finally:
        conn.close()


def format_report(data: dict[str, Any]) -> str:
    lines = [
        "20260620_4군_88to1228_수학적연관성_테스트정찰",
        "동생 → 커서 | 2026-06-20 | READ-ONLY 정찰·테스트",
        "",
        "원칙: R2 정직 / R14 정찰의무",
        "대상: 88~1228회차 (era_B 시작, 1141회) | 보너스 본번호 분리",
        f"DB: {data['db']} (읽기만, 무수정)",
        f"JSON: tools/_audit_88to1228_math_correlation.json",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "STEP 1 — 데이터 집결 (RAW)",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    s1 = data["step1_raw"]
    lines += [
        f"회차 범위: {s1['draw_range'][0]}~{s1['draw_range'][1]}",
        f"기대 {s1['expected_count']}회 / 실제 {s1['actual_count']}회 / 누락 {len(s1['missing_draws'])}",
        f"완전성: {'✅' if s1['complete'] else '❌'}",
        f"total_sales=0: {s1['zero_total_sales_count']}회 (샘플 {s1['zero_total_sales_sample'][:5]})",
        f"first_prize=0: {s1['zero_first_prize_count']}회",
        f"first_winners=0: {s1['zero_first_winners_count']}회 — {s1['zero_first_winners_note']}",
        f"  (회차: {s1['zero_first_winners_sample']})",
        f"lotto_draw_tiers 행: {s1['lotto_draw_tiers_rows']} (기대 {EXPECTED_DRAWS * 5})",
        f"티어 누락 회차: {s1['draws_missing_tier_count']}",
        f"lotto4_winners_full: {s1['lotto4_winners_full_count']}행 / 누락 {s1['winners_full_missing_count']}",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "STEP 2 — 상관 테스트 (Pearson / Spearman)",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "pair | pearson_r | p | spearman_r | p | 판정",
    ]
    for p in data["step2_correlations"]["pairs"]:
        lines.append(
            f"{p['pair']} | {p.get('pearson_r','?')} | {p.get('pearson_p','?')} | "
            f"{p.get('spearman_r','?')} | {p.get('spearman_p','?')} | {p.get('pearson_sig','')}"
        )
    lines += [
        "",
        f"combo_no 관련 최대 |r| (pearson): {data['step2_correlations']['combo_no_max_abs_pearson']:.4f}",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "STEP 3 — 분포·균등성",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    s3 = data["step3_distributions"]
    mn = s3["main_number_freq"]
    bn = s3["bonus_number_freq"]
    sm = s3["num_sum_distribution"]
    cu = s3["combo_no_uniformity_88_1228"]
    lines += [
        f"본번호 1~45 출현 χ²={mn['chi2']} (df=44) p={mn['p_value']} → 공평 가설 {'유지' if mn['fair_uniform_p05'] else '기각'}",
        f"  출현 min/max: {mn['min_count']}/{mn['max_count']} (기대≈{mn['expected_per_number']})",
        f"보너스 1~45 χ²={bn['chi2']} p={bn['p_value']}",
        f"본번호 합계: mean={sm['mean']} std={sm['std']} range [{sm['min']},{sm['max']}]",
        f"  Shapiro p={sm['shapiro_p']} → 정규 {'근사' if sm['normal_like_p05'] else '거부'}",
        f"combo_no 균등성(88~1228 당첨 1141개, 45 bins): χ²={cu['chi2']} p={cu['p_value']}",
        f"  KS uniform p={cu['ks_p']} → 무작위 공간 가설 {'양립' if cu['uniform_like_p05'] else '기각'}",
        "",
        "보너스-본번호 동반 상위쌍:",
    ]
    for tp in s3["bonus_main_top_pairs"][:5]:
        lines.append(f"  {tp['nums']}: {tp['count']}회")

    s4 = data["step4_verdict"]
    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "STEP 4 — 종합 판정 (R2)",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🟢 분배·구조상 당연 (예측 아님):",
    ]
    for g in s4["green_structural"]:
        lines.append(f"  · {g}")
    lines.append("🔴 무관계·무작위 (예측 신호 없음):")
    for r in s4["red_no_signal"]:
        lines.append(f"  · {r}")
    if s4["yellow_caution"]:
        lines.append("🟡 주의 (통계 유의하나 인과·예측 불가):")
        for y in s4["yellow_caution"]:
            lines.append(f"  · {y}")
    lines += [
        "",
        "결론:",
        s4["conclusion"],
        "",
        "UI: 미구현 (정찰만) | 기억 갱신: 형 확인 후",
    ]
    return "\n".join(lines)


def main() -> None:
    data = run()
    OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    report = format_report(data)
    report_path = _ROOT / "reports" / "20260620_4군_88to1228_수학적연관성_테스트정찰.txt"
    report_path.write_text(report, encoding="utf-8")
    print(report.encode("utf-8", errors="replace").decode("utf-8", errors="replace"))
    print(f"\nJSON: {OUT_JSON}")
    print(f"TXT: {report_path}")


if __name__ == "__main__":
    main()
