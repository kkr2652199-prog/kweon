"""V10 Anti-Correlation Learning 모듈 (Brown & Wyatt NCL 기반).

핵심 개념:
- 1군과 같은 회차에서 같이 맞추면 가중치 ↓ (중복 신호)
- 1군이 틀린 회차에서 2군이 맞추면 가중치 ↑ (보완 신호)
- 명시적 다양성 강제 → 합집합 효과 극대화

1군 데이터는 읽기 전용. 1군 코드 의존성 0.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

LOTTO_DB_PATH = Path(__file__).parent.parent.parent / "data" / "lotto4.db"

# 1군 6뇌 태그 (읽기 전용 참조)
ARMY1_BRAINS = ("stat", "markov", "llm", "lstm", "fusion", "hyena")
DEFAULT_LAMBDA = 0.5


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(LOTTO_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def get_v1_max_per_draw(start_draw: int, end_draw: int) -> dict[int, int]:
    """1군 회차별 max(matched_count) 읽기 전용 조회.

    Returns: {draw_no: v1_max}
    """
    conn = _connect()
    try:
        rows = conn.execute(
            f"""
            SELECT target_draw_no, MAX(matched_count) AS v1_max
            FROM lotto_predictions
            WHERE matched_count >= 0
              AND brain_tag IN ({",".join("?" * len(ARMY1_BRAINS))})
              AND target_draw_no BETWEEN ? AND ?
            GROUP BY target_draw_no
            """,
            (*ARMY1_BRAINS, start_draw, end_draw),
        ).fetchall()
        return {r["target_draw_no"]: r["v1_max"] for r in rows}
    finally:
        conn.close()


def get_army2_brain_per_draw(brain_tag: str, start_draw: int, end_draw: int) -> dict[int, int]:
    """2군 특정 뇌의 회차별 max 조회.

    Returns: {draw_no: max_matched_count}
    """
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT target_draw_no, MAX(matched_count) AS m
            FROM lotto_predictions_army2
            WHERE matched_count >= 0
              AND brain_tag = ?
              AND target_draw_no BETWEEN ? AND ?
            GROUP BY target_draw_no
            """,
            (brain_tag, start_draw, end_draw),
        ).fetchall()
        return {r["target_draw_no"]: r["m"] for r in rows}
    finally:
        conn.close()


def compute_anti_correlation_score(
    army2_per_draw: dict[int, int],
    v1_per_draw: dict[int, int],
    lambda_: float = DEFAULT_LAMBDA,
) -> dict:
    """Anti-Correlation 점수 계산.

    원본 평균 적중 - λ × 1군과의 양의 상관 페널티 + λ × 단독 보완 보너스.

    Args:
        army2_per_draw: 2군 회차별 max
        v1_per_draw: 1군 회차별 max
        lambda_: 페널티/보너스 강도 (기본 0.5)

    Returns:
        {
            "n": 비교 회차 수,
            "raw_avg": 원본 평균 적중,
            "redundancy_penalty": 1군과 같이 맞춘 비율,
            "complement_bonus": 1군이 틀렸을 때 2군이 맞춘 비율,
            "anti_corr_score": 최종 점수 (raw_avg - λ*redundancy + λ*complement),
        }
    """
    common = sorted(set(army2_per_draw.keys()) & set(v1_per_draw.keys()))
    n = len(common)
    if n == 0:
        return {
            "n": 0,
            "raw_avg": 0.0,
            "redundancy_penalty": 0.0,
            "complement_bonus": 0.0,
            "anti_corr_score": 0.0,
        }

    total_match = 0
    redundant = 0  # 1군 5등이상 + 2군 5등이상 (양쪽 다 맞춤)
    complement = 0  # 1군 4등이하 + 2군 5등이상 (2군이 단독 보완)

    for draw_no in common:
        v1m = v1_per_draw[draw_no]
        v2m = army2_per_draw[draw_no]
        total_match += v2m
        v1_hit = v1m >= 5
        v2_hit = v2m >= 5
        if v1_hit and v2_hit:
            redundant += 1
        elif (not v1_hit) and v2_hit:
            complement += 1

    raw_avg = total_match / n
    redundancy_ratio = redundant / n
    complement_ratio = complement / n
    score = raw_avg - lambda_ * redundancy_ratio + lambda_ * complement_ratio

    return {
        "n": n,
        "raw_avg": round(raw_avg, 4),
        "redundancy_penalty": round(redundancy_ratio, 4),
        "complement_bonus": round(complement_ratio, 4),
        "anti_corr_score": round(score, 4),
    }


def evaluate_all_army2_brains(
    start_draw: int,
    end_draw: int,
    lambda_: float = DEFAULT_LAMBDA,
) -> list[dict]:
    """2군 6뇌 전체에 대한 Anti-Correlation 점수 평가.

    Returns: [{brain_tag, n, raw_avg, redundancy_penalty, complement_bonus, anti_corr_score}, ...]
    """
    army2_brains = (
        "army2_stat",
        "army2_markov",
        "army2_combo",
        "army2_lstm",
        "army2_fusion",
        "army2_hyena",
    )
    v1_per_draw = get_v1_max_per_draw(start_draw, end_draw)
    out = []
    for tag in army2_brains:
        a2 = get_army2_brain_per_draw(tag, start_draw, end_draw)
        scored = compute_anti_correlation_score(a2, v1_per_draw, lambda_=lambda_)
        scored["brain_tag"] = tag
        out.append(scored)
    out.sort(key=lambda x: -x["anti_corr_score"])
    return out


def adjusted_brain_weights(
    base_weights: dict[str, float],
    anti_scores: list[dict],
    eta: float = 0.3,
) -> dict[str, float]:
    """Anti-Correlation 점수로 가중치 보정.

    new_weight = base_weight * (1 + eta * anti_corr_score)

    Args:
        base_weights: {brain_tag: current_weight}
        anti_scores: evaluate_all_army2_brains() 결과
        eta: 보정 강도 (기본 0.3)

    Returns:
        {brain_tag: adjusted_weight}
    """
    score_map = {s["brain_tag"]: s["anti_corr_score"] for s in anti_scores}
    out = {}
    for tag, w in base_weights.items():
        s = score_map.get(tag, 0.0)
        out[tag] = w * (1.0 + eta * s)
    return out
