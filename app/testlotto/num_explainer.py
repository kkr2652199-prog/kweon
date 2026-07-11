"""번호별 기여 근거·오답노트 내러티브 (읽기 전용, DB 미변경)."""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.testlotto.features.draw_features import (
    build_number_gaps,
    build_pair_freq,
    repeat_rate_after_draw,
    sorted_nums,
)
from app.testlotto.predict_statistical import get_statistical_prob_vector

MAX_TAGS = 3


def _top_freq_nums(draws: list[dict], k: int = 15) -> set[int]:
    if not draws:
        return set()
    vec = get_statistical_prob_vector(draws)
    return {n for n, _ in sorted(vec.items(), key=lambda x: -x[1])[:k]}


def _hot_endings(draws: list[dict], window: int = 10) -> set[int]:
    c: Counter[int] = Counter()
    for d in draws[-window:]:
        for n in sorted_nums(d):
            c[n % 10] += 1
    return {d for d, cnt in c.items() if cnt >= 3}


def explain_num_stat(num: int, draws: list[dict], prev: dict | None) -> list[str]:
    tags: list[str] = []
    gaps = build_number_gaps(draws)
    if prev and num in set(sorted_nums(prev)):
        tags.append("이월수")
    if num in _top_freq_nums(draws):
        tags.append("빈도상위")
    if gaps.get(num, 0) >= 30:
        tags.append("미출장기")
    if num % 10 in _hot_endings(draws):
        tags.append(f"끝수{num % 10}")
    return tags[:MAX_TAGS] or ["통계후보"]


def explain_num_markov(num: int, draws: list[dict], prev: dict | None, all_nums: list[int]) -> list[str]:
    tags: list[str] = []
    if prev and num in set(sorted_nums(prev)):
        tags.append("전이연결")
    pf = build_pair_freq(draws)
    pair_score = 0
    for o in all_nums:
        if o == num:
            continue
        pair = tuple(sorted((num, o)))
        pair_score += pf.get(pair, 0)
    if pair_score >= 5:
        tags.append("동반출현")
    if len(all_nums) >= 2:
        s = sorted(all_nums)
        if num in s and any(abs(num - x) == 1 for x in s if x != num):
            tags.append("연속궁합")
    return tags[:MAX_TAGS] or ["흐름가중"]


def explain_num_review(num: int, draws: list[dict], prev: dict | None) -> list[str]:
    tags: list[str] = []
    if prev and num in set(sorted_nums(prev)):
        tags.append("전회복습")
    rates = repeat_rate_after_draw(draws)
    if rates.get(num, 0) >= 0.12:
        tags.append("반복후보")
    if draws and num in sorted_nums(draws[-1]):
        tags.append("직전출현")
    return tags[:MAX_TAGS] or ["복습가중"]


def explain_best_set(
    brain_tag: str,
    nums: list[int],
    draws: list[dict],
) -> list[dict[str, Any]]:
    """best 세트 번호별 기여 태그 (explainerdashboard 스타일)."""
    prev = draws[-1] if draws else None
    out: list[dict[str, Any]] = []
    for n in sorted(nums):
        if brain_tag == "stat":
            tags = explain_num_stat(n, draws, prev)
        elif brain_tag == "markov":
            tags = explain_num_markov(n, draws, prev, nums)
        else:
            tags = explain_num_review(n, draws, prev)
        out.append({"num": int(n), "tags": tags})
    return out


def build_wrong_note_narrative(
    brain_name: str,
    *,
    matched_count: int,
    tier_label: str,
    tier_rank: int,
    hit_nums: list[int],
    missed_pattern_labels: list[str],
    actual_missed_nums: list[int],
    best_set_no: int,
) -> str:
    """규칙 기반 한 줄 요약 (ThoughtSpot/Databricks narrative 스타일)."""
    if tier_rank and 1 <= tier_rank <= 5:
        hit_str = ", ".join(map(str, hit_nums)) if hit_nums else "없음"
        reason = ""
        if missed_pattern_labels:
            reason = f", {missed_pattern_labels[0]} 신호는 맞았지만"
        elif actual_missed_nums:
            reason = f", {actual_missed_nums[0]}번을 더 맞췄으면 상위 등수"
        return (
            f"{brain_name}: {tier_label} — {matched_count}개 적중({hit_str})"
            f"{reason} · {best_set_no}세트 핵심"
        )

    parts: list[str] = []
    if matched_count >= 3:
        parts.append(f"{matched_count}개 근접했으나 등수 미달")
    elif matched_count == 2:
        parts.append("2개 근접")
    elif matched_count == 1:
        parts.append("1개만 맞춤")
    else:
        parts.append("전멸 미적중")

    if missed_pattern_labels:
        parts.append(f"{missed_pattern_labels[0]} 놓침이 아쉬움")
    elif actual_missed_nums:
        miss_preview = ", ".join(map(str, actual_missed_nums[:3]))
        parts.append(f"실제 {miss_preview} 놓침")
    else:
        parts.append("패턴 단서 부족")

    return f"{brain_name}: " + ", ".join(parts)


def build_wrong_note(
    brain_tag: str,
    brain_name: str,
    best_nums: list[int],
    actual_nums: list[int],
    *,
    best_set_no: int,
    matched_count: int,
    tier_label: str,
    tier_rank: int,
    hit_nums: list[int],
    missed_pattern_labels: list[str],
    draws: list[dict],
) -> dict[str, Any]:
    """뇌 1건 오답노트 블록."""
    pred_set = set(best_nums)
    actual_set = set(actual_nums)
    actual_missed = sorted(actual_set - pred_set)
    false_nums = sorted(pred_set - actual_set)

    return {
        "narrative": build_wrong_note_narrative(
            brain_name,
            matched_count=matched_count,
            tier_label=tier_label,
            tier_rank=tier_rank,
            hit_nums=sorted(hit_nums) if hit_nums else sorted(pred_set & actual_set),
            missed_pattern_labels=missed_pattern_labels,
            actual_missed_nums=actual_missed,
            best_set_no=best_set_no,
        ),
        "best_set_no": best_set_no,
        "best_nums": list(best_nums),
        "num_explains": explain_best_set(brain_tag, best_nums, draws),
        "hit_nums": sorted(pred_set & actual_set),
        "false_nums": false_nums,
        "actual_missed_nums": actual_missed,
    }
