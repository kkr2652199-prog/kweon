"""회차별 특징 — target_draw_no 미만 데이터만 사용 (walk-forward, 컨닝 금지)."""

from __future__ import annotations

from collections import Counter
from typing import Any


def sorted_nums(draw: dict) -> list[int]:
    return sorted(int(draw[f"num{k}"]) for k in range(1, 7))


def ac_value(nums: list[int]) -> int:
    """AC값: 정렬된 6수의 서로 다른 간격 개수 - 5."""
    if len(nums) < 2:
        return 0
    s = sorted(nums)
    diffs = {s[j] - s[i] for i in range(len(s)) for j in range(i + 1, len(s))}
    return max(0, len(diffs) - (len(s) - 1))


def ending_digits(nums: list[int]) -> list[int]:
    return [n % 10 for n in nums]


def consecutive_pairs(nums: list[int]) -> int:
    s = sorted(nums)
    return sum(1 for i in range(len(s) - 1) if s[i + 1] - s[i] == 1)


def odd_even_ratio(nums: list[int]) -> tuple[int, int]:
    odd = sum(1 for n in nums if n % 2 == 1)
    return odd, len(nums) - odd


def sum_range(nums: list[int]) -> int:
    return sum(nums)


def carry_over_from_prev(prev: dict | None, nums: list[int]) -> list[int]:
    """이월수: 직전 회차 번호와 겹치는 수."""
    if not prev:
        return []
    prev_set = set(sorted_nums(prev))
    return [n for n in nums if n in prev_set]


def pair_set(nums: list[int]) -> set[tuple[int, int]]:
    s = sorted(nums)
    return {(s[i], s[j]) for i in range(len(s)) for j in range(i + 1, len(s))}


def build_pair_freq(draws: list[dict], window: int = 100) -> Counter:
    """동반출현 쌍 빈도 (최근 window회)."""
    c: Counter = Counter()
    for d in draws[-window:]:
        for pair in pair_set(sorted_nums(d)):
            c[pair] += 1
    return c


def build_number_gaps(draws: list[dict]) -> dict[int, int]:
    """번호별 마지막 출현 이후 간격(회차)."""
    last: dict[int, int] = {}
    latest = draws[-1]["draw_no"] if draws else 0
    for d in draws:
        for n in sorted_nums(d):
            last[n] = d["draw_no"]
    return {n: latest - last.get(n, 0) for n in range(1, 46)}


def repeat_rate_after_draw(draws: list[dict], lookback: int = 200) -> dict[int, float]:
    """번호가 직전 회차에 나온 뒤 다음 회차에도 나올 역사적 비율 (복습왕용)."""
    if len(draws) < 3:
        return {n: 1 / 45 for n in range(1, 46)}
    sample = draws[-lookback:] if len(draws) >= lookback else draws
    appeared_next: Counter = Counter()
    appeared_prev: Counter = Counter()
    for i in range(1, len(sample)):
        prev_nums = set(sorted_nums(sample[i - 1]))
        cur_nums = set(sorted_nums(sample[i]))
        for n in prev_nums:
            appeared_prev[n] += 1
            if n in cur_nums:
                appeared_next[n] += 1
    rates: dict[int, float] = {}
    for n in range(1, 46):
        if appeared_prev[n] > 0:
            rates[n] = appeared_next[n] / appeared_prev[n]
        else:
            rates[n] = 0.08
    return rates


def combo_features(nums: list[int], draws: list[dict]) -> dict[str, Any]:
    """한 조합(6수)에 대한 보조 뇌용 특징."""
    prev = draws[-1] if draws else None
    return {
        "nums": sorted(nums),
        "sum": sum_range(nums),
        "odd_even": odd_even_ratio(nums),
        "consecutive": consecutive_pairs(nums),
        "ac": ac_value(nums),
        "endings": ending_digits(nums),
        "carry_over": carry_over_from_prev(prev, nums),
        "carry_count": len(carry_over_from_prev(prev, nums)),
    }
