"""4군 v13_offset: 출현 간격 분포·자기상관 기반 예측 (워크포워드 전제).

`predict_run`과 다른 통계 특성만 사용 (연속 run 금지). 파이프라인 호환 `nums` 키.
"""
from __future__ import annotations

import numpy as np

from app.lotto4.legacy.v13_models import V13_WIN_AVOID_N, get_recent_winning_sets, v13_pass_win_avoid

# 가중치: run과 겹치는「현재/평균 offset 비」항목은 점수에서 제외, 간격 분포·자기상관 중심
_GAMMA_A = 0.18  # 분산(규칙성)
_GAMMA_B = 0.12  # 중앙값/평균
_GAMMA_C = 0.28  # IQR
_DELTA_D = 0.37  # 간격 lag-1 자기상관
_DELTA_SKEW = 0.05  # 간격 왜도(3차 모멘트, numpy만 사용)


def _six_from_draw(d: dict) -> list[int] | None:
    """회차 dict에서 당첨 6개 정렬 리스트 추출."""
    try:
        xs = [int(d[f"num{i}"]) for i in range(1, 7)]
        return sorted(xs)
    except (KeyError, TypeError, ValueError):
        return None


def _rng_seed_from_tail(training: list[dict]) -> int:
    """최근 10회차 (draw_no + 6번호) 해시 — 결정성."""
    tail = training[-10:]
    key_tuples: list[tuple[int, int, int, int, int, int, int]] = []
    for d in tail:
        nums = _six_from_draw(d)
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
    return int(seed)


def _gap_autocorr_lag1(gaps: np.ndarray) -> float:
    """간격 시퀀스 lag-1 피어슨 상관. 표본·분산 부족 시 0."""
    if gaps.size < 3:
        return 0.0
    a = gaps[:-1].astype(np.float64)
    b = gaps[1:].astype(np.float64)
    c = np.corrcoef(a, b)[0, 1]
    if not np.isfinite(c):
        return 0.0
    return float(np.clip(c, -1.0, 1.0))


def army4_offset_predict(
    training: list[dict],
    n_sets: int = 5,
    target_draw_no: int | None = None,
) -> list[dict]:
    """간격 분산·IQR·중앙/평균·lag-1 자기상관·간격 왜도로 후보 점수화.

    예측 대상 회차는 인자로 받지 않음 — 학습 구간은 호출자가 워크포워드로만 넘길 것.
    """
    if not training or n_sets <= 0:
        return []

    rng = np.random.default_rng(_rng_seed_from_tail(training))

    draws: list[list[int]] = []
    for d in training:
        s = _six_from_draw(d)
        if s is not None and len(s) == 6:
            draws.append(s)
    if not draws:
        return []

    appear: list[list[int]] = [[] for _ in range(46)]
    for idx, nums in enumerate(draws):
        for x in nums:
            if 1 <= x <= 45:
                appear[x].append(idx)

    var_raw = np.zeros(45, dtype=np.float64)
    iqr_raw = np.zeros(45, dtype=np.float64)
    med_ratio = np.zeros(45, dtype=np.float64)
    ac_raw = np.zeros(45, dtype=np.float64)
    skew_raw = np.zeros(45, dtype=np.float64)

    for n in range(1, 46):
        idxs = appear[n]
        if not idxs:
            var_raw[n - 1] = 0.0
            iqr_raw[n - 1] = 0.0
            med_ratio[n - 1] = 0.5
            ac_raw[n - 1] = 0.0
            skew_raw[n - 1] = 0.0
            continue
        if len(idxs) == 1:
            gaps = np.array([], dtype=np.float64)
        else:
            gaps = np.diff(np.array(idxs, dtype=np.float64))
        if gaps.size >= 2:
            var_raw[n - 1] = float(np.var(gaps))
            q1, q3 = np.percentile(gaps, [25, 75])
            iqr_raw[n - 1] = float(max(0.0, q3 - q1))
            med = float(np.median(gaps))
            mu = float(np.mean(gaps))
            med_ratio[n - 1] = med / mu if mu > 1e-9 else 0.5
            ac_raw[n - 1] = _gap_autocorr_lag1(gaps)
            if gaps.size >= 3:
                sd_g = float(np.std(gaps))
                if sd_g > 1e-9:
                    skew_raw[n - 1] = float(np.mean(((gaps - mu) / sd_g) ** 3))
        else:
            var_raw[n - 1] = 0.0
            iqr_raw[n - 1] = 0.0
            med_ratio[n - 1] = 0.5
            ac_raw[n - 1] = 0.0
            skew_raw[n - 1] = 0.0

    max_var = float(np.max(var_raw)) if np.any(var_raw > 0) else 1.0
    if max_var <= 0:
        max_var = 1.0
    max_iqr = float(np.max(iqr_raw)) if np.any(iqr_raw > 0) else 1.0
    if max_iqr <= 0:
        max_iqr = 1.0
    max_sk = float(np.max(np.abs(skew_raw))) if np.any(np.abs(skew_raw) > 1e-12) else 1.0
    if max_sk <= 0:
        max_sk = 1.0

    scores = np.zeros(45, dtype=np.float64)
    for i in range(45):
        v_norm = min(var_raw[i] / max_var, 1.0)
        reg_a = 1.0 - v_norm
        mr = med_ratio[i]
        stab_b = 1.0 / (1.0 + abs(1.0 - mr))
        iqr_n = min(iqr_raw[i] / max_iqr, 1.0)
        tight_c = 1.0 - iqr_n
        ac_comp = (ac_raw[i] + 1.0) * 0.5
        sk_n = min(abs(skew_raw[i]) / max_sk, 1.0)
        scores[i] = (
            _GAMMA_A * reg_a
            + _GAMMA_B * stab_b
            + _GAMMA_C * tight_c
            + _DELTA_D * ac_comp
            + _DELTA_SKEW * sk_n
        )

    # 후보 15: 상위 8 + 나머지 37개 중 자기상관 상위 7 (run의 단순 offset 순위와 분리)
    by_score = sorted(range(1, 46), key=lambda x: (-scores[x - 1], x))
    pool8 = by_score[:8]
    rest = [n for n in range(1, 46) if n not in pool8]
    by_ac = sorted(rest, key=lambda x: (-ac_raw[x - 1], -skew_raw[x - 1], x))
    pool15 = pool8 + by_ac[:7]

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
                "brain_tag": "v13_offset",
                "confidence": conf,
                "method": "🎼 리듬분석가",
                "reasoning": "interval_distribution",
            }
        )
    return out
