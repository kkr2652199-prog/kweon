"""v13_trend: 다중 윈도우 + surprisal + 최근성 + 동반출현(상위) 보정."""

from __future__ import annotations

import math
import random
from collections import defaultdict

from app.lotto4.brains._utils import (
    generate_sets_with_filters,
    load_cooccur3,
    load_draws_before,
    predict_sum_range_adaptive,
)

WINDOWS: list[tuple[int | None, float]] = [
    (10, 0.40),
    (30, 0.25),
    (50, 0.20),
    (100, 0.12),
    (None, 0.08),
]
SCORE_WEIGHTS = {"freq": 0.5, "surprisal": 0.2, "recency": 0.3}
SIGMOID_CENTER = 7
SIGMOID_SLOPE = 0.1
SUM_RANGE = (100, 175)
JACCARD_LIMIT = 0.5
COOCCUR3_TOP_N = 100
COOCCUR3_BONUS = 0.05
MAX_RETRY = 50
EPS = 1e-9


def _count_in_window(draws_slice: list[dict], ball: int) -> int:
    c = 0
    for d in draws_slice:
        for x in d["nums"]:
            if x == ball:
                c += 1
    return c


def _triple_cover_bonus(
    top_rows: list[tuple[int, int, int, int]],
) -> dict[int, float]:
    """상위 동반 3조합에 자주 등장하는 번호에 최대 COOCCUR3_BONUS까지 가산."""
    if not top_rows:
        return {}
    max_c = max(r[3] for r in top_rows)
    if max_c <= 0:
        return {}
    acc: dict[int, float] = defaultdict(float)
    for a, b, cc, cnt in top_rows:
        w = (cnt / max_c) * (COOCCUR3_BONUS / 3.0)
        acc[a] += w
        acc[b] += w
        acc[cc] += w
    return {k: min(COOCCUR3_BONUS, v) for k, v in acc.items()}


def predict(draw_no: int, db_path: str) -> list[list[int]]:
    """5세트, 각 6개 번호 (1~45), 오름차순."""
    draws = load_draws_before(db_path, draw_no)
    if len(draws) < 3:
        return []

    n = len(draws)
    last_seen: dict[int, int] = {}
    for d in draws:
        dn = int(d["draw_no"])
        for x in d["nums"]:
            last_seen[int(x)] = dn

    weighted_freq: dict[int, float] = {i: 0.0 for i in range(1, 46)}
    for size, w in WINDOWS:
        if size is None:
            sl = draws
        else:
            sl = draws[-size:] if n >= size else draws
        denom = max(6 * len(sl), 1)
        for i in range(1, 46):
            wc = _count_in_window(sl, i)
            weighted_freq[i] += w * (wc / denom)

    surps = [-math.log2(weighted_freq[i] + EPS) for i in range(1, 46)]
    mn, mx = min(surps), max(surps)
    span = mx - mn + 1e-12
    surprisal_norm = {i: (surps[i - 1] - mn) / span for i in range(1, 46)}

    recency_boost: dict[int, float] = {}
    for i in range(1, 46):
        gap = draw_no - last_seen[i] if i in last_seen else draw_no + 50
        recency_boost[i] = 1.0 / (1.0 + math.exp(-SIGMOID_SLOPE * (gap - SIGMOID_CENTER)))

    co_rows = load_cooccur3(db_path, COOCCUR3_TOP_N)
    tri_bonus = _triple_cover_bonus(co_rows)

    scores: dict[int, float] = {}
    for i in range(1, 46):
        f = weighted_freq[i]
        s = surprisal_norm[i]
        r = recency_boost[i]
        t = tri_bonus.get(i, 0.0)
        scores[i] = (
            SCORE_WEIGHTS["freq"] * f
            + SCORE_WEIGHTS["surprisal"] * s
            + SCORE_WEIGHTS["recency"] * r
            + t
        )

    rng = random.Random(draw_no * 1_000_003 + 4242)
    sum_rng = predict_sum_range_adaptive(draws, history=50, ma_window=10, std_mult=1.0, fallback=(SUM_RANGE[0], SUM_RANGE[1]))
    return generate_sets_with_filters(
        scores,
        n_sets=5,
        n_pick=6,
        sum_range=sum_rng,
        jaccard_limit=JACCARD_LIMIT,
        max_retry=MAX_RETRY,
        rng=rng,
    )[:5]
