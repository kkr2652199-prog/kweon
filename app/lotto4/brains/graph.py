"""
v13_graph — GNN-inspired 동반출현 그래프 뇌
번호 간 동반출현을 대칭 가중 그래프로 모델링하고, 클러스터 경향 샘플링 + 필터로 세트 생성.
순수 numpy, 외부 GNN 프레임워크 미사용.
"""

from __future__ import annotations

import random

import numpy as np

from app.lotto4.brains._utils import (
    generate_sets_with_filters,
    jaccard,
    load_cooccur3,
    load_cooccur4,
    load_draws_before,
    smart_filter,
)

RECENT_WINDOW = 30
RECENCY_BOOST = 0.3
COOCCUR4_WEIGHT = 0.5
PAGERANK_ITER = 2
PAGERANK_DAMPING = 0.85
DEGREE_RATIO = 0.6
PR_RATIO = 0.4
CANDIDATE_POOL = 20
CLUSTER_WEIGHT = 0.3
NUM_SETS = 5
MAX_RETRIES = 60
SUM_RANGE = (100, 175)
JACCARD_LIMIT = 0.5
CLUSTER_ATTEMPT_MULT = 40


def _add_pair(adj: np.ndarray, a: int, b: int, w: float) -> None:
    if a == b or not (1 <= a <= 45 and 1 <= b <= 45) or w <= 0:
        return
    adj[a, b] += w
    adj[b, a] += w


def _build_adjacency(
    cooccur3: list[tuple[int, ...]],
    cooccur4: list[tuple[int, ...]],
) -> np.ndarray:
    adj = np.zeros((46, 46), dtype=np.float64)
    for row in cooccur3:
        if len(row) < 4:
            continue
        a, b, c, freq = int(row[0]), int(row[1]), int(row[2]), float(row[3] or 0)
        if freq <= 0:
            continue
        w = freq * 1.0
        _add_pair(adj, a, b, w)
        _add_pair(adj, a, c, w)
        _add_pair(adj, b, c, w)
    for row in cooccur4:
        if len(row) < 5:
            continue
        nums = [int(row[i]) for i in range(4)]
        freq = float(row[4] or 0)
        if freq <= 0:
            continue
        w = freq * COOCCUR4_WEIGHT
        for i in range(4):
            for j in range(i + 1, 4):
                _add_pair(adj, nums[i], nums[j], w)
    return adj


def _add_recency(adj: np.ndarray, draws: list[dict], window: int, boost: float) -> None:
    recent = draws[-window:] if len(draws) >= window else draws
    for d in recent:
        nums = [int(x) for x in d["nums"] if 1 <= int(x) <= 45]
        for i in range(len(nums)):
            for j in range(i + 1, len(nums)):
                _add_pair(adj, nums[i], nums[j], boost)


def _degree_centrality(adj: np.ndarray) -> np.ndarray:
    deg = np.zeros(46, dtype=np.float64)
    for i in range(1, 46):
        deg[i] = float(adj[i, 1:46].sum())
    return deg


def _pagerank_light(adj: np.ndarray, iterations: int, damping: float) -> np.ndarray:
    n = 45
    pr = np.zeros(46, dtype=np.float64)
    pr[1:46] = 1.0 / n
    deg = _degree_centrality(adj)
    for _ in range(iterations):
        new_pr = np.zeros(46, dtype=np.float64)
        new_pr[1:46] = (1.0 - damping) / n
        for i in range(1, 46):
            s = 0.0
            for j in range(1, 46):
                if j == i:
                    continue
                dj = deg[j]
                if dj <= 0:
                    continue
                s += damping * float(adj[j, i]) / dj * pr[j]
            new_pr[i] += s
        pr = new_pr
    return pr


def _cluster_select(
    adj: np.ndarray,
    node_score: dict[int, float],
    pool: list[int],
    rng: np.random.Generator,
) -> list[int]:
    remaining = list(pool)
    selected: list[int] = []
    w0 = np.array([max(float(node_score.get(n, 0.001)), 1e-9) for n in remaining], dtype=np.float64)
    w0 /= w0.sum()
    idx = int(rng.choice(len(remaining), p=w0))
    selected.append(remaining.pop(idx))

    while len(selected) < 6 and remaining:
        scores: list[float] = []
        for n in remaining:
            ns = max(float(node_score.get(n, 0.001)), 1e-9)
            bonus = float(np.mean([adj[s, n] for s in selected]))
            scores.append(ns + CLUSTER_WEIGHT * bonus)
        ps = np.array(scores, dtype=np.float64)
        ps = np.maximum(ps, 1e-12)
        ps /= ps.sum()
        idx = int(rng.choice(len(remaining), p=ps))
        selected.append(remaining.pop(idx))

    return sorted(selected)


def _passes_cluster_filters(candidate: list[int], existing: list[list[int]]) -> bool:
    if len(candidate) != 6 or len(set(candidate)) != 6:
        return False
    s = sum(candidate)
    if not (SUM_RANGE[0] <= s <= SUM_RANGE[1]):
        return False
    oddc = sum(1 for n in candidate if n % 2 == 1)
    if oddc < 2 or oddc > 4:
        return False
    st = set(candidate)
    for ex in existing:
        if jaccard(st, set(ex)) >= JACCARD_LIMIT:
            return False
    return smart_filter(candidate)


def predict(draw_no: int, db_path: str) -> list[list[int]]:
    """동반출현 그래프 + 간이 PageRank → 상위 20풀 클러스터 샘플 → 부족 시 가중 필터 생성."""
    draws = load_draws_before(db_path, draw_no)
    cooccur3 = load_cooccur3(db_path, None)
    cooccur4 = load_cooccur4(db_path, None)

    if not draws:
        rng = random.Random(draw_no * 700_027 + 13)
        return generate_sets_with_filters(
            {i: 1.0 for i in range(1, 46)},
            n_sets=NUM_SETS,
            n_pick=6,
            sum_range=SUM_RANGE,
            jaccard_limit=JACCARD_LIMIT,
            max_retry=400,
            rng=rng,
        )[:NUM_SETS]

    adj = _build_adjacency(cooccur3, cooccur4)
    _add_recency(adj, draws, RECENT_WINDOW, RECENCY_BOOST)

    deg = _degree_centrality(adj)
    pr = _pagerank_light(adj, PAGERANK_ITER, PAGERANK_DAMPING)
    dmax = float(deg[1:46].max()) or 1.0
    pmax = float(pr[1:46].max()) or 1.0

    node_score: dict[int, float] = {}
    for i in range(1, 46):
        node_score[i] = DEGREE_RATIO * (deg[i] / dmax) + PR_RATIO * (pr[i] / pmax)

    score_dict = {i: max(float(node_score[i]), 0.001) for i in range(1, 46)}

    sorted_nodes = sorted(node_score.items(), key=lambda x: x[1], reverse=True)
    pool = [n for n, _ in sorted_nodes[:CANDIDATE_POOL]]
    if len(pool) < 6:
        rng_fb = random.Random(draw_no * 700_027 + 99)
        return generate_sets_with_filters(
            score_dict,
            n_sets=NUM_SETS,
            n_pick=6,
            sum_range=SUM_RANGE,
            jaccard_limit=JACCARD_LIMIT,
            max_retry=MAX_RETRIES,
            rng=rng_fb,
        )[:NUM_SETS]

    rng_np = np.random.default_rng((draw_no * 700_027 + 13) % (2**32))
    results: list[list[int]] = []
    max_attempts = MAX_RETRIES * CLUSTER_ATTEMPT_MULT
    attempts = 0
    seen: set[tuple[int, ...]] = set()
    while len(results) < NUM_SETS and attempts < max_attempts:
        attempts += 1
        cand = _cluster_select(adj, node_score, list(pool), rng_np)
        t = tuple(cand)
        if t in seen:
            continue
        if _passes_cluster_filters(cand, results):
            seen.add(t)
            results.append(cand)

    if len(results) < NUM_SETS:
        rng_extra = random.Random(draw_no * 700_027 + 17)
        extra = generate_sets_with_filters(
            score_dict,
            n_sets=NUM_SETS - len(results),
            n_pick=6,
            sum_range=SUM_RANGE,
            jaccard_limit=JACCARD_LIMIT,
            max_retry=MAX_RETRIES,
            rng=rng_extra,
        )
        for s in extra:
            ts = tuple(s)
            if ts in seen:
                continue
            if _passes_cluster_filters(s, results):
                seen.add(ts)
                results.append(s)
            if len(results) >= NUM_SETS:
                break

    if len(results) < NUM_SETS:
        fill = generate_sets_with_filters(
            score_dict,
            n_sets=NUM_SETS,
            n_pick=6,
            sum_range=SUM_RANGE,
            jaccard_limit=JACCARD_LIMIT,
            max_retry=MAX_RETRIES,
            rng=random.Random(draw_no * 700_027 + 19),
        )
        for s in fill:
            if len(results) >= NUM_SETS:
                break
            ts = tuple(s)
            if ts in seen:
                continue
            seen.add(ts)
            results.append(s)

    out = [list(x) for x in results[:NUM_SETS]]
    if len(out) < NUM_SETS:
        rng_last = random.Random(draw_no * 700_027 + 21)
        pad = generate_sets_with_filters(
            score_dict,
            n_sets=NUM_SETS - len(out),
            n_pick=6,
            sum_range=SUM_RANGE,
            jaccard_limit=JACCARD_LIMIT,
            max_retry=300,
            rng=rng_last,
        )
        for s in pad:
            if len(out) >= NUM_SETS:
                break
            out.append(sorted(s))
    return out[:NUM_SETS]
