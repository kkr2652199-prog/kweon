"""로또 통계 두뇌 예측 — app.lotto 독립 패키지."""
import logging
import random
from math import exp

from app.lotto.filters import tier1_filter

logger = logging.getLogger(__name__)


def get_statistical_prob_vector(draws: list[dict]) -> dict[int, float]:
    """통계 두뇌의 1~45 확률 벡터를 반환한다.
    _statistical_predict 내부의 weights 계산 로직과 동일.
    반환: {1: 0.025, 2: 0.018, ..., 45: 0.031} (합계 1.0)
    """
    from math import exp

    freq: dict[int, float] = {}
    last_seen: dict[int, int] = {}
    total_draws = len(draws)

    for idx, d in enumerate(draws):
        recency_weight = exp(-0.02 * (total_draws - 1 - idx))
        for k in ["num1", "num2", "num3", "num4", "num5", "num6"]:
            n = d[k]
            freq[n] = freq.get(n, 0.0) + recency_weight
            last_seen[n] = d["draw_no"]

    for n in range(1, 46):
        if n not in freq:
            freq[n] = 0.1
        if n not in last_seen:
            last_seen[n] = 0

    latest_draw_no = draws[-1]["draw_no"] if draws else 0
    for n in range(1, 46):
        gap = latest_draw_no - last_seen[n]
        if gap >= 50:
            freq[n] *= 1.3
        elif gap >= 30:
            freq[n] *= 1.15

    recent_5 = draws[-5:] if len(draws) >= 5 else draws
    hot_count: dict[int, int] = {}
    for d in recent_5:
        for k in ["num1", "num2", "num3", "num4", "num5", "num6"]:
            n = d[k]
            hot_count[n] = hot_count.get(n, 0) + 1
    for n, cnt in hot_count.items():
        if cnt >= 2:
            freq[n] *= 1.2

    recent_for_pairs = draws[-200:] if len(draws) >= 200 else draws
    pair_freq: dict[tuple[int, int], int] = {}
    for d in recent_for_pairs:
        nums_in_draw = sorted([d["num1"], d["num2"], d["num3"], d["num4"], d["num5"], d["num6"]])
        for i in range(len(nums_in_draw)):
            for j in range(i + 1, len(nums_in_draw)):
                pair = (nums_in_draw[i], nums_in_draw[j])
                pair_freq[pair] = pair_freq.get(pair, 0) + 1
    top_pairs = sorted(pair_freq.items(), key=lambda x: x[1], reverse=True)[:30]
    pair_bonus_nums: dict[int, float] = {}
    for (a, b), cnt in top_pairs:
        bonus = 0.05 * cnt
        pair_bonus_nums[a] = pair_bonus_nums.get(a, 0) + bonus
        pair_bonus_nums[b] = pair_bonus_nums.get(b, 0) + bonus
    for n, bonus in pair_bonus_nums.items():
        freq[n] *= 1 + min(bonus, 0.5)

    # 피드백 반영
    try:
        from app.lotto.feedback import get_feedback_summary

        fb = get_feedback_summary(last_n=20)
        if fb.get("has_feedback"):
            for trap_n in fb.get("frequent_traps", []):
                if trap_n in freq:
                    freq[trap_n] *= 0.8
            for hit_n in fb.get("frequent_hits", []):
                if hit_n in freq:
                    freq[hit_n] *= 1.15
    except Exception:
        pass

    # 최종 정규화 (합계 정확히 1.0)
    total = sum(freq.values())
    return {n: freq[n] / total for n in range(1, 46)}


def _statistical_predict(draws: list[dict], n_sets: int = 5) -> list[dict]:
    """통계 두뇌: 빈도·구간·홀짝·합계 기반 확률 가중 선택."""
    if not draws:
        return []

    # ── 1티어 가중 빈도 (Exponential Decay + Hot/Cold/Overdue) ──
    freq: dict[int, float] = {}  # 번호별 가중 빈도
    last_seen: dict[int, int] = {}  # 번호별 마지막 출현 회차
    total_draws = len(draws)

    for idx, d in enumerate(draws):
        # 지수 감쇠: 최근일수록 높은 가중치 (오래된=idx 0, 최신=idx total_draws-1)
        recency_weight = exp(-0.02 * (total_draws - 1 - idx))

        for k in ["num1", "num2", "num3", "num4", "num5", "num6"]:
            n = d[k]
            freq[n] = freq.get(n, 0.0) + recency_weight
            last_seen[n] = d["draw_no"]

    # 모든 번호 1~45 초기화
    for n in range(1, 46):
        if n not in freq:
            freq[n] = 0.1  # 한 번도 안 나온 번호도 최소값
        if n not in last_seen:
            last_seen[n] = 0

    # Overdue 보너스: 오래 안 나온 번호에 추가 가중치
    latest_draw_no = draws[-1]["draw_no"] if draws else 0
    for n in range(1, 46):
        gap = latest_draw_no - last_seen[n]
        if gap >= 50:
            freq[n] *= 1.3  # 50회 이상 미출현: 30% 보너스
        elif gap >= 30:
            freq[n] *= 1.15  # 30회 이상 미출현: 15% 보너스

    # Hot streak 보너스: 최근 5회 중 2회 이상 나온 번호
    recent_5 = draws[-5:] if len(draws) >= 5 else draws
    hot_count: dict[int, int] = {}
    for d in recent_5:
        for k in ["num1", "num2", "num3", "num4", "num5", "num6"]:
            n = d[k]
            hot_count[n] = hot_count.get(n, 0) + 1
    for n, cnt in hot_count.items():
        if cnt >= 2:
            freq[n] *= 1.2  # 최근 5회 중 2회 이상: 20% 보너스

    # ── 동반출현 쌍 보너스 ──
    # 최근 200회에서 자주 같이 나온 쌍의 번호에 추가 가중치
    recent_for_pairs = draws[-200:] if len(draws) >= 200 else draws
    pair_freq: dict[tuple[int, int], int] = {}
    for d in recent_for_pairs:
        nums_in_draw = sorted([d["num1"], d["num2"], d["num3"], d["num4"], d["num5"], d["num6"]])
        for i in range(len(nums_in_draw)):
            for j in range(i + 1, len(nums_in_draw)):
                pair = (nums_in_draw[i], nums_in_draw[j])
                pair_freq[pair] = pair_freq.get(pair, 0) + 1
    # 상위 30개 쌍에 포함된 번호에 보너스
    top_pairs = sorted(pair_freq.items(), key=lambda x: x[1], reverse=True)[:30]
    pair_bonus_nums: dict[int, float] = {}
    for (a, b), cnt in top_pairs:
        bonus = 0.05 * cnt  # 출현 횟수에 비례한 보너스
        pair_bonus_nums[a] = pair_bonus_nums.get(a, 0) + bonus
        pair_bonus_nums[b] = pair_bonus_nums.get(b, 0) + bonus
    for n, bonus in pair_bonus_nums.items():
        freq[n] *= 1 + min(bonus, 0.5)  # 최대 50% 보너스 상한

    # 가중 확률 계산
    total = sum(freq.values())
    weights = {n: freq[n] / total for n in range(1, 46)}

    # ── 피드백 루프: 과거 적중/함정 패턴 반영 ──
    try:
        from app.lotto.feedback import get_feedback_summary

        fb = get_feedback_summary(last_n=20)
        if fb.get("has_feedback"):
            # 함정 번호 가중치 20% 감소
            for trap_n in fb.get("frequent_traps", []):
                if trap_n in weights:
                    weights[trap_n] *= 0.8
            # 적중 번호 가중치 15% 증가
            for hit_n in fb.get("frequent_hits", []):
                if hit_n in weights:
                    weights[hit_n] *= 1.15
    except Exception as e:
        logger.debug("피드백 반영 스킵: %s", e)

    results = []
    used_combos = set()
    attempts = 0

    while len(results) < n_sets and attempts < 5000:
        attempts += 1
        nums: list[int] = []
        pool = list(range(1, 46))
        w = [weights[n] for n in pool]

        for pick_idx in range(6):
            chosen = random.choices(pool, weights=w, k=1)[0]
            nums.append(chosen)
            idx = pool.index(chosen)
            pool.pop(idx)
            w.pop(idx)

            # 동반출현 실시간 가중치 조정
            # 방금 뽑은 번호와 자주 함께 나온 번호의 가중치를 올림
            if pick_idx < 5:  # 마지막 번호 뽑은 후에는 불필요
                for p_idx, p_num in enumerate(pool):
                    pair_key = (min(chosen, p_num), max(chosen, p_num))
                    p_count = pair_freq.get(pair_key, 0)
                    if p_count >= 5:  # 최소 5회 이상 동반출현한 쌍만
                        boost = 1 + min(p_count * 0.02, 0.4)  # 최대 40% 부스트
                        w[p_idx] *= boost

        nums.sort()

        # ── 1티어 조합 필터: 과거 패턴에 벗어나는 조합 제거 ──
        s = sum(nums)
        odd_count = sum(1 for n in nums if n % 2 == 1)
        ranges_hit = len({(n - 1) // 10 for n in nums})
        # 연속번호 개수 (예: [3,4,5] → 연속 3개)
        consec = 1
        max_consec = 1
        for ci in range(1, len(nums)):
            if nums[ci] == nums[ci - 1] + 1:
                consec += 1
                max_consec = max(max_consec, consec)
            else:
                consec = 1

        if not tier1_filter(nums):
            continue

        key = tuple(nums)
        if key in used_combos:
            continue
        used_combos.add(key)

        # 신뢰도: 합계 범위(100~175) + 홀짝 균형(2:4~4:2) + 구간 분산
        confidence = 50.0
        if 100 <= s <= 175:
            confidence += 15
        if 2 <= odd_count <= 4:
            confidence += 10
        if ranges_hit >= 4:
            confidence += 15
        elif ranges_hit >= 3:
            confidence += 8
        # 빈도 점수
        avg_freq = sum(freq.get(n, 0) for n in nums) / 6
        max_freq = max(freq.values()) if freq else 1
        confidence += (avg_freq / max_freq) * 10

        confidence = min(round(confidence, 1), 99.0)

        results.append(
            {
                "nums": nums,
                "confidence": confidence,
                "reasoning": f"1티어통계v5(피드백반영), 합계={s}, 홀{odd_count}짝{6 - odd_count}, 구간{ranges_hit}, 연속최대{max_consec}",
            }
        )

    results.sort(key=lambda x: x["confidence"], reverse=True)
    return results
