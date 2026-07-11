"""
v13_rl — 경량 강화학습 뇌 (Tabular Q-Learning)
번호를 순차 선택하며 Q-table 정책으로 조합 생성.
순수 numpy, 외부 ML 프레임워크 미사용.
"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Any

import numpy as np

from app.lotto4.brains._utils import (
    generate_sets_with_filters,
    jaccard,
    load_draws_before,
)

ALPHA = 0.08
EPSILON = 0.12
TRAIN_WINDOW = 300
EPISODES_PER_DRAW = 3
NUM_SETS = 5
MAX_RETRIES = 80
QUANTIZE_BINS = 4
STATE_DIM = 5
TRAIN_RNG_SEED = 42
SUM_RANGE = (100, 175)
JACCARD_LIMIT = 0.5
MIN_DRAWS = 30

BANDS: list[tuple[int, int]] = [(1, 9), (10, 18), (19, 27), (28, 36), (37, 45)]


def _get_band(n: int) -> int:
    for idx, (lo, hi) in enumerate(BANDS):
        if lo <= n <= hi:
            return idx
    return 0


def _encode_state(selected: list[int]) -> str:
    k = len(selected)
    s = [0.0] * STATE_DIM

    s[0] = k / 6.0
    s[1] = sum(selected) / 175.0 if selected else 0.0
    s[2] = (sum(1 for n in selected if n % 2 == 1) / 6.0) if selected else 0.0

    if k >= 2:
        sorted_sel = sorted(selected)
        gaps = [sorted_sel[i + 1] - sorted_sel[i] for i in range(len(sorted_sel) - 1)]
        s[3] = max(gaps) / 44.0
    else:
        s[3] = 0.0

    s[4] = (float(np.mean([_get_band(n) for n in selected])) / 4.0) if selected else 0.0

    key_parts: list[str] = []
    for v in s:
        b = min(int(v * QUANTIZE_BINS), QUANTIZE_BINS - 1)
        key_parts.append(str(max(0, b)))
    return "".join(key_parts)


def _build_qtable(
    draws: list[dict[str, Any]], window: int, train_rng: np.random.Generator
) -> dict[str, np.ndarray]:
    q_inner: defaultdict[str, np.ndarray] = defaultdict(
        lambda: np.zeros(46, dtype=np.float64)
    )
    recent = draws[-window:] if len(draws) >= window else draws

    for d in recent:
        nums = [int(x) for x in d["nums"] if 1 <= int(x) <= 45]
        if len(nums) != 6 or len(set(nums)) != 6:
            continue

        selected: list[int] = []
        for n in sorted(nums):
            state = _encode_state(selected)
            q_inner[state][n] += ALPHA * (1.0 - q_inner[state][n])
            selected.append(n)

        for _ in range(EPISODES_PER_DRAW - 1):
            rand_nums = sorted(
                train_rng.choice(np.arange(1, 46), size=6, replace=False).tolist()
            )
            selected = []
            for n in rand_nums:
                state = _encode_state(selected)
                q_inner[state][n] += ALPHA * (0.0 - q_inner[state][n])
                selected.append(n)

    return {k: v.copy() for k, v in q_inner.items()}


def _select_with_policy(Q: dict[str, np.ndarray], rng: np.random.Generator) -> list[int]:
    selected: list[int] = []
    for _step in range(6):
        state = _encode_state(selected)
        q_vals = Q.get(state)
        if q_vals is None:
            q_vals = np.zeros(46, dtype=np.float64)

        available = [n for n in range(1, 46) if n not in selected]
        if not available:
            break

        if float(rng.random()) < EPSILON:
            chosen = int(rng.choice(available))
        else:
            scores = np.array([max(float(q_vals[n]), 1e-9) for n in available], dtype=np.float64)
            scores /= scores.sum()
            idx = int(rng.choice(len(available), p=scores))
            chosen = available[idx]

        selected.append(chosen)

    return sorted(selected)


def _validate(nums: list[int]) -> bool:
    if len(nums) != 6 or len(set(nums)) != 6:
        return False
    if not all(1 <= n <= 45 for n in nums):
        return False
    sm = sum(nums)
    odd = sum(1 for n in nums if n % 2 == 1)
    return SUM_RANGE[0] <= sm <= SUM_RANGE[1] and 2 <= odd <= 4


def _q_to_score_dict(Q: dict[str, np.ndarray]) -> dict[int, float]:
    acc = np.zeros(46, dtype=np.float64)
    for arr in Q.values():
        acc += arr
    out = {i: max(float(acc[i]), 0.001) for i in range(1, 46)}
    tot = sum(out.values())
    if tot <= 0:
        return {i: 1.0 for i in range(1, 46)}
    return {i: max(out[i] / tot, 0.001) for i in range(1, 46)}


def predict(draw_no: int, db_path: str) -> list[list[int]]:
    draws = load_draws_before(db_path, draw_no)
    if not draws or len(draws) < MIN_DRAWS:
        rng = random.Random(draw_no * 900_031 + 19)
        return [sorted(rng.sample(range(1, 46), 6)) for _ in range(NUM_SETS)]

    train_rng = np.random.default_rng(TRAIN_RNG_SEED)
    Q = _build_qtable(draws, TRAIN_WINDOW, train_rng)
    rng = np.random.default_rng((draw_no * 900_031 + 19) % (2**32))

    results: list[list[int]] = []
    seen: set[tuple[int, ...]] = set()
    attempts = 0
    while len(results) < NUM_SETS and attempts < MAX_RETRIES:
        attempts += 1
        candidate = _select_with_policy(Q, rng)
        if not _validate(candidate):
            continue
        if any(jaccard(set(candidate), set(ex)) >= JACCARD_LIMIT for ex in results):
            continue
        t = tuple(candidate)
        if t in seen:
            continue
        seen.add(t)
        results.append(candidate)

    extra_guard = 0
    while len(results) < NUM_SETS and extra_guard < MAX_RETRIES * 6:
        extra_guard += 1
        candidate = sorted(
            rng.choice(np.arange(1, 46), size=6, replace=False).astype(int).tolist()
        )
        if not _validate(candidate):
            continue
        if any(jaccard(set(candidate), set(ex)) >= JACCARD_LIMIT for ex in results):
            continue
        t = tuple(candidate)
        if t in seen:
            continue
        seen.add(t)
        results.append(candidate)

    if len(results) < NUM_SETS:
        score_dict = _q_to_score_dict(Q)
        seed = (draw_no * 900_031 + 23) % (2**32)
        extra = generate_sets_with_filters(
            score_dict,
            n_sets=NUM_SETS - len(results),
            n_pick=6,
            sum_range=SUM_RANGE,
            jaccard_limit=JACCARD_LIMIT,
            max_retry=MAX_RETRIES,
            rng=random.Random(seed),
            odd_range=(2, 4),
        )
        for s in extra:
            if len(results) >= NUM_SETS:
                break
            ts = tuple(s)
            if ts in seen:
                continue
            if any(jaccard(set(s), set(ex)) >= JACCARD_LIMIT for ex in results):
                continue
            seen.add(ts)
            results.append(sorted(s))

    if len(results) < NUM_SETS:
        pad = generate_sets_with_filters(
            {i: 1.0 for i in range(1, 46)},
            n_sets=NUM_SETS - len(results),
            n_pick=6,
            sum_range=SUM_RANGE,
            jaccard_limit=JACCARD_LIMIT,
            max_retry=MAX_RETRIES * 2,
            rng=random.Random((draw_no * 900_031 + 29) % (2**32)),
            odd_range=(2, 4),
        )
        for s in pad:
            if len(results) >= NUM_SETS:
                break
            ts = tuple(s)
            if ts in seen:
                continue
            seen.add(ts)
            results.append(sorted(s))

    return [sorted(list(x)) for x in results[:NUM_SETS]]
