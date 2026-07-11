"""lotto_fullbacktest_army4 집계: 뇌별 평균·분포·고적중·안정성 표."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

DB_DEFAULT = str(ROOT / "data" / "lotto4.db")

DISPLAY_ORDER = [
    "v13_ensemble",
    "v13_seq",
    "v13_struct",
    "v13_diversity",
    "v13_gap",
    "v13_ev",
    "v13_evolution",
]


def fetch_rows(conn: sqlite3.Connection, lo: int | None, hi: int | None):
    q = """
        SELECT draw_no, brain_tag, set_no, matched_count, bonus_matched, numbers
        FROM lotto_fullbacktest_army4
        WHERE matched_count >= 0
    """
    params: list[int] = []
    if lo is not None:
        q += " AND draw_no >= ?"
        params.append(lo)
    if hi is not None:
        q += " AND draw_no <= ?"
        params.append(hi)
    q += " ORDER BY brain_tag, draw_no, set_no"
    return conn.execute(q, params).fetchall()


def summarize(rows) -> dict[str, dict]:
    by_tag: dict[str, list[tuple]] = defaultdict(list)
    for r in rows:
        by_tag[str(r[1])].append(r)

    out: dict[str, dict] = {}
    for tag, lst in by_tag.items():
        mcs = [int(x[3]) for x in lst]
        dist = {k: 0 for k in range(7)}
        for m in mcs:
            if 0 <= m <= 6:
                dist[m] += 1
        n = len(mcs)
        avg = sum(mcs) / n if n else 0.0
        ge4 = sum(1 for m in mcs if m >= 4)
        ge5 = sum(1 for m in mcs if m >= 5)
        c6 = sum(1 for m in mcs if m == 6)
        c5 = sum(1 for m in mcs if m == 5)
        c5b = sum(
            1
            for x in lst
            if int(x[3]) == 5 and int(x[4] or 0) == 1
        )
        mx = max(mcs) if mcs else 0

        best_per_draw: dict[int, int] = {}
        for draw_no, _, _, mc, _, _ in lst:
            d = int(draw_no)
            best_per_draw[d] = max(best_per_draw.get(d, 0), int(mc))
        draws = list(best_per_draw.values())
        best_avg = sum(draws) / len(draws) if draws else 0.0
        ge3 = sum(1 for m in mcs if m >= 3)
        consistency = (ge3 / n * 100) if n else 0.0

        out[tag] = {
            "n_sets": n,
            "avg": avg,
            "dist": dist,
            "high4p": (ge4 / n * 100) if n else 0.0,
            "high5p": (ge5 / n * 100) if n else 0.0,
            "c6": c6,
            "c5b": c5b,
            "c5": c5,
            "max": mx,
            "best_avg": best_avg,
            "consistency": consistency,
        }
    return out


def print_table(sums: dict[str, dict], title: str) -> None:
    print(title)
    hdr = (
        "| 뇌 | avg | 분포(0/1/2/3/4/5/6) | 4+% | 5+% | 6적중 | 5+B | 5적중 | max | best_avg | 안정성 |"
    )
    sep = "|----|-----|----------------------|-----|-----|-------|-----|-------|-----|----------|--------|"
    print(hdr)
    print(sep)
    tags = [t for t in DISPLAY_ORDER if t in sums] + [
        t for t in sorted(sums.keys()) if t not in DISPLAY_ORDER
    ]
    for tag in tags:
        s = sums[tag]
        d = s["dist"]
        dist_s = "/".join(str(d[i]) for i in range(7))
        print(
            f"| {tag} | {s['avg']:.4f} | {dist_s} | {s['high4p']:.2f}% | "
            f"{s['high5p']:.2f}% | {s['c6']} | {s['c5b']} | {s['c5']} | {s['max']} | "
            f"{s['best_avg']:.4f} | {s['consistency']:.2f}% |"
        )


def print_summary_markdown(sums: dict[str, dict]) -> None:
    print()
    print("### 성적표 (세트수·분포·4+%·5+%)")
    print()
    print("| 뇌 | 세트수 | avg | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 4+% | 5+% | max |")
    print("|----|--------|-----|---|---|---|---|---|---|---|-----|-----|-----|")
    tags = [t for t in DISPLAY_ORDER if t in sums] + [
        t for t in sorted(sums.keys()) if t not in DISPLAY_ORDER
    ]
    for tag in tags:
        s = sums[tag]
        d = s["dist"]
        print(
            f"| {tag} | {s['n_sets']} | {s['avg']:.4f} | "
            f"{d[0]} | {d[1]} | {d[2]} | {d[3]} | {d[4]} | {d[5]} | {d[6]} | "
            f"{s['high4p']:.2f}% | {s['high5p']:.2f}% | {s['max']} |"
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB_DEFAULT)
    ap.add_argument("--from", dest="lo", type=int, default=None)
    ap.add_argument("--to", dest="hi", type=int, default=None)
    args = ap.parse_args()

    conn = sqlite3.connect(os.path.abspath(args.db))
    try:
        rows = fetch_rows(conn, args.lo, args.hi)
    finally:
        conn.close()

    if not rows:
        print("lotto_fullbacktest_army4 에 해당 구간 데이터가 없습니다.")
        return

    sums = summarize(rows)
    lo = args.lo if args.lo is not None else min(int(r[0]) for r in rows)
    hi = args.hi if args.hi is not None else max(int(r[0]) for r in rows)
    print_table(sums, f"### 구간 draw {lo}~{hi} ({len(rows)}행)")
    print_summary_markdown(sums)

    conn = sqlite3.connect(os.path.abspath(args.db))
    try:
        conds = ["matched_count >= 5", "matched_count >= 0"]
        qparams: list[int] = []
        if args.lo is not None:
            conds.append("draw_no >= ?")
            qparams.append(int(args.lo))
        if args.hi is not None:
            conds.append("draw_no <= ?")
            qparams.append(int(args.hi))
        where = " AND ".join(conds)
        hi_rows = conn.execute(
            f"""
            SELECT draw_no, brain_tag, set_no, numbers, matched_count,
                   matched_numbers, bonus_matched
            FROM lotto_fullbacktest_army4
            WHERE {where}
            ORDER BY matched_count DESC, draw_no, brain_tag, set_no
            """,
            qparams,
        ).fetchall()
    finally:
        conn.close()

    if hi_rows:
        print()
        print("### 5개 이상 적중 세트 (전부)")
        for r in hi_rows:
            print(
                f"  draw={r[0]} tag={r[1]} set={r[2]} nums={r[3]} "
                f"mc={r[4]} hits={r[5]} bonus={r[6]}"
            )


if __name__ == "__main__":
    main()
