"""복습왕 — 전회차 복습 학습형 (walk-forward 반복률, LotteryML lag 벤치마킹)."""

from __future__ import annotations

import random

from app.testlotto.features.draw_features import repeat_rate_after_draw, sorted_nums
from app.testlotto.filters import tier1_filter
from app.testlotto.learn_state import load_learn_state


def predict_sets(draws: list[dict], n_sets: int = 5) -> list[dict]:
    if not draws:
        return []
    prev = draws[-1]
    prev_nums = sorted_nums(prev)
    rates = repeat_rate_after_draw(draws)
    learn = load_learn_state("review")
    adj = learn.get("adjustments", {})
    carry_boost = 1.0 + float(adj.get("carry_over_boost", 0))
    weights = {n: rates.get(n, 0.08) for n in range(1, 46)}
    for n in prev_nums:
        weights[n] *= 1.8 * carry_boost
    for n in range(1, 46):
        if n not in prev_nums:
            weights[n] *= 0.85

    results: list[dict] = []
    used: set[tuple[int, ...]] = set()
    attempts = 0
    while len(results) < n_sets and attempts < 3000:
        attempts += 1
        pool = list(range(1, 46))
        w = [weights[n] for n in pool]
        pick: list[int] = []
        for _ in range(6):
            if not pool:
                break
            chosen = random.choices(pool, weights=w, k=1)[0]
            pick.append(chosen)
            idx = pool.index(chosen)
            pool.pop(idx)
            w.pop(idx)
        pick = sorted(pick)
        if len(pick) != 6:
            continue
        key = tuple(pick)
        if key in used:
            continue
        if not tier1_filter(pick):
            continue
        used.add(key)
        repeat_hits = [n for n in pick if n in prev_nums]
        conf = 60 + len(repeat_hits) * 5 + sum(rates.get(n, 0) for n in repeat_hits) * 20
        results.append(
            {
                "nums": pick,
                "confidence": min(95, conf),
                "reasoning": (
                    f"복습왕: {prev['draw_no']}회 복습 "
                    f"이월후보{repeat_hits} 반복률가중"
                    f" [학습조정 이월×{carry_boost:.2f} 복습{learn.get('review_count',0)}회]"
                ),
                "method": "복습왕",
                "brain_tag": "review",
                "rank": len(results) + 1,
            }
        )
    return results
