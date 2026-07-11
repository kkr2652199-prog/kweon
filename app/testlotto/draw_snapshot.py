"""회차별 정밀 분석판 — 1~45 빈도·급등·쌍·연속·6구간·보너스 (READ ONLY)."""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.testlotto.features.draw_features import (
    ac_value,
    build_number_gaps,
    build_pair_freq,
    carry_over_from_prev,
    consecutive_pairs,
    ending_digits,
    odd_even_ratio,
    sorted_nums,
)

# 민간 6구간 (1~6구간)
ZONE6_BOUNDS: list[tuple[int, int, str]] = [
    (1, 7, "1구간"),
    (8, 14, "2구간"),
    (15, 21, "3구간"),
    (22, 28, "4구간"),
    (29, 35, "5구간"),
    (36, 45, "6구간"),
]

# 색 구간 (엑셀 대시보드 벤치마킹)
ZONE5_BOUNDS: list[tuple[int, int, str]] = [
    (1, 10, "1~10"),
    (11, 20, "11~20"),
    (21, 30, "21~30"),
    (31, 40, "31~40"),
    (41, 45, "41~45"),
]

RECENT_WINDOW = 20
SPIKE_RATIO = 1.6
COLD_GAP_MIN = 25


def zone6_label(num: int) -> str:
    for lo, hi, label in ZONE6_BOUNDS:
        if lo <= num <= hi:
            return label
    return "?"


def zone5_label(num: int) -> str:
    for lo, hi, label in ZONE5_BOUNDS:
        if lo <= num <= hi:
            return label
    return "?"


def _count_freq(draws: list[dict]) -> Counter[int]:
    c: Counter[int] = Counter()
    for d in draws:
        for n in sorted_nums(d):
            c[n] += 1
    return c


def _count_recent(draws: list[dict], window: int = RECENT_WINDOW) -> Counter[int]:
    c: Counter[int] = Counter()
    for d in draws[-window:]:
        for n in sorted_nums(d):
            c[n] += 1
    return c


def _consecutive_runs(nums: list[int]) -> list[list[int]]:
    s = sorted(nums)
    if not s:
        return []
    runs: list[list[int]] = []
    run = [s[0]]
    for i in range(1, len(s)):
        if s[i] == s[i - 1] + 1:
            run.append(s[i])
        else:
            if len(run) >= 2:
                runs.append(run)
            run = [s[i]]
    if len(run) >= 2:
        runs.append(run)
    return runs


def _pairs_in_nums(nums: list[int]) -> list[list[int]]:
    s = sorted(nums)
    return [[a, b] for i, a in enumerate(s) for b in s[i + 1 :]]


def _detect_spike_nums(
    total_freq: Counter[int],
    recent_freq: Counter[int],
    num_draws: int,
    window: int = RECENT_WINDOW,
) -> list[int]:
    if num_draws < 5:
        return []
    spikes: list[tuple[int, float]] = []
    for n in range(1, 46):
        baseline = (total_freq.get(n, 0) / max(num_draws, 1)) * window
        recent = recent_freq.get(n, 0)
        if recent >= 2 and baseline > 0 and recent >= baseline * SPIKE_RATIO:
            spikes.append((n, recent / baseline))
        elif recent >= 3 and baseline < 1.5:
            spikes.append((n, float(recent)))
    spikes.sort(key=lambda x: -x[1])
    return [n for n, _ in spikes[:10]]


def _detect_cold_comeback(
    nums: list[int],
    gaps: dict[int, int],
    min_gap: int = COLD_GAP_MIN,
) -> list[int]:
    return sorted([n for n in nums if gaps.get(n, 0) >= min_gap])


def _hot_cold_top(
    freq: Counter[int], k: int = 5
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    total = sum(freq.values()) or 1
    ranked = sorted(
        [
            {
                "num": n,
                "count": freq.get(n, 0),
                "pct": round(freq.get(n, 0) / total * 100, 2),
            }
            for n in range(1, 46)
        ],
        key=lambda x: (-x["count"], x["num"]),
    )
    hot = ranked[:k]
    cold = sorted(ranked, key=lambda x: (x["count"], x["num"]))[:k]
    return hot, cold


def _zone_counts(nums: list[int], bounds: list[tuple[int, int, str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for lo, hi, label in bounds:
        cnt = sum(1 for n in nums if lo <= n <= hi)
        out.append({"label": label, "low": lo, "high": hi, "count": cnt})
    return out


def build_snapshot_context(draws: list[dict]) -> dict[str, Any]:
    """예측 시점(draws = target 이전) 스냅샷 — num_explainer 보강용."""
    if not draws:
        return {}
    total = _count_freq(draws)
    recent = _count_recent(draws)
    gaps = build_number_gaps(draws)
    spike = _detect_spike_nums(total, recent, len(draws))
    pf = build_pair_freq(draws)
    hot_pairs = {p for p, _ in pf.most_common(15)}
    hot, cold = _hot_cold_top(total)
    return {
        "spike_nums": spike,
        "cold_gap_nums": sorted([n for n in range(1, 46) if gaps.get(n, 0) >= COLD_GAP_MIN]),
        "hot_top5": hot,
        "cold_top5": cold,
        "hot_pair_keys": [list(p) for p in hot_pairs],
        "freq_grid": {str(n): total.get(n, 0) for n in range(1, 46)},
    }


def build_analysis_board(
    draw_no: int,
    nums: list[int],
    bonus: int,
    draws_inclusive: list[dict],
) -> dict[str, Any]:
    """회차 N 당첨 기준 정밀 분석판 (draws 1..N 포함)."""
    nums = sorted(int(n) for n in nums)
    bonus = int(bonus or 0)
    total_freq = _count_freq(draws_inclusive)
    recent_freq = _count_recent(draws_inclusive)
    gaps = build_number_gaps(draws_inclusive)
    pf = build_pair_freq(draws_inclusive)
    prev = draws_inclusive[-2] if len(draws_inclusive) >= 2 else None

    spike_in_draw = [
        n for n in nums if n in _detect_spike_nums(total_freq, recent_freq, len(draws_inclusive))
    ]
    cold_in_draw = _detect_cold_comeback(nums, gaps)
    hot_top, cold_top = _hot_cold_top(total_freq)
    pairs_draw = _pairs_in_nums(nums)
    hot_pair_hits = []
    for pair in pairs_draw:
        key = tuple(sorted(pair))
        if pf.get(key, 0) >= 3:
            hot_pair_hits.append({"pair": pair, "hist_count": pf[key]})

    odd, even = odd_even_ratio(nums)
    carry = carry_over_from_prev(prev, nums) if prev else []
    bonus_carry = bonus in set(sorted_nums(prev)) if prev and bonus else False

    return {
        "draw_no": draw_no,
        "total_draws": len(draws_inclusive),
        "winning_nums": nums,
        "bonus": bonus,
        "freq_grid": [{"num": n, "count": total_freq.get(n, 0)} for n in range(1, 46)],
        "freq_recent_window": RECENT_WINDOW,
        "freq_recent": [{"num": n, "count": recent_freq.get(n, 0)} for n in range(1, 46)],
        "hot_top5": hot_top,
        "cold_top5": cold_top,
        "spike_nums": spike_in_draw,
        "cold_comeback": cold_in_draw,
        "consecutive_runs": _consecutive_runs(nums),
        "consecutive_count": consecutive_pairs(nums),
        "pairs_in_draw": pairs_draw,
        "pair_hot_hits": hot_pair_hits,
        "zone6": _zone_counts(nums, ZONE6_BOUNDS),
        "zone5_color": _zone_counts(nums, ZONE5_BOUNDS),
        "zone_low_mid_high": [
            sum(1 for n in nums if 1 <= n <= 15),
            sum(1 for n in nums if 16 <= n <= 30),
            sum(1 for n in nums if 31 <= n <= 45),
        ],
        "ending_digits": ending_digits(nums),
        "ac_value": ac_value(nums),
        "sum_total": sum(nums),
        "odd_count": odd,
        "even_count": even,
        "carry_over_nums": carry,
        "bonus_profile": {
            "num": bonus,
            "zone6": zone6_label(bonus) if bonus else "",
            "zone5": zone5_label(bonus) if bonus else "",
            "hist_count": total_freq.get(bonus, 0) if bonus else 0,
            "carry_from_prev": bonus_carry,
            "gap": gaps.get(bonus, 0) if bonus else 0,
        },
    }


def enrich_tags_from_snapshot(num: int, tags: list[str], ctx: dict[str, Any] | None) -> list[str]:
    """num_explainer 태그에 스냅샷 신호 병합."""
    if not ctx:
        return tags[:4]
    out = list(tags)
    if num in (ctx.get("spike_nums") or []) and "급등" not in out:
        out.insert(0, "급등")
    if num in (ctx.get("cold_gap_nums") or []) and "장기미출" not in out:
        if "미출장기" not in out:
            out.insert(0, "장기미출")
    hot5 = {x["num"] for x in (ctx.get("hot_top5") or [])}
    if num in hot5 and "HOT" not in out:
        out.append("HOT")
    z6 = zone6_label(num)
    if z6 and z6 not in "".join(out):
        out.append(z6)
    return out[:4]
