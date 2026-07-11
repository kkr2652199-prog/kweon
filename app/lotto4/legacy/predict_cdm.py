"""4군 CDM(Compound-Dirichlet-Multinomial) 뇌 — v13_stat 슬롯 교체(M-3).

워크포워드: brain_tag는 **v13_stat** 유지. Dirichlet 사후 정규화 PMF로 비복원 6개 추출.
참고: arXiv 2403.12836 (Compound-Dirichlet-Multinomial prediction model).
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

ALPHA_PRIOR = 1.0
RECENCY_BOOST = 50
RECENCY_MULTIPLIER = 2.0
_MAX_MAIN_ATTEMPTS = 5000


def _six_from_draw(d: dict) -> list[int] | None:
    try:
        return sorted(int(d[f"num{i}"]) for i in range(1, 7))
    except (KeyError, TypeError, ValueError):
        return None


def _accumulate_counts(training_draws: list[dict]) -> list[float]:
    """번호 1..45 출현 가중치 합. 최근 RECENCY_BOOST회차는 RECENCY_MULTIPLIER 배."""
    counts = [0.0] * 46
    tlen = len(training_draws)
    for idx, d in enumerate(training_draws):
        nums = _six_from_draw(d)
        if not nums or len(nums) != 6:
            continue
        wt = RECENCY_MULTIPLIER if idx >= max(0, tlen - RECENCY_BOOST) else 1.0
        for n in nums:
            if 1 <= n <= 45:
                counts[n] += wt
    return counts


def _posterior_pmf_raw(counts: list[float], alpha_prior: float) -> dict[int, float]:
    """Dirichlet 사후 기대 비율 = alpha 사후 합 정규화."""
    tot = 0.0
    alphas: dict[int, float] = {}
    for n in range(1, 46):
        a = alpha_prior + counts[n]
        alphas[n] = a
        tot += a
    if tot <= 0:
        return {n: 1.0 / 45.0 for n in range(1, 46)}
    return {n: alphas[n] / tot for n in range(1, 46)}


def army4_cdm_prob_vector(training_draws: list[dict]) -> dict[int, float]:
    """Fusion 입력용 PMF (dict 1..45 → float)."""
    if not training_draws:
        return {n: 1.0 / 45.0 for n in range(1, 46)}
    counts = _accumulate_counts(training_draws)
    return _posterior_pmf_raw(counts, ALPHA_PRIOR)


def _weighted_sample_six_without_replacement(
    pmf: dict[int, float],
    rng: random.Random,
) -> list[int]:
    pool = list(range(1, 46))
    out: list[int] = []
    for _ in range(6):
        wts = [max(float(pmf.get(n, 0.0)), 1e-15) for n in pool]
        pick = rng.choices(pool, weights=wts, k=1)[0]
        out.append(pick)
        pool.remove(pick)
    return sorted(out)


def _generate_sets_with_alpha(
    training_draws: list[dict],
    alpha_prior: float,
    n_sets: int,
    target_draw_no: int | None,
    rng: random.Random,
    used_start: set[tuple[int, ...]] | None = None,
) -> list[dict[str, Any]]:
    counts = _accumulate_counts(training_draws)
    pmf = _posterior_pmf_raw(counts, alpha_prior)

    win_sets = (
        get_recent_winning_sets(target_draw_no, V13_WIN_AVOID_N) if target_draw_no else []
    )

    out: list[dict[str, Any]] = []
    used: set[tuple[int, ...]] = set(used_start) if used_start else set()
    st: dict[str, int | bool] = {"fail_count": 0, "bypass": False}

    attempts = 0
    while len(out) < n_sets and attempts < _MAX_MAIN_ATTEMPTS:
        attempts += 1
        cand = _weighted_sample_six_without_replacement(pmf, rng)
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
        conc = sum(pmf.get(n, 0.0) ** 2 for n in cand)
        conf = round(min(0.99, 0.42 + 12.0 * conc), 2)
        out.append(
            {
                "nums": cand,
                "brain_tag": "v13_stat",
                "confidence": conf,
                "method": "📊 베이지안CDM",
                "reasoning": "cdm_dirichlet_posterior_sample",
            },
        )

    return out[:n_sets]


def _training_rng_seed(training_draws: list[dict]) -> int:
    tail = training_draws[-min(10, len(training_draws)) :]
    key_tuples: list[tuple[int, ...]] = []
    for d in tail:
        dd = int(d.get("draw_no", 0) or 0)
        ns = _six_from_draw(d)
        if ns:
            key_tuples.append((dd, *ns))
    seed = hash(tuple(key_tuples)) % (2**32)
    return seed + (2**32 if seed < 0 else 0)


def _cdm_perturb_fallback_fill(
    training_draws: list[dict],
    target_draw_no: int | None,
    n_sets: int,
    seed: int,
    out: list[dict[str, Any]],
    used_global: set[tuple[int, ...]],
) -> None:
    win_sets = (
        get_recent_winning_sets(target_draw_no, V13_WIN_AVOID_N)
        if target_draw_no
        else []
    )
    pmf_fb = army4_cdm_prob_vector(training_draws)
    guard = 0
    while len(out) < n_sets and guard < 8000:
        guard += 1
        rr = random.Random((seed ^ guard) % (2**32))
        cand = _weighted_sample_six_without_replacement(pmf_fb, rr)
        st2: dict[str, int | bool] = {"fail_count": 0, "bypass": False}
        nums2 = list(cand)
        for _ in range(40):
            if v13_pass_win_avoid(nums2, win_sets, st2):
                break
            nums2 = v13_perturb_combo_one_swap(nums2, rr)
        nums2 = sorted(nums2)
        try:
            if not tier1_filter(nums2):
                continue
        except (TypeError, ValueError):
            continue
        t = tuple(nums2)
        if t in used_global:
            continue
        used_global.add(t)
        out.append(
            {
                "nums": nums2,
                "brain_tag": "v13_stat",
                "confidence": 0.48,
                "method": "📊 베이지안CDM",
                "reasoning": "cdm_perturb_fallback",
            },
        )


def army4_cdm_predict(
    training_draws: list[dict],
    n_sets: int = 5,
    target_draw_no: int | None = None,
) -> list[dict]:
    """CDM 사후 PMF 기반 비복원 샘플링."""
    if not training_draws or n_sets <= 0:
        return []

    seed = _training_rng_seed(training_draws)
    rng = random.Random(seed)

    out = _generate_sets_with_alpha(
        training_draws, ALPHA_PRIOR, n_sets, target_draw_no, rng,
    )
    used_global = {tuple(sorted(x["nums"])) for x in out}  # type: ignore[misc]

    if len(out) < n_sets:
        logger.warning(
            "cdm: alpha=%s 부족 (%d/%d), alpha_prior 0.5 재시도",
            ALPHA_PRIOR,
            len(out),
            n_sets,
        )
        rng2 = random.Random((seed ^ 0xCD0303) % (2**32))
        extra = _generate_sets_with_alpha(
            training_draws,
            0.5,
            n_sets - len(out),
            target_draw_no,
            rng2,
            used_start=used_global,
        )
        out.extend(extra)
        for x in extra:
            used_global.add(tuple(x["nums"]))  # nums는 이미 정렬됨

    if len(out) < n_sets:
        _cdm_perturb_fallback_fill(
            training_draws, target_draw_no, n_sets, seed, out, used_global,
        )

    if len(out) < n_sets:
        logger.warning(
            "cdm: only %d/%d sets (target=%s)",
            len(out),
            n_sets,
            target_draw_no,
        )

    return out[:n_sets]
