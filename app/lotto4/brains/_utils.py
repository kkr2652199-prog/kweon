"""4군 뇌 공통 유틸리티 — draws / 동반출현 / 필터 / 점수 기반 세트 생성."""

from __future__ import annotations

import math
import random
import sqlite3
from collections.abc import Callable
from typing import Any


def load_draws_before(db_path: str, draw_no: int) -> list[dict[str, Any]]:
    """draw_no **이전** 회차 당첨번호만, 오름차순. 반환: [{draw_no, nums: [6개]}]."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT draw_no, num1, num2, num3, num4, num5, num6
            FROM lotto_draws
            WHERE draw_no < ?
            ORDER BY draw_no ASC
            """,
            (draw_no,),
        ).fetchall()
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        try:
            nums = [int(d[f"num{k}"]) for k in range(1, 7)]
        except (KeyError, TypeError, ValueError):
            continue
        out.append({"draw_no": int(d["draw_no"]), "nums": nums})
    return out


def load_cooccur3(db_path: str, top_n: int | None = 100) -> list[tuple[int, int, int, int]]:
    """lotto_cooccur_3. (n1, n2, n3, count). top_n=None 이면 전체 행."""
    conn = sqlite3.connect(db_path)
    try:
        if top_n is None:
            rows = conn.execute(
                """
                SELECT num1, num2, num3, count
                FROM lotto_cooccur_3
                ORDER BY count DESC, num1, num2, num3
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT num1, num2, num3, count
                FROM lotto_cooccur_3
                ORDER BY count DESC, num1, num2, num3
                LIMIT ?
                """,
                (top_n,),
            ).fetchall()
        return [(int(r[0]), int(r[1]), int(r[2]), int(r[3])) for r in rows]
    finally:
        conn.close()


def load_cooccur4(db_path: str, top_n: int | None = 100) -> list[tuple[int, int, int, int, int]]:
    """lotto_cooccur_4. (n1, n2, n3, n4, count). top_n=None 이면 전체 행."""
    conn = sqlite3.connect(db_path)
    try:
        if top_n is None:
            rows = conn.execute(
                """
                SELECT num1, num2, num3, num4, count
                FROM lotto_cooccur_4
                ORDER BY count DESC, num1, num2, num3, num4
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT num1, num2, num3, num4, count
                FROM lotto_cooccur_4
                ORDER BY count DESC, num1, num2, num3, num4
                LIMIT ?
                """,
                (top_n,),
            ).fetchall()
        return [(int(r[0]), int(r[1]), int(r[2]), int(r[3]), int(r[4])) for r in rows]
    finally:
        conn.close()


def load_bonus_stats(db_path: str) -> dict[int, int]:
    """lotto_bonus_stats: {bonus_no: total_count}."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT bonus_no, total_count FROM lotto_bonus_stats").fetchall()
        return {int(r[0]): int(r[1] or 0) for r in rows}
    finally:
        conn.close()


def interarrival_gap_mean_std(draws: list[dict[str, Any]]) -> tuple[dict[int, float], dict[int, float]]:
    """번호별 연속 출현 간격(회차 차)의 평균·표준편차 (히스토리 부족 시 완만한 기본값)."""
    by_ball: dict[int, list[int]] = {i: [] for i in range(1, 46)}
    for d in draws:
        dn = int(d["draw_no"])
        for x in d["nums"]:
            xi = int(x)
            if 1 <= xi <= 45:
                by_ball[xi].append(dn)
    mean_g: dict[int, float] = {}
    std_g: dict[int, float] = {}
    for i in range(1, 46):
        t = sorted(by_ball[i])
        if len(t) < 2:
            mean_g[i] = 10.0
            std_g[i] = 5.0
            continue
        gaps = [float(t[j + 1] - t[j]) for j in range(len(t) - 1)]
        m = sum(gaps) / len(gaps)
        if len(gaps) < 2:
            std_g[i] = max(m * 0.5, 1.0)
            mean_g[i] = float(m)
            continue
        var = sum((g - m) ** 2 for g in gaps) / (len(gaps) - 1)
        std = max(float(var**0.5), 1e-6)
        mean_g[i] = float(m)
        std_g[i] = std
    return mean_g, std_g


def z_scores_current_gap(draws: list[dict[str, Any]], draw_no: int) -> dict[int, float]:
    """현재 회차 기준 번호별 간격 z-score (연출현 간격 분포 대비)."""
    mean_g, std_g = interarrival_gap_mean_std(draws)
    last_seen: dict[int, int] = {}
    for d in draws:
        dn = int(d["draw_no"])
        for x in d["nums"]:
            xi = int(x)
            if 1 <= xi <= 45:
                last_seen[xi] = max(last_seen.get(xi, 0), dn)
    out: dict[int, float] = {}
    for i in range(1, 46):
        cg = float(draw_no - last_seen[i] if i in last_seen else draw_no)
        sd = std_g[i]
        if sd <= 1e-9:
            out[i] = 0.0
        else:
            out[i] = (cg - mean_g[i]) / sd
    return out


def predict_sum_range_adaptive(
    draws: list[dict[str, Any]],
    *,
    history: int = 50,
    ma_window: int = 10,
    std_mult: float = 1.0,
    fallback: tuple[int, int] = (100, 175),
) -> tuple[int, int]:
    """최근 당첨 합계의 이동평균·표준편차로 합계 허용 구간 추정."""
    if len(draws) < ma_window:
        return fallback
    sums: list[float] = []
    recent = draws[-history:] if len(draws) >= history else draws
    for d in recent:
        nums = [int(x) for x in d["nums"] if 1 <= int(x) <= 45]
        if len(nums) == 6:
            sums.append(float(sum(nums)))
    if len(sums) < ma_window:
        return fallback
    window = sums[-ma_window:]
    center = sum(window) / len(window)
    if len(window) < 2:
        return fallback
    m = center
    var = sum((s - m) ** 2 for s in window) / (len(window) - 1)
    std = float(var**0.5)
    lo = int(round(center - std_mult * std))
    hi = int(round(center + std_mult * std))
    lo = max(21, min(lo, 255))
    hi = max(21, min(hi, 255))
    if hi - lo < 15:
        mid = (lo + hi) // 2
        lo, hi = mid - 8, mid + 8
        lo = max(21, lo)
        hi = min(255, hi)
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi


def load_number_freq(db_path: str) -> dict[int, int]:
    """lotto_number_freq: {number: total_count}."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT number, total_count FROM lotto_number_freq").fetchall()
        return {int(r[0]): int(r[1] or 0) for r in rows}
    finally:
        conn.close()


def sum_filter(nums: list[int], lo: int = 100, hi: int = 175) -> bool:
    s = sum(nums)
    return lo <= s <= hi


def odd_even_filter(nums: list[int], min_odd: int = 1, min_even: int = 1) -> bool:
    """0:6 / 6:0 배제 → 각각 최소 1개 이상."""
    odd = sum(1 for x in nums if x % 2 == 1)
    even = len(nums) - odd
    return odd >= min_odd and even >= min_even


def jaccard(a: set[int], b: set[int]) -> float:
    u = len(a | b)
    return len(a & b) / u if u else 0.0


def _weighted_draw_without_replacement(
    rng: random.Random, weights: dict[int, float], n_pick: int
) -> list[int]:
    picked: list[int] = []
    for _ in range(n_pick):
        avail = {
            k: float(v)
            for k, v in weights.items()
            if k not in picked and 1 <= int(k) <= 45 and float(v) > 0
        }
        if not avail:
            break
        tot = sum(avail.values())
        r = rng.random() * tot
        acc = 0.0
        for k in sorted(avail.keys()):
            acc += avail[k]
            if r <= acc:
                picked.append(k)
                break
    return sorted(picked)


def _random_valid_combo(
    rng: random.Random,
    existing: list[list[int]],
    n_pick: int,
    sum_range: tuple[int, int],
    jaccard_limit: float,
    odd_range: tuple[int, int] | None = None,
    extra_accept: Callable[[list[int]], bool] | None = None,
) -> list[int] | None:
    for _ in range(300):
        cand = sorted(rng.sample(range(1, 46), n_pick))
        if not sum_filter(cand, sum_range[0], sum_range[1]):
            continue
        oddc = sum(1 for x in cand if x % 2 == 1)
        if odd_range is not None:
            lo_o, hi_o = odd_range
            if not (lo_o <= oddc <= hi_o):
                continue
        elif not odd_even_filter(cand):
            continue
        if extra_accept is not None and not extra_accept(cand):
            continue
        st = set(cand)
        if any(jaccard(st, set(p)) >= jaccard_limit for p in existing):
            continue
        return cand
    return None


SMART_RETRY_SOFT = 150


def generate_sets_with_filters(
    score_dict: dict[int, float],
    n_sets: int = 5,
    n_pick: int = 6,
    sum_range: tuple[int, int] = (100, 175),
    jaccard_limit: float = 0.5,
    max_retry: int = 200,
    rng: random.Random | None = None,
    odd_range: tuple[int, int] | None = None,
    extra_accept: Callable[[list[int]], bool] | None = None,
    *,
    smart_filter_mode: str = "strict",
) -> list[list[int]]:
    """스마트필터: smart_filter_mode strict | relaxed | off."""
    rng = rng or random.Random()
    base = {i: max(float(score_dict.get(i, 0.0)), 0.0) for i in range(1, 46)}
    lo = min(base.values())
    if lo < 0:
        base = {k: v - lo + 1e-9 for k, v in base.items()}
    tot_mass = sum(base.values())
    if tot_mass <= 0:
        base = {i: 1.0 for i in range(1, 46)}

    use_smart = smart_filter_mode != "off"

    sets: list[list[int]] = []
    for _ in range(n_sets):
        cand: list[int] | None = None
        if not use_smart:
            phases: list[tuple[str, int]] = [("off", max_retry)]
        elif smart_filter_mode == "relaxed":
            phases = [("relaxed", max_retry + SMART_RETRY_SOFT)]
        else:
            phases = [("strict", max_retry), ("soft", SMART_RETRY_SOFT)]

        for phase_name, lim in phases:
            if cand is not None:
                break
            for _r in range(lim):
                cand_try = _weighted_draw_without_replacement(rng, base, n_pick)
                if len(cand_try) != n_pick:
                    continue
                if not sum_filter(cand_try, sum_range[0], sum_range[1]):
                    continue
                oddc = sum(1 for x in cand_try if x % 2 == 1)
                if odd_range is not None:
                    lo_o, hi_o = odd_range
                    if not (lo_o <= oddc <= hi_o):
                        continue
                elif not odd_even_filter(cand_try):
                    continue
                if extra_accept is not None and not extra_accept(cand_try):
                    continue
                st = set(cand_try)
                if any(jaccard(st, set(p)) >= jaccard_limit for p in sets):
                    continue
                if use_smart:
                    if phase_name == "strict" and not smart_filter(cand_try):
                        continue
                    if phase_name in ("soft", "relaxed") and not smart_filter_relaxed(cand_try):
                        continue
                cand = cand_try
                break

        if cand is None:
            for _ in range(300):
                cand_rc = _random_valid_combo(
                    rng,
                    sets,
                    n_pick,
                    sum_range,
                    jaccard_limit,
                    odd_range=odd_range,
                    extra_accept=extra_accept,
                )
                if cand_rc is None:
                    break
                if use_smart and not smart_filter_relaxed(cand_rc):
                    continue
                cand = cand_rc
                break
        if cand is None:
            break
        sets.append(sorted(cand))
    return sets


def calc_ac_value(nums: list[int]) -> int:
    """AC값: 6개 번호 쌍 차이의 서로 다른 값 개수 − 5."""
    diffs: set[int] = set()
    sorted_nums = sorted(nums)
    for i in range(len(sorted_nums)):
        for j in range(i + 1, len(sorted_nums)):
            diffs.add(sorted_nums[j] - sorted_nums[i])
    return len(diffs) - 5


def calc_tail_sum(nums: list[int]) -> int:
    return sum(n % 10 for n in nums)


def count_consecutive(nums: list[int]) -> int:
    sorted_nums = sorted(nums)
    c = 0
    for i in range(len(sorted_nums) - 1):
        if sorted_nums[i + 1] - sorted_nums[i] == 1:
            c += 1
    return c


def count_same_decade(nums: list[int]) -> int:
    decades: dict[int, int] = {}
    for n in nums:
        d = (n - 1) // 10
        decades[d] = decades.get(d, 0) + 1
    return max(decades.values()) if decades else 0


_PRIMES_45 = frozenset({2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43})


def count_primes(nums: list[int]) -> int:
    return sum(1 for n in nums if n in _PRIMES_45)


_DOUBLES = frozenset({11, 22, 33, 44})


def count_doubles(nums: list[int]) -> int:
    return sum(1 for n in nums if n in _DOUBLES)


def smart_filter(nums: list[int]) -> bool:
    """7대 스마트 필터 (엄격)."""
    s = sorted(nums)
    if len(s) != 6 or len(set(s)) != 6:
        return False
    total = sum(s)
    odd_count = sum(1 for n in s if n % 2 == 1)
    if not (100 <= total <= 175):
        return False
    if not (2 <= odd_count <= 4):
        return False
    if calc_ac_value(s) < 7:
        return False
    tail_sum = calc_tail_sum(s)
    if not (15 <= tail_sum <= 38):
        return False
    if count_consecutive(s) > 2:
        return False
    if count_same_decade(s) > 3:
        return False
    if s[0] >= 14 or s[-1] <= 30:
        return False
    if count_primes(s) > 3:
        return False
    if count_doubles(s) > 2:
        return False
    return True


def smart_filter_relaxed(nums: list[int]) -> bool:
    """스마트 필터 완화: 끝수합·소수 개수만 완화 (나머지 동일)."""
    s = sorted(nums)
    if len(s) != 6 or len(set(s)) != 6:
        return False
    total = sum(s)
    odd_count = sum(1 for n in s if n % 2 == 1)
    if not (100 <= total <= 175):
        return False
    if not (2 <= odd_count <= 4):
        return False
    if calc_ac_value(s) < 7:
        return False
    tail_sum = calc_tail_sum(s)
    if not (10 <= tail_sum <= 40):
        return False
    if count_consecutive(s) > 2:
        return False
    if count_same_decade(s) > 3:
        return False
    if s[0] >= 14 or s[-1] <= 30:
        return False
    if count_primes(s) > 4:
        return False
    if count_doubles(s) > 2:
        return False
    return True
