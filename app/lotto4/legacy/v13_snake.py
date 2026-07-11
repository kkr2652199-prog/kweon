"""V11 Snake — 1군 predict_snake.py 미러링.

2군 v13_* 6뇌의 30셋트를 hyena식 합의로 메타 최적화하여
1군 30셋트와 Jaccard < 0.4 차별화된 셋트만 채택.

- 입력: v13_* 6뇌 30셋트 (run_prediction_v13 내부에서 전달)
- 비교: 1군 lotto_predictions 30셋트 (읽기만 공유)
- 합의 가중치: lotto_brain_weights_army4 (get_v13_brain_weights) 연동
- Jaccard 임계값: 0.4 (1군 검증값 그대로)
- 출력 brain_tag: "v13_snake"
- 저장 DB: lotto_predictions_army4
"""

from __future__ import annotations

import logging
import random
from itertools import combinations

from app.lotto4.legacy.v13_models import V13_WIN_AVOID_N, get_recent_winning_sets, v13_pass_win_avoid

logger = logging.getLogger(__name__)

# 패치 H — 하위 4뇌(stat/run/offset/contrarian) 합의 제외. 독립 예측은 유지 (v13_engine과 동일 집합).
_EXCLUDE_LOWER4_FROM_CONSENSUS: frozenset[str] = frozenset(
    {"v13_stat", "v13_run", "v13_offset", "v13_contrarian"}
)


def _load_snake_weights() -> dict[str, float]:
    """Hedge 가중치 테이블에서 7뇌 current_weight를 읽어 snake consensus 가중치로 사용."""
    from app.lotto4.legacy.v13_models import get_v13_brain_weights

    weights = get_v13_brain_weights()
    if not weights:
        return {}
    return weights


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


def v13_snake_predict_sets(
    v13_predictions: list[dict],
    target_draw_no: int,
    n_sets: int = 5,
) -> list[dict]:
    """V11 Snake: v13_* 6뇌 30셋트 → 1군과 차별화된 합성 셋트 생성.

    Args:
        v13_predictions: v13_* 6뇌 결과 셋트 리스트 (각 dict는 nums + brain_tag).
        target_draw_no: 1군 셋트 로드 기준 회차.
        n_sets: 생성할 셋트 수.

    Returns:
        list[dict]: brain_tag="v13_snake" 셋트 리스트.
    """
    if len(v13_predictions) < 6:
        logger.warning("v13_snake: insufficient predictions (%d)", len(v13_predictions))
        return []

    snake_weights = _load_snake_weights()

    # 1) tier1_filter 가져오기 (1군 모듈 재사용)
    try:
        from app.lotto.filters import tier1_filter
    except Exception:
        tier1_filter = None

    # 2) 1군 셋트 로드 (Jaccard 비교 대상)
    army1_sets = _load_army1_sets_for_target(target_draw_no)
    win_sets = get_recent_winning_sets(target_draw_no, V13_WIN_AVOID_N)
    win_st: dict[str, int | bool] = {"fail_count": 0, "bypass": False}

    # 3) 가중 합의: 1~45 점수 산출
    consensus: dict[int, float] = {n: 0.0 for n in range(1, 46)}
    for p in v13_predictions:
        tag = str(p.get("brain_tag", ""))
        w = float(snake_weights.get(tag, 1.0))
        if tag in _EXCLUDE_LOWER4_FROM_CONSENSUS:
            w = 0.0
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
        if not v13_pass_win_avoid(cand, win_sets, win_st):
            continue

        score = sum(consensus[n] for n in cand)
        sets.append({
            "nums": cand,
            "confidence": min(0.7, 0.4 + score / 200.0),
            "reasoning": f"V11 Snake 합성 (1군 Jaccard<0.4) score={score:.2f}",
            "brain_tag": "v13_snake",
            "method": "V11_Snake_합성뇌",
        })
        if len(sets) >= n_sets:
            break

    # 6) 부족 시 가중 랜덤 충원
    if len(sets) < n_sets:
        attempts = 0
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
            if not v13_pass_win_avoid(cand, win_sets, win_st):
                continue
            score = sum(consensus[n] for n in cand)
            sets.append({
                "nums": cand,
                "confidence": min(0.6, 0.35 + score / 250.0),
                "reasoning": f"V11 Snake 충원 (1군 Jaccard<0.4) score={score:.2f}",
                "brain_tag": "v13_snake",
                "method": "V11_Snake_합성뇌",
            })

    return sets[:n_sets]
