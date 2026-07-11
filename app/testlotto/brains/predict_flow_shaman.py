"""흐름술사 — 마르코프 전이 + 동반출현 (lottery_predictor STRAT05 벤치마킹)."""

from __future__ import annotations

from app.testlotto.features.draw_features import build_pair_freq, pair_set, sorted_nums
from app.testlotto.predict_markov import _markov_predict


def predict_sets(draws: list[dict], n_sets: int = 5) -> list[dict]:
    base = _markov_predict(draws, n_sets)
    pair_freq = build_pair_freq(draws)
    out: list[dict] = []
    for i, r in enumerate(base):
        nums = sorted(r["nums"])
        pairs = pair_set(nums)
        hot_pairs = sum(pair_freq.get(p, 0) for p in pairs)
        reasoning = f"흐름술사: 마르코프전이+동반쌍점수{hot_pairs}"
        out.append(
            {
                "nums": sorted(nums),
                "confidence": float(r.get("confidence", 68)),
                "reasoning": reasoning,
                "method": "흐름술사",
                "brain_tag": "markov",
                "rank": i + 1,
            }
        )
    return out
