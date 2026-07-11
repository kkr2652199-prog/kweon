"""로또 Shannon 엔트로피 분석 — app.hyodo 독립 패키지.
각 번호의 예측 불확실성을 측정하여 확률 벡터를 조정.
2026-04-25 Layer 3.5: 비대칭 클립 [0.5, 1.5] → [0.85, 1.5] (강자 보호, peak 손실 35.6% → 7.5%)."""
import logging
import math

logger = logging.getLogger(__name__)


def get_entropy_weights(prob_vector: dict[int, float]) -> dict[int, float]:
    """확률 벡터에 Shannon 엔트로피 가중치를 적용한다.

    엔트로피가 높은 번호(불확실한) → 가중치 감소
    엔트로피가 낮은 번호(확실한) → 가중치 유지/증가

    입력: {1: 0.025, ..., 45: 0.031} (합계 1.0)
    출력: {1: 0.024, ..., 45: 0.033} (합계 1.0, 엔트로피 반영)
    """
    if not prob_vector:
        return {n: 1.0 / 45 for n in range(1, 46)}

    # 각 번호의 엔트로피 기여도: -p * log2(p)
    entropy_contrib = {}
    for n, p in prob_vector.items():
        if p > 0:
            entropy_contrib[n] = -p * math.log2(p)
        else:
            entropy_contrib[n] = 0.0

    # 전체 엔트로피
    total_entropy = sum(entropy_contrib.values())
    if total_entropy == 0:
        return prob_vector.copy()

    # 엔트로피 역수 가중: 불확실한 번호는 낮추고 확실한 번호는 높임
    # 정보량(information content) = -log2(p) 가 높을수록 희귀
    # 확률 × (1 - 정규화된 엔트로피 기여도) 로 조정
    adjusted = {}
    for n in range(1, 46):
        p = prob_vector.get(n, 0.0)
        e = entropy_contrib.get(n, 0.0)
        # 엔트로피 기여가 평균보다 높으면 감소, 낮으면 증가
        avg_entropy = total_entropy / 45
        if avg_entropy > 0:
            entropy_factor = 1.0 - 0.3 * (e - avg_entropy) / avg_entropy
            entropy_factor = max(0.85, min(1.5, entropy_factor))
        else:
            entropy_factor = 1.0
        adjusted[n] = p * entropy_factor

    # 재정규화
    total = sum(adjusted.values())
    if total == 0:
        return {n: 1.0 / 45 for n in range(1, 46)}

    return {n: adjusted[n] / total for n in range(1, 46)}
