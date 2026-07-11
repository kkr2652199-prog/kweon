"""4군 CDM(Compound-Dirichlet-Multinomial) 뇌 — 3군 predict_cdm.py 독립 이식.

R13: draw_no < target_draw 데이터만 사용.
Hyena Commander consensus 풀 기여용 PMF + 독립 5세트 생성.
"""

from __future__ import annotations

import random
from itertools import combinations
from typing import Any

from app.lotto4.brains._utils import (
    calc_ac_value,
    count_consecutive,
    jaccard,
    load_draws_before,
)

ALPHA_PRIOR = 1.0
LOOKBACK = 100
COOCCUR_BOOST = 0.15
TOP_K = 15
NUM_SETS = 5
JACCARD_LIMIT = 0.5
RNG_MUL = 20260523


def _pass_struct_filter(combo: tuple[int, ...] | list[int]) -> bool:
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


class CDMBrain:
    """조건부 확률 분포(Dirichlet-Multinomial) 뇌 — consensus PMF + 5세트 생성."""

    def _recent_draws(self, target_draw: int, db_path: str) -> list[dict[str, Any]]:
        draws = load_draws_before(db_path, target_draw)
        return draws[-LOOKBACK:] if len(draws) > LOOKBACK else draws

    def _base_counts(self, draws: list[dict[str, Any]]) -> list[float]:
        counts = [0.0] * 46
        for d in draws:
            for n in d.get("nums") or []:
                ni = int(n)
                if 1 <= ni <= 45:
                    counts[ni] += 1.0
        return counts

    def _apply_conditional_boost(
        self, draws: list[dict[str, Any]], counts: list[float]
    ) -> list[float]:
        """직전 회차 당첨번호와 공동출현 빈도 반영."""
        if len(draws) < 2:
            return counts
        last_nums = {int(n) for n in draws[-1].get("nums") or []}
        boost = [0.0] * 46
        for d in draws[:-1]:
            nums = {int(n) for n in d.get("nums") or []}
            if nums & last_nums:
                for n in nums - last_nums:
                    if 1 <= n <= 45:
                        boost[n] += 1.0
        return [counts[i] + COOCCUR_BOOST * boost[i] for i in range(46)]

    def get_pmf(self, target_draw: int, db_path: str) -> dict[int, float]:
        """45차원 PMF {1..45 → float}, 합 ≈ 1.0."""
        draws = self._recent_draws(target_draw, db_path)
        if not draws:
            return {n: 1.0 / 45.0 for n in range(1, 46)}
        counts = self._apply_conditional_boost(draws, self._base_counts(draws))
        alphas = {n: ALPHA_PRIOR + counts[n] for n in range(1, 46)}
        tot = sum(alphas.values())
        if tot <= 0:
            return {n: 1.0 / 45.0 for n in range(1, 46)}
        return {n: alphas[n] / tot for n in range(1, 46)}

    def predict(
        self, target_draw: int, db_path: str, n_sets: int = NUM_SETS
    ) -> list[list[int]]:
        """PMF → Top15 → 15C6 전수탐색 → 구조필터 → 상위 n_sets."""
        pmf = self.get_pmf(target_draw, db_path)
        top15 = sorted(pmf.keys(), key=lambda n: (-pmf[n], n))[:TOP_K]
        if len(top15) < 6:
            return []

        scored: list[tuple[tuple[int, ...], float]] = []
        for c in combinations(top15, 6):
            if _pass_struct_filter(c):
                scored.append((tuple(sorted(c)), sum(pmf[n] for n in c)))
        scored.sort(key=lambda x: (-x[1], x[0]))

        selected: list[list[int]] = []
        for combo, _ in scored:
            if len(selected) >= n_sets:
                break
            cl = list(combo)
            st = set(cl)
            if any(jaccard(st, set(s)) >= JACCARD_LIMIT for s in selected):
                continue
            selected.append(cl)

        if len(selected) < n_sets:
            rng = random.Random(int(target_draw) * RNG_MUL)
            pool = list(range(1, 46))
            wts = [max(pmf.get(n, 1e-12), 1e-12) for n in pool]
            guard = 0
            while len(selected) < n_sets and guard < 3000:
                guard += 1
                picked: list[int] = []
                pw = wts.copy()
                pp = pool.copy()
                for _ in range(6):
                    s = sum(pw)
                    if s <= 0:
                        break
                    r = rng.random() * s
                    acc = 0.0
                    for j, w in enumerate(pw):
                        acc += w
                        if r <= acc:
                            picked.append(pp[j])
                            pp.pop(j)
                            pw.pop(j)
                            break
                if len(picked) != 6:
                    continue
                cand = sorted(picked)
                if not _pass_struct_filter(cand):
                    continue
                if any(jaccard(set(cand), set(s)) >= JACCARD_LIMIT for s in selected):
                    continue
                selected.append(cand)

        return selected[:n_sets]


def predict(draw_no: int, db_path: str) -> list[list[int]]:
    """모듈 규약: 5세트 반환."""
    return CDMBrain().predict(draw_no, db_path, NUM_SETS)


def update_alpha(draws: list[dict[str, Any]]) -> dict[str, Any]:
    """진단용: PMF 요약 (기존 테스트 호환)."""
    if not draws:
        return {"top10": [], "prob_sum_top10": 0.0, "total_draws": 0}
    counts = [0.0] * 46
    for d in draws:
        for n in d.get("nums") or []:
            ni = int(n)
            if 1 <= ni <= 45:
                counts[ni] += 1.0
    alphas = {n: ALPHA_PRIOR + counts[n] for n in range(1, 46)}
    tot = sum(alphas.values())
    pmf = {n: alphas[n] / tot for n in range(1, 46)} if tot > 0 else {}
    top10 = sorted(pmf.keys(), key=lambda n: (-pmf[n], n))[:10]
    return {
        "top10": top10,
        "prob_sum_top10": round(sum(pmf[n] for n in top10), 4),
        "total_draws": len(draws),
    }
