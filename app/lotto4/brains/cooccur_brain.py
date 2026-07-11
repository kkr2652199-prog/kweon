"""4군 공동출현 그래프 뇌 — 3군 predict_cooccur.py 독립 이식 (v12_run).

45×45 공출현 → modularity 6커뮤니티 → 커뮤니티당 1번호 표집 → 5세트.
R13: target_draw 미만 데이터만 사용.
"""

from __future__ import annotations

import random
import sqlite3
from typing import Any

from app.lotto4.brains._utils import (
    calc_ac_value,
    count_consecutive,
    jaccard,
    load_draws_before,
)

N_COMMUNITIES = 6
RECENCY_WEIGHT = 2.0
MIN_DRAWS_FOR_GRAPH = 20
_LAST_CUT = 1223
WIN_AVOID_N = 3
WIN_AVOID_THRESH = 0.4


def _history_cut(draw_no: int) -> int:
    return min(int(draw_no), _LAST_CUT)


def _six_from_draw(d: dict[str, Any]) -> list[int] | None:
    try:
        nums = d.get("nums")
        if nums:
            return sorted(int(x) for x in nums)
        return sorted(int(d[f"num{i}"]) for i in range(1, 7))
    except (KeyError, TypeError, ValueError):
        return None


def _build_cooccur_matrix(training_draws: list[dict[str, Any]]) -> list[list[float]]:
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
    return sum(w[i][j] for i in range(45) for j in range(45))


def _greedy_modularity_merge(w: list[list[float]], target_groups: int) -> list[set[int]]:
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
                w_ab = sum(w[u][v] for u in a_set for v in b_set)
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


def _pass_struct_filter(combo: list[int]) -> bool:
    nums = sorted(combo)
    if len(nums) != 6 or len(set(nums)) != 6:
        return False
    total = sum(nums)
    if not (100 <= total <= 175):
        return False
    odd = sum(1 for n in nums if n % 2 == 1)
    if odd < 2 or odd > 4:
        return False
    high = sum(1 for n in nums if n >= 23)
    if high < 2 or high > 4:
        return False
    if count_consecutive(nums) > 2:
        return False
    if calc_ac_value(nums) < 7:
        return False
    return True


def _get_recent_wins(target_draw: int, db_path: str) -> list[set[int]]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT num1, num2, num3, num4, num5, num6
            FROM lotto_draws WHERE draw_no < ?
            ORDER BY draw_no DESC LIMIT ?
            """,
            (int(target_draw), WIN_AVOID_N),
        ).fetchall()
    finally:
        conn.close()
    return [set(r) for r in rows if r]


def _pass_win_avoid(combo: list[int], recent_wins: list[set[int]]) -> bool:
    st = set(combo)
    for win in recent_wins:
        if jaccard(st, win) >= WIN_AVOID_THRESH:
            return False
    return True


def _pick_one_per_community(
    w: list[list[float]], communities: list[set[int]], rng: random.Random
) -> list[int]:
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


def get_pmf(target_draw: int, db_path: str) -> dict[int, float]:
    """행합(공동출현 총합) 기반 PMF."""
    draws = load_draws_before(db_path, _history_cut(target_draw))
    if not draws:
        return {n: 1.0 / 45.0 for n in range(1, 46)}
    w = _build_cooccur_matrix(draws)
    mass = [sum(w[i][j] for j in range(45) if j != i) for i in range(45)]
    tot = sum(mass)
    if tot <= 0:
        return {n: 1.0 / 45.0 for n in range(1, 46)}
    return {i + 1: mass[i] / tot for i in range(45)}


def _deterministic_seed(draws: list[dict[str, Any]], target_draw: int) -> int:
    tail = draws[-min(10, len(draws)) :]
    key_tuples: list[tuple[int, ...]] = []
    for d in tail:
        ns = _six_from_draw(d)
        if ns:
            key_tuples.append(tuple(ns))
    seed = hash((target_draw, tuple(key_tuples))) % (2**32)
    return seed + 2**32 if seed < 0 else seed


def predict(target_draw: int, db_path: str, n_sets: int = 5) -> list[list[int]]:
    """공출현 그래프 → 5세트 (walk-forward)."""
    draws = load_draws_before(db_path, _history_cut(target_draw))
    if not draws or n_sets <= 0:
        return []

    w = _build_cooccur_matrix(draws)
    pmf = get_pmf(target_draw, db_path)
    twice_m = _twice_total_weight(w)
    communities: list[set[int]] = []
    if len(draws) >= MIN_DRAWS_FOR_GRAPH and twice_m > 1e-9:
        communities = _greedy_modularity_merge(w, N_COMMUNITIES)

    rng = random.Random(_deterministic_seed(draws, target_draw))
    win_sets = _get_recent_wins(target_draw, db_path)
    out: list[list[int]] = []
    used: set[tuple[int, ...]] = set()
    attempts = 0

    while len(out) < n_sets and attempts < 3000:
        attempts += 1
        if communities:
            cand = _pick_one_per_community(w, communities, rng)
        else:
            cand = sorted(rng.choices(range(1, 46), weights=[pmf[n] for n in range(1, 46)], k=6))
        if len(set(cand)) != 6:
            continue
        if not _pass_struct_filter(cand):
            continue
        if not _pass_win_avoid(cand, win_sets):
            continue
        t = tuple(cand)
        if t in used:
            continue
        used.add(t)
        out.append(sorted(cand))

    guard = 0
    nums = list(range(1, 46))
    weights = [max(pmf[n], 1e-9) for n in nums]
    while len(out) < n_sets and guard < 5000:
        guard += 1
        cand = sorted(rng.choices(nums, weights=weights, k=6))
        if len(set(cand)) != 6:
            continue
        if not _pass_struct_filter(cand) or not _pass_win_avoid(cand, win_sets):
            continue
        t = tuple(cand)
        if t in used:
            continue
        used.add(t)
        out.append(sorted(cand))

    return out[:n_sets]
