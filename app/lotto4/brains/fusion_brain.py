"""Phase 2A — Fusion PMF 합성 (3군 v12_fusion_v5 핵심 포팅, 4군 독립).

Phase 2A: 2뇌 PMF 가중 합성 → Top15 → 15C6 → 구조 필터 → 5세트.
"""

from __future__ import annotations

from itertools import combinations

from app.lotto4.brains._utils import calc_ac_value, count_consecutive

POOL_SIZE = 15
NUM_SETS = 5


def _pass_struct_filter(combo: tuple[int, ...] | list[int]) -> bool:
    nums = sorted(combo)
    if len(nums) != 6 or len(set(nums)) != 6:
        return False
    if not (100 <= sum(nums) <= 175):
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


class FusionBrain:
    """다중 뇌 PMF 가중 합성."""

    def get_fused_pmf(
        self,
        pmf_list: list[dict[int, float]],
        weights: list[float],
    ) -> dict[int, float]:
        if not pmf_list:
            return {n: 1.0 / 45.0 for n in range(1, 46)}
        wsum = sum(float(w) for w in weights) or float(len(pmf_list))
        combined: dict[int, float] = {n: 0.0 for n in range(1, 46)}
        for pmf, w in zip(pmf_list, weights):
            wf = float(w) / wsum if wsum > 0 else 1.0 / len(pmf_list)
            for n in range(1, 46):
                combined[n] += wf * float(pmf.get(n, 0.0))
        total = sum(combined.values())
        if total <= 0:
            return {n: 1.0 / 45.0 for n in range(1, 46)}
        return {n: v / total for n, v in combined.items()}

    def predict(
        self,
        target_draw: int,
        db_path: str,
        pmf_list: list[dict[int, float]],
        weights: list[float],
        n_sets: int = NUM_SETS,
    ) -> list[list[int]]:
        _ = target_draw, db_path
        pmf = self.get_fused_pmf(pmf_list, weights)
        ranked = sorted(pmf.items(), key=lambda x: (-x[1], x[0]))
        pool = [n for n, _ in ranked[:POOL_SIZE]]
        if len(pool) < 6:
            return []

        scored: list[tuple[tuple[int, ...], float]] = []
        for combo in combinations(pool, 6):
            cand = tuple(sorted(combo))
            if not _pass_struct_filter(cand):
                continue
            score = sum(pmf.get(n, 0.0) for n in cand)
            scored.append((cand, score))
        scored.sort(key=lambda x: (-x[1], x[0]))

        out: list[list[int]] = []
        seen: set[tuple[int, ...]] = set()
        for cand, _ in scored:
            if cand in seen:
                continue
            seen.add(cand)
            out.append(list(cand))
            if len(out) >= n_sets:
                break
        return out[:n_sets]
