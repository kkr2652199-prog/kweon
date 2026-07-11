"""V9 2군 lstm: 1군 LSTM 재사용 + 미당첨 데이터."""

from __future__ import annotations

import logging
import random

from app.lotto.filters import tier1_filter
from app.lotto.predict_lstm import get_lstm_prob_vector
from app.lotto4.legacy.v13_models import V13_WIN_AVOID_N, get_recent_winning_sets, v13_pass_win_avoid

logger = logging.getLogger(__name__)


def army4_lstm_prob_vector(miss_draws: list[dict]) -> dict[int, float]:
    if not miss_draws or len(miss_draws) < 10:
        return {n: 1.0 / 45 for n in range(1, 46)}
    return get_lstm_prob_vector(miss_draws)


def army4_lstm_predict(
    miss_draws: list[dict],
    n_sets: int = 5,
    target_draw_no: int | None = None,
) -> list[dict]:
    """LSTM PMF 기반 샘플링."""
    if not miss_draws or len(miss_draws) < 10:
        return []

    pmf = get_lstm_prob_vector(miss_draws)
    nums = list(pmf.keys())
    weights = list(pmf.values())
    win_sets = (
        get_recent_winning_sets(target_draw_no, V13_WIN_AVOID_N) if target_draw_no else []
    )
    st: dict[str, int | bool] = {"fail_count": 0, "bypass": False}

    sets: list[dict] = []
    attempts = 0
    while len(sets) < n_sets and attempts < 20000:
        attempts += 1
        cand = sorted(random.choices(nums, weights=weights, k=6))
        if len(set(cand)) != 6:
            continue
        try:
            if not tier1_filter(cand):
                continue
        except (TypeError, ValueError) as e:
            logger.debug("역전LSTM tier1_filter 스킵: %s", e)
            continue
        if not v13_pass_win_avoid(cand, win_sets, st):
            continue
        sets.append(
            {
                "nums": cand,
                "confidence": 0.5,
                "reasoning": "역전LSTM 미당첨 시계열",
                "brain_tag": "army4_lstm",
                "method": "역전LSTM두뇌",
                "source": "army4_lstm",
            }
        )
    return sets
