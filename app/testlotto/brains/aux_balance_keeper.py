"""균형지킴이 — 홀짝·고저·구간 쏠림 방지 (3예측뇌 결과 균형 조율)."""

from __future__ import annotations

from app.testlotto.features.draw_features import odd_even_ratio, sum_range


def _zone_counts(nums: list[int]) -> tuple[int, int, int]:
    low = sum(1 for n in nums if 1 <= n <= 15)
    mid = sum(1 for n in nums if 16 <= n <= 30)
    high = sum(1 for n in nums if 31 <= n <= 45)
    return low, mid, high


def _historical_targets(draws: list[dict]) -> dict[str, float]:
    if not draws:
        return {"odd": 3.0, "sum": 150.0, "zone": 2.0}
    odds, sums = [], []
    zones = []
    for d in draws[-80:]:
        nums = sorted([int(d[f"num{k}"]) for k in range(1, 7)])
        o, _ = odd_even_ratio(nums)
        odds.append(o)
        sums.append(sum_range(nums))
        zones.append(max(_zone_counts(nums)))
    return {
        "odd": sum(odds) / len(odds),
        "sum": sum(sums) / len(sums),
        "zone": sum(zones) / len(zones),
    }


def score_set(nums: list[int], draws: list[dict], target_draw_no: int) -> float:
    tgt = _historical_targets(draws)
    odd, even = odd_even_ratio(nums)
    s = sum_range(nums)
    low, mid, high = _zone_counts(nums)
    zone_spread = max(low, mid, high) - min(low, mid, high)

    odd_score = 1.0 - min(1.0, abs(odd - tgt["odd"]) / 3)
    sum_score = 1.0 - min(1.0, abs(s - tgt["sum"]) / 60)
    zone_score = 1.0 - min(1.0, zone_spread / 4)
    return max(0.1, min(1.0, 0.35 * odd_score + 0.35 * sum_score + 0.30 * zone_score))


def describe(nums: list[int], draws: list[dict], target_draw_no: int) -> str:
    odd, even = odd_even_ratio(nums)
    low, mid, high = _zone_counts(nums)
    return (
        f"균형지킴이:홀{odd}짝{even} "
        f"구간{low}-{mid}-{high} 점수{score_set(nums, draws, target_draw_no):.2f}"
    )
