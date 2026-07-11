"""5005 전수 + greedy union 커버리지 최적화 (R13 walk-forward, R2 조합 최적화).

Mandel covering design 계열 — 미래 예측 주장 없음.
"""

from __future__ import annotations

import math
from itertools import combinations
from typing import Any

from app.lotto4.brains._utils import jaccard
from app.lotto4.brains.popularity_freq_brain import avg_popularity_score
from app.lotto4.brains.shape_brain import _matches_shape, extract_shape_metrics

NUM_SETS = 5
POOL_SIZE = 15
JACCARD_LIMIT = 0.5
COMBO_TOTAL = 5005  # 15C6
FULL_ENUM_MAX = 20_000  # C(n,6) 이하이면 전수 평가
GREEDY_SCAN_LIMIT = 600  # 세트당 후보 스캔 상한
SUB_POOL_MAX = 18  # 큰 풀 시 상위 N번호만 부분 전수


def select_top_pool(
    pool_weight: dict[int, float],
    *,
    top_n: int = POOL_SIZE,
) -> list[int]:
    """인기 가중 상위 N번호 풀."""
    ranked = sorted(
        ((n, pool_weight.get(n, 0.0)) for n in range(1, 46)),
        key=lambda x: (-x[1], x[0]),
    )
    return [n for n, _ in ranked[:top_n]]


def _combo_count(n: int) -> int:
    if n < 6:
        return 0
    return math.comb(n, 6)


def evaluate_all_combinations(
    pool: list[int],
    number_weights: dict[int, float],
) -> list[tuple[tuple[int, ...], float]]:
    """pool C6 전수(또는 상한 내), 인기적합도 정렬."""
    if len(pool) < 6:
        return []
    rows: list[tuple[tuple[int, ...], float]] = []
    for combo in combinations(pool, 6):
        nums = tuple(sorted(combo))
        score = float(sum(number_weights.get(n, 0.0) for n in nums))
        rows.append((nums, score))
    rows.sort(key=lambda x: (-x[1], x[0]))
    return rows


def _ranked_candidates(
    universe: list[int],
    number_weights: dict[int, float],
    pool_weight: dict[int, float] | None = None,
) -> list[tuple[tuple[int, ...], float]]:
    """전수 가능 시 전수, 아니면 상위 번호 부분집합 전수."""
    if _combo_count(len(universe)) <= FULL_ENUM_MAX:
        return evaluate_all_combinations(universe, number_weights)

    # 큰 풀: 상위 SUB_POOL_MAX 번호에서만 C(6) 부분 전수
    pw = pool_weight or {}
    ranked_nums = sorted(
        universe,
        key=lambda n: (-(pw.get(n, 0.0) + number_weights.get(n, 0.0)), n),
    )
    sub_n = min(SUB_POOL_MAX, len(ranked_nums))
    sub = ranked_nums[:sub_n]
    while sub_n >= 6 and _combo_count(sub_n) > FULL_ENUM_MAX:
        sub_n -= 1
        sub = ranked_nums[:sub_n]
    return evaluate_all_combinations(sub, number_weights)


def greedy_coverage_sets(
    ranked: list[tuple[tuple[int, ...], float]],
    number_weights: dict[int, float],
    shape_profile: dict[str, Any] | None = None,
    *,
    n_sets: int = NUM_SETS,
    jaccard_limit: float = JACCARD_LIMIT,
) -> list[dict[str, Any]]:
    """union 커버리지 최대화 greedy + 인기 tie-break."""
    if not ranked:
        return []

    selected: list[tuple[tuple[int, ...], float]] = []
    covered: set[int] = set()
    used: set[tuple[int, ...]] = set()

    scan = ranked[:GREEDY_SCAN_LIMIT] if len(ranked) > GREEDY_SCAN_LIMIT else ranked

    for _ in range(n_sets):
        best_combo: tuple[int, ...] | None = None
        best_score = (-1, -1.0)
        best_pop = 0.0

        for combo, pop_sum in scan:
            if combo in used:
                continue
            nums = list(combo)
            if shape_profile and not _matches_shape(
                extract_shape_metrics(nums), shape_profile
            ):
                continue
            st = set(combo)
            if any(jaccard(st, set(s[0])) >= jaccard_limit for s in selected):
                continue
            new_cov = len(st - covered)
            key = (new_cov, pop_sum)
            if key > best_score:
                best_score = key
                best_combo = combo
                best_pop = pop_sum

        if best_combo is None:
            break
        used.add(best_combo)
        covered |= set(best_combo)
        selected.append((best_combo, best_pop))

    sets: list[dict[str, Any]] = []
    prior_union: set[int] = set()
    for i, (combo, pop_sum) in enumerate(selected, start=1):
        nums = list(combo)
        st = set(nums)
        sets.append(
            {
                "set_no": i,
                "numbers": nums,
                "popularity_score": round(
                    avg_popularity_score(nums, number_weights), 4
                ),
                "popularity_sum": round(pop_sum, 4),
                "new_coverage": len(st - prior_union),
            }
        )
        prior_union |= st
    return sets


def generate_coverage_sets(
    pool_weight: dict[int, float],
    number_weights: dict[int, float],
    shape_profile: dict[str, Any] | None = None,
    *,
    n_sets: int = NUM_SETS,
    pool_size: int = POOL_SIZE,
) -> dict[str, Any]:
    """풀→전수/부분전수→greedy 5세트."""
    pool = select_top_pool(pool_weight, top_n=pool_size)
    ranked = _ranked_candidates(pool, number_weights, pool_weight)
    sets = greedy_coverage_sets(
        ranked,
        number_weights,
        shape_profile,
        n_sets=n_sets,
    )
    union_nums: set[int] = set()
    for s in sets:
        union_nums.update(int(n) for n in s["numbers"])
    return {
        "mode": f"coverage_pool{pool_size}_greedy",
        "pool_size": pool_size,
        "pool": pool,
        "combo_evaluated": len(ranked),
        "combo_space": _combo_count(len(pool)),
        "sets": sets,
        "union_coverage": len(union_nums),
        "union_numbers": sorted(union_nums),
    }


def _sequential_greedy_one_set(
    universe: list[int],
    covered: set[int],
    blend_weight: dict[int, float],
    number_weights: dict[int, float],
    shape_profile: dict[str, Any] | None,
    existing: list[list[int]],
    *,
    jaccard_limit: float = JACCARD_LIMIT,
    set_no: int = 1,
) -> list[int] | None:
    """45공간 직접: 번호 단위 greedy 6개 + shape/jaccard."""
    rot = (set_no - 1) % max(len(universe), 1)
    rotated = universe[rot:] + universe[:rot]
    for attempt in range(400):
        picked: list[int] = []
        local_covered = set(covered)
        ok = True
        for step in range(6):
            best_n = None
            best_key = (-1, -1.0)
            scan = rotated if attempt == 0 else universe
            if attempt > 0:
                scan = sorted(
                    universe,
                    key=lambda n: (
                        -(1 if n not in local_covered else 0),
                        -blend_weight.get(n, 0.01),
                        (n + attempt + step) % 46,
                    ),
                )
            for n in scan:
                if n in picked:
                    continue
                new_cov = 1 if n not in local_covered else 0
                w = blend_weight.get(n, 0.01)
                key = (new_cov, w)
                if key > best_key:
                    best_key = key
                    best_n = n
            if best_n is None:
                ok = False
                break
            picked.append(best_n)
            local_covered.add(best_n)
        if not ok or len(picked) != 6:
            continue
        nums = sorted(picked)
        if shape_profile and not _matches_shape(
            extract_shape_metrics(nums), shape_profile
        ):
            continue
        st = set(nums)
        if any(jaccard(st, set(prev)) >= jaccard_limit for prev in existing):
            continue
        return nums
    return None


def generate_full45_coverage_sets(
    pool_weight: dict[int, float],
    number_weights: dict[int, float],
    shape_profile: dict[str, Any] | None = None,
    *,
    n_sets: int = NUM_SETS,
) -> dict[str, Any]:
    """45번호 전체 직접 greedy union 최대화 (풀 제한 없음)."""
    universe = list(range(1, 46))
    blend = {
        n: pool_weight.get(n, 0.0) + number_weights.get(n, 0.0)
        for n in universe
    }
    covered: set[int] = set()
    existing: list[list[int]] = []
    sets: list[dict[str, Any]] = []
    prior: set[int] = set()

    for i in range(1, n_sets + 1):
        nums = _sequential_greedy_one_set(
            universe,
            covered,
            blend,
            number_weights,
            shape_profile,
            existing,
            set_no=i,
        )
        if not nums:
            break
        existing.append(nums)
        st = set(nums)
        covered |= st
        sets.append(
            {
                "set_no": i,
                "numbers": nums,
                "popularity_score": round(
                    avg_popularity_score(nums, number_weights), 4
                ),
                "new_coverage": len(st - prior),
            }
        )
        prior |= st

    return {
        "mode": "coverage_full45_greedy",
        "pool_size": 45,
        "pool": universe,
        "sets": sets,
        "union_coverage": len(covered),
        "union_numbers": sorted(covered),
    }


def avg_pairwise_jaccard(sets: list[list[int]]) -> float:
    if len(sets) < 2:
        return 0.0
    sims: list[float] = []
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            sims.append(jaccard(set(sets[i]), set(sets[j])))
    return round(sum(sims) / len(sims), 4) if sims else 0.0


def generate_coverage_sets_legacy(
    pool_weight: dict[int, float],
    number_weights: dict[int, float],
    shape_profile: dict[str, Any] | None = None,
    *,
    n_sets: int = NUM_SETS,
) -> dict[str, Any]:
    return generate_coverage_sets(
        pool_weight, number_weights, shape_profile, n_sets=n_sets, pool_size=POOL_SIZE
    )


# 하위 호환 alias
generate_coverage_sets_15 = generate_coverage_sets_legacy


def union_coverage(sets: list[list[int]]) -> int:
    u: set[int] = set()
    for s in sets:
        u.update(int(n) for n in s)
    return len(u)


def pool_hit_count(pool: list[int], actual: list[int]) -> int:
    ps = set(pool)
    return sum(1 for n in actual if int(n) in ps)


def covering_guarantee_analysis(
    sets: list[list[int]],
    pool: list[int],
) -> dict[str, Any]:
    """15풀 안 당첨 6개 가정 시 조합론적 최소 보장 적중."""
    if len(pool) < 6 or not sets:
        return {"min_guarantee_match": 0, "tier_guarantee": "none"}

    pool_list = sorted(int(n) for n in pool)
    set_s: list[set[int]] = [set(int(n) for n in s) for s in sets]

    worst = 6
    hist: dict[int, int] = {k: 0 for k in range(7)}
    total = 0

    for win in combinations(pool_list, 6):
        w = set(win)
        best = max(len(s & w) for s in set_s)
        hist[best] = hist.get(best, 0) + 1
        total += 1
        worst = min(worst, best)

    def _tier(m: int) -> str:
        if m >= 6:
            return "1등"
        if m >= 5:
            return "3등+(보너스미반영)"
        if m >= 4:
            return "4등+"
        if m >= 3:
            return "5등+"
        return "미당첨"

    rate_at_least = {
        str(k): round(hist.get(k, 0) / max(total, 1), 4)
        for k in range(3, 7)
    }
    cum_4plus = round(
        sum(hist.get(k, 0) for k in range(4, 7)) / max(total, 1), 4
    )
    cum_3plus = round(
        sum(hist.get(k, 0) for k in range(3, 7)) / max(total, 1), 4
    )

    return {
        "pool_size": len(pool_list),
        "win_scenarios": total,
        "min_guarantee_match": worst,
        "min_tier_guarantee": _tier(worst),
        "match_histogram": hist,
        "rate_exact_match": rate_at_least,
        "rate_4plus_if_all6_in_pool": cum_4plus,
        "rate_3plus_if_all6_in_pool": cum_3plus,
    }
