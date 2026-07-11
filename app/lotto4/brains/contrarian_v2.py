"""
v13_contrarian_v2 — 역발상 뇌 (Entropy-Maximizing Contrarian).
오래 안 나온 번호 선호, 과열 번호 회피, 5대역 중 최소 3대역 분산.
"""

from __future__ import annotations

import math
import random

from app.lotto4.brains._utils import (
    generate_sets_with_filters,
    load_cooccur3,
    load_draws_before,
)

MEDIAN_GAP = 9
SLOPE = 3.0
WINDOW = 15
OVERHEAT_THRESHOLD = 2
PENALTY_RATE = 0.15
COOCCUR_PENALTY = 0.03
COOCCUR_BONUS = 0.02
COOCCUR_TOP_N = 150
NUM_SETS = 5
SUM_RANGE = (100, 175)
JACCARD_LIMIT = 0.5
MAX_RETRY = 60
BANDS: list[tuple[int, int]] = [(1, 9), (10, 18), (19, 27), (28, 36), (37, 45)]
MIN_BANDS = 3


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _calc_gap(draws: list[dict], draw_no: int) -> dict[int, int]:
    last_seen: dict[int, int] = {}
    for d in draws:
        dn = int(d["draw_no"])
        for n in d["nums"]:
            xi = int(n)
            if 1 <= xi <= 45:
                last_seen[xi] = max(last_seen.get(xi, 0), dn)
    gap: dict[int, int] = {}
    for i in range(1, 46):
        if i in last_seen:
            gap[i] = draw_no - last_seen[i]
        else:
            gap[i] = draw_no
    return gap


def _calc_window_freq(draws: list[dict], window: int) -> dict[int, int]:
    freq = {i: 0 for i in range(1, 46)}
    recent = draws[-window:] if len(draws) >= window else draws
    for d in recent:
        for n in d["nums"]:
            xi = int(n)
            if 1 <= xi <= 45:
                freq[xi] += 1
    return freq


def _get_cooccur_hot_cold(db_path: str, top_n: int) -> tuple[set[int], set[int]]:
    rows = load_cooccur3(db_path, top_n)
    hot_nums: set[int] = set()
    for r in rows:
        for val in r[:3]:
            xi = int(val)
            if 1 <= xi <= 45:
                hot_nums.add(xi)
    cold_nums = set(range(1, 46)) - hot_nums
    return hot_nums, cold_nums


def _band_filter(nums: list[int]) -> bool:
    bands_hit: set[int] = set()
    for n in nums:
        for idx, (lo, hi) in enumerate(BANDS):
            if lo <= n <= hi:
                bands_hit.add(idx)
                break
    return len(bands_hit) >= MIN_BANDS


def _random_five_sets(draw_no: int) -> list[list[int]]:
    rng = random.Random(draw_no * 400_019 + 29)
    out: list[list[int]] = []
    seen: set[tuple[int, ...]] = set()
    guard = 0
    while len(out) < NUM_SETS and guard < 20_000:
        guard += 1
        s = sorted(rng.sample(range(1, 46), 6))
        if not _band_filter(s):
            continue
        oddc = sum(1 for x in s if x % 2 == 1)
        if oddc < 2 or oddc > 4:
            continue
        sm = sum(s)
        if sm < SUM_RANGE[0] or sm > SUM_RANGE[1]:
            continue
        t = tuple(s)
        if t in seen:
            continue
        seen.add(t)
        out.append(s)
    rng2 = random.Random(draw_no * 400_019 + 30)
    while len(out) < NUM_SETS:
        s = sorted(rng2.sample(range(1, 46), 6))
        t = tuple(s)
        if t in seen:
            continue
        seen.add(t)
        out.append(s)
    return out[:NUM_SETS]


def predict(draw_no: int, db_path: str) -> list[list[int]]:
    draws = load_draws_before(db_path, draw_no)
    if not draws:
        return _random_five_sets(draw_no)

    gap = _calc_gap(draws, draw_no)
    cooling: dict[int, float] = {}
    for i in range(1, 46):
        cooling[i] = _sigmoid((gap[i] - MEDIAN_GAP) / SLOPE)

    freq_w = _calc_window_freq(draws, WINDOW)
    overheat: dict[int, float] = {}
    for i in range(1, 46):
        overheat[i] = max(0, freq_w[i] - OVERHEAT_THRESHOLD) * PENALTY_RATE

    hot_nums, cold_nums = _get_cooccur_hot_cold(db_path, COOCCUR_TOP_N)
    cooccur_adj: dict[int, float] = {}
    for i in range(1, 46):
        if i in hot_nums:
            cooccur_adj[i] = -COOCCUR_PENALTY
        elif i in cold_nums:
            cooccur_adj[i] = COOCCUR_BONUS
        else:
            cooccur_adj[i] = 0.0

    score_dict: dict[int, float] = {}
    for i in range(1, 46):
        s = cooling[i] - overheat[i] + cooccur_adj[i]
        score_dict[i] = max(float(s), 0.001)

    rng = random.Random(draw_no * 502_017 + 77)
    sets: list[list[int]] = []
    seen: set[tuple[int, ...]] = set()
    guard = 0
    while len(sets) < NUM_SETS and guard < 120:
        guard += 1
        batch = generate_sets_with_filters(
            score_dict,
            n_sets=NUM_SETS,
            n_pick=6,
            sum_range=SUM_RANGE,
            jaccard_limit=JACCARD_LIMIT,
            max_retry=MAX_RETRY,
            rng=rng,
            odd_range=(2, 4),
            extra_accept=_band_filter,
        )
        for s in batch:
            t = tuple(s)
            if t in seen:
                continue
            seen.add(t)
            sets.append(s)
            if len(sets) >= NUM_SETS:
                break

    fill_guard = 0
    while len(sets) < NUM_SETS and fill_guard < 100:
        fill_guard += 1
        one = generate_sets_with_filters(
            score_dict,
            n_sets=1,
            n_pick=6,
            sum_range=SUM_RANGE,
            jaccard_limit=JACCARD_LIMIT,
            max_retry=MAX_RETRY,
            rng=rng,
            odd_range=(2, 4),
            extra_accept=_band_filter,
        )
        for s in one:
            t = tuple(s)
            if t in seen:
                continue
            seen.add(t)
            sets.append(s)
            break

    if len(sets) < NUM_SETS:
        loose = generate_sets_with_filters(
            score_dict,
            n_sets=NUM_SETS,
            n_pick=6,
            sum_range=SUM_RANGE,
            jaccard_limit=JACCARD_LIMIT,
            max_retry=80,
            rng=rng,
            odd_range=(2, 4),
            extra_accept=None,
        )
        for s in loose:
            if len(sets) >= NUM_SETS:
                break
            t = tuple(s)
            if t in seen:
                continue
            if _band_filter(s):
                seen.add(t)
                sets.append(s)

    while len(sets) < NUM_SETS:
        fill = _random_five_sets(draw_no + len(sets))
        for s in fill:
            t = tuple(s)
            if t in seen:
                continue
            seen.add(t)
            sets.append(s)
            if len(sets) >= NUM_SETS:
                break

    return [list(x) for x in sets[:NUM_SETS]]
