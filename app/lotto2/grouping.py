"""V10 계층적 그룹핑 모듈 (한국 특허 KR102306385B1 기반).

1차 그룹: n회차 단위 묶음
2차 그룹: 1차 그룹 m개 묶음
조건변수 (n, m, epochs)를 진화시키며 패턴 추출.

1군 코드 의존성 0. lotto_draws 읽기 전용.
"""
from __future__ import annotations
import sqlite3
from pathlib import Path
from collections import Counter
from itertools import combinations

LOTTO_DB_PATH = Path(__file__).parent.parent.parent / "data" / "lotto4.db"


def _read_draws(target_draw_no: int) -> list[dict]:
    """target 미만 회차의 당첨번호를 raw로 읽어옴 (컷닝 방지)."""
    conn = sqlite3.connect(str(LOTTO_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT draw_no, num1, num2, num3, num4, num5, num6, bonus "
            "FROM lotto_draws WHERE draw_no < ? ORDER BY draw_no",
            (target_draw_no,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def build_tier1_groups(draws: list[dict], n: int) -> list[list[dict]]:
    """1차 그룹: 연속 n회차 단위 묶음."""
    if n <= 0:
        return []
    return [draws[i : i + n] for i in range(0, len(draws), n) if len(draws[i : i + n]) == n]


def build_tier2_groups(tier1: list[list[dict]], m: int) -> list[list[list[dict]]]:
    """2차 그룹: 1차 그룹 m개씩 묶음."""
    if m <= 0:
        return []
    return [tier1[i : i + m] for i in range(0, len(tier1), m) if len(tier1[i : i + m]) == m]


def extract_tier1_signatures(tier1: list[list[dict]]) -> list[dict]:
    """각 1차 그룹별 시그니처 추출 (번호 빈도 / 합 / 연번 / 공출현쌍)."""
    out = []
    for group in tier1:
        num_freq = Counter()
        sum_list = []
        consec_list = []
        pair_freq = Counter()
        for d in group:
            nums = sorted([d["num1"], d["num2"], d["num3"], d["num4"], d["num5"], d["num6"]])
            for x in nums:
                num_freq[x] += 1
            sum_list.append(sum(nums))
            consec_list.append(sum(1 for i in range(5) if nums[i + 1] - nums[i] == 1))
            for p in combinations(nums, 2):
                pair_freq[p] += 1
        n_g = max(1, len(group))
        out.append(
            {
                "size": len(group),
                "num_freq": dict(num_freq),
                "sum_avg": sum(sum_list) / n_g if sum_list else 0,
                "consec_avg": sum(consec_list) / n_g if consec_list else 0,
                "pair_top": pair_freq.most_common(20),
            }
        )
    return out


def extract_tier2_signatures(tier2: list[list[list[dict]]]) -> list[dict]:
    """각 2차 그룹별 시그니처 (구성 1차 그룹들의 평균/추세)."""
    out = []
    for big in tier2:
        flat = [d for g in big for d in g]
        num_freq = Counter()
        sum_list = []
        for d in flat:
            for x in [d["num1"], d["num2"], d["num3"], d["num4"], d["num5"], d["num6"]]:
                num_freq[x] += 1
            sum_list.append(d["num1"] + d["num2"] + d["num3"] + d["num4"] + d["num5"] + d["num6"])
        n_f = max(1, len(flat))
        out.append(
            {
                "n_tier1": len(big),
                "n_draws": len(flat),
                "num_freq": dict(num_freq),
                "sum_avg": sum(sum_list) / n_f if sum_list else 0,
            }
        )
    return out


def get_grouped_pmf(target_draw_no: int, n: int = 10, m: int = 5) -> dict[int, float]:
    """target 미만 회차로 계층적 그룹 PMF 산출.

    Args:
        target_draw_no: 예측 대상 회차 (이 회차 미만만 사용)
        n: 1차 그룹 크기 (회차 수)
        m: 2차 그룹 크기 (1차 그룹 수)

    Returns:
        1~45 번호별 확률
    """
    draws = _read_draws(target_draw_no)
    if len(draws) < n * m:
        return {x: 1.0 / 45 for x in range(1, 46)}

    tier1 = build_tier1_groups(draws, n)
    tier2 = build_tier2_groups(tier1, m)

    if not tier2:
        return {x: 1.0 / 45 for x in range(1, 46)}

    # 최근 2차 그룹에 가중치 더 부여 (최근 신호 우선)
    score = {x: 0.0 for x in range(1, 46)}
    decay = 0.85
    weight = 1.0
    for big in reversed(tier2):
        for g in big:
            for d in g:
                for x in [d["num1"], d["num2"], d["num3"], d["num4"], d["num5"], d["num6"]]:
                    if 1 <= x <= 45:
                        score[x] += weight
        weight *= decay

    total = sum(score.values()) or 1.0
    return {x: v / total for x, v in score.items()}


def evaluate_condition_variables(
    target_draw_no: int,
    n_grid: tuple = (5, 10, 20),
    m_grid: tuple = (3, 5, 10),
) -> list[dict]:
    """조건변수 (n, m) 격자 탐색. PMF 엔트로피 + 데이터 충분성 평가.

    낮은 엔트로피 = 확신 높음 / 높은 엔트로피 = 분산.
    """
    import math

    out = []
    for n in n_grid:
        for m in m_grid:
            pmf = get_grouped_pmf(target_draw_no, n=n, m=m)
            entropy = -sum(p * math.log(p + 1e-12) for p in pmf.values())
            top5_mass = sum(sorted(pmf.values(), reverse=True)[:5])
            out.append(
                {
                    "n": n,
                    "m": m,
                    "entropy": round(entropy, 4),
                    "top5_mass": round(top5_mass, 4),
                }
            )
    return out
