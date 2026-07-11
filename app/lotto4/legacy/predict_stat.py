"""V9 2군 stat: 1군 _statistical_predict 재사용 + 미당첨 데이터."""

from __future__ import annotations

import random

from app.lotto.predict_statistical import _statistical_predict, get_statistical_prob_vector
from app.lotto4.legacy.v13_models import (
    V13_WIN_AVOID_N,
    get_recent_winning_sets,
    v13_pass_win_avoid,
    v13_perturb_combo_one_swap,
)


def army4_stat_predict(
    miss_draws: list[dict],
    n_sets: int = 5,
    target_draw_no: int | None = None,
) -> list[dict]:
    """1군 stat 함수를 미당첨 데이터로 호출."""
    if not miss_draws:
        return []
    win_sets = (
        get_recent_winning_sets(target_draw_no, V13_WIN_AVOID_N) if target_draw_no else []
    )
    results = _statistical_predict(miss_draws, n_sets)
    out: list[dict] = []
    for r in results:
        st: dict[str, int | bool] = {"fail_count": 0, "bypass": False}
        nums = sorted(int(x) for x in r["nums"])
        rng = random.Random(hash(tuple(nums)) % (2**32))
        guard = 0
        while guard < 8000:
            guard += 1
            if v13_pass_win_avoid(nums, win_sets, st):
                break
            nums = v13_perturb_combo_one_swap(nums, rng)
        rr = dict(r)
        rr["nums"] = nums
        rr["brain_tag"] = "army4_stat"
        rr["method"] = "역전통계두뇌"
        out.append(rr)
    return out


def army4_stat_prob_vector(miss_draws: list[dict]) -> dict[int, float]:
    if not miss_draws:
        return {n: 1.0 / 45 for n in range(1, 46)}
    return get_statistical_prob_vector(miss_draws)
