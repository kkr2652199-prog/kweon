"""v13_gap — 갭(Z-score) 기반 리스코어링·가중 표집 (5단계-A)."""

from __future__ import annotations

import random
from typing import Any

import numpy as np

from app.lotto4.brains._utils import (
    jaccard,
    load_draws_before,
    smart_filter_relaxed,
    _weighted_draw_without_replacement,
    sum_filter,
    odd_even_filter,
)

_LAST_PUBLIC_CUT = 1223  # draw_no 미만만 로드 → 1222까지


def _history_cut(draw_no: int) -> int:
    return min(int(draw_no), _LAST_PUBLIC_CUT)


def _nums(draw: dict[str, Any]) -> list[int]:
    return [int(x) for x in draw["nums"]]


def compute_z_scores(draw_no: int, db_path: str) -> dict[int, float]:
    """번호별 Z-score: 양수일수록 출현 간격 대비 오버듀."""
    draws = load_draws_before(db_path, _history_cut(draw_no))
    total_draws = len(draws)
    by_num: dict[int, list[int]] = {i: [] for i in range(1, 46)}
    for d in draws:
        dn = int(d["draw_no"])
        for n in _nums(d):
            nn = int(n)
            if 1 <= nn <= 45:
                by_num[nn].append(dn)

    z_out: dict[int, float] = {}
    d_no = int(draw_no)

    for i in range(1, 46):
        app = sorted(by_num[i])
        if not app:
            z_out[i] = 0.0
            continue
        last_d = app[-1]
        gap_now = float(d_no - last_d)
        mean_gap = float(total_draws) / float(len(app)) if total_draws > 0 else gap_now

        if len(app) >= 2:
            inter = [app[j + 1] - app[j] for j in range(len(app) - 1)]
            std_gap = float(np.std(inter, ddof=0))
        else:
            std_gap = max(mean_gap, 1.0)

        if std_gap < 1e-9:
            std_gap = 1.0
        z_out[i] = (gap_now - mean_gap) / std_gap

    return z_out


def gap_score_for_set(s: list[int], z: dict[int, float]) -> float:
    st = sorted(set(int(x) for x in s if 1 <= int(x) <= 45))
    if len(st) != 6:
        return 0.0
    gap_score = 0.0
    for num in st:
        zi = float(z.get(num, 0.0))
        if zi > 2.0:
            gap_score += 3.0
        elif zi > 1.0:
            gap_score += 1.5
        elif zi > 0.0:
            gap_score += 0.5
        elif zi < -1.5:
            gap_score -= 2.0

    overdue_count = sum(1 for num in st if z.get(num, 0.0) > 1.0)
    recent_count = sum(1 for num in st if z.get(num, 0.0) < 0.0)
    if 1 <= overdue_count <= 3 and 1 <= recent_count <= 3:
        gap_score += 2.0

    return gap_score


def _minmax_normalize(raw: list[float]) -> list[float]:
    if not raw:
        return []
    lo, hi = min(raw), max(raw)
    if hi - lo < 1e-9:
        return [0.5] * len(raw)
    return [(r - lo) / (hi - lo) for r in raw]


def score_combo(combo: set, target_draw: int, db) -> float:
    """갭 Z-score 기반 점수 (0~1 정규화)."""
    st = sorted({int(x) for x in combo if 1 <= int(x) <= 45})
    if len(st) != 6:
        return 0.0
    z = compute_z_scores(target_draw, db)
    raw = gap_score_for_set(st, z)
    return min(1.0, max(0.0, (raw + 5.0) / 15.0))


def score_batch(combos: list, target_draw: int, db) -> list[float]:
    """Z-score 1회 계산 후 배치 점수 (min-max 0~1)."""
    z = compute_z_scores(target_draw, db)
    raw: list[float] = []
    for combo in combos:
        st = sorted({int(x) for x in combo if 1 <= int(x) <= 45})
        if len(st) != 6:
            raw.append(0.0)
        else:
            raw.append(gap_score_for_set(st, z))
    return _minmax_normalize(raw)


def rescore(
    candidate_sets: list[list[int]],
    draw_no: int,
    db_path: str,
) -> list[tuple[list[int], float]]:
    z = compute_z_scores(draw_no, db_path)
    out: list[tuple[list[int], float]] = []
    for raw in candidate_sets:
        st = sorted({int(x) for x in raw if 1 <= int(x) <= 45})
        if len(st) != 6:
            continue
        sc = gap_score_for_set(list(st), z)
        out.append((list(st), sc))
    out.sort(key=lambda x: -x[1])
    return out


def predict(draw_no: int, db_path: str) -> list[list[int]]:
    z = compute_z_scores(draw_no, db_path)
    weights: dict[int, float] = {
        i: max(0.1, float(z[i]) + 2.0) for i in range(1, 46)
    }
    rng = random.Random(draw_no * 193_357 + 4_241)
    sets: list[list[int]] = []
    sum_range = (100, 175)
    for _ in range(3000):
        if len(sets) >= 5:
            break
        cand = _weighted_draw_without_replacement(rng, weights, 6)
        if len(cand) != 6:
            continue
        cand = sorted(cand)
        if not sum_filter(cand, sum_range[0], sum_range[1]):
            continue
        if not odd_even_filter(cand):
            continue
        if not smart_filter_relaxed(cand):
            continue
        st = set(cand)
        if any(jaccard(st, set(p)) >= 0.5 for p in sets):
            continue
        sets.append(cand)

    while len(sets) < 5:
        cand = sorted(rng.sample(range(1, 46), 6))
        if smart_filter_relaxed(cand) and not any(
            jaccard(set(cand), set(p)) >= 0.5 for p in sets
        ):
            sets.append(cand)
        if len(sets) >= 5 or rng.random() > 0.99:
            break
    while len(sets) < 5:
        sets.append(sorted(rng.sample(range(1, 46), 6)))
    return sets[:5]
