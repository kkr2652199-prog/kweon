"""패턴돋보기 — 쌍수·연속수·AC값 (SELMA consecutive + pair 벤치마킹)."""

from __future__ import annotations

from app.testlotto.features.draw_features import ac_value, build_pair_freq, combo_features, consecutive_pairs, pair_set


def score_set(nums: list[int], draws: list[dict], target_draw_no: int) -> float:
    feats = combo_features(nums, draws)
    pair_freq = build_pair_freq(draws)
    pairs = pair_set(nums)
    pair_score = sum(pair_freq.get(p, 0) for p in pairs)
    pair_norm = min(1.0, pair_score / 30.0)
    consec = feats["consecutive"]
    ac = feats["ac"]
    ac_target = 7
    ac_score = 1.0 - min(1.0, abs(ac - ac_target) / 10.0)
    consec_score = 0.7 if consec in (0, 1) else (0.5 if consec == 2 else 0.3)
    return max(0.1, min(1.0, 0.4 * pair_norm + 0.35 * ac_score + 0.25 * consec_score))


def describe(nums: list[int], draws: list[dict], target_draw_no: int) -> str:
    feats = combo_features(nums, draws)
    return f"패턴돋보기:AC{feats['ac']} 연속{feats['consecutive']} 점수{score_set(nums, draws, target_draw_no):.2f}"
