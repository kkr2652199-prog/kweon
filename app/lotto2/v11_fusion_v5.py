"""V11 Fusion V5 - 1군 _vector_fusion_predict v5 미러링.

V12-C 핵심:
- DB 동적 가중치 (1군 _load_brain_weights_from_db 미러링)
- entropy 가중치 + cluster 가중치 곱하기
- Top-K Greedy 1세트 + 4세트 가중 random
- tier1_filter 적용

2군 정체성:
- 입력: v11_* 4뇌 PMF (stat/markov/combo/lstm)
- combo가 1군 llm 자리
- 출력: brain_tag = "v11_fusion"
"""

from __future__ import annotations

import logging
import random
from typing import Any

logger = logging.getLogger(__name__)

# 2군 fusion이 사용할 4뇌 (combo가 llm 자리)
_V11_FUSION_BRAINS: tuple[str, ...] = (
    "v11_stat",
    "v11_markov",
    "v11_combo",
    "v11_lstm",
)

# V12-D: 1군 fusion 회피 (Snake와 같은 패턴, 약한 회피)
_ARMY1_FUSION_TAG = "fusion"
_FUSION_JACCARD_THRESHOLD = 0.6   # 시뮬레이션 검증값 (0.5 너무 강함, 0.7 효과 동일)


def _v11_load_army1_fusion_sets(target_draw_no: int) -> list[set[int]]:
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


def _v11_is_diff_from_army1_fusion(
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


def _v11_load_brain_weights_from_db() -> dict[str, float]:
    """2군 가중치 로드 (1군 _load_brain_weights_from_db 미러링).

    v11_brain_weights_army2 또는 v11_models.get_v11_brain_weights() 활용.
    실패 시 1군 검증값 (FALLBACK).
    """
    try:
        from app.lotto2.v11_models import get_v11_brain_weights
        w = get_v11_brain_weights()
        if w:
            return {k: float(v) for k, v in w.items()}
    except Exception:  # noqa: BLE001
        pass
    # FALLBACK (1군 검증값, llm -> combo 매핑)
    return {
        "v11_stat": 1.0,
        "v11_markov": 1.0,
        "v11_combo": 1.5,
        "v11_lstm": 2.5,
    }


def _v11_get_cluster_weights(target_draw_no: int) -> dict[int, float]:
    """1군 cluster 가중치 재사용. 1군 모듈 직접 import (DB 공유)."""
    try:
        from app.lotto.predict_cluster import get_cluster_weights
        cw = get_cluster_weights(target_draw_no=target_draw_no)
        if cw:
            return {int(k): float(v) for k, v in cw.items()}
    except Exception:  # noqa: BLE001
        pass
    return {n: 1.0 for n in range(1, 46)}


def _v11_get_entropy_weights(training_draws: list[dict]) -> dict[int, float]:
    """1군 entropy 가중치 재사용."""
    try:
        from app.lotto.predict_entropy import get_entropy_weights
        ew = get_entropy_weights(training_draws)
        if ew:
            return {int(k): float(v) for k, v in ew.items()}
    except Exception:  # noqa: BLE001
        pass
    return {n: 1.0 for n in range(1, 46)}


def _v11_load_brain_pmfs(training_draws: list[dict]) -> dict[str, dict[int, float]]:
    """4뇌 PMF 로드 (combo가 llm 자리)."""
    pmfs: dict[str, dict[int, float]] = {}

    try:
        from app.lotto2.predict_stat import army2_stat_prob_vector
        pmfs["v11_stat"] = army2_stat_prob_vector(training_draws)
    except Exception:  # noqa: BLE001
        pmfs["v11_stat"] = {n: 1.0 / 45.0 for n in range(1, 46)}

    try:
        from app.lotto2.predict_markov import army2_markov_prob_vector
        pmfs["v11_markov"] = army2_markov_prob_vector(training_draws)
    except Exception:  # noqa: BLE001
        pmfs["v11_markov"] = {n: 1.0 / 45.0 for n in range(1, 46)}

    try:
        from app.lotto2.predict_combo import army2_combo_prob_vector
        pmfs["v11_combo"] = army2_combo_prob_vector(training_draws)
    except Exception:  # noqa: BLE001
        pmfs["v11_combo"] = {n: 1.0 / 45.0 for n in range(1, 46)}

    try:
        from app.lotto2.predict_lstm import army2_lstm_prob_vector
        pmfs["v11_lstm"] = army2_lstm_prob_vector(training_draws)
    except Exception:  # noqa: BLE001
        pmfs["v11_lstm"] = {n: 1.0 / 45.0 for n in range(1, 46)}

    return pmfs


def _v11_combine_pmfs(
    pmfs: dict[str, dict[int, float]],
    brain_weights: dict[str, float],
) -> dict[int, float]:
    """4뇌 PMF + 가중치 결합 (1군 v5 방식)."""
    combined: dict[int, float] = {n: 0.0 for n in range(1, 46)}
    for tag, pmf in pmfs.items():
        w = float(brain_weights.get(tag, 1.0))
        for n in range(1, 46):
            combined[n] += w * float(pmf.get(n, 0.0))

    # 정규화
    total = sum(combined.values())
    if total > 0:
        return {n: v / total for n, v in combined.items()}
    return {n: 1.0 / 45.0 for n in range(1, 46)}


def _v11_apply_entropy_cluster(
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


def _v11_top_k_greedy(pmf: dict[int, float], k: int = 6) -> list[int]:
    """Top-K Greedy 1세트 (1군 v5 미러링)."""
    sorted_nums = sorted(pmf.items(), key=lambda x: -x[1])
    return sorted([n for n, _ in sorted_nums[:k]])


def _v11_weighted_random(
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


def v11_fusion_v5_predict(
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
    brain_weights = _v11_load_brain_weights_from_db()

    # 2) 4뇌 PMF
    pmfs = _v11_load_brain_pmfs(training_draws)

    # 3) 결합
    combined_pmf = _v11_combine_pmfs(pmfs, brain_weights)

    # 4) entropy x cluster
    entropy_w = _v11_get_entropy_weights(training_draws)
    cluster_w = _v11_get_cluster_weights(target_draw_no)
    final_pmf = _v11_apply_entropy_cluster(combined_pmf, entropy_w, cluster_w)

    sets: list[dict[str, Any]] = []

    # V12-D: 1군 fusion 회피 비교 대상 로드
    army1_fusion_sets = _v11_load_army1_fusion_sets(target_draw_no)

    # 5-1) Top-K Greedy 1세트 (1군과 너무 비슷하면 변형)
    top_k = _v11_top_k_greedy(final_pmf, k=6)
    if not _v11_is_diff_from_army1_fusion(top_k, army1_fusion_sets):
        # Top-K 풀 확장 후 1번호씩 swap 시도
        sorted_nums = sorted(final_pmf.items(), key=lambda x: -x[1])
        top_pool = [n for n, _ in sorted_nums[:12]]
        swapped = False
        for swap_idx in range(6):
            for new_num in top_pool[6:]:
                if new_num in top_k:
                    continue
                candidate = sorted([n for i, n in enumerate(top_k) if i != swap_idx] + [new_num])
                if _v11_is_diff_from_army1_fusion(candidate, army1_fusion_sets):
                    top_k = candidate
                    swapped = True
                    break
            if swapped:
                break
    sets.append({
        "nums": top_k,
        "confidence": 0.65,
        "reasoning": f"V11 Fusion V5 Top-K Greedy 회피 (target={target_draw_no})",
        "brain_tag": "v11_fusion",
        "method": "V11_Fusion_V5_TopK",
    })

    # 5-2) 가중 random 4세트 (회피 검증 + 안전장치)
    attempts_round = 0
    while len(sets) < n_sets and attempts_round < 5:
        attempts_round += 1
        # 부족분의 3배수 만큼 후보 생성
        wanted = (n_sets - len(sets)) * 3
        random_sets = _v11_weighted_random(final_pmf, n_sets=wanted)
        for cand in random_sets:
            if any(s["nums"] == cand for s in sets):
                continue
            if not _v11_is_diff_from_army1_fusion(cand, army1_fusion_sets):
                continue
            sets.append({
                "nums": cand,
                "confidence": 0.55,
                "reasoning": "V11 Fusion V5 weighted random 회피",
                "brain_tag": "v11_fusion",
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
            # 회피 통과 OR 마지막 강제 채움 (3회 이상 실패 시)
            if _v11_is_diff_from_army1_fusion(cand, army1_fusion_sets) or bypass_attempts > 30:
                sets.append({
                    "nums": cand,
                    "confidence": 0.50,
                    "reasoning": "V11 Fusion V5 bypass (안전장치)",
                    "brain_tag": "v11_fusion",
                    "method": "V11_Fusion_V5_Bypass",
                })

    return sets[:n_sets]


# 호환용 alias (기존 v11_fusion_predict 호출 지점에서 그대로 사용 가능)
v11_fusion_predict = v11_fusion_v5_predict
