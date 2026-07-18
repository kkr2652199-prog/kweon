"""로또 1티어 조합 필터 — 공통 모듈."""


def tier1_filter(nums: list[int]) -> bool:
    """1티어 필터 통과 여부.
    합계 80~210, 홀수 1~5개, 범위 2개+, 연속 3개 이하.
    True = 통과, False = 탈락."""
    s = sum(nums)
    odd_count = sum(1 for n in nums if n % 2 == 1)
    ranges_hit = len({(n - 1) // 10 for n in nums})
    consec = 1
    max_consec = 1
    for i in range(1, len(nums)):
        if nums[i] == nums[i - 1] + 1:
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 1
    if s < 80 or s > 210:
        return False
    if odd_count == 0 or odd_count == 6:
        return False
    if ranges_hit <= 1:
        return False
    if max_consec >= 4:
        return False
    return True
