"""4군 공동출현 그래프 뇌 — v13_run 슬롯 교체(M-2).

워크포워드 전제: 호출자가 `training`만 전달. `brain_tag`는 **v13_run** 유지.
"""

from __future__ import annotations

import logging
import random
from typing import Any

from app.lotto.filters import tier1_filter
from app.lotto4.legacy.v13_models import (
    V13_WIN_AVOID_N,
    get_recent_winning_sets,
    v13_pass_win_avoid,
    v13_perturb_combo_one_swap,
)

logger = logging.getLogger(__name__)

N_COMMUNITIES = 6
RECENCY_WEIGHT = 2.0
MIN_DRAWS_FOR_GRAPH = 20


def _six_from_draw(d: dict) -> list[int] | None:
    try:
        return sorted(int(d[f"num{i}"]) for i in range(1, 7))
    except (KeyError, TypeError, ValueError):
        return None


def _build_cooccur_matrix(training_draws: list[dict]) -> list[list[float]]:
    """45×45 대칭 공동출현 가중치. 최근 50회는 RECENCY_WEIGHT."""
    n = 45
    w: list[list[float]] = [[0.0] * n for _ in range(n)]
    tlen = len(training_draws)
    for idx, d in enumerate(training_draws):
        nums = _six_from_draw(d)
        if not nums or len(nums) != 6:
            continue
        wt = RECENCY_WEIGHT if idx >= max(0, tlen - 50) else 1.0
        for a in range(6):
            for b in range(a + 1, 6):
                i, j = nums[a] - 1, nums[b] - 1
                if 0 <= i < n and 0 <= j < n:
                    w[i][j] += wt
                    w[j][i] += wt
    return w


def _node_degrees(w: list[list[float]]) -> list[float]:
    return [sum(w[i][j] for j in range(45)) for i in range(45)]


def _twice_total_weight(w: list[list[float]]) -> float:
    s = 0.0
    for i in range(45):
        for j in range(45):
            s += w[i][j]
    return s


def _greedy_modularity_merge(w: list[list[float]], target_groups: int) -> list[set[int]]:
    """45 노드 가중 무방향 그래프: 탐욕 병합으로 커뮤니티 수를 target_groups까지 축소."""
    k = _node_degrees(w)
    twice_m = sum(k)
    if twice_m <= 1e-12:
        return [{i} for i in range(45)]

    communities: list[set[int]] = [{i} for i in range(45)]
    while len(communities) > target_groups:
        best_dq = float("-inf")
        best_i = best_j = 0
        for i in range(len(communities)):
            for j in range(i + 1, len(communities)):
                a_set, b_set = communities[i], communities[j]
                w_ab = 0.0
                for u in a_set:
                    row = w[u]
                    for v in b_set:
                        w_ab += row[v]
                sa = sum(k[u] for u in a_set)
                sb = sum(k[v] for v in b_set)
                dq = (2.0 * w_ab) / twice_m - (2.0 * sa * sb) / (twice_m**2)
                if dq > best_dq:
                    best_dq = dq
                    best_i, best_j = i, j
        merged = communities[best_i] | communities[best_j]
        lo, hi = (best_i, best_j) if best_i < best_j else (best_j, best_i)
        communities[lo] = merged
        communities.pop(hi)
    return communities


def _internal_strength(w: list[list[float]], node: int, comm: set[int]) -> float:
    return sum(w[node][j] for j in comm if j != node)


def _pick_one_per_community(
    w: list[list[float]],
    communities: list[set[int]],
    rng: random.Random,
) -> list[int]:
    """커뮤니티당 1개, 내부 연결 강도 가중."""
    out: list[int] = []
    for comm in communities:
        members = sorted(comm)
        if not members:
            continue
        weights = [max(_internal_strength(w, u, comm), 1e-9) for u in members]
        pick = rng.choices(members, weights=weights, k=1)[0]
        out.append(pick + 1)
    while len(out) < 6:
        largest = max(communities, key=len)
        members = sorted(largest)
        ws = [max(_internal_strength(w, u, largest), 1e-9) for u in members]
        pick = rng.choices(members, weights=ws, k=1)[0] + 1
        if pick not in out:
            out.append(pick)
    return sorted(out[:6])


def army4_cooccur_prob_vector(training_draws: list[dict]) -> dict[int, float]:
    """행합(공동출현 총합) 기반 PMF."""
    if not training_draws:
        return {n: 1.0 / 45.0 for n in range(1, 46)}
    w = _build_cooccur_matrix(training_draws)
    mass = [sum(w[i][j] for j in range(45) if j != i) for i in range(45)]
    tot = sum(mass)
    if tot <= 0:
        return {n: 1.0 / 45.0 for n in range(1, 46)}
    return {i + 1: mass[i] / tot for i in range(45)}


def _fallback_sample(
    rng: random.Random,
    pmf: dict[int, float],
    win_sets: list[set[int]],
    st: dict[str, int | bool],
    max_tries: int = 2000,
) -> list[int] | None:
    nums = list(range(1, 46))
    weights = [max(pmf[n], 1e-9) for n in nums]
    for _ in range(max_tries):
        cand = sorted(rng.choices(nums, weights=weights, k=6))
        if len(set(cand)) != 6:
            continue
        try:
            if not tier1_filter(cand):
                continue
        except (TypeError, ValueError):
            continue
        if not v13_pass_win_avoid(cand, win_sets, st):
            continue
        return cand
    return None


def army4_cooccur_predict(
    training_draws: list[dict],
    n_sets: int = 5,
    target_draw_no: int | None = None,
) -> list[dict]:
    if not training_draws or n_sets <= 0:
        return []

    w = _build_cooccur_matrix(training_draws)
    pmf = army4_cooccur_prob_vector(training_draws)

    twice_m = _twice_total_weight(w)
    communities: list[set[int]] = []
    if len(training_draws) >= MIN_DRAWS_FOR_GRAPH and twice_m > 1e-9:
        communities = _greedy_modularity_merge(w, N_COMMUNITIES)
        logger.debug(
            "cooccur: %d communities (modularity merge), sizes=%s",
            len(communities),
            sorted(len(c) for c in communities),
        )

    tail = training_draws[-min(10, len(training_draws)) :]
    key_tuples: list[tuple[int, ...]] = []
    for d in tail:
        dd = int(d.get("draw_no", 0) or 0)
        ns = _six_from_draw(d)
        if ns:
            key_tuples.append((dd, *ns))
    seed = hash(tuple(key_tuples)) % (2**32)
    if seed < 0:
        seed += 2**32
    rng = random.Random(seed)

    win_sets = (
        get_recent_winning_sets(target_draw_no, V13_WIN_AVOID_N) if target_draw_no else []
    )
    st: dict[str, int | bool] = {"fail_count": 0, "bypass": False}

    out: list[dict[str, Any]] = []
    used: set[tuple[int, ...]] = set()
    attempts = 0
    max_attempts = 3000

    while len(out) < n_sets and attempts < max_attempts:
        attempts += 1
        if communities and len(communities) >= 1:
            cand = _pick_one_per_community(w, communities, rng)
        else:
            cand = None
        if cand is None or len(set(cand)) != 6:
            fb = _fallback_sample(rng, pmf, win_sets, st, max_tries=500)
            if fb is None:
                continue
            cand = fb
        try:
            if not tier1_filter(cand):
                continue
        except (TypeError, ValueError):
            continue
        if not v13_pass_win_avoid(cand, win_sets, st):
            continue
        t = tuple(cand)
        if t in used:
            continue
        used.add(t)
        out.append(
            {
                "nums": cand,
                "brain_tag": "v13_run",
                "confidence": round(min(0.99, 0.36 + 0.01 * len(communities)), 2),
                "method": "🕸️ 공동출현그래프",
                "reasoning": "cooccur_modularity+weighted_pick",
            },
        )

    guard2 = 0
    while len(out) < n_sets and guard2 < 8000:
        guard2 += 1
        fb = _fallback_sample(rng, pmf, win_sets, {"fail_count": 0, "bypass": False}, max_tries=80)
        if fb is None:
            continue
        nums2 = list(fb)
        rr = random.Random((seed ^ guard2) % (2**32))
        st2: dict[str, int | bool] = {"fail_count": 0, "bypass": False}
        for _ in range(40):
            if v13_pass_win_avoid(nums2, win_sets, st2):
                break
            nums2 = v13_perturb_combo_one_swap(nums2, rr)
        t = tuple(sorted(nums2))
        if t in used:
            continue
        try:
            if not tier1_filter(nums2):
                continue
        except (TypeError, ValueError):
            continue
        used.add(t)
        out.append(
            {
                "nums": sorted(nums2),
                "brain_tag": "v13_run",
                "confidence": 0.42,
                "method": "🕸️ 공동출현그래프",
                "reasoning": "cooccur_fallback_perturb",
            },
        )

    if len(out) < n_sets:
        logger.warning(
            "cooccur: only %d/%d sets (target=%s)",
            len(out),
            n_sets,
            target_draw_no,
        )

    return out[:n_sets]
