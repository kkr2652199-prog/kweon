"""
v13_gen — 경량 VAE 스타일 생성 뇌
과거 당첨 조합 분포를 PCA 잠재 공간으로 압축·샘플링하여 조합 생성.
순수 numpy, 외부 ML 프레임워크 미사용.
"""

from __future__ import annotations

import random
from typing import Any

import numpy as np

from app.lotto4.brains._utils import (
    generate_sets_with_filters,
    jaccard,
    load_draws_before,
    predict_sum_range_adaptive,
)

LATENT_DIM = 8
NOISE_SCALE = 0.8
RECENT_WINDOW = 20
RECENT_BOOST = 0.1
NUM_SETS = 5
MAX_RETRIES = 80
SUM_RANGE = (100, 175)
JACCARD_LIMIT = 0.5
MIN_DRAWS = 30


def _encode_draws(draws: list[dict[str, Any]]) -> np.ndarray:
    rows: list[np.ndarray] = []
    for d in draws:
        vec = np.zeros(45, dtype=np.float64)
        for n in d["nums"]:
            ni = int(n)
            if 1 <= ni <= 45:
                vec[ni - 1] = 1.0
        rows.append(vec)
    return np.stack(rows, axis=0)


def _pca_fit(
    X: np.ndarray, n_components: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
    mean = X.mean(axis=0)
    Xc = X - mean
    if Xc.shape[0] < 2:
        raise ValueError("too_few_rows")
    n_comp = min(n_components, Xc.shape[0] - 1, Xc.shape[1])
    n_comp = max(1, int(n_comp))
    _u, _s, Vt = np.linalg.svd(Xc, full_matrices=False)
    components = np.asarray(Vt[:n_comp], dtype=np.float64)
    Z = Xc @ components.T
    mu = Z.mean(axis=0)
    sigma = Z.std(axis=0) + 1e-8
    return mean, components, mu, sigma, n_comp


def _decode(z: np.ndarray, mean_row: np.ndarray, components: np.ndarray) -> np.ndarray:
    return z @ components + mean_row


def _recent_freq(draws: list[dict[str, Any]], window: int) -> np.ndarray:
    freq = np.zeros(45, dtype=np.float64)
    recent = draws[-window:] if len(draws) >= window else draws
    for d in recent:
        for n in d["nums"]:
            ni = int(n)
            if 1 <= ni <= 45:
                freq[ni - 1] += 1.0
    mx = float(freq.max())
    if mx > 0:
        freq /= mx
    return freq


def _select_numbers(decoded: np.ndarray, recent_boost: np.ndarray) -> list[int]:
    score = decoded + RECENT_BOOST * recent_boost
    top6_idx = np.argsort(score)[-6:]
    return sorted((int(i) + 1) for i in top6_idx)


def _validate(nums: list[int], sum_lo: int, sum_hi: int) -> bool:
    if len(nums) != 6 or len(set(nums)) != 6:
        return False
    if not all(1 <= n <= 45 for n in nums):
        return False
    s = sum(nums)
    odd = sum(1 for n in nums if n % 2 == 1)
    return sum_lo <= s <= sum_hi and 2 <= odd <= 4


def predict(draw_no: int, db_path: str) -> list[list[int]]:
    draws = load_draws_before(db_path, draw_no)
    if not draws or len(draws) < MIN_DRAWS:
        rng = random.Random(draw_no * 800_029 + 17)
        return [sorted(rng.sample(range(1, 46), 6)) for _ in range(NUM_SETS)]

    X = _encode_draws(draws)
    try:
        mean_row, components, mu, sigma, k = _pca_fit(X, LATENT_DIM)
    except ValueError:
        rng = random.Random(draw_no * 800_029 + 19)
        return [sorted(rng.sample(range(1, 46), 6)) for _ in range(NUM_SETS)]

    recent_boost = _recent_freq(draws, RECENT_WINDOW)
    seed = (draw_no * 800_029 + 17) % (2**32)
    rng_np = np.random.default_rng(seed)

    sum_lo, sum_hi = predict_sum_range_adaptive(
        draws,
        history=50,
        ma_window=10,
        std_mult=1.0,
        fallback=(SUM_RANGE[0], SUM_RANGE[1]),
    )
    width = max(sum_hi - sum_lo, 1)
    ref_w = 75.0
    noise_eff = float(np.clip(NOISE_SCALE * (width / ref_w), 0.35, 1.25))

    results: list[list[int]] = []
    seen: set[tuple[int, ...]] = set()
    attempts = 0
    while len(results) < NUM_SETS and attempts < MAX_RETRIES:
        attempts += 1
        eps = rng_np.standard_normal(k)
        z = mu + sigma * noise_eff * eps
        decoded = _decode(z, mean_row, components)
        nums = _select_numbers(decoded, recent_boost)
        if not _validate(nums, sum_lo, sum_hi):
            continue
        st = set(nums)
        if any(jaccard(st, set(ex)) >= JACCARD_LIMIT for ex in results):
            continue
        t = tuple(nums)
        if t in seen:
            continue
        seen.add(t)
        results.append(nums)

    noise_hi = min(1.5, noise_eff * 1.8)
    extra_guard = 0
    while len(results) < NUM_SETS and extra_guard < MAX_RETRIES * 4:
        extra_guard += 1
        eps = rng_np.standard_normal(k)
        z = mu + sigma * noise_hi * eps
        decoded = _decode(z, mean_row, components)
        nums = _select_numbers(decoded, recent_boost)
        if not _validate(nums, sum_lo, sum_hi):
            continue
        if any(jaccard(set(nums), set(ex)) >= JACCARD_LIMIT for ex in results):
            continue
        t = tuple(nums)
        if t in seen:
            continue
        seen.add(t)
        results.append(nums)

    if len(results) < NUM_SETS:
        score_dict = {i: max(float(recent_boost[i - 1]), 0.001) for i in range(1, 46)}
        extra = generate_sets_with_filters(
            score_dict,
            n_sets=NUM_SETS - len(results),
            n_pick=6,
            sum_range=(sum_lo, sum_hi),
            jaccard_limit=JACCARD_LIMIT,
            max_retry=MAX_RETRIES,
            rng=random.Random(seed + 7),
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
        final = generate_sets_with_filters(
            {i: 1.0 for i in range(1, 46)},
            n_sets=NUM_SETS,
            n_pick=6,
            sum_range=(sum_lo, sum_hi),
            jaccard_limit=JACCARD_LIMIT,
            max_retry=MAX_RETRIES,
            rng=random.Random(seed + 11),
            odd_range=(2, 4),
        )
        for s in final:
            if len(results) >= NUM_SETS:
                break
            ts = tuple(s)
            if ts in seen:
                continue
            seen.add(ts)
            results.append(sorted(s))

    if len(results) < NUM_SETS:
        last_rng = random.Random(seed + 99)
        pad = generate_sets_with_filters(
            {i: 1.0 for i in range(1, 46)},
            n_sets=NUM_SETS - len(results),
            n_pick=6,
            sum_range=(sum_lo, sum_hi),
            jaccard_limit=JACCARD_LIMIT,
            max_retry=MAX_RETRIES * 2,
            rng=last_rng,
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
