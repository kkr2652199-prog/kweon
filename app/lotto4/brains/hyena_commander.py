"""Phase 4 hyena Commander — stat-only consensus + tier1 + 220 후보 풀."""

from __future__ import annotations

import sqlite3
from itertools import combinations
from typing import Any

from app.lotto4.brains import stat_generator
from app.lotto4.brains.cdm_brain import CDMBrain
from app.lotto4.brains.cooccur_brain import predict as cooccur_predict
from app.lotto4.brains.constraint_brain import ConstraintBrain
from app.lotto4.brains.sumrange_brain import SumrangeBrain
from app.lotto4.brains._utils import calc_ac_value, count_consecutive, jaccard

NUM_SETS = 5
POOL_SIZE = 15
FREQ_CANDIDATES = 200
CDM_SETS = 5
COOCCUR_SETS = 5
AUX_SETS = 5
JACCARD_LIMIT = 0.4
JACCARD_RELAX = (0.5, 0.6)
WIN_AVOID_N = 3
WIN_AVOID_THRESH = 0.4

SUM_MIN, SUM_MAX = 80, 210
ODD_MIN, ODD_MAX = 1, 5
CONSEC_MAX = 3
DECADE_MIN = 2

EXCLUDED_FROM_CONSENSUS: frozenset[str] = frozenset(
    {"cdm_brain", "cooccur_brain", "sumrange_brain", "constraint_brain"}
)

CandidateEntry = tuple[str, list[int]]


def _consensus_from_tagged(entries: list[CandidateEntry]) -> dict[int, float]:
    consensus: dict[int, float] = {}
    for source, combo in entries:
        if source in EXCLUDED_FROM_CONSENSUS:
            continue
        for n in combo:
            ni = int(n)
            if 1 <= ni <= 45:
                consensus[ni] = consensus.get(ni, 0.0) + 1.0
    return consensus


def _collect_all_candidates(target_draw: int, db_path: str) -> list[CandidateEntry]:
    """220세트: stat(200) + CDM(5) + cooccur(5) + sumrange(5) + constraint(5)."""
    entries: list[CandidateEntry] = []
    for combo in stat_generator.generate_candidates(
        target_draw, db_path, FREQ_CANDIDATES
    ):
        entries.append(("stat_generator", sorted(int(x) for x in combo)))
    try:
        for combo in CDMBrain().predict(target_draw, db_path, CDM_SETS):
            if isinstance(combo, list) and len(combo) == 6:
                entries.append(("cdm_brain", sorted(int(x) for x in combo)))
    except (OSError, ValueError, TypeError, ImportError):
        pass
    try:
        for combo in cooccur_predict(target_draw, db_path, COOCCUR_SETS):
            if isinstance(combo, list) and len(combo) == 6:
                entries.append(("cooccur_brain", sorted(int(x) for x in combo)))
    except (OSError, ValueError, TypeError, ImportError):
        pass
    try:
        for combo in SumrangeBrain().predict(target_draw, db_path, AUX_SETS):
            if isinstance(combo, list) and len(combo) == 6:
                entries.append(("sumrange_brain", sorted(int(x) for x in combo)))
    except (OSError, ValueError, TypeError, ImportError):
        pass
    try:
        for combo in ConstraintBrain().predict(target_draw, db_path, AUX_SETS):
            if isinstance(combo, list) and len(combo) == 6:
                entries.append(("constraint_brain", sorted(int(x) for x in combo)))
    except (OSError, ValueError, TypeError, ImportError):
        pass
    return entries


def _build_stat_consensus(target_draw: int, db_path: str) -> dict[int, float]:
    """Phase 4: stat 200세트만 consensus (하위4뇌 제외)."""
    entries = _collect_all_candidates(target_draw, db_path)
    if not entries:
        return {n: 0.0 for n in range(1, 46)}
    return _consensus_from_tagged(entries)


def _legacy_freq_consensus(target_draw: int, db_path: str) -> dict[int, float]:
    """Phase 2 fallback: 210세트 전부 동일 가중."""
    candidates: list = list(
        stat_generator.generate_candidates(target_draw, db_path, FREQ_CANDIDATES)
    )
    try:
        for combo in CDMBrain().predict(target_draw, db_path, CDM_SETS):
            if isinstance(combo, list) and len(combo) == 6:
                candidates.append(combo)
    except (OSError, ValueError, TypeError, ImportError):
        pass
    try:
        for combo in cooccur_predict(target_draw, db_path, COOCCUR_SETS):
            if isinstance(combo, list) and len(combo) == 6:
                candidates.append(combo)
    except (OSError, ValueError, TypeError, ImportError):
        pass
    consensus: dict[int, float] = {}
    for combo in candidates:
        for n in combo:
            ni = int(n)
            if 1 <= ni <= 45:
                consensus[ni] = consensus.get(ni, 0.0) + 1.0
    return consensus


def _build_freq_consensus(target_draw: int, db_path: str) -> dict[int, float]:
    return _build_stat_consensus(target_draw, db_path)


def _build_consensus(target_draw: int, db_path: str) -> dict[int, float]:
    return _build_stat_consensus(target_draw, db_path)


def _select_candidate_pool(consensus: dict[int, float], pool_size: int = POOL_SIZE) -> list[int]:
    ranked = sorted(consensus.items(), key=lambda x: (-x[1], x[0]))
    pool = [n for n, _ in ranked[:pool_size]]
    if len(pool) < pool_size:
        for n in range(1, 46):
            if n not in pool:
                pool.append(n)
            if len(pool) >= pool_size:
                break
    return pool[:pool_size]


def _tier1_max_consec(nums: list[int]) -> int:
    run = consec = 1
    best = 1
    for i in range(1, len(nums)):
        if nums[i] == nums[i - 1] + 1:
            consec += 1
            best = max(best, consec)
        else:
            consec = 1
    return best


def _pass_tier1_filter(combo: tuple[int, ...] | list[int]) -> bool:
    """3군 tier1 동형: sum 80~210, odd 1~5, decade 2+, 연번 max3, AC 없음."""
    nums = sorted(combo)
    if len(nums) != 6 or len(set(nums)) != 6:
        return False
    total = sum(nums)
    if total < SUM_MIN or total > SUM_MAX:
        return False
    odd = sum(1 for n in nums if n % 2 == 1)
    if odd < ODD_MIN or odd > ODD_MAX:
        return False
    if len({(n - 1) // 10 for n in nums}) < DECADE_MIN:
        return False
    if _tier1_max_consec(nums) > CONSEC_MAX:
        return False
    return True


def _pass_struct_filter(combo: tuple[int, ...] | list[int]) -> bool:
    """Legacy Phase1 struct (AC≥7, sum 100~175)."""
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


def _get_recent_wins(target_draw: int, db_path: str, n: int = WIN_AVOID_N) -> list[set[int]]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT num1, num2, num3, num4, num5, num6
            FROM lotto_draws
            WHERE draw_no < ?
            ORDER BY draw_no DESC
            LIMIT ?
            """,
            (int(target_draw), int(n)),
        ).fetchall()
    finally:
        conn.close()
    return [set(r) for r in rows if r]


def _pass_win_avoid(
    combo: tuple[int, ...] | list[int],
    recent_wins: list[set[int]],
    threshold: float = WIN_AVOID_THRESH,
) -> bool:
    combo_set = set(combo)
    for win in recent_wins:
        if jaccard(combo_set, win) >= threshold:
            return False
    return True


def _select_top5(
    scored: list[tuple[tuple[int, ...], float]],
    target_draw: int,
    db_path: str,
    n_sets: int = NUM_SETS,
) -> list[list[int]]:
    recent_wins = _get_recent_wins(target_draw, db_path, WIN_AVOID_N)
    selected: list[list[int]] = []
    thresholds = (JACCARD_LIMIT, *JACCARD_RELAX)

    def _try(thresh: float) -> None:
        for combo, _score in scored:
            if len(selected) >= n_sets:
                break
            combo_list = sorted(combo)
            if combo_list in selected:
                continue
            if not _pass_tier1_filter(combo_list):
                continue
            if not _pass_win_avoid(combo_list, recent_wins, WIN_AVOID_THRESH):
                continue
            st = set(combo_list)
            if any(jaccard(st, set(s)) > thresh for s in selected):
                continue
            selected.append(combo_list)

    for thresh in thresholds:
        if len(selected) >= n_sets:
            break
        _try(thresh)

    if len(selected) < n_sets:
        for combo, _ in scored:
            if len(selected) >= n_sets:
                break
            combo_list = sorted(combo)
            if combo_list not in selected and _pass_tier1_filter(combo_list):
                selected.append(combo_list)

    return selected[:n_sets]


def predict(target_draw: int, db_path: str, n_sets: int = NUM_SETS) -> list[list[int]]:
    """Phase4 stat-only consensus → Top15 → 15C6 tier1 → 5세트."""
    try:
        consensus = _build_stat_consensus(target_draw, db_path)
        if not any(v > 0 for v in consensus.values()):
            consensus = _legacy_freq_consensus(target_draw, db_path)
        pool = _select_candidate_pool(consensus, POOL_SIZE)
        if len(pool) < 6:
            return []

        scored = [
            (tuple(sorted(c)), sum(consensus.get(n, 0.0) for n in c))
            for c in combinations(pool, 6)
            if _pass_tier1_filter(c)
        ]
        scored.sort(key=lambda x: (-x[1], x[0]))
        result = _select_top5(scored, target_draw, db_path, n_sets)
        if result:
            return result[:n_sets]
    except (OSError, ValueError, TypeError, sqlite3.Error):
        pass
    return []


# ── Phase 2A~3 legacy (비활성 보존) ──────────────────────────────────────

def _normalize_scores(scores: dict[int, float]) -> dict[int, float]:
    total = sum(scores.values())
    if total <= 0:
        return {n: 1.0 / 45.0 for n in range(1, 46)}
    return {n: float(scores.get(n, 0.0)) / total for n in range(1, 46)}


def _legacy_hybrid_consensus(target_draw: int, db_path: str) -> dict[int, float]:
    from app.lotto4.brains.fusion_brain import FusionBrain
    from app.lotto4.brains.stat_cdm_brain import StatCDMBrain

    freq = _normalize_scores(_legacy_freq_consensus(target_draw, db_path))
    cdm_pmf = StatCDMBrain().get_pmf(target_draw, db_path)
    stat_pmf = stat_generator.get_pmf(target_draw, db_path)
    fused = FusionBrain().get_fused_pmf(pmf_list=[cdm_pmf, stat_pmf], weights=[0.5, 0.5])
    hybrid = {n: 0.7 * freq.get(n, 0.0) + 0.3 * fused.get(n, 0.0) for n in range(1, 46)}
    return _normalize_scores(hybrid)


def _legacy_fusion_only(target_draw: int, db_path: str, n_sets: int = NUM_SETS) -> list[list[int]]:
    from app.lotto4.brains.fusion_brain import FusionBrain
    from app.lotto4.brains.stat_cdm_brain import StatCDMBrain

    cdm_pmf = StatCDMBrain().get_pmf(target_draw, db_path)
    stat_pmf = stat_generator.get_pmf(target_draw, db_path)
    fused = FusionBrain().get_fused_pmf(pmf_list=[cdm_pmf, stat_pmf], weights=[0.5, 0.5])
    pool = _select_candidate_pool(fused, POOL_SIZE)
    if len(pool) < 6:
        return []
    scored = [
        (tuple(sorted(c)), sum(fused.get(n, 0.0) for n in c))
        for c in combinations(pool, 6)
        if _pass_struct_filter(c)
    ]
    scored.sort(key=lambda x: (-x[1], x[0]))
    return _select_top5(scored, target_draw, db_path, n_sets)


def _legacy_phase3_predict(target_draw: int, db_path: str, n_sets: int = NUM_SETS) -> list[list[int]]:
    from app.lotto4.brains.hyena_scavenger import HyenaScavenger
    from app.lotto4.brains.struct_predictor import StructPredictor

    consensus = dict(_legacy_freq_consensus(target_draw, db_path))
    scavenger = HyenaScavenger()
    scavenge_pool = scavenger.get_scavenge_pool(target_draw, db_path, pool_size=8)
    if scavenge_pool:
        for num, sc_score in scavenge_pool:
            consensus[num] = consensus.get(num, 0.0) + sc_score * 0.3
    pool = _select_candidate_pool(consensus, POOL_SIZE)
    sp = StructPredictor()
    sp.train(target_draw, db_path)
    struct_filter = sp.get_struct_filter(target_draw, db_path)
    scav_nums = {num for num, _ in scavenge_pool} if scavenge_pool else set()
    scored = []
    for combo in combinations(pool, 6):
        cand = tuple(sorted(combo))
        if not _pass_struct_filter(cand):
            continue
        c_score = sum(consensus.get(n, 0.0) for n in cand)
        s_score = struct_filter(list(cand))
        scav_bonus = len(set(cand) & scav_nums) * 0.1
        final = c_score * (1.0 + 0.3 * s_score + scav_bonus)
        scored.append((cand, final))
    scored.sort(key=lambda x: (-x[1], x[0]))
    return _select_top5(scored, target_draw, db_path, n_sets)
