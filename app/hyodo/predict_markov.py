"""로또 마르코프 체인 예측 — app.hyodo 독립 패키지.
2026-04-20: Layer 2-a — 피드백 학습 고리 주입 (frequent_traps ×0.8, frequent_hits ×1.15). 컨닝 방지: get_feedback_summary로 과거 피드백만 참조.
"""

import logging
import random
from math import exp

logger = logging.getLogger(__name__)


def build_transition_matrix(draws: list[dict], decay: float = 0.02) -> dict:
    """
    연속 회차 간 전이행렬 구축.
    draws는 draw_no 오름차순 정렬된 리스트.
    decay: 최신 회차에 높은 가중치 (지수감쇠).

    전이행렬[a][b] = "a가 나온 회차 다음에 b가 나올 가중 횟수"
    """
    matrix = {}
    for i in range(1, 46):
        matrix[i] = {}
        for j in range(1, 46):
            matrix[i][j] = 0.5  # Laplace smoothing (k=0.5)

    total_draws = len(draws)
    for idx in range(len(draws) - 1):
        current_nums = [draws[idx][f"num{k}"] for k in range(1, 7)]
        next_nums = [draws[idx + 1][f"num{k}"] for k in range(1, 7)]
        weight = exp(-decay * (total_draws - 1 - idx))
        for a in current_nums:
            for b in next_nums:
                matrix[a][b] += weight

    return matrix


def markov_random_walk(matrix: dict, start_nums: list[int], steps: int = 50) -> dict:
    """
    전이행렬 기반 Random Walk.
    start_nums: 최근 회차의 6개 당첨번호 (시작점).
    steps: 각 시작점에서 걸을 횟수.

    반환: {번호: 방문횟수} 딕셔너리
    """
    visit_count = {}
    for i in range(1, 46):
        visit_count[i] = 0

    for start in start_nums:
        current = start
        for _ in range(steps):
            targets = list(range(1, 46))
            weights = [matrix[current][t] for t in targets]
            total_w = sum(weights)
            if total_w == 0:
                current = random.randint(1, 45)
            else:
                current = random.choices(targets, weights=weights, k=1)[0]
            visit_count[current] += 1

    return visit_count


def get_markov_prob_vector(draws: list[dict]) -> dict[int, float]:
    """마르코프 두뇌의 1~45 확률 벡터를 반환한다.
    전이행렬 + 랜덤워크 방문 횟수를 정규화.
    반환: {1: 0.025, 2: 0.018, ..., 45: 0.031} (합계 1.0)
    """
    if len(draws) < 2:
        return {n: 1.0 / 45 for n in range(1, 46)}

    matrix = build_transition_matrix(draws)
    last_draw = draws[-1]
    start_nums = [last_draw[f"num{k}"] for k in range(1, 7)]
    visit_count = markov_random_walk(matrix, start_nums, steps=80)

    # ── 피드백 학습 고리 (Layer 2-a) ──
    # 컨닝 방지: get_feedback_summary는 DB의 과거 피드백만 반환
    try:
        from app.hyodo.feedback import get_feedback_summary

        fb = get_feedback_summary(last_n=20)
        if fb.get("has_feedback"):
            for trap_n in fb.get("frequent_traps", []):
                if trap_n in visit_count:
                    visit_count[trap_n] *= 0.8  # 함정 번호 20% 감소
            for hit_n in fb.get("frequent_hits", []):
                if hit_n in visit_count:
                    visit_count[hit_n] *= 1.15  # 적중 번호 15% 증가
    except Exception as e:  # noqa: BLE001
        logger.debug("마르코프 피드백 반영 스킵: %s", e)

    total = sum(visit_count.values())
    if total == 0:
        return {n: 1.0 / 45 for n in range(1, 46)}

    return {n: visit_count[n] / total for n in range(1, 46)}


def _markov_predict(draws: list[dict], n_sets: int = 5) -> list[dict]:
    """
    Markov Chain 기반 예측.
    1) 전이행렬 구축
    2) 최근 회차 번호에서 Random Walk
    3) 방문빈도 상위 번호로 가중 조합 생성
    4) 1티어 필터 적용
    """
    if len(draws) < 2:
        return []

    matrix = build_transition_matrix(draws)

    last_draw = draws[-1]
    start_nums = [last_draw[f"num{k}"] for k in range(1, 7)]

    visit_count = markov_random_walk(matrix, start_nums, steps=80)

    # ── 피드백 학습 고리 (Layer 2-a) ──
    try:
        from app.hyodo.feedback import get_feedback_summary

        fb = get_feedback_summary(last_n=20)
        if fb.get("has_feedback"):
            for trap_n in fb.get("frequent_traps", []):
                if trap_n in visit_count:
                    visit_count[trap_n] *= 0.8
            for hit_n in fb.get("frequent_hits", []):
                if hit_n in visit_count:
                    visit_count[hit_n] *= 1.15
    except Exception as e:  # noqa: BLE001
        logger.debug("마르코프 피드백 반영 스킵 (_markov_predict): %s", e)

    top_candidates = sorted(visit_count.items(), key=lambda x: x[1], reverse=True)[:25]
    candidate_nums = [n for n, _ in top_candidates]
    candidate_weights = [c for _, c in top_candidates]

    results = []
    used = set()
    attempts = 0

    while len(results) < n_sets and attempts < 5000:
        attempts += 1

        if len(candidate_nums) >= 6:
            pool = candidate_nums[:]
            w = candidate_weights[:]
            nums = []
            for _ in range(6):
                chosen = random.choices(pool, weights=w, k=1)[0]
                nums.append(chosen)
                ci = pool.index(chosen)
                pool.pop(ci)
                w.pop(ci)
        else:
            nums = random.sample(range(1, 46), 6)

        nums.sort()

        # 1티어 필터
        s = sum(nums)
        odd_count = sum(1 for n in nums if n % 2 == 1)
        ranges_hit = len({(n - 1) // 10 for n in nums})
        consec = 1
        max_consec = 1
        for ci in range(1, len(nums)):
            if nums[ci] == nums[ci - 1] + 1:
                consec += 1
                max_consec = max(max_consec, consec)
            else:
                consec = 1

        if s < 80 or s > 210:
            continue
        if odd_count == 0 or odd_count == 6:
            continue
        if ranges_hit <= 1:
            continue
        if max_consec >= 4:
            continue

        key = tuple(nums)
        if key in used:
            continue
        used.add(key)

        confidence = 50.0
        if 100 <= s <= 175:
            confidence += 12
        if 2 <= odd_count <= 4:
            confidence += 8
        if ranges_hit >= 4:
            confidence += 10
        elif ranges_hit >= 3:
            confidence += 5
        total_visits = sum(visit_count[n] for n in nums)
        max_visits = sum(sorted(visit_count.values(), reverse=True)[:6])
        if max_visits > 0:
            confidence += (total_visits / max_visits) * 15
        confidence = min(round(confidence, 1), 99.0)

        results.append(
            {
                "nums": nums,
                "confidence": confidence,
                "reasoning": f"마르코프v1, 합계={s}, 홀{odd_count}짝{6 - odd_count}, 구간{ranges_hit}, 연속최대{max_consec}",
            }
        )

    results.sort(key=lambda x: x["confidence"], reverse=True)
    return results[:n_sets]
