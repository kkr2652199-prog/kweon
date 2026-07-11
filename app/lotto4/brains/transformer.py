"""
v13_transformer — 경량 PatchTST 시계열 뇌
역사적 빈도 패턴(유사 패치) 매칭으로 다음 회차 번호 가중치 추정.
순수 numpy, 외부 ML 프레임워크 미사용.
"""

from __future__ import annotations

import random
from collections import OrderedDict

import numpy as np

from app.lotto4.brains._utils import generate_sets_with_filters, load_draws_before

# === 상수 (TASK 2: 느리면 SLIDE_STEP=10, TOP_K=15, HISTORY_LEN=50 으로 조정) ===
HISTORY_LEN = 100
PATCH_SIZE = 10
SIG_PATCHES = 3
TOP_K = 20
MIN_HISTORY = 120
NUM_SETS = 5
SLIDE_STEP = 5
SUM_RANGE = (100, 175)
JACCARD_LIMIT = 0.5
MAX_RETRY = 60

_CACHE_MAX = 200
_MATRIX_CACHE: OrderedDict[tuple[int, int, int], np.ndarray] = OrderedDict()


def _build_freq_matrix(
    draw_by_no: dict[int, list[int]],
    center_draw: int,
    length: int,
    cache_key: tuple[int, int, int],
) -> np.ndarray:
    """center_draw 직전 length 회차 구간의 번호별 출현 이진 행렬. shape (45, length)."""
    key = cache_key
    if key in _MATRIX_CACHE:
        _MATRIX_CACHE.move_to_end(key)
        return _MATRIX_CACHE[key]

    mat = np.zeros((45, length), dtype=np.float32)
    start = center_draw - length
    for dno in range(start, center_draw):
        nums = draw_by_no.get(dno)
        if not nums:
            continue
        t = dno - start
        if 0 <= t < length:
            for n in nums:
                if 1 <= n <= 45:
                    mat[n - 1, t] = 1.0
    _MATRIX_CACHE[key] = mat
    _MATRIX_CACHE.move_to_end(key)
    while len(_MATRIX_CACHE) > _CACHE_MAX:
        _MATRIX_CACHE.popitem(last=False)
    return mat


def _patchify(matrix: np.ndarray, patch_size: int) -> np.ndarray:
    t = matrix.shape[1]
    num_patches = t // patch_size
    out = np.zeros((45, num_patches), dtype=np.float32)
    for p in range(num_patches):
        out[:, p] = matrix[:, p * patch_size : (p + 1) * patch_size].sum(axis=1)
    return out


def _extract_signature(patch_matrix: np.ndarray, last_n: int) -> np.ndarray:
    n = min(last_n, patch_matrix.shape[1])
    sig = patch_matrix[:, -n:].astype(np.float64).ravel()
    norm = float(np.linalg.norm(sig))
    if norm > 0:
        sig = sig / norm
    return sig


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _nums_at(draw_by_no: dict[int, list[int]], dno: int) -> set[int]:
    nums = draw_by_no.get(dno)
    if not nums:
        return set()
    return {int(n) for n in nums if 1 <= int(n) <= 45}


def predict(draw_no: int, db_path: str) -> list[list[int]]:
    """PatchTST-style 패턴 매칭 → `generate_sets_with_filters`로 5세트."""
    draws = load_draws_before(db_path, draw_no)
    if not draws or len(draws) < MIN_HISTORY:
        rng = random.Random(draw_no * 500_009 + 11)
        return [sorted(rng.sample(range(1, 46), 6)) for _ in range(NUM_SETS)]

    draw_by_no = {int(d["draw_no"]): [int(x) for x in d["nums"]] for d in draws}
    min_d = min(draw_by_no.keys())

    cache_prefix = draw_no
    cur_mat = _build_freq_matrix(draw_by_no, draw_no, HISTORY_LEN, (cache_prefix, draw_no, HISTORY_LEN))
    cur_patches = _patchify(cur_mat, PATCH_SIZE)
    cur_sig = _extract_signature(cur_patches, SIG_PATCHES)

    min_scan = min_d + HISTORY_LEN
    max_scan = draw_no - 1
    similarities: list[tuple[int, float]] = []

    past_dno = min_scan
    while past_dno <= max_scan:
        past_mat = _build_freq_matrix(
            draw_by_no, past_dno, HISTORY_LEN, (cache_prefix, past_dno, HISTORY_LEN)
        )
        past_patches = _patchify(past_mat, PATCH_SIZE)
        past_sig = _extract_signature(past_patches, SIG_PATCHES)
        similarities.append((past_dno, _cosine_sim(cur_sig, past_sig)))
        past_dno += SLIDE_STEP

    similarities.sort(key=lambda x: x[1], reverse=True)
    top_matches = similarities[:TOP_K]

    vote_score = np.zeros(46, dtype=np.float64)
    for past_dno, sim in top_matches:
        # 이력 창 [past_dno - HISTORY_LEN, past_dno - 1] 직후 당첨 = 회차 past_dno
        next_nums = _nums_at(draw_by_no, past_dno)
        for n in next_nums:
            vote_score[n] += sim

    total = float(vote_score[1:46].sum())
    if total <= 0:
        score_dict = {i: 1.0 for i in range(1, 46)}
    else:
        score_dict = {i: max(float(vote_score[i] / total), 0.001) for i in range(1, 46)}

    rng = random.Random(draw_no * 900_001 + 909)
    return generate_sets_with_filters(
        score_dict,
        n_sets=NUM_SETS,
        n_pick=6,
        sum_range=SUM_RANGE,
        jaccard_limit=JACCARD_LIMIT,
        max_retry=MAX_RETRY,
        rng=rng,
    )[:NUM_SETS]
