"""간격정찰병 — 미출·overdue 번호 (SELMA recency/distance 벤치마킹)."""

from __future__ import annotations

from app.testlotto.features.draw_features import build_number_gaps


def score_set(nums: list[int], draws: list[dict], target_draw_no: int) -> float:
    gaps = build_number_gaps(draws)
    overdue = [n for n in nums if gaps.get(n, 0) >= 25]
    fresh = [n for n in nums if gaps.get(n, 0) <= 5]
    overdue_score = min(1.0, len(overdue) * 0.18)
    fresh_penalty = min(0.3, len(fresh) * 0.05)
    return max(0.1, min(1.0, 0.5 + overdue_score - fresh_penalty))


def describe(nums: list[int], draws: list[dict], target_draw_no: int) -> str:
    gaps = build_number_gaps(draws)
    overdue = [n for n in nums if gaps.get(n, 0) >= 25]
    return f"간격정찰병:미출25+{overdue} 점수{score_set(nums, draws, target_draw_no):.2f}"
