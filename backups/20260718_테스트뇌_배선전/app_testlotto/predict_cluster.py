"""로또 K-Means 클러스터링 분석 — app.testlotto 독립 패키지.
번호를 그룹으로 묶어 숨겨진 패턴을 찾고 확률 벡터를 보정."""
import logging

import numpy as np
from sklearn.cluster import KMeans

logger = logging.getLogger(__name__)


def get_cluster_weights(
    draws: list[dict],
    prob_vector: dict[int, float],
    n_clusters: int = 5,
) -> dict[int, float]:
    """K-Means 클러스터링으로 번호 그룹 패턴을 분석하고
    확률 벡터를 보정한다.

    각 번호를 (빈도, 최근성, 확률) 3차원 특성으로 임베딩 후
    K-Means로 클러스터링. 최근 당첨에 많이 나온 클러스터의
    번호에 가중치를 높인다.

    입력: draws, prob_vector (합계 1.0)
    출력: 보정된 prob_vector (합계 1.0)
    """
    if len(draws) < 10:
        return prob_vector.copy()

    total_draws = len(draws)

    # 번호별 특성 추출: [빈도비율, 최근성, 현재확률]
    freq_count = {}
    last_seen = {}
    for idx, d in enumerate(draws):
        for k in ["num1", "num2", "num3", "num4", "num5", "num6"]:
            n = d[k]
            freq_count[n] = freq_count.get(n, 0) + 1
            last_seen[n] = idx

    features = np.zeros((45, 3))
    for i, n in enumerate(range(1, 46)):
        features[i, 0] = freq_count.get(n, 0) / total_draws  # 빈도 비율
        features[i, 1] = last_seen.get(n, 0) / total_draws  # 최근성 (0~1)
        features[i, 2] = prob_vector.get(n, 1.0 / 45)  # 현재 확률

    # K-Means 클러스터링
    actual_k = min(n_clusters, len(draws) // 5, 45)
    if actual_k < 2:
        return prob_vector.copy()

    try:
        kmeans = KMeans(n_clusters=actual_k, random_state=42, n_init=10)
        labels = kmeans.fit_predict(features)
    except Exception as e:
        logger.debug("클러스터링 실패: %s", e)
        return prob_vector.copy()

    # 최근 10회 당첨번호가 어떤 클러스터에 속하는지 카운트
    recent_10 = draws[-10:] if len(draws) >= 10 else draws
    cluster_hits = {}
    for d in recent_10:
        for k in ["num1", "num2", "num3", "num4", "num5", "num6"]:
            n = d[k]
            c = labels[n - 1]  # 0-indexed
            cluster_hits[c] = cluster_hits.get(c, 0) + 1

    # 클러스터별 가중치: 최근 당첨이 많은 클러스터 = 높은 가중
    max_hits = max(cluster_hits.values()) if cluster_hits else 1
    cluster_weight = {}
    for c in range(actual_k):
        hits = cluster_hits.get(c, 0)
        cluster_weight[c] = 0.7 + 0.6 * (hits / max_hits)  # 0.7 ~ 1.3

    # 확률 보정
    adjusted = {}
    for i, n in enumerate(range(1, 46)):
        c = labels[i]
        adjusted[n] = prob_vector.get(n, 1.0 / 45) * cluster_weight.get(c, 1.0)

    # 재정규화
    total = sum(adjusted.values())
    if total == 0:
        return {n: 1.0 / 45 for n in range(1, 46)}

    return {n: adjusted[n] / total for n in range(1, 46)}
