"""v13_bayesian: Beta 시간감쇠 사후 + 동반출현·보너스 통계 보정."""

from __future__ import annotations

import random
from collections import defaultdict

from app.lotto4.brains._utils import (
    generate_sets_with_filters,
    load_bonus_stats,
    load_cooccur3,
    load_cooccur4,
    load_draws_before,
)

DECAY = 0.998
COOCCUR_BOOST_MAX = 0.15
BONUS_BOOST = 0.03
BONUS_TOP_N = 10
SUM_RANGE = (100, 175)
JACCARD_LIMIT = 0.5
MAX_RETRY = 200
COOCCUR_TOP = 100


def _marginal_cooccur(
    co3: list[tuple[int, int, int, int]], co4: list[tuple[int, int, int, int, int]]
) -> dict[int, float]:
    m3: dict[int, int] = defaultdict(int)
    for a, b, c, cnt in co3:
        for x in (a, b, c):
            m3[x] += cnt
    m4: dict[int, int] = defaultdict(int)
    for a, b, c, d, cnt in co4:
        for x in (a, b, c, d):
            m4[x] += cnt
    max3 = max(m3.values(), default=1)
    max4 = max(m4.values(), default=1)
    out: dict[int, float] = {}
    for i in range(1, 46):
        out[i] = COOCCUR_BOOST_MAX * (
            0.5 * (m3.get(i, 0) / max3) + 0.5 * (m4.get(i, 0) / max4)
        )
    return out


def _bonus_boost_map(stats: dict[int, int]) -> dict[int, float]:
    if not stats:
        return {i: 0.0 for i in range(1, 46)}
    ranked = sorted(stats.items(), key=lambda x: -x[1])[:BONUS_TOP_N]
    hot = {k for k, _ in ranked}
    return {i: (BONUS_BOOST if i in hot else 0.0) for i in range(1, 46)}


def predict(draw_no: int, db_path: str) -> list[list[int]]:
    draws = load_draws_before(db_path, draw_no)
    if len(draws) < 3:
        return []

    alpha = [0.0] * 46
    beta_param = [0.0] * 46
    for i in range(1, 46):
        alpha[i] = 1.0
        beta_param[i] = 1.0

    for d in draws:
        dn = int(d["draw_no"])
        w = DECAY ** max(0, draw_no - dn)
        winners = set(d["nums"])
        for i in range(1, 46):
            if i in winners:
                alpha[i] += w
            else:
                beta_param[i] += w

    E = {i: alpha[i] / (alpha[i] + beta_param[i]) for i in range(1, 46)}

    co3 = load_cooccur3(db_path, COOCCUR_TOP)
    co4 = load_cooccur4(db_path, COOCCUR_TOP)
    co_boost = _marginal_cooccur(co3, co4)
    bstats = load_bonus_stats(db_path)
    bmap = _bonus_boost_map(bstats)

    raw = {i: E[i] + co_boost.get(i, 0.0) + bmap.get(i, 0.0) for i in range(1, 46)}
    rng = random.Random(draw_no * 900_011 + 2151)
    return generate_sets_with_filters(
        raw,
        n_sets=5,
        n_pick=6,
        sum_range=SUM_RANGE,
        jaccard_limit=JACCARD_LIMIT,
        max_retry=MAX_RETRY,
        rng=rng,
        smart_filter_mode="relaxed",
    )[:5]
