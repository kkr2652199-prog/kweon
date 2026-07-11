"""구조검증관 — 홀짝·합계 구조 (SELMA oddeven/sumrange 벤치마킹)."""

from __future__ import annotations

from app.testlotto.features.draw_features import combo_features, odd_even_ratio, sum_range


def _historical_sum_band(draws: list[dict]) -> tuple[float, float]:
    if not draws:
        return 120.0, 180.0
    sums = [sum_range(sorted([d[f"num{k}"] for k in range(1, 7)])) for d in draws[-100:]]
    avg = sum(sums) / len(sums)
    return avg - 35, avg + 35


def score_set(nums: list[int], draws: list[dict], target_draw_no: int) -> float:
    s = sum_range(nums)
    lo, hi = _historical_sum_band(draws)
    sum_score = 1.0 if lo <= s <= hi else max(0.2, 1.0 - min(abs(s - lo), abs(s - hi)) / 80)
    odd, even = odd_even_ratio(nums)
    oe_score = 1.0 if odd in (2, 3, 4) else 0.5
    return max(0.1, min(1.0, 0.55 * sum_score + 0.45 * oe_score))


def describe(nums: list[int], draws: list[dict], target_draw_no: int) -> str:
    s = sum_range(nums)
    odd, even = odd_even_ratio(nums)
    return f"구조검증관:합{s} 홀{odd}짝{even} 점수{score_set(nums, draws, target_draw_no):.2f}"
