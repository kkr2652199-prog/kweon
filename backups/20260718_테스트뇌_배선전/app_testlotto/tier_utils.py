"""로또 예측 세트 등수 채점 — 본번호·보너스 기준."""

from __future__ import annotations

from typing import Any


def prediction_rank_tier(matched_count: int, bonus_matched: int = 0) -> tuple[int, str]:
    """matched_count·bonus_matched → (tier_rank 1~5 또는 0, 한글 등급)."""
    bm = 1 if bonus_matched else 0
    mc = int(matched_count or 0)
    if mc >= 6:
        return 1, "1등"
    if mc == 5 and bm:
        return 2, "2등"
    if mc == 5:
        return 3, "3등"
    if mc == 4:
        return 4, "4등"
    if mc >= 3:
        return 5, "5등"
    return 0, "미적중"


def score_predicted_set(
    nums: list[int], actual_nums: list[int], bonus: int = 0
) -> dict[str, Any]:
    """단일 예측 세트 채점."""
    actual_set = set(actual_nums or [])
    nums = [int(n) for n in (nums or [])]
    matched = len(set(nums) & actual_set)
    bonus_matched = 1 if bonus and bonus in nums else 0
    tier_rank, tier_label = prediction_rank_tier(matched, bonus_matched)
    return {
        "matched_count": matched,
        "bonus_matched": bonus_matched,
        "tier_rank": tier_rank,
        "tier_label": tier_label,
    }


def enrich_predicted_sets(
    sets: list[dict[str, Any]], actual_nums: list[int], bonus: int = 0
) -> list[dict[str, Any]]:
    """세트 목록에 등수 필드 보강(기존 데이터 호환)."""
    out: list[dict[str, Any]] = []
    for s in sets or []:
        row = dict(s)
        if row.get("tier_rank") is None:
            scored = score_predicted_set(row.get("nums") or [], actual_nums, bonus)
            row.update(scored)
        else:
            row.setdefault("tier_label", prediction_rank_tier(
                int(row.get("matched_count") or 0),
                int(row.get("bonus_matched") or 0),
            )[1])
        out.append(row)
    return out


def pick_best_set_index(sets: list[dict[str, Any]]) -> int:
    """등수 우선(1등>…>5등>미적중), 동등 시 적중 수 많은 세트."""
    if not sets:
        return 0

    def sort_key(s: dict[str, Any]) -> tuple[int, int]:
        tr = int(s.get("tier_rank") or 0)
        if tr == 0:
            tr = 99
        return (tr, -int(s.get("matched_count") or 0))

    return min(range(len(sets)), key=lambda i: sort_key(sets[i]))


def best_tier_from_sets(sets: list[dict[str, Any]]) -> dict[str, Any]:
    """세트 목록에서 최고 등수 요약."""
    if not sets:
        return {"tier_rank": 0, "tier_label": "미적중", "matched_count": 0, "bonus_matched": 0}
    idx = pick_best_set_index(sets)
    s = sets[idx]
    return {
        "tier_rank": int(s.get("tier_rank") or 0),
        "tier_label": s.get("tier_label") or "미적중",
        "matched_count": int(s.get("matched_count") or 0),
        "bonus_matched": int(s.get("bonus_matched") or 0),
        "best_set_no": int(s.get("set_no") or idx + 1),
    }
