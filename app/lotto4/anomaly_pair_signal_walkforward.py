"""급등 쌍 이상치 신호 — 정적 cooccur vs 최근 구간 괴리 (R13 walk-forward).

draw_no < cutoff 만 사용. 정적 누적 빈도와 최근 window 빈도를 비교해
괴리율이 큰 2쌍 = "갑자기 튄 쌍" 탐지.
R2: 당첨 확률 향상 주장 금지 — precision@K·인기적합도 측정 전용.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from itertools import combinations
from typing import Any

from app.lotto4.models import LOTTO_DB_PATH

DEFAULT_RECENT_WINDOW = 40
DEFAULT_TOP_K = 50


def _pair_key(a: int, b: int) -> tuple[int, int]:
    x, y = int(a), int(b)
    return (x, y) if x < y else (y, x)


def _aggregate_pairs(rows: list[tuple]) -> dict[tuple[int, int], int]:
    counts: dict[tuple[int, int], int] = defaultdict(int)
    for draw_no, *nums in rows:
        try:
            six = sorted(int(x) for x in nums)
        except (TypeError, ValueError):
            continue
        if len(six) != 6:
            continue
        for a, b in combinations(six, 2):
            counts[(a, b)] += 1
    return counts


def compute_anomaly_pairs_before(
    cutoff_draw_no: int,
    db_path: str | None = None,
    *,
    recent_window: int = DEFAULT_RECENT_WINDOW,
    top_k: int = DEFAULT_TOP_K,
) -> dict[str, Any]:
    """cutoff 미만 draws로 정적·최근 cooccur 비교 (R13)."""
    path = str(db_path or LOTTO_DB_PATH)
    cutoff = int(cutoff_draw_no)
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute(
            """
            SELECT draw_no, num1, num2, num3, num4, num5, num6
            FROM lotto_draws
            WHERE draw_no < ?
            ORDER BY draw_no ASC
            """,
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()

    total_n = len(rows)
    if total_n < 2:
        return {
            "cutoff_draw_no": cutoff,
            "draw_count": total_n,
            "top_pairs": [],
            "pair_boost": {n: 0.0 for n in range(1, 46)},
        }

    static = _aggregate_pairs(rows)
    recent_rows = rows[max(0, total_n - int(recent_window)) :]
    recent_n = len(recent_rows)
    recent = _aggregate_pairs(recent_rows)

    anomalies: list[dict[str, Any]] = []
    for pair, static_cnt in static.items():
        static_rate = static_cnt / total_n
        recent_cnt = recent.get(pair, 0)
        recent_rate = recent_cnt / max(recent_n, 1)
        if static_rate <= 0:
            continue
        ratio = recent_rate / static_rate
        z_like = (recent_cnt - static_rate * recent_n) / max(
            (static_rate * recent_n * (1 - static_rate)) ** 0.5, 0.01
        )
        anomalies.append(
            {
                "pair": list(pair),
                "static_count": int(static_cnt),
                "recent_count": int(recent_cnt),
                "static_rate": round(static_rate, 6),
                "recent_rate": round(recent_rate, 6),
                "surge_ratio": round(ratio, 4),
                "z_score": round(z_like, 4),
                "anomaly_score": round(max(ratio - 1.0, 0.0) * max(z_like, 0.0), 4),
            }
        )

    anomalies.sort(
        key=lambda e: (-e["anomaly_score"], -e["surge_ratio"], e["pair"]),
    )
    top = anomalies[: int(top_k)]

    pair_boost: dict[int, float] = defaultdict(float)
    if top:
        max_score = max(e["anomaly_score"] for e in top) or 1.0
        for e in top:
            w = e["anomaly_score"] / max_score
            a, b = e["pair"]
            pair_boost[a] += w
            pair_boost[b] += w
        for n in range(1, 46):
            pair_boost[n] = round(min(float(pair_boost[n]), 1.0), 4)

    return {
        "cutoff_draw_no": cutoff,
        "draw_count": total_n,
        "recent_window": recent_n,
        "top_k": int(top_k),
        "top_pairs": top,
        "pair_boost": dict(pair_boost),
    }


def apply_anomaly_boost(
    pool_weight: dict[int, float],
    anomaly_data: dict[str, Any],
    blend: float = 0.15,
) -> dict[int, float]:
    """급등 쌍에 속한 번호에 보조 가중."""
    b = max(float(blend), 0.0)
    pb = anomaly_data.get("pair_boost") or {}
    return {
        n: max(pool_weight.get(n, 0.0) * (1.0 + b * float(pb.get(n, 0.0))), 0.001)
        for n in range(1, 46)
    }


def precision_at_k(
    top_pairs: list[dict[str, Any]],
    actual_nums: list[int],
    k: int | None = None,
) -> float:
    """튄 쌍 Top-K 중 실제 당첨 6수에 포함된 쌍 비율."""
    if not top_pairs:
        return 0.0
    kk = k if k is not None else len(top_pairs)
    actual = set(int(n) for n in actual_nums)
    hits = 0
    for e in top_pairs[:kk]:
        a, b = int(e["pair"][0]), int(e["pair"][1])
        if a in actual and b in actual:
            hits += 1
    return round(hits / max(kk, 1), 4)
