"""비인기 형태 회피 신호 — lotto_draw_tiers 4·5등 + 형태 특징 (R13 walk-forward).

draw_no < cutoff 만 사용. 4·5등 당첨자가 많이 몰린(인기) 형태 프로필을 학습하고,
후보 조합이 그 프로필과 멀수록 비인기(회피) 점수가 높음.
R2: 당첨 확률 향상 주장 금지 — 인기적합도·커버리지 측정 전용.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.lotto4.brains.shape_brain import extract_shape_metrics
from app.lotto4.models import LOTTO_DB_PATH

SHAPE_FIELDS = ("sum6", "odd_cnt", "low_cnt", "decade_cnt", "consec_pairs", "ending_cnt")


def extended_shape_metrics(nums: list[int]) -> dict[str, int]:
    """합·홀짝·구간·연속·끝수 다양성."""
    s = sorted(int(n) for n in nums)
    base = extract_shape_metrics(s)
    consec = sum(1 for i in range(5) if s[i + 1] - s[i] == 1)
    base["consec_pairs"] = int(consec)
    base["ending_cnt"] = len({n % 10 for n in s})
    return base


def _load_tier45_rows(cutoff: int, db_path: str) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT d.draw_no,
                   d.num1, d.num2, d.num3, d.num4, d.num5, d.num6,
                   COALESCE(t4.winner_count, 0) + COALESCE(t5.winner_count, 0) AS tier45
            FROM lotto_draws d
            LEFT JOIN lotto_draw_tiers t4
              ON d.draw_no = t4.draw_no AND t4.tier_rank = 4
            LEFT JOIN lotto_draw_tiers t5
              ON d.draw_no = t5.draw_no AND t5.tier_rank = 5
            WHERE d.draw_no < ?
            ORDER BY d.draw_no ASC
            """,
            (int(cutoff),),
        ).fetchall()
    finally:
        conn.close()

    out: list[dict[str, Any]] = []
    for r in rows:
        nums = [int(r[i]) for i in range(1, 7)]
        out.append(
            {
                "draw_no": int(r[0]),
                "nums": nums,
                "tier45": int(r[7]),
                "shape": extended_shape_metrics(nums),
            }
        )
    return out


def _normalize_shapes(rows: list[dict[str, Any]]) -> dict[str, tuple[float, float]]:
    """필드별 min/max (동일 값이면 0~1 평탄)."""
    stats: dict[str, tuple[float, float]] = {}
    for field in SHAPE_FIELDS:
        vals = [float(r["shape"][field]) for r in rows]
        if not vals:
            stats[field] = (0.0, 1.0)
            continue
        lo, hi = min(vals), max(vals)
        if hi <= lo:
            stats[field] = (lo, lo + 1.0)
        else:
            stats[field] = (lo, hi)
    return stats


def _shape_vector(shape: dict[str, int], stats: dict[str, tuple[float, float]]) -> list[float]:
    vec: list[float] = []
    for field in SHAPE_FIELDS:
        lo, hi = stats[field]
        v = float(shape[field])
        vec.append((v - lo) / (hi - lo))
    return vec


def _euclidean(a: list[float], b: list[float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def compute_unpopularity_before(
    cutoff_draw_no: int,
    db_path: str | None = None,
    *,
    crowd_top_pct: float = 0.30,
) -> dict[str, Any]:
    """cutoff 미만 tiers+draws로 인기(혼잡) 형태 프로필 학습 (R13)."""
    path = str(db_path or LOTTO_DB_PATH)
    cutoff = int(cutoff_draw_no)
    rows = _load_tier45_rows(cutoff, path)
    if not rows:
        return {
            "cutoff_draw_no": cutoff,
            "draw_count": 0,
            "number_unpop": {n: 0.5 for n in range(1, 46)},
            "crowded_centroid": {},
            "tier45_median": 0,
        }

    stats = _normalize_shapes(rows)
    tier_vals = sorted(r["tier45"] for r in rows)
    median_t = tier_vals[len(tier_vals) // 2]
    k = max(1, int(len(rows) * crowd_top_pct))
    crowded_rows = sorted(rows, key=lambda r: r["tier45"], reverse=True)[:k]

    centroid = {
        field: sum(r["shape"][field] for r in crowded_rows) / len(crowded_rows)
        for field in SHAPE_FIELDS
    }
    centroid_vec = _shape_vector(
        {f: int(round(centroid[f])) for f in SHAPE_FIELDS},
        stats,
    )
    max_dist = (len(SHAPE_FIELDS) ** 0.5) or 1.0

    number_tier: dict[int, list[int]] = {n: [] for n in range(1, 46)}
    for r in rows:
        for n in r["nums"]:
            number_tier[n].append(r["tier45"])

    tier_max = max(tier_vals) or 1
    number_unpop: dict[int, float] = {}
    for n in range(1, 46):
        vals = number_tier[n]
        if not vals:
            number_unpop[n] = 0.5
        else:
            avg_t = sum(vals) / len(vals)
            number_unpop[n] = round(1.0 - (avg_t / tier_max), 4)

    return {
        "cutoff_draw_no": cutoff,
        "draw_count": len(rows),
        "tier45_median": median_t,
        "crowded_centroid": centroid,
        "shape_stats": stats,
        "centroid_vec": centroid_vec,
        "max_shape_dist": max_dist,
        "number_unpop": number_unpop,
        "crowded_draws_n": len(crowded_rows),
    }


def set_unpopularity_score(nums: list[int], profile: dict[str, Any]) -> float:
    """조합 비인기 점수 0~1 (인기 혼잡 형태와 멀수록 높음)."""
    stats = profile.get("shape_stats") or _normalize_shapes(
        [{"shape": extended_shape_metrics(nums)}]
    )
    vec = _shape_vector(extended_shape_metrics(nums), stats)
    centroid = profile.get("centroid_vec") or [0.5] * len(SHAPE_FIELDS)
    max_d = float(profile.get("max_shape_dist") or 1.0)
    dist = _euclidean(vec, centroid)
    return round(min(dist / max_d, 1.0), 4)


def apply_unpop_boost(
    pool_weight: dict[int, float],
    profile: dict[str, Any],
    blend: float = 0.15,
) -> dict[int, float]:
    """풀 가중치에 번호별 비인기(저혼잡) 보조 혼합."""
    b = max(float(blend), 0.0)
    nu = profile.get("number_unpop") or {}
    return {
        n: max(pool_weight.get(n, 0.0) * (1.0 + b * float(nu.get(n, 0.5))), 0.001)
        for n in range(1, 46)
    }


def winner_dispersion_score(
    sets: list[list[int]],
    profile: dict[str, Any],
) -> float:
    """5세트가 비인기(저혼잡) 영역을 얼마나 넓게 덮는지 — 세트별 비인기 점수 표준편차."""
    if not sets:
        return 0.0
    scores = [set_unpopularity_score(s, profile) for s in sets]
    if len(scores) < 2:
        return scores[0] if scores else 0.0
    mean_s = sum(scores) / len(scores)
    var_s = sum((x - mean_s) ** 2 for x in scores) / len(scores)
    return round(var_s ** 0.5, 4)
