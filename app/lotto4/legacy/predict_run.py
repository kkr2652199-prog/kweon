"""4군 v13_run: 연속 출현(run) 통계 기반 예측 (워크포워드 전제, 호출자가 training만 전달).

출력은 v13_engine 파이프라인과 동일하게 `nums` 키 사용 (INSERT/합의 호환).
"""
from __future__ import annotations

import numpy as np

from app.lotto4.legacy.v13_models import V13_WIN_AVOID_N, get_recent_winning_sets, v13_pass_win_avoid

# run 가중·오프셋 보정 (지시서 α, β)
_ALPHA_RUN = 0.6
_BETA_OFFSET = 0.4
_NUM_COLS = 5  # run 길이 2~6 → 5열


def _draw_nums(d: dict) -> list[int] | None:
    try:
        return sorted(
            int(d[k])
            for k in ("num1", "num2", "num3", "num4", "num5", "num6")
        )
    except (KeyError, TypeError, ValueError):
        return None


def _maximal_run_segments(sorted_nums: list[int]) -> list[tuple[list[int], int]]:
    """한 회차 정렬 번호에서 길이>=2 인 최대 연속 구간만 반환."""
    if len(sorted_nums) < 2:
        return []
    runs: list[tuple[list[int], int]] = []
    i = 0
    n = len(sorted_nums)
    while i < n:
        j = i
        while j + 1 < n and sorted_nums[j + 1] - sorted_nums[j] == 1:
            j += 1
        seg = sorted_nums[i : j + 1]
        if len(seg) >= 2:
            runs.append((list(seg), len(seg)))
        i = j + 1
    return runs


def army4_run_predict(
    training: list[dict],
    n_sets: int = 5,
    target_draw_no: int | None = None,
) -> list[dict]:
    """연속 출현(run) 빈도 + 미출현 경과 회차 가중으로 후보를 뽑아 n_sets개 세트 생성.

    예측 대상 회차는 인자로 받지 않음 — 학습 구간은 호출자가 워크포워드로만 넘길 것.
    """
    if not training or n_sets <= 0:
        return []

    # 결정성: 최근 최대 10회차 (draw_no, num1..6) 기반 시드
    tail = training[-10:]
    key_tuples: list[tuple[int, int, int, int, int, int, int]] = []
    for d in tail:
        nums = _draw_nums(d)
        if nums is None:
            continue
        try:
            dn = int(d["draw_no"])
        except (KeyError, TypeError, ValueError):
            dn = 0
        key_tuples.append((dn, *nums))
    seed = hash(tuple(key_tuples)) % (2**32)
    if seed < 0:
        seed += 2**32
    rng = np.random.default_rng(seed)

    draws: list[list[int]] = []
    for d in training:
        nums = _draw_nums(d)
        if nums is not None and len(nums) == 6:
            draws.append(nums)

    if not draws:
        return []

    # 번호별 run 참여 빈도 (45 × 5): 열 k = run 길이 (k+2)
    mat = np.zeros((46, _NUM_COLS), dtype=np.float64)
    last_idx: dict[int, int] = {}

    for idx, nums in enumerate(draws):
        for x in nums:
            last_idx[x] = idx
        for seg, leng in _maximal_run_segments(nums):
            col = min(leng - 2, _NUM_COLS - 1)
            for x in seg:
                if 1 <= x <= 45:
                    mat[x, col] += 1.0

    run_freq = mat[1:46].sum(axis=1)
    max_rf = float(run_freq.max()) if run_freq.size else 0.0
    last_draw_i = len(draws) - 1
    offsets = np.zeros(45, dtype=np.float64)
    for n in range(1, 46):
        if n in last_idx:
            offsets[n - 1] = float(last_draw_i - last_idx[n])
        else:
            offsets[n - 1] = float(len(draws))

    avg_off = float(offsets.mean()) if offsets.size else 1.0
    if avg_off <= 0:
        avg_off = 1.0

    scores = np.zeros(45, dtype=np.float64)
    for i in range(45):
        rfn = float(run_freq[i]) / max_rf if max_rf > 0 else 0.0
        ofn = float(offsets[i]) / avg_off
        scores[i] = _ALPHA_RUN * rfn + _BETA_OFFSET * ofn

    ranked_n = sorted(
        range(1, 46),
        key=lambda x: (-scores[x - 1], x),
    )
    pool15 = ranked_n[:15]

    win_sets = (
        get_recent_winning_sets(target_draw_no, V13_WIN_AVOID_N) if target_draw_no else []
    )
    st: dict[str, int | bool] = {"fail_count": 0, "bypass": False}

    out: list[dict] = []
    outer_guard = 0
    while len(out) < n_sets:
        outer_guard += 1
        if outer_guard > 50000:
            break
        pick = rng.choice(len(pool15), size=6, replace=False)
        nums6 = sorted(int(pool15[j]) for j in pick)
        if not v13_pass_win_avoid(nums6, win_sets, st):
            continue
        conf = float(min(0.99, 0.35 + 0.1 * sum(scores[n - 1] for n in nums6)))
        out.append(
            {
                "nums": nums6,
                "brain_tag": "v13_run",
                "confidence": conf,
                "method": "🎯 사냥꾼",
                "reasoning": "run_length_stats+offset",
            }
        )
    return out
