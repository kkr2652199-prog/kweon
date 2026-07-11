"""미출현 간격(gap) 신호 — draw_no < cutoff 만 사용 (R13 walk-forward)."""

from __future__ import annotations

import random
import sqlite3
from typing import Any

from app.lotto4.brains._utils import _weighted_draw_without_replacement, jaccard
from app.lotto4.models import LOTTO_DB_PATH

NUM_SETS = 5
JACCARD_LIMIT = 0.5
RNG_SEED_MUL = 20260623


class GapState:
    """증분 gap 추적 (백테스트용)."""

    def __init__(self) -> None:
        self.last_seen: dict[int, int] = {}

    def add_draw(self, draw_no: int, nums: list[int]) -> None:
        dn = int(draw_no)
        for n in nums:
            ni = int(n)
            if 1 <= ni <= 45:
                self.last_seen[ni] = dn

    def gaps_at(self, cutoff_draw_no: int) -> dict[int, int]:
        cutoff = int(cutoff_draw_no)
        out: dict[int, int] = {}
        for n in range(1, 46):
            last = self.last_seen.get(n, 0)
            if last <= 0:
                out[n] = cutoff - 1
            else:
                out[n] = max(cutoff - last, 1)
        return out

    def copy(self) -> GapState:
        g = GapState()
        g.last_seen = dict(self.last_seen)
        return g


def compute_gap_before(
    cutoff_draw_no: int,
    db_path: str | None = None,
) -> dict[str, Any]:
    """cutoff_draw_no 미만 당첨만으로 각 번호의 미출현 간격 산출 (R13).

    gap(n) = cutoff - last_draw_no (마지막 본번호 출현 회차 이후 경과).
    미출현 이력 없으면 cutoff - 1.
    """
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

    last_seen: dict[int, int] = {}
    for draw_no, *nums in rows:
        dn = int(draw_no)
        for raw in nums:
            try:
                n = int(raw)
            except (TypeError, ValueError):
                continue
            if 1 <= n <= 45:
                last_seen[n] = dn

    gaps: dict[int, int] = {}
    for n in range(1, 46):
        last = last_seen.get(n, 0)
        gaps[n] = (cutoff - last) if last > 0 else (cutoff - 1)

    ranked = sorted(gaps.items(), key=lambda x: (-x[1], x[0]))
    return {
        "cutoff_draw_no": cutoff,
        "draw_count": len(rows),
        "max_draw_no": max((int(r[0]) for r in rows), default=None),
        "gaps": gaps,
        "top_gap_numbers": [
            {"number": n, "gap": g} for n, g in ranked[:15]
        ],
    }


def gap_weights_from_gaps(gaps: dict[int, int]) -> dict[int, float]:
    """gap 클수록 가중치 높음 (0~1 정규화)."""
    if not gaps:
        return {n: 1.0 / 45.0 for n in range(1, 46)}
    max_g = max(gaps.values()) or 1
    return {n: max(float(gaps.get(n, 1)) / max_g, 0.01) for n in range(1, 46)}


def apply_gap_boost(
    pool_weight: dict[int, float],
    gaps: dict[int, int],
    blend: float = 0.2,
) -> dict[int, float]:
    """풀 가중치에 gap 신호 혼합 (hyena 보조용)."""
    b = max(float(blend), 0.0)
    gw = gap_weights_from_gaps(gaps)
    return {
        n: max(pool_weight.get(n, 0.0) * (1.0 + b * gw[n]), 0.001)
        for n in range(1, 46)
    }


def _draw_gap_set(
    rng: random.Random,
    weights: dict[int, float],
    existing: list[list[int]],
) -> list[int] | None:
    for _ in range(200):
        w = {n: max(weights.get(n, 0.01), 0.001) for n in range(1, 46)}
        picked = _weighted_draw_without_replacement(rng, w, 6)
        if len(picked) != 6:
            continue
        nums = sorted(picked)
        st = set(nums)
        if any(jaccard(st, set(prev)) >= JACCARD_LIMIT for prev in existing):
            continue
        return nums
    return None


def generate_gap_sets(
    target_draw_no: int,
    *,
    gaps: dict[int, int] | None = None,
    n_sets: int = NUM_SETS,
) -> dict[str, Any]:
    """gap 가중 단독 5세트 (검증용)."""
    td = int(target_draw_no)
    gap_map = gaps if gaps is not None else compute_gap_before(td)["gaps"]
    weights = gap_weights_from_gaps(gap_map)
    sets: list[dict[str, Any]] = []
    existing: list[list[int]] = []
    for set_no in range(1, n_sets + 1):
        seed = td * RNG_SEED_MUL + set_no * 151
        rng = random.Random(seed)
        nums = _draw_gap_set(rng, weights, existing)
        if nums is None:
            continue
        existing.append(nums)
        avg_gap = round(sum(gap_map.get(n, 0) for n in nums) / 6.0, 2)
        sets.append(
            {
                "set_no": set_no,
                "numbers": nums,
                "avg_gap": avg_gap,
            }
        )
    return {
        "target_draw_no": td,
        "brain": "strategy_x_gap",
        "mode": "walk_forward",
        "disclaimer": (
            "미출현 간격 가중 조합입니다. 추첨 결과 예측이 아니며 "
            "당첨 확률은 모든 조합이 동일합니다."
        ),
        "sets": sets,
    }
