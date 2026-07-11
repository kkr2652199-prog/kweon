"""45C6 combinadic 순위 — 형 앱 lotto_common.py와 동일 (DB 불필요)."""

from __future__ import annotations

import math

TOTAL_COMBOS = 8_145_060
PICK = 6
POOL = 45


def _validate_nums(nums: list[int] | tuple[int, ...]) -> tuple[int, ...]:
    if len(nums) != PICK:
        raise ValueError(f"6개 번호가 필요합니다 (입력 {len(nums)}개)")
    s = sorted(int(n) for n in nums)
    if len(set(s)) != PICK:
        raise ValueError("중복 번호는 허용되지 않습니다")
    if any(n < 1 or n > POOL for n in s):
        raise ValueError("번호는 1~45 범위여야 합니다")
    return tuple(s)


def combo_to_no(nums: list[int] | tuple[int, ...]) -> int:
    """6번호(순서 무관) → 814만 중 순위 No (1-based)."""
    combo = _validate_nums(nums)
    no = 1
    prev = 0
    for i, num in enumerate(combo):
        remaining = PICK - i - 1
        for candidate in range(prev + 1, num):
            no += math.comb(POOL - candidate, remaining)
        prev = num
    return no


def no_to_combo(no: int) -> tuple[int, ...]:
    """순위 No → 6번호 (오름차순)."""
    n = int(no)
    if n < 1 or n > TOTAL_COMBOS:
        raise ValueError(f"combo_no는 1~{TOTAL_COMBOS} 범위여야 합니다")
    index = n - 1
    combo: list[int] = []
    start = 1
    for i in range(PICK):
        remaining = PICK - i - 1
        for candidate in range(start, POOL + 1):
            count = math.comb(POOL - candidate, remaining)
            if index < count:
                combo.append(candidate)
                start = candidate + 1
                break
            index -= count
    return tuple(combo)
