"""V10 통합 엔진: grouping + correlation + stacking 결합.

V9 엔진(engine.py)은 보존. V10은 별도 함수로 동작.
- 학습 데이터: 전체 회차 (get_full_draws_for_army2)
- PMF 결합: 6뇌 PMF + grouping PMF → stacking 메타모델 입력
- 가중치 보정: correlation 기반 anti-corr 점수 반영

1군 코드 의존성 0. 1군 DB 읽기 전용.
"""
from __future__ import annotations

import logging
import random
from pathlib import Path

from app.lotto.filters import tier1_filter
from app.lotto2.models import get_lotto2_db, get_full_draws_for_army2

logger = logging.getLogger(__name__)

SETS_PER_BRAIN_V10 = 5
ARMY2_BRAINS_V10 = (
    "army2_stat",
    "army2_markov",
    "army2_combo",
    "army2_lstm",
    "army2_fusion",
    "army2_hyena",
)
V10_BRAIN_TAG_PREFIX = "v10d_"  # V10_v4 (Hyena 100%, Grouping 제거)


def _build_pmf_from_brain(brain_tag: str, draws: list[dict]) -> dict:
    """V9 뇌 함수를 V10용으로 호출 (전체 회차 입력)."""
    if brain_tag == "army2_stat":
        from app.lotto2.predict_stat import army2_stat_prob_vector

        return army2_stat_prob_vector(draws)
    if brain_tag == "army2_markov":
        from app.lotto2.predict_markov import army2_markov_prob_vector

        return army2_markov_prob_vector(draws)
    if brain_tag == "army2_combo":
        from app.lotto2.predict_combo import army2_combo_prob_vector

        return army2_combo_prob_vector(draws)
    if brain_tag == "army2_lstm":
        from app.lotto2.predict_lstm import army2_lstm_prob_vector

        return army2_lstm_prob_vector(draws)
    return {n: 1.0 / 45 for n in range(1, 46)}


def _stacking_meta_predict(target_draw_no: int) -> dict[int, float] | None:
    """V10 회차별 메타모델 재학습 + 추론 (B 방식, 컷닝 0%).

    target_draw_no 미만 데이터로 학습하여 그 회차 PMF 산출.
    """
    try:
        import numpy as np
        from app.lotto2.stacking import (
            ARMY2_BRAINS,
            N_NUMBERS,
            INPUT_DIM,
            build_feature_vector,
            build_dataset,
            train_meta_model,
            predict_meta_pmf,
        )
    except Exception as e:
        logger.warning(f"V10 stacking import failed: {e}")
        return None

    # 학습 시작 회차 50 (메타모델 데이터 최소 43개 확보)
    if target_draw_no < 50:
        return None

    try:
        # 컷닝 방지: target 미만 데이터만 학습
        X, Y, draws = build_dataset(50, target_draw_no - 1)
        if X.shape[0] < 30:
            return None

        # 회차별 재학습
        model = train_meta_model(X, Y, lr=0.05, epochs=200, l2=1e-3)

        # 추론
        x_target = build_feature_vector(target_draw_no)
        if x_target.sum() == 0:
            return None
        P = predict_meta_pmf(x_target.reshape(1, -1), model)
        return {i + 1: float(P[0][i]) for i in range(N_NUMBERS)}
    except Exception as e:
        logger.warning(f"V10 stacking predict failed at {target_draw_no}: {e}")
        return None


def _grouping_pmf(target_draw_no: int) -> dict[int, float]:
    """계층적 그룹핑 PMF (Phase B)."""
    try:
        from app.lotto2.grouping import get_grouped_pmf

        return get_grouped_pmf(target_draw_no, n=5, m=3)  # 격자 최저 entropy
    except Exception:  # noqa: BLE001
        return {n: 1.0 / 45 for n in range(1, 46)}


def _v10_fused_pmf(target_draw_no: int) -> dict[int, float]:
    """V10_v4 PMF: Hyena 100% (Grouping 제거).

    raw 진단(V10_v3):
    - hyena 단독 top5_mass=0.7007, entropy=2.3368
    - hyena 90 + grouping 10 → top5_mass 0.6322 (희석 -0.0685)
    → grouping이 hyena 신호를 끌어내림 → 완전 제거

    블렌드 없음. Hyena Top-K Greedy 단독.
    """
    return _compute_hyena_pmf(target_draw_no)


def _compute_hyena_pmf(target_draw_no: int) -> dict[int, float]:
    """V10_v3: 2군 hyena 5뇌 합의 + Top-K Greedy.

    V9 hyena 알고리즘 충실 재현:
    1. 5뇌 호출 (각 5세트, 총 25세트)
    2. 1~45 합의 점수 (등장 횟수)
    3. 상위 15개 번호 풀
    4. C(15,6)=5005 조합 중 tier1_filter 통과 후 점수 정렬
    5. 상위 조합들의 등장 빈도로 PMF 산출

    컷닝 0%: target_draw_no 미만만 사용.
    """
    # V10_v4: fused==hyena 동일성(결정성) 확보를 위해 회차 기반 seed 고정
    seed = int(target_draw_no)
    random.seed(seed)
    try:
        import numpy as np

        np.random.seed(seed)
    except Exception:  # noqa: BLE001
        pass
    try:
        import torch

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
    except Exception:  # noqa: BLE001
        pass

    from itertools import combinations

    from app.lotto.filters import tier1_filter
    from app.lotto2.models import get_full_draws_for_army2
    from app.lotto2.predict_stat import army2_stat_predict
    from app.lotto2.predict_markov import army2_markov_predict
    from app.lotto2.predict_combo import army2_combo_predict
    from app.lotto2.predict_lstm import army2_lstm_predict
    from app.lotto2.fusion import army2_fusion_predict

    full = get_full_draws_for_army2(target_draw_no)
    if len(full) < 50:
        return {n: 1.0 / 45 for n in range(1, 46)}

    # 1) 5뇌 호출
    pool = []
    for fn in (
        army2_stat_predict,
        army2_markov_predict,
        army2_combo_predict,
        army2_lstm_predict,
        army2_fusion_predict,
    ):
        try:
            pool.extend(fn(full, 5))
        except Exception:  # noqa: BLE001
            pass

    if not pool:
        return {n: 1.0 / 45 for n in range(1, 46)}

    # 2) 5뇌 합의 점수
    consensus = {n: 0.0 for n in range(1, 46)}
    for p in pool:
        for x in p.get("nums", []):
            if 1 <= x <= 45:
                consensus[x] += 1.0

    # 3) 상위 15 번호 풀
    pool_top = sorted(consensus.items(), key=lambda x: -x[1])[:15]
    pool_nums = [n for n, _ in pool_top]

    # 4) 조합 평가 (최대 2000개, V9 hyena와 동일 제한)
    combos = []
    eval_count = 0
    for c in combinations(pool_nums, 6):
        if eval_count >= 2000:
            break
        eval_count += 1
        cand = sorted(c)
        try:
            if not tier1_filter(cand):
                continue
        except Exception:  # noqa: BLE001
            pass
        s = sum(consensus[n] for n in cand)
        combos.append((cand, s))

    if not combos:
        total = sum(consensus.values()) or 1.0
        return {n: consensus[n] / total for n in range(1, 46)}

    combos.sort(key=lambda x: -x[1])

    # 5) 상위 50개 조합의 번호 등장 빈도 → PMF
    top_combos = combos[:50]
    pmf_score = {n: 0.0 for n in range(1, 46)}
    for cand, score in top_combos:
        for x in cand:
            pmf_score[x] += score

    total = sum(pmf_score.values()) or 1.0
    return {n: pmf_score[n] / total for n in range(1, 46)}


def _sample_sets_from_pmf(
    pmf: dict[int, float], n_sets: int = 5, max_attempts: int = 200
) -> list[dict]:
    """PMF 가중 샘플링으로 n_sets 생성 (tier1_filter 통과)."""
    nums = list(pmf.keys())
    weights = list(pmf.values())
    sets: list[dict] = []
    attempts = 0
    while len(sets) < n_sets and attempts < max_attempts:
        attempts += 1
        cand = sorted(random.choices(nums, weights=weights, k=6))
        if len(set(cand)) != 6:
            continue
        try:
            if not tier1_filter(cand):
                continue
        except Exception:  # noqa: BLE001
            pass
        sets.append(
            {
                "nums": cand,
                "confidence": 0.55,
                "reasoning": "V10 fused PMF (stacking+grouping)",
                "brain_tag": V10_BRAIN_TAG_PREFIX + "fusion",
                "method": "V10역전퓨전두뇌",
            }
        )
    return sets


def run_prediction_v10(target_draw_no: int) -> dict:
    """V10 단일 회차 예측. V9 데이터 영향 없음.

    저장은 lotto_predictions_army2 테이블의 brain_tag='v10_*' 로.
    V9 6뇌(army2_*)와 분리 식별.
    """
    conn = get_lotto2_db()
    try:
        existing = conn.execute(
            """
            SELECT brain_tag
            FROM lotto_predictions_army2
            WHERE target_draw_no = ?
              AND brain_tag LIKE 'v10d_%'
            """,
            (target_draw_no,),
        ).fetchall()
    finally:
        conn.close()

    if existing and len(existing) >= SETS_PER_BRAIN_V10:
        return {
            "status": "cached",
            "target_draw_no": target_draw_no,
            "v10_sets": len(existing),
        }

    pmf = _v10_fused_pmf(target_draw_no)
    sets = _sample_sets_from_pmf(pmf, n_sets=SETS_PER_BRAIN_V10)

    if not sets:
        return {"status": "error", "reason": "no_sets_generated", "target_draw_no": target_draw_no}

    conn = get_lotto2_db()
    try:
        conn.execute(
            "DELETE FROM lotto_predictions_army2 WHERE target_draw_no = ? AND brain_tag LIKE 'v10d_%'",
            (target_draw_no,),
        )
        for r in sets:
            nums = r["nums"]
            conn.execute(
                """
                INSERT INTO lotto_predictions_army2
                (target_draw_no, method, num1, num2, num3, num4, num5, num6,
                 confidence, reasoning, brain_tag)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target_draw_no,
                    r["method"],
                    nums[0],
                    nums[1],
                    nums[2],
                    nums[3],
                    nums[4],
                    nums[5],
                    r["confidence"],
                    r["reasoning"],
                    r["brain_tag"],
                ),
            )
        conn.commit()
        _score_v10_predictions(target_draw_no)
    finally:
        conn.close()

    return {"status": "ok", "target_draw_no": target_draw_no, "v10_sets": len(sets)}


def _score_v10_predictions(target_draw_no: int) -> None:
    """V10 예측 채점 (V9와 동일 방식, brain_tag만 다름)."""
    conn = get_lotto2_db()
    try:
        actual = conn.execute(
            "SELECT num1, num2, num3, num4, num5, num6, bonus FROM lotto_draws WHERE draw_no = ?",
            (target_draw_no,),
        ).fetchone()
        if not actual:
            return
        actual_set = {actual[i] for i in range(6)}
        bonus = actual[6]
        rows = conn.execute(
            """
            SELECT id, num1, num2, num3, num4, num5, num6
            FROM lotto_predictions_army2
            WHERE target_draw_no = ?
              AND brain_tag LIKE 'v10_%'
            """,
            (target_draw_no,),
        ).fetchall()
        for r in rows:
            pred_set = {r[i + 1] for i in range(6)}
            matched = len(pred_set & actual_set)
            bonus_m = 1 if bonus in pred_set else 0
            conn.execute(
                "UPDATE lotto_predictions_army2 SET matched_count = ?, bonus_matched = ? WHERE id = ?",
                (matched, bonus_m, r[0]),
            )
        conn.commit()
    finally:
        conn.close()

