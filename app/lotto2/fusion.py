"""V9 2군 fusion: 4뇌(stat/markov/combo/lstm) 비대칭 앙상블."""
import logging
import random
import sqlite3

from app.lotto.filters import tier1_filter
from app.lotto2.predict_combo import army2_combo_prob_vector
from app.lotto2.predict_markov import army2_markov_prob_vector
from app.lotto2.predict_lstm import army2_lstm_prob_vector
from app.lotto2.predict_stat import army2_stat_prob_vector

logger = logging.getLogger(__name__)


def _load_army2_weights() -> dict[str, float]:
    """2군 가중치 DB에서 로드."""
    from app.lotto2.models import get_lotto2_db

    conn = get_lotto2_db()
    try:
        rows = conn.execute(
            """
            SELECT brain_tag, current_weight
            FROM lotto_brain_weights_army2
            WHERE brain_tag IN (
                'army2_stat','army2_markov','army2_combo','army2_lstm'
            )
            """
        ).fetchall()
        return {str(r[0]): float(r[1]) for r in rows}
    except (OSError, sqlite3.Error) as e:
        logger.warning("2군 fusion 가중치 로드 실패, 기본값 사용: %s", e)
        return {
            "army2_stat": 1.5,
            "army2_markov": 1.0,
            "army2_combo": 2.5,
            "army2_lstm": 2.0,
        }
    finally:
        conn.close()


def army2_fusion_predict(miss_draws: list[dict], n_sets: int = 5) -> list[dict]:
    """4뇌 PMF 가중 합성 + 샘플링."""
    if not miss_draws:
        return []

    weights = _load_army2_weights()
    pmfs = {
        "army2_stat": army2_stat_prob_vector(miss_draws),
        "army2_markov": army2_markov_prob_vector(miss_draws),
        "army2_combo": army2_combo_prob_vector(miss_draws),
        "army2_lstm": army2_lstm_prob_vector(miss_draws),
    }

    fused: dict[int, float] = dict.fromkeys(range(1, 46), 0.0)
    total_w = sum(weights.get(t, 1.0) for t in pmfs)
    for tag, pmf in pmfs.items():
        w = weights.get(tag, 1.0) / total_w
        for n in range(1, 46):
            fused[n] += pmf.get(n, 0) * w

    nums_list = list(fused.keys())
    w_list = list(fused.values())

    sets: list[dict] = []
    attempts = 0
    while len(sets) < n_sets and attempts < 100:
        attempts += 1
        cand = sorted(random.choices(nums_list, weights=w_list, k=6))
        if len(set(cand)) != 6:
            continue
        try:
            if not tier1_filter(cand):
                continue
        except (TypeError, ValueError) as e:
            logger.debug("역전퓨전 tier1_filter 스킵: %s", e)
            continue
        sets.append(
            {
                "nums": cand,
                "confidence": 0.55,
                "reasoning": (
                    f"역전퓨전 4뇌 가중 합성 (LSTM {weights.get('army2_lstm', 2.0):.1f})"
                ),
                "brain_tag": "army2_fusion",
                "method": "역전퓨전두뇌",
                "source": "army2_fusion",
            }
        )
    return sets
