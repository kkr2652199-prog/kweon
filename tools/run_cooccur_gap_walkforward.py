"""동반출현/출현간격 패턴 walk-forward 예측력 검증 (4군 정찰)."""
from __future__ import annotations

import json
import math
import random
import sqlite3
import statistics
from collections import defaultdict
from itertools import combinations
from pathlib import Path

DB = Path(r"d:\3kweon\data\lotto4.db")
OUT = Path(r"d:\3kweon\tools\_cooccur_gap_backtest.json")
BASELINE = 0.7894
DRAW_MIN = 6
DRAW_MAX = 1225
SETS_PER_DRAW = 5


def load_draws(conn: sqlite3.Connection) -> dict[int, list[int]]:
    rows = conn.execute(
        """
        SELECT draw_no, num1, num2, num3, num4, num5, num6
        FROM lotto4_winners
        WHERE draw_no BETWEEN 1 AND ?
        ORDER BY draw_no
        """,
        (DRAW_MAX,),
    ).fetchall()
    return {r[0]: [r[1], r[2], r[3], r[4], r[5], r[6]] for r in rows}


def score_sets(sets: list[list[int]], actual: list[int]) -> list[int]:
    actual_set = set(actual)
    return [len(set(s) & actual_set) for s in sets]


def fill_to_six(nums: set[int], pair_counts: dict[tuple[int, int], int]) -> list[int]:
    if len(nums) >= 6:
        return sorted(nums)[:6]
    freq: dict[int, int] = defaultdict(int)
    for (a, b), c in pair_counts.items():
        freq[a] += c
        freq[b] += c
    for n, _ in sorted(freq.items(), key=lambda x: (-x[1], x[0])):
        nums.add(n)
        if len(nums) >= 6:
            break
    for n in range(1, 46):
        if len(nums) >= 6:
            break
        nums.add(n)
    return sorted(nums)[:6]


def gen_cooccur_sets(pair_counts: dict[tuple[int, int], int], k: int = SETS_PER_DRAW) -> list[list[int]]:
    if not pair_counts:
        rng = random.Random(0)
        return [sorted(rng.sample(range(1, 46), 6)) for _ in range(k)]
    sorted_pairs = sorted(pair_counts.items(), key=lambda x: (-x[1], x[0][0], x[0][1]))
    out: list[list[int]] = []
    for s_idx in range(k):
        nums: set[int] = set()
        idx = s_idx
        step = max(1, len(sorted_pairs) // k)
        while len(nums) < 6 and idx < len(sorted_pairs):
            a, b = sorted_pairs[idx][0]
            nums.add(a)
            nums.add(b)
            idx += step
        if len(nums) < 6:
            idx = 0
            while len(nums) < 6 and idx < len(sorted_pairs):
                a, b = sorted_pairs[idx][0]
                nums.add(a)
                nums.add(b)
                idx += 1
        out.append(fill_to_six(nums, pair_counts))
    return out


def gen_gap_sets(
    last_seen: dict[int, int],
    gap_history: dict[int, list[int]],
    target_draw: int,
    k: int = SETS_PER_DRAW,
) -> list[list[int]]:
    scores: list[tuple[float, int, int]] = []
    for num in range(1, 46):
        if num in last_seen:
            overdue = target_draw - last_seen[num] - 1
            avg_gap = statistics.mean(gap_history[num]) if gap_history[num] else float(overdue)
        else:
            overdue = target_draw - 1
            avg_gap = float(target_draw)
        ratio = overdue / avg_gap if avg_gap > 0 else float(overdue)
        scores.append((ratio, overdue, num))
    scores.sort(key=lambda x: (-x[0], -x[1], x[2]))
    ranked = [x[2] for x in scores]
    out: list[list[int]] = []
    for s_idx in range(k):
        pick: list[int] = []
        i = s_idx
        while len(pick) < 6 and i < len(ranked):
            n = ranked[i]
            if n not in pick:
                pick.append(n)
            i += 1
        if len(pick) < 6:
            for n in ranked:
                if n not in pick:
                    pick.append(n)
                if len(pick) >= 6:
                    break
        out.append(sorted(pick[:6]))
    return out


def gen_random_sets(target_draw: int, k: int = SETS_PER_DRAW) -> list[list[int]]:
    out: list[list[int]] = []
    for s_idx in range(k):
        rng = random.Random(target_draw * 1000 + s_idx)
        out.append(sorted(rng.sample(range(1, 46), 6)))
    return out


def summarize(matches: list[int]) -> dict:
    n = len(matches)
    avg = sum(matches) / n if n else 0.0
    return {
        "n_predictions": n,
        "avg_matched": round(avg, 4),
        "std_matched": round(statistics.pstdev(matches), 4) if n > 1 else 0.0,
        "max_matched": max(matches) if matches else 0,
        "hit4_plus": sum(1 for m in matches if m >= 4),
        "hit6": sum(1 for m in matches if m == 6),
        "delta_vs_baseline": round(avg - BASELINE, 4),
    }


def add_draw_to_history(
    draw_no: int,
    nums: list[int],
    pair_counts: dict[tuple[int, int], int],
    last_seen: dict[int, int],
    gap_history: dict[int, list[int]],
) -> None:
    for a, b in combinations(sorted(nums), 2):
        pair_counts[(a, b)] += 1
    for num in nums:
        if num in last_seen:
            gap_history[num].append(draw_no - last_seen[num])
        last_seen[num] = draw_no


def run_backtest(draws: dict[int, list[int]]) -> dict:
    pair_counts: dict[tuple[int, int], int] = defaultdict(int)
    last_seen: dict[int, int] = {}
    gap_history: dict[int, list[int]] = defaultdict(list)

    cooccur_matches: list[int] = []
    gap_matches: list[int] = []
    random_matches: list[int] = []

    # draw_no < DRAW_MIN 선적재 (회차 6 예측 시 1~5만 사용)
    for d in range(1, DRAW_MIN):
        if d in draws:
            add_draw_to_history(d, draws[d], pair_counts, last_seen, gap_history)

    for target in range(DRAW_MIN, DRAW_MAX + 1):
        if target not in draws:
            continue
        actual = draws[target]

        co_sets = gen_cooccur_sets(pair_counts)
        ga_sets = gen_gap_sets(last_seen, gap_history, target)
        ra_sets = gen_random_sets(target)

        cooccur_matches.extend(score_sets(co_sets, actual))
        gap_matches.extend(score_sets(ga_sets, actual))
        random_matches.extend(score_sets(ra_sets, actual))

        add_draw_to_history(target, actual, pair_counts, last_seen, gap_history)

    co_sum = summarize(cooccur_matches)
    ga_sum = summarize(gap_matches)
    ra_sum = summarize(random_matches)

    return {
        "range": f"{DRAW_MIN}~{DRAW_MAX}",
        "draws_tested": DRAW_MAX - DRAW_MIN + 1,
        "sets_per_draw": SETS_PER_DRAW,
        "baseline_theory": BASELINE,
        "cooccur": co_sum,
        "gap": ga_sum,
        "random": ra_sum,
        "cooccur_minus_random": round(co_sum["avg_matched"] - ra_sum["avg_matched"], 4),
        "gap_minus_random": round(ga_sum["avg_matched"] - ra_sum["avg_matched"], 4),
        "cooccur_minus_baseline": co_sum["delta_vs_baseline"],
        "gap_minus_baseline": ga_sum["delta_vs_baseline"],
        "random_minus_baseline": ra_sum["delta_vs_baseline"],
    }


def verdict(result: dict) -> dict:
    THRESH = 0.05

    def judge(name: str, avg: float, vs_random: float, vs_base: float) -> str:
        if abs(vs_random) <= THRESH and abs(vs_base) <= THRESH:
            return f"❌ {name}: 패턴 존재하나 예측력 없음 (무작위 수준, Δrandom={vs_random:+.4f})"
        if vs_random > THRESH or vs_base > THRESH:
            return f"✅ {name}: 예측 신호 발견 (avg={avg:.4f}, Δrandom={vs_random:+.4f}, Δbaseline={vs_base:+.4f})"
        return f"❌ {name}: 랜덤/기준선 이하 (avg={avg:.4f}, Δrandom={vs_random:+.4f})"

    return {
        "cooccur": judge("쌍 동반출현", result["cooccur"]["avg_matched"], result["cooccur_minus_random"], result["cooccur_minus_baseline"]),
        "gap": judge("출현간격", result["gap"]["avg_matched"], result["gap_minus_random"], result["gap_minus_baseline"]),
        "threshold": THRESH,
    }


def main() -> None:
    conn = sqlite3.connect(DB)
    try:
        draws = load_draws(conn)
        result = run_backtest(draws)
        result["verdict"] = verdict(result)
        OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
