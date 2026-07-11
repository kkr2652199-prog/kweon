"""심판관 — 최근 성적 좋은 예측뇌에 가중치 배분."""

from __future__ import annotations

from app.testlotto.learn_state import get_referee_weights


def get_predict_brain_weights() -> dict[str, float]:
    return get_referee_weights()


def score_set(nums: list[int], draws: list[dict], target_draw_no: int) -> float:
    """보조 채점 파이프라인 호환용 — 중립 기본값."""
    return 0.5


def describe(nums: list[int], draws: list[dict], target_draw_no: int) -> str:
    w = get_predict_brain_weights()
    parts = [f"{k}:{v:.2f}" for k, v in sorted(w.items())]
    return f"심판관:가중치 {' '.join(parts)}"
