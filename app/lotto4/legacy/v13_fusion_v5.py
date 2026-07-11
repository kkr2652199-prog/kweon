"""V11 Fusion V5 - 1군 _vector_fusion_predict v5 미러링.

V12-C 핵심:
- DB 동적 가중치 (1군 _load_brain_weights_from_db 미러링)
- entropy 가중치 + cluster 가중치 곱하기
- Top-K Greedy 1세트 + 4세트 가중 random
- tier1_filter 적용

2군 정체성:
- 입력: v13_* 4뇌 PMF (stat/markov/combo/lstm)
- combo가 1군 llm 자리
- 출력: brain_tag = "v13_fusion"
"""

from __future__ import annotations

import logging
import random
from typing import Any

from app.lotto4.legacy.v13_models import (
    V13_WIN_AVOID_N,
    V13_WIN_AVOID_THRESHOLD,
    get_recent_winning_sets,
    is_diff_from_recent_wins,
    v13_pass_win_avoid,
)

logger = logging.getLogger(__name__)

# 2군 fusion이 사용할 4뇌 (combo가 llm 자리)
_V11_FUSION_BRAINS: tuple[str, ...] = (
    "v13_stat",
    "v13_markov",
    "v13_combo",
    "v13_lstm",
)

# V12-D: 1군 fusion 회피 (Snake와 같은 패턴, 약한 회피)
_ARMY1_FUSION_TAG = "fusion"
_FUSION_JACCARD_THRESHOLD = 0.6   # 시뮬레이션 검증값 (0.5 너무 강함, 0.7 효과 동일)


def _v13_load_army1_fusion_sets(target_draw_no: int) -> list[set[int]]:
    """1군 fusion 셋트 로드 (회피 비교 대상, 읽기만)."""
    try:
        from app.lotto.models import get_lotto_db
    except Exception:  # noqa: BLE001
        return []
    conn = get_lotto_db()
    try:
        rows = conn.execute(
            """
            SELECT num1, num2, num3, num4, num5, num6
            FROM lotto_predictions
            WHERE target_draw_no = ? AND brain_tag = ?
            """,
            (target_draw_no, _ARMY1_FUSION_TAG),
        ).fetchall()
    finally:
        conn.close()
    return [set(r) for r in rows if r]


def _v13_is_diff_from_army1_fusion(
    combo,
    army1_fusion_sets: list[set[int]],
    threshold: float = _FUSION_JACCARD_THRESHOLD,
) -> bool:
    """1군 fusion 셋트와 Jaccard >= threshold면 탈락."""
    if not army1_fusion_sets:
        return True
    s = set(combo)
    for a1 in army1_fusion_sets:
        inter = len(s & a1)
        uni = len(s | a1)
        jac = inter / uni if uni else 0.0
        if jac >= threshold:
            return False
    return True


def _v13_load_brain_weights_from_db() -> dict[str, float]:
    """2군 가중치 로드 (1군 _load_brain_weights_from_db 미러링).

    v13_brain_weights_army4 또는 v13_models.get_v13_brain_weights() 활용.
    실패 시 1군 검증값 (FALLBACK).
    """
    try:
        from app.lotto4.legacy.v13_models import get_v13_brain_weights
        w = get_v13_brain_weights()
        if w:
            return {k: float(v) for k, v in w.items()}
    except Exception:  # noqa: BLE001
        pass
    # FALLBACK (1군 검증값, llm -> combo 매핑)
    return {
        "v13_stat": 1.0,
        "v13_markov": 1.0,
        "v13_combo": 1.5,
        "v13_lstm": 2.5,
    }


def _v13_get_cluster_weights(target_draw_no: int) -> dict[int, float]:
    """1군 cluster 가중치 재사용. 1군 모듈 직접 import (DB 공유)."""
    try:
        from app.lotto.predict_cluster import get_cluster_weights
        cw = get_cluster_weights(target_draw_no=target_draw_no)
        if cw:
            return {int(k): float(v) for k, v in cw.items()}
    except Exception:  # noqa: BLE001
        pass
    return {n: 1.0 for n in range(1, 46)}


def _v13_get_entropy_weights(training_draws: list[dict]) -> dict[int, float]:
    """1군 entropy 가중치 재사용."""
    try:
        from app.lotto.predict_entropy import get_entropy_weights
        ew = get_entropy_weights(training_draws)
        if ew:
            return {int(k): float(v) for k, v in ew.items()}
    except Exception:  # noqa: BLE001
        pass
    return {n: 1.0 for n in range(1, 46)}


def _v13_load_brain_pmfs(training_draws: list[dict]) -> dict[str, dict[int, float]]:
    """4뇌 PMF 로드 (combo가 llm 자리)."""
    pmfs: dict[str, dict[int, float]] = {}

    try:
        from app.lotto4.legacy.predict_cdm import army4_cdm_prob_vector
        pmfs["v13_stat"] = army4_cdm_prob_vector(training_draws)
    except Exception:  # noqa: BLE001
        pmfs["v13_stat"] = {n: 1.0 / 45.0 for n in range(1, 46)}

    try:
        from app.lotto4.legacy.predict_markov import army4_markov_prob_vector
        pmfs["v13_markov"] = army4_markov_prob_vector(training_draws)
    except Exception:  # noqa: BLE001
        pmfs["v13_markov"] = {n: 1.0 / 45.0 for n in range(1, 46)}

    try:
        from app.lotto4.legacy.predict_combo import army4_combo_prob_vector
        pmfs["v13_combo"] = army4_combo_prob_vector(training_draws)
    except Exception:  # noqa: BLE001
        pmfs["v13_combo"] = {n: 1.0 / 45.0 for n in range(1, 46)}

    try:
        from app.lotto4.legacy.predict_lstm import army4_lstm_prob_vector
        pmfs["v13_lstm"] = army4_lstm_prob_vector(training_draws)
    except Exception:  # noqa: BLE001
        pmfs["v13_lstm"] = {n: 1.0 / 45.0 for n in range(1, 46)}

    return pmfs


def _v13_combine_pmfs(
    pmfs: dict[str, dict[int, float]],
    brain_weights: dict[str, float],
) -> dict[int, float]:
    """4뇌 PMF + 가중치 결합 (1군 v5 방식)."""
    uniform = {n: 1.0 / 45.0 for n in range(1, 46)}
    combined: dict[int, float] = {n: 0.0 for n in range(1, 46)}
    for tag in _V11_FUSION_BRAINS:
        pmf = pmfs.get(tag) or uniform
        w = float(brain_weights.get(tag, 1.0))
        for n in range(1, 46):
            combined[n] += w * float(pmf.get(n, 0.0))

    # 정규화
    total = sum(combined.values())
    if total > 0:
        return {n: v / total for n, v in combined.items()}
    return {n: 1.0 / 45.0 for n in range(1, 46)}


def _v13_apply_entropy_cluster(
    pmf: dict[int, float],
    entropy_w: dict[int, float],
    cluster_w: dict[int, float],
) -> dict[int, float]:
    """entropy x cluster 가중치 곱하기 (1군 v5 핵심)."""
    weighted: dict[int, float] = {}
    for n in range(1, 46):
        weighted[n] = (
            float(pmf.get(n, 0.0))
            * float(entropy_w.get(n, 1.0))
            * float(cluster_w.get(n, 1.0))
        )
    total = sum(weighted.values())
    if total > 0:
        return {n: v / total for n, v in weighted.items()}
    return {n: 1.0 / 45.0 for n in range(1, 46)}


def _v13_top_k_greedy(pmf: dict[int, float], k: int = 6) -> list[int]:
    """Top-K Greedy 1세트 (1군 v5 미러링)."""
    sorted_nums = sorted(pmf.items(), key=lambda x: -x[1])
    return sorted([n for n, _ in sorted_nums[:k]])


def _v13_weighted_random(
    pmf: dict[int, float],
    n_sets: int = 4,
    max_attempts: int = 5000,
) -> list[list[int]]:
    """가중 random 4세트 + tier1_filter."""
    try:
        from app.lotto.filters import tier1_filter
    except Exception:  # noqa: BLE001
        tier1_filter = None  # type: ignore

    nums = list(range(1, 46))
    weights = [max(pmf.get(n, 0.0), 1e-9) for n in nums]

    sets: list[list[int]] = []
    attempts = 0
    while len(sets) < n_sets and attempts < max_attempts:
        attempts += 1
        try:
            cand_raw = random.choices(nums, weights=weights, k=12)
            cand = sorted(set(cand_raw))[:6]
            if len(cand) < 6:
                continue
        except Exception:  # noqa: BLE001
            continue

        if tier1_filter is not None:
            try:
                if not tier1_filter(cand):
                    continue
            except Exception:  # noqa: BLE001
                pass

        if cand in sets:
            continue
        sets.append(cand)

    return sets


def v13_fusion_v5_predict(
    training_draws: list[dict],
    target_draw_no: int,
    n_sets: int = 5,
) -> list[dict]:
    """V11 Fusion V5 - 1군 _vector_fusion_predict v5 미러링.

    1) DB 동적 가중치 로드
    2) 4뇌 PMF 로드
    3) PMF 결합 + 가중치 곱
    4) entropy x cluster 가중치 적용
    5) Top-K Greedy 1세트 + 가중 random 4세트
    """
    if not training_draws:
        return []

    # 1) DB 가중치
    brain_weights = _v13_load_brain_weights_from_db()

    # 2) 4뇌 PMF
    pmfs = _v13_load_brain_pmfs(training_draws)

    # 3) 결합
    combined_pmf = _v13_combine_pmfs(pmfs, brain_weights)

    # 4) entropy x cluster
    entropy_w = _v13_get_entropy_weights(training_draws)
    cluster_w = _v13_get_cluster_weights(target_draw_no)
    final_pmf = _v13_apply_entropy_cluster(combined_pmf, entropy_w, cluster_w)

    sets: list[dict[str, Any]] = []

    # V12-D: 1군 fusion 회피 비교 대상 로드
    army1_fusion_sets = _v13_load_army1_fusion_sets(target_draw_no)
    win_sets = get_recent_winning_sets(target_draw_no, V13_WIN_AVOID_N)
    win_st: dict[str, int | bool] = {"fail_count": 0, "bypass": False}

    # 5-1) Top-K Greedy 1세트 (1군과 너무 비슷하면 변형)
    top_k = _v13_top_k_greedy(final_pmf, k=6)
    if not _v13_is_diff_from_army1_fusion(top_k, army1_fusion_sets):
        # Top-K 풀 확장 후 1번호씩 swap 시도
        sorted_nums = sorted(final_pmf.items(), key=lambda x: -x[1])
        top_pool = [n for n, _ in sorted_nums[:12]]
        swapped = False
        for swap_idx in range(6):
            for new_num in top_pool[6:]:
                if new_num in top_k:
                    continue
                candidate = sorted([n for i, n in enumerate(top_k) if i != swap_idx] + [new_num])
                if _v13_is_diff_from_army1_fusion(candidate, army1_fusion_sets):
                    top_k = candidate
                    swapped = True
                    break
            if swapped:
                break
    if _v13_is_diff_from_army1_fusion(top_k, army1_fusion_sets):
        if not is_diff_from_recent_wins(top_k, win_sets, V13_WIN_AVOID_THRESHOLD):
            sorted_nums2 = sorted(final_pmf.items(), key=lambda x: -x[1])
            top_pool2 = [n for n, _ in sorted_nums2[:15]]
            for swi in range(6):
                for new_n in top_pool2:
                    if new_n in top_k:
                        continue
                    alt = sorted([n for i, n in enumerate(top_k) if i != swi] + [new_n])
                    if _v13_is_diff_from_army1_fusion(alt, army1_fusion_sets) and is_diff_from_recent_wins(
                        alt, win_sets, V13_WIN_AVOID_THRESHOLD
                    ):
                        top_k = alt
                        break
                else:
                    continue
                break
    if _v13_is_diff_from_army1_fusion(top_k, army1_fusion_sets) and v13_pass_win_avoid(
        top_k, win_sets, win_st
    ):
        sets.append({
            "nums": top_k,
            "confidence": 0.65,
            "reasoning": f"V11 Fusion V5 Top-K Greedy 회피 (target={target_draw_no})",
            "brain_tag": "v13_fusion",
            "method": "V11_Fusion_V5_TopK",
        })

    # 5-2) 가중 random 4세트 (회피 검증 + 안전장치)
    attempts_round = 0
    while len(sets) < n_sets and attempts_round < 5:
        attempts_round += 1
        # 부족분의 3배수 만큼 후보 생성
        wanted = (n_sets - len(sets)) * 3
        random_sets = _v13_weighted_random(final_pmf, n_sets=wanted)
        for cand in random_sets:
            if any(s["nums"] == cand for s in sets):
                continue
            if not _v13_is_diff_from_army1_fusion(cand, army1_fusion_sets):
                continue
            if not v13_pass_win_avoid(cand, win_sets, win_st):
                continue
            sets.append({
                "nums": cand,
                "confidence": 0.55,
                "reasoning": "V11 Fusion V5 weighted random 회피",
                "brain_tag": "v13_fusion",
                "method": "V11_Fusion_V5_R",
            })
            if len(sets) >= n_sets:
                break

    # 5-3) V12-D 안전장치: 회피 후보 부족 시 Top-K 변형으로 보완
    if len(sets) < n_sets:
        sorted_nums = sorted(final_pmf.items(), key=lambda x: -x[1])
        top_pool = [n for n, _ in sorted_nums[:15]]
        bypass_attempts = 0
        while len(sets) < n_sets and bypass_attempts < 50:
            bypass_attempts += 1
            import random as _rnd
            cand = sorted(_rnd.sample(top_pool, 6))
            if any(s["nums"] == cand for s in sets):
                continue
            if _v13_is_diff_from_army1_fusion(cand, army1_fusion_sets) and v13_pass_win_avoid(
                cand, win_sets, win_st
            ):
                sets.append({
                    "nums": cand,
                    "confidence": 0.50,
                    "reasoning": "V11 Fusion V5 bypass (안전장치)",
                    "brain_tag": "v13_fusion",
                    "method": "V11_Fusion_V5_Bypass",
                })

    # 5-4) Top-K/bypass 미충족 시: Jaccard 통과 조합만 가중 random으로 보충
    fill_round = 0
    while len(sets) < n_sets and fill_round < 40:
        fill_round += 1
        wanted = max((n_sets - len(sets)) * 3, 6)
        random_sets = _v13_weighted_random(final_pmf, n_sets=wanted)
        for cand in random_sets:
            if any(s["nums"] == cand for s in sets):
                continue
            if not _v13_is_diff_from_army1_fusion(cand, army1_fusion_sets):
                continue
            if not v13_pass_win_avoid(cand, win_sets, win_st):
                continue
            sets.append({
                "nums": cand,
                "confidence": 0.52,
                "reasoning": "V11 Fusion V5 가중 random 보충 (패치 B)",
                "brain_tag": "v13_fusion",
                "method": "V11_Fusion_V5_R_fill",
            })
            if len(sets) >= n_sets:
                break

    return sets[:n_sets]


# 호환용 alias (기존 v13_fusion_predict 호출 지점에서 그대로 사용 가능)
v13_fusion_predict = v13_fusion_v5_predict
