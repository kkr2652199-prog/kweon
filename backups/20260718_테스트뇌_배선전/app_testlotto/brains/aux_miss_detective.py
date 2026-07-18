"""오답탐정 — 과거 예측 오답 패턴 페널티 (1군 feedback 벤치마킹)."""

from __future__ import annotations

from app.testlotto.features.draw_features import combo_features


def score_set(nums: list[int], draws: list[dict], target_draw_no: int) -> float:
    """0~1. 과거 frequent_traps 번호 포함 시 감점."""
    feats = combo_features(nums, draws)
    penalty = 0.0
    try:
        from app.testlotto.feedback import get_feedback_summary

        fb = get_feedback_summary(last_n=30)
        traps = set(fb.get("frequent_traps") or [])
        hits_on_trap = sum(1 for n in nums if n in traps)
        penalty = min(0.5, hits_on_trap * 0.12)
    except Exception:
        penalty = 0.0
    base = 0.75 - penalty
    return max(0.1, min(1.0, base))


def describe(nums: list[int], draws: list[dict], target_draw_no: int) -> str:
    s = score_set(nums, draws, target_draw_no)
    return f"오답탐정:{s:.2f}"
