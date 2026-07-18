"""통계요정 — 빈도·끝수·이월수 (SELMA hot/cold + 이월수 벤치마킹)."""

from __future__ import annotations

import random

from app.testlotto.features.draw_features import build_number_gaps, carry_over_from_prev, sorted_nums
from app.testlotto.learn_state import load_learn_state
from app.testlotto.predict_statistical import _statistical_predict


def predict_sets(draws: list[dict], n_sets: int = 5) -> list[dict]:
    """기존 통계 엔진 + 끝수/이월수 reasoning + 학습 조정."""
    base = _statistical_predict(draws, n_sets)
    prev = draws[-1] if draws else None
    gaps = build_number_gaps(draws)
    learn = load_learn_state("stat")
    adj = learn.get("adjustments", {})
    carry_boost = 1.0 + float(adj.get("carry_over_boost", 0))
    ending_boost = 1.0 + float(adj.get("ending_digit_boost", 0))
    overdue_boost = 1.0 + float(adj.get("overdue_boost", 0))
    out: list[dict] = []
    for i, r in enumerate(base):
        nums = sorted(r["nums"])
        carry = carry_over_from_prev(prev, nums)
        endings = sorted({n % 10 for n in nums})
        overdue = sorted([n for n in nums if gaps.get(n, 0) >= 30])
        learn_note = ""
        if adj:
            learn_note = f" [학습조정 이월×{carry_boost:.2f} 끝수×{ending_boost:.2f}]"
        conf = float(r.get("confidence", 70))
        if carry and carry_boost > 1:
            conf = min(95, conf + len(carry) * (carry_boost - 1) * 8)
        reasoning = (
            f"통계요정: 빈도가중+끝수{endings}"
            f"+이월{len(carry)}개{carry if carry else ''}"
            f"+미출30+{overdue if overdue else '없음'}"
            f"{learn_note}"
        )
        out.append(
            {
                "nums": sorted(nums),
                "confidence": float(r.get("confidence", 70)),
                "reasoning": reasoning,
                "method": "통계요정",
                "brain_tag": "stat",
                "rank": i + 1,
            }
        )
    return out
