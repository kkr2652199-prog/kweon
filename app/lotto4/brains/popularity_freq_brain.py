"""v13_popularity_freq — 역사적 인기번호 기반 조합 생성기 (전략 X 1뇌).

number_popularity.top30_pct 가중치로 6번호 × 5세트 생성.
R2: 당첨 확률 향상 주장 금지 — 기술통계 기반 조합 생성만.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from app.lotto4.brains._utils import _weighted_draw_without_replacement
from app.lotto4.models import get_lotto4_db

NUM_SETS = 5
DISCLAIMER = (
    "역사적으로 당첨자가 많았던 회차에 자주 등장한 번호 기반입니다. "
    "당첨 확률은 모든 조합이 동일합니다."
)
BRAIN_TAG = "v13_popularity_freq"
RNG_SEED_MUL = 20260617


def load_popularity_weights(db_path: str | Path | None = None) -> dict[int, float]:
    """number_popularity 테이블에서 top30_pct 가중치 로드."""
    _ = db_path  # 호환용; 4군 DB 고정
    conn = get_lotto4_db()
    try:
        rows = conn.execute(
            """
            SELECT number, top30_pct
            FROM number_popularity
            WHERE era = 'C'
            ORDER BY number
            """
        ).fetchall()
        if not rows:
            return {n: 1.0 / 45.0 for n in range(1, 46)}
        weights = {int(r[0]): max(float(r[1]), 0.01) for r in rows}
        for n in range(1, 46):
            weights.setdefault(n, 0.01)
        return weights
    finally:
        conn.close()


def avg_popularity_score(nums: list[int], weights: dict[int, float]) -> float:
    """세트 6번호의 평균 top30_pct."""
    vals = [weights.get(int(n), 0.0) for n in nums if 1 <= int(n) <= 45]
    if not vals:
        return 0.0
    return round(sum(vals) / len(vals), 4)


def _draw_one_set(
    rng: random.Random,
    weights: dict[int, float],
    existing: list[list[int]],
    jaccard_limit: float = 0.5,
) -> list[int] | None:
    from app.lotto4.brains._utils import jaccard

    for _ in range(200):
        picked = _weighted_draw_without_replacement(rng, weights, 6)
        if len(picked) != 6:
            continue
        st = set(picked)
        if any(jaccard(st, set(prev)) >= jaccard_limit for prev in existing):
            continue
        return picked
    picked = _weighted_draw_without_replacement(rng, weights, 6)
    return picked if len(picked) == 6 else None


def generate_popularity_sets(
    target_draw_no: int,
    db_path: str | Path | None = None,
    n_sets: int = NUM_SETS,
) -> dict[str, Any]:
    """가중 랜덤으로 인기번호 기반 조합 n_sets개 생성."""
    weights = load_popularity_weights(db_path)
    sets: list[dict[str, Any]] = []
    existing: list[list[int]] = []

    for set_no in range(1, n_sets + 1):
        seed = int(target_draw_no) * RNG_SEED_MUL + set_no * 97
        rng = random.Random(seed)
        nums = _draw_one_set(rng, weights, existing)
        if nums is None:
            continue
        existing.append(nums)
        sets.append(
            {
                "set_no": set_no,
                "numbers": nums,
                "avg_popularity_score": avg_popularity_score(nums, weights),
            }
        )

    return {
        "target_draw_no": int(target_draw_no),
        "brain": BRAIN_TAG,
        "disclaimer": DISCLAIMER,
        "source_table": "number_popularity",
        "sets": sets,
    }


def generate(target_draw_no: int, db_path: str | Path | None = None) -> dict[str, Any]:
    """API·테스트용 진입점."""
    return generate_popularity_sets(target_draw_no, db_path=db_path)
