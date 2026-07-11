"""V11 Snake — 1군 predict_snake.py 미러링.

2군 v11_* 6뇌의 30셋트를 hyena식 합의로 메타 최적화하여
1군 30셋트와 Jaccard < 0.4 차별화된 셋트만 채택.

- 입력: v11_* 6뇌 30셋트 (run_prediction_v11 내부에서 전달)
- 비교: 1군 lotto_predictions 30셋트 (읽기만 공유)
- Jaccard 임계값: 0.4 (1군 검증값 그대로)
- 출력 brain_tag: "v11_snake"
- 저장 DB: lotto_predictions_army2
"""

from __future__ import annotations

import logging
import random
from itertools import combinations

logger = logging.getLogger(__name__)

# 가중치 (1군 검증값 매핑: combo 50.0 / hyena 30.0 / 나머지 5.0)
_V11_SNAKE_WEIGHTS: dict[str, float] = {
    "v11_stat":   5.0,
    "v11_markov": 5.0,
    "v11_lstm":   5.0,
    "v11_combo": 50.0,   # 1군 miss_combo 자리
    "v11_fusion": 5.0,
    "v11_hyena": 30.0,   # 1군 miss_weak 자리 (메타 두뇌)
}

# 비교 대상 (1군 6뇌 brain_tag)
_ARMY1_TAGS: tuple[str, ...] = (
    "stat", "markov", "llm", "lstm", "fusion", "hyena",
)


def _is_diff_from_army1(
    combo: list[int],
    army1_sets: list[set[int]],
    threshold: float = 0.4,
) -> bool:
    """1군 셋트 중 단 하나라도 Jaccard >= threshold 면 탈락.

    1군 predict_snake.py와 100% 동일한 로직.
    """
    if not army1_sets:
        return True
    s = set(combo)
    for a1 in army1_sets:
        inter = len(s & a1)
        uni = len(s | a1)
        jac = inter / uni if uni else 0.0
        if jac >= threshold:
            return False
    return True


def _load_army1_sets_for_target(target_draw_no: int) -> list[set[int]]:
    """1군 lotto_predictions에서 6뇌 셋트 로드 (읽기만)."""
    from app.lotto.models import get_lotto_db

    ph = ",".join("?" * len(_ARMY1_TAGS))
    conn = get_lotto_db()
    try:
        rows = conn.execute(
            f"""
            SELECT num1, num2, num3, num4, num5, num6
            FROM lotto_predictions
            WHERE target_draw_no = ? AND brain_tag IN ({ph})
            """,
            (target_draw_no, *_ARMY1_TAGS),
        ).fetchall()
    finally:
        conn.close()
    return [set(r) for r in rows if r]


def v11_snake_predict_sets(
    v11_predictions: list[dict],
    target_draw_no: int,
    n_sets: int = 5,
) -> list[dict]:
    """V11 Snake: v11_* 6뇌 30셋트 → 1군과 차별화된 합성 셋트 생성.

    Args:
        v11_predictions: v11_* 6뇌 결과 셋트 리스트 (각 dict는 nums + brain_tag).
        target_draw_no: 1군 셋트 로드 기준 회차.
        n_sets: 생성할 셋트 수.

    Returns:
        list[dict]: brain_tag="v11_snake" 셋트 리스트.
    """
    if len(v11_predictions) < 6:
        logger.warning("v11_snake: insufficient predictions (%d)", len(v11_predictions))
        return []

    # 1) tier1_filter 가져오기 (1군 모듈 재사용)
    try:
        from app.lotto.filters import tier1_filter
    except Exception:
        tier1_filter = None

    # 2) 1군 셋트 로드 (Jaccard 비교 대상)
    army1_sets = _load_army1_sets_for_target(target_draw_no)

    # 3) 가중 합의: 1~45 점수 산출
    consensus: dict[int, float] = {n: 0.0 for n in range(1, 46)}
    for p in v11_predictions:
        tag = str(p.get("brain_tag", ""))
        w = float(_V11_SNAKE_WEIGHTS.get(tag, 1.0))
        nums = p.get("nums", [])
        for n in nums:
            if 1 <= int(n) <= 45:
                consensus[int(n)] += w

    # 4) Top 15 풀 선정
    ranked = sorted(consensus.items(), key=lambda x: -x[1])
    pool = [n for n, _s in ranked[:15]]

    if len(pool) < 6:
        return []

    # 5) 5005 조합 + tier1 + Jaccard 검증
    sets: list[dict] = []
    eval_count = 0
    for c in combinations(pool, 6):
        if eval_count >= 2000:
            break
        eval_count += 1
        cand = sorted(c)

        # tier1 필터
        if tier1_filter is not None:
            try:
                if not tier1_filter(cand):
                    continue
            except Exception:
                pass

        # Jaccard < 0.4 검증
        if not _is_diff_from_army1(cand, army1_sets, threshold=0.4):
            continue

        score = sum(consensus[n] for n in cand)
        sets.append({
            "nums": cand,
            "confidence": min(0.7, 0.4 + score / 200.0),
            "reasoning": f"V11 Snake 합성 (1군 Jaccard<0.4) score={score:.2f}",
            "brain_tag": "v11_snake",
            "method": "V11_Snake_합성뇌",
        })
        if len(sets) >= n_sets:
            break

    # 6) 부족 시 가중 랜덤 충원
    if len(sets) < n_sets:
        attempts = 0
        weights = [consensus[n] for n in pool]
        while len(sets) < n_sets and attempts < 200:
            attempts += 1
            try:
                cand = sorted(random.sample(
                    population=pool,
                    k=6,
                ))
            except Exception:
                continue
            if tier1_filter is not None:
                try:
                    if not tier1_filter(cand):
                        continue
                except Exception:
                    pass
            if not _is_diff_from_army1(cand, army1_sets, threshold=0.4):
                continue
            score = sum(consensus[n] for n in cand)
            sets.append({
                "nums": cand,
                "confidence": min(0.6, 0.35 + score / 250.0),
                "reasoning": f"V11 Snake 충원 (1군 Jaccard<0.4) score={score:.2f}",
                "brain_tag": "v11_snake",
                "method": "V11_Snake_합성뇌",
            })

    return sets[:n_sets]
