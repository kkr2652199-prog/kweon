"""전략 X 5뇌 — 동반출현(cooccur) 체인 조합 생성기.

입력: aggregate_cooccur_before(target_draw) — R13 누수 없음.
로직: 고빈도 2쌍 시드 → 3쌍/4쌍 체인으로 6번호 완성, 5세트, Jaccard<0.5.
기존 ensemble cooccur_brain.py 와 별계열 (파일명 충돌 방지: cooccur_brain_v13).
R2: 당첨 확률 향상 주장 금지.
"""

from __future__ import annotations

import random
from collections import defaultdict
from itertools import combinations
from typing import Any

from app.lotto4.brains._utils import _weighted_draw_without_replacement, jaccard
from app.lotto4.cooccur_walkforward import aggregate_cooccur_before

NUM_SETS = 5
JACCARD_LIMIT = 0.5
RNG_SEED_MUL = 20260621
TOP_PAIR_POOL = 80
COOCCUR_TOP_N_2 = None
COOCCUR_TOP_N_3 = 4000
COOCCUR_TOP_N_4 = 6000

DISCLAIMER = (
    "역사적 동반출현(2·3·4쌍) 빈도 기반 인기영역 조합입니다. "
    "미래를 예측하지 않으며 당첨 확률은 모든 조합이 동일합니다."
)
BRAIN_TAG = "strategy_x_cooccur"


def _pair_key(a: int, b: int) -> tuple[int, int]:
    x, y = int(a), int(b)
    return (x, y) if x < y else (y, x)


class CooccurState:
    """증분 동반출현 집계 (백테스트용, draw_no < target 만 반영)."""

    def __init__(self) -> None:
        self.c2: dict[tuple[int, int], int] = defaultdict(int)
        self.c3: dict[tuple[int, int, int], int] = defaultdict(int)
        self.c4: dict[tuple[int, int, int, int], int] = defaultdict(int)

    def add_draw(self, nums: list[int]) -> None:
        six = sorted(int(n) for n in nums)
        if len(six) != 6:
            return
        for a, b in combinations(six, 2):
            self.c2[(a, b)] += 1
        for tri in combinations(six, 3):
            self.c3[tri] += 1
        for quad in combinations(six, 4):
            self.c4[quad] += 1

    def copy(self) -> CooccurState:
        out = CooccurState()
        out.c2 = defaultdict(int, self.c2)
        out.c3 = defaultdict(int, self.c3)
        out.c4 = defaultdict(int, self.c4)
        return out


def _entries_from_counts(
    counts: dict,
    top_n: int | None,
) -> list[dict[str, Any]]:
    entries = [
        {"nums": list(k), "count": int(v)}
        for k, v in counts.items()
    ]
    entries.sort(key=lambda e: (-int(e["count"]), tuple(e["nums"])))
    if top_n is not None:
        return entries[:top_n]
    return entries


def _state_from_aggregate(data: dict[str, Any]) -> CooccurState:
    st = CooccurState()
    for e in data.get("cooccur_2") or []:
        nums = tuple(sorted(int(n) for n in e["nums"]))
        if len(nums) == 2:
            st.c2[nums] = int(e["count"])
    for e in data.get("cooccur_3") or []:
        nums = tuple(sorted(int(n) for n in e["nums"]))
        if len(nums) == 3:
            st.c3[nums] = int(e["count"])
    for e in data.get("cooccur_4") or []:
        nums = tuple(sorted(int(n) for n in e["nums"]))
        if len(nums) == 4:
            st.c4[nums] = int(e["count"])
    return st


def build_cooccur_indexes(
    state: CooccurState,
    *,
    top_n_2: int | None = TOP_PAIR_POOL,
    top_n_3: int | None = COOCCUR_TOP_N_3,
    top_n_4: int | None = COOCCUR_TOP_N_4,
) -> dict[str, Any]:
    e2 = _entries_from_counts(state.c2, top_n_2)
    e3 = _entries_from_counts(state.c3, top_n_3)
    e4 = _entries_from_counts(state.c4, top_n_4)

    max2 = max((e["count"] for e in e2), default=1) or 1
    max3 = max((e["count"] for e in e3), default=1) or 1
    max4 = max((e["count"] for e in e4), default=1) or 1

    pair_w: dict[tuple[int, int], float] = {}
    for e in e2:
        key = tuple(sorted(int(n) for n in e["nums"]))
        pair_w[key] = float(e["count"]) / max2

    tri_full: dict[tuple[int, int, int], float] = {}
    tri_idx: dict[tuple[int, int], list[tuple[int, float]]] = defaultdict(list)
    for e in e3:
        nums = tuple(sorted(int(n) for n in e["nums"]))
        w = float(e["count"]) / max3
        tri_full[nums] = w
        a, b, c = nums
        tri_idx[_pair_key(a, b)].append((c, w))
        tri_idx[_pair_key(a, c)].append((b, w))
        tri_idx[_pair_key(b, c)].append((a, w))

    quad_full: dict[tuple[int, int, int, int], float] = {}
    quad_idx: dict[tuple[int, int, int], list[tuple[int, float]]] = defaultdict(list)
    for e in e4:
        nums = tuple(sorted(int(n) for n in e["nums"]))
        w = float(e["count"]) / max4
        quad_full[nums] = w
        for omit in range(4):
            tri = tuple(sorted(nums[i] for i in range(4) if i != omit))
            fourth = nums[omit]
            quad_idx[tri].append((fourth, w))

    return {
        "pair_w": pair_w,
        "tri_full": tri_full,
        "quad_full": quad_full,
        "tri_idx": dict(tri_idx),
        "quad_idx": dict(quad_idx),
        "seed_pairs": e2[:TOP_PAIR_POOL],
    }


def calc_cooccur_score(nums: list[int], indexes: dict[str, Any]) -> float:
    """세트 내 2·3·4쌍 동반출현 점수 (0~1 근사)."""
    pair_w = indexes["pair_w"]
    tri_full = indexes["tri_full"]
    quad_full = indexes["quad_full"]
    sorted_nums = sorted(int(n) for n in nums)
    if len(sorted_nums) != 6:
        return 0.0
    p_vals = [pair_w.get(_pair_key(a, b), 0.0) for a, b in combinations(sorted_nums, 2)]
    t_vals = [tri_full.get(tuple(sorted(t)), 0.0) for t in combinations(sorted_nums, 3)]
    q_vals = [quad_full.get(tuple(sorted(q)), 0.0) for q in combinations(sorted_nums, 4)]
    combined = (
        0.5 * (sum(p_vals) / len(p_vals) if p_vals else 0.0)
        + 0.3 * (sum(t_vals) / len(t_vals) if t_vals else 0.0)
        + 0.2 * (sum(q_vals) / len(q_vals) if q_vals else 0.0)
    )
    return round(combined, 4)


def _pick_seed_pair(
    rng: random.Random,
    indexes: dict[str, Any],
) -> list[int]:
    seeds = indexes.get("seed_pairs") or []
    if not seeds:
        return sorted(rng.sample(range(1, 46), 2))
    weights = {i: max(float(s["count"]), 1.0) for i, s in enumerate(seeds)}
    idx_list = _weighted_draw_without_replacement(rng, weights, 1)
    if not idx_list:
        return sorted(rng.sample(range(1, 46), 2))
    pair = seeds[idx_list[0]]["nums"]
    return [int(pair[0]), int(pair[1])]


def _chain_extend(
    rng: random.Random,
    picked: list[int],
    indexes: dict[str, Any],
) -> int | None:
    available = [n for n in range(1, 46) if n not in picked]
    if not available:
        return None
    pair_w = indexes["pair_w"]
    tri_idx = indexes["tri_idx"]
    quad_idx = indexes["quad_idx"]
    weights: dict[int, float] = {}
    plen = len(picked)
    for c in available:
        w = 0.0
        if plen >= 3:
            for tri in combinations(picked, 3):
                tk = tuple(sorted(int(x) for x in tri))
                for fourth, cnt in quad_idx.get(tk, []):
                    if fourth == c:
                        w += cnt
        if plen >= 2:
            for a, b in combinations(picked, 2):
                pk = _pair_key(a, b)
                for third, cnt in tri_idx.get(pk, []):
                    if third == c:
                        w += cnt
        for p in picked:
            w += pair_w.get(_pair_key(c, p), 0.001)
        weights[c] = max(float(w), 0.001)
    one = _weighted_draw_without_replacement(rng, weights, 1)
    return one[0] if one else None


def _draw_one_cooccur_set(
    rng: random.Random,
    indexes: dict[str, Any],
    existing: list[list[int]],
) -> list[int] | None:
    for _ in range(300):
        picked = _pick_seed_pair(rng, indexes)
        ok = True
        while len(picked) < 6:
            n = _chain_extend(rng, picked, indexes)
            if n is None:
                ok = False
                break
            picked.append(n)
        if not ok or len(picked) != 6:
            continue
        nums = sorted(picked)
        st = set(nums)
        if any(jaccard(st, set(prev)) >= JACCARD_LIMIT for prev in existing):
            continue
        return nums
    return None


def generate_cooccur_sets(
    target_draw_no: int,
    n_sets: int = NUM_SETS,
    *,
    state: CooccurState | None = None,
    draw_count: int | None = None,
) -> dict[str, Any]:
    """동반출현 체인 기반 n_sets 생성."""
    td = int(target_draw_no)
    dc = draw_count
    if state is None:
        agg = aggregate_cooccur_before(td)
        state = _state_from_aggregate(agg)
        dc = int(agg.get("draw_count") or 0)

    indexes = build_cooccur_indexes(state)
    sets: list[dict[str, Any]] = []
    existing: list[list[int]] = []

    for set_no in range(1, n_sets + 1):
        seed = td * RNG_SEED_MUL + set_no * 173
        rng = random.Random(seed)
        nums = _draw_one_cooccur_set(rng, indexes, existing)
        if nums is None:
            continue
        existing.append(nums)
        score = calc_cooccur_score(nums, indexes)
        sets.append(
            {
                "set_no": set_no,
                "numbers": nums,
                "cooccur_score": score,
            }
        )

    return {
        "target_draw_no": td,
        "brain": BRAIN_TAG,
        "disclaimer": DISCLAIMER,
        "source": "aggregate_cooccur_before",
        "cutoff_draw_no": td,
        "draw_count": dc,
        "sets": sets,
    }


def generate(target_draw_no: int) -> dict[str, Any]:
    return generate_cooccur_sets(int(target_draw_no))
