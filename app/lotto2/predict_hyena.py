"""V9 2군 hyena: 5뇌 합의 점수 + Top-K Greedy.

pool_nums 상위 15개에서만 C(15,6) 조합을 평가해 조합 폭주를 방지한다(5005개 상한).
"""
import logging
import sqlite3
from itertools import combinations

from app.lotto.filters import tier1_filter

logger = logging.getLogger(__name__)

# 상위 15개 번호 → C(15,6)=5005 로 상한 고정
_POOL_TOP_K = 15
# 정렬 후 상위 세트만 채택(동일 점수 대비 안정성)
_MAX_COMBO_EVAL = 2000


def _load_army2_hyena_weights() -> dict[str, float]:
    """2군 hyena 가중치: 5뇌 + fusion."""
    from app.lotto2.models import get_lotto2_db

    conn = get_lotto2_db()
    try:
        rows = conn.execute(
            "SELECT brain_tag, current_weight FROM lotto_brain_weights_army2"
        ).fetchall()
        return {str(r[0]): float(r[1]) for r in rows}
    except (OSError, sqlite3.Error) as e:
        logger.warning("2군 hyena 가중치 로드 실패, 기본값: %s", e)
        return {
            "army2_stat": 1.5,
            "army2_markov": 1.0,
            "army2_combo": 2.5,
            "army2_lstm": 2.0,
            "army2_fusion": 2.0,
            "army2_hyena": 2.0,
        }
    finally:
        conn.close()


def _compute_consensus(
    all_predictions: list[dict], weights: dict[str, float]
) -> dict[int, float]:
    """1~45 번호별 합의 점수(가중 등장 횟수)."""
    score = {n: 0.0 for n in range(1, 46)}
    for p in all_predictions:
        tag = p.get("brain_tag", "")
        w = weights.get(tag, 1.0)
        for n in p.get("nums", []):
            if 1 <= n <= 45:
                score[n] += w
    return score


def army2_hyena_predict(all_predictions: list[dict], n_sets: int = 5) -> list[dict]:
    """2군 5뇌 25세트 → 합의 점수 → Top-K Greedy."""
    if len(all_predictions) < 10:
        return []

    weights = _load_army2_hyena_weights()
    consensus = _compute_consensus(all_predictions, weights)

    pool = sorted(consensus.items(), key=lambda x: -x[1])[:_POOL_TOP_K]
    pool_nums = [n for n, _ in pool]
    if len(pool_nums) < 6:
        return []

    combos: list[tuple[list[int], float]] = []
    for i, c in enumerate(combinations(pool_nums, 6)):
        if i >= _MAX_COMBO_EVAL:
            break
        cand = sorted(c)
        try:
            if not tier1_filter(cand):
                continue
        except (TypeError, ValueError) as e:
            logger.debug("역전하이에나 tier1_filter 스킵: %s", e)
            continue
        s = sum(consensus[n] for n in cand)
        combos.append((cand, s))

    combos.sort(key=lambda x: -x[1])

    sets: list[dict] = []
    for cand, s in combos[: n_sets * 3]:
        if len(sets) >= n_sets:
            break
        sets.append(
            {
                "nums": cand,
                "confidence": min(0.7, 0.4 + s / 100),
                "reasoning": (
                    f"역전하이에나 합의점수 상위 {_POOL_TOP_K}후보, 조합점수 {s:.2f}"
                ),
                "brain_tag": "army2_hyena",
                "method": "역전하이에나두뇌",
                "source": "army2_hyena",
            }
        )
    return sets
