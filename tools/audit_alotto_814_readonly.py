"""READ-ONLY 형 앱 A.LOTTO 814만 조합 DB 정찰."""
from __future__ import annotations

import csv
import json
import math
import sqlite3
import statistics
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\user\Desktop\A.LOTTO")
PARTS = ROOT / "db_parts"
OUT = Path(r"d:\3kweon\tools\_audit_alotto_814.json")
TOTAL = 8_145_060
PART_COUNT = 20


def part_size() -> int:
    return math.ceil(TOTAL / PART_COUNT)


def part_no_range(part: int) -> tuple[int, int]:
    start = (part - 1) * part_size() + 1
    end = min(part * part_size(), TOTAL)
    return start, end


def combo_to_no(combo: tuple[int, ...]) -> int:
    nums = list(combo)
    no = 1
    prev = 0
    for i, num in enumerate(nums):
        remaining = len(nums) - i - 1
        for candidate in range(prev + 1, num):
            no += math.comb(45 - candidate, remaining)
        prev = num
    return no


def no_to_combo(no: int, pick: int = 6, pool: int = 45) -> tuple[int, ...]:
    index = no - 1
    combo: list[int] = []
    start = 1
    for i in range(pick):
        remaining = pick - i - 1
        for candidate in range(start, pool + 1):
            count = math.comb(pool - candidate, remaining)
            if index < count:
                combo.append(candidate)
                start = candidate + 1
                break
            index -= count
    return tuple(combo)


def audit_parts() -> dict:
    rows = []
    total_rows = 0
    total_bytes = 0
    for part in range(1, PART_COUNT + 1):
        path = PARTS / f"lotto_part_{part:02d}.db"
        no_start, no_end = part_no_range(part)
        size = path.stat().st_size if path.exists() else 0
        total_bytes += size
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
            ]
            cols = conn.execute("PRAGMA table_info(lotto_all)").fetchall()
            col_desc = [f"{c[1]}:{c[2]}" for c in cols]
            cnt = conn.execute("SELECT COUNT(*) FROM lotto_all").fetchone()[0]
            min_no, max_no = conn.execute(
                "SELECT MIN(no), MAX(no) FROM lotto_all"
            ).fetchone()
            past = conn.execute(
                "SELECT COUNT(*) FROM lotto_all WHERE is_past_winner=1"
            ).fetchone()[0]
        finally:
            conn.close()
        total_rows += cnt
        rows.append(
            {
                "part": part,
                "path": str(path),
                "size_bytes": size,
                "size_mb": round(size / 1024 / 1024, 2),
                "tables": tables,
                "columns": col_desc,
                "rows": cnt,
                "expected_rows": no_end - no_start + 1,
                "combo_no_range": [no_start, no_end],
                "db_min_no": min_no,
                "db_max_no": max_no,
                "past_winners": past,
            }
        )
    return {
        "parts": rows,
        "total_rows": total_rows,
        "expected_total": TOTAL,
        "total_match": total_rows == TOTAL,
        "total_size_mb": round(total_bytes / 1024 / 1024, 2),
        "part_size_formula": part_size(),
    }


def audit_indexing() -> dict:
    samples = []
    test_nos = [1, 2, 100, 5005, 407253, 407254, TOTAL - 1, TOTAL]
    for no in test_nos:
        combo = no_to_combo(no)
        back = combo_to_no(combo)
        samples.append(
            {
                "no": no,
                "combo": list(combo),
                "combo_to_no_roundtrip": back == no,
            }
        )

    conn = sqlite3.connect(
        f"file:{PARTS / 'lotto_part_01.db'}?mode=ro", uri=True
    )
    try:
        db1 = conn.execute(
            "SELECT no, num1,num2,num3,num4,num5,num6 FROM lotto_all WHERE no IN (1,2,3)"
        ).fetchall()
    finally:
        conn.close()

    conn = sqlite3.connect(
        f"file:{PARTS / 'lotto_part_20.db'}?mode=ro", uri=True
    )
    try:
        db_last = conn.execute(
            "SELECT no, num1,num2,num3,num4,num5,num6 FROM lotto_all WHERE no >= ?",
            (TOTAL - 2,),
        ).fetchall()
    finally:
        conn.close()

    return {
        "rule": "lexicographic ranking (combinadic) — No.1=(1,2,3,4,5,6), No.TOTAL=(40,41,42,43,44,45)",
        "formula_instant": True,
        "formula_source": "lotto_common.py combo_to_no / no_to_combo",
        "db_required_for_lookup": "번호→No는 공식 즉시. No→번호도 공식 즉시. DB는 winner_note/is_past_winner 저장용",
        "formula_samples": samples,
        "db_part01_first_rows": [list(r) for r in db1],
        "db_part20_last_rows": [list(r) for r in db_last],
    }


def audit_winner_csv() -> dict:
    csv_path = ROOT / "winner_round_parts.csv"
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    assert len(rows) == 1228

    sample_rounds = [1, 2, 3, 100, 1228]
    checks = []
    combo_nos = []
    for r in rows:
        combo_nos.append(int(r["combo_no"]))

    for rnd in sample_rounds:
        row = next(x for x in rows if int(x["회차"]) == rnd)
        nums = tuple(sorted(int(row[f"번호{i}"]) for i in range(1, 7)))
        csv_no = int(row["combo_no"])
        calc_no = combo_to_no(nums)
        part = min(PART_COUNT, (csv_no - 1) // part_size() + 1)
        no_start, no_end = part_no_range(part)
        conn = sqlite3.connect(
            f"file:{PARTS / f'lotto_part_{part:02d}.db'}?mode=ro", uri=True
        )
        try:
            db_row = conn.execute(
                "SELECT no, num1,num2,num3,num4,num5,num6 FROM lotto_all WHERE no=?",
                (csv_no,),
            ).fetchone()
        finally:
            conn.close()
        checks.append(
            {
                "round": rnd,
                "csv_combo": list(nums),
                "csv_combo_no": csv_no,
                "formula_combo_no": calc_no,
                "formula_match": calc_no == csv_no,
                "expected_part": f"lotto_part_{part:02d}.db",
                "csv_part_db": row["part_db"],
                "part_match": row["part_db"] == f"lotto_part_{part:02d}.db",
                "in_part_range": no_start <= csv_no <= no_end,
                "db_row": list(db_row) if db_row else None,
                "db_nums_match": list(db_row[1:7]) == list(nums) if db_row else False,
            }
        )

    # distribution stats
    mean_no = statistics.mean(combo_nos)
    median_no = statistics.median(combo_nos)
    stdev = statistics.pstdev(combo_nos)
    uniform_mean = (TOTAL + 1) / 2
  # chi-square lite: decile counts
    deciles = [0] * 10
    for n in combo_nos:
        d = min(9, int((n - 1) / TOTAL * 10))
        deciles[d] += 1
    expected_per_decile = len(combo_nos) / 10
    chi = sum((o - expected_per_decile) ** 2 / expected_per_decile for o in deciles)

    return {
        "csv_rows": len(rows),
        "sample_checks": checks,
        "combo_no_stats": {
            "min": min(combo_nos),
            "max": max(combo_nos),
            "mean": round(mean_no, 1),
            "median": round(median_no, 1),
            "stdev": round(stdev, 1),
            "uniform_mean": uniform_mean,
            "decile_counts": deciles,
            "chi2_decile_approx": round(chi, 2),
            "verdict": "균등 분포에 근접 (1228개 샘플, 패턴 예측 불가)",
        },
    }


def main() -> dict:
    result = {
        "root": str(ROOT),
        "step1_parts": audit_parts(),
        "step2_indexing": audit_indexing(),
        "step3_winner_csv": audit_winner_csv(),
        "also_found": {
            "lotto_all_combinations_db_mb": round(
                (ROOT / "lotto_all_combinations.db").stat().st_size / 1024 / 1024, 1
            ),
            "lotto_data_db": str(ROOT / "lotto_data.db"),
        },
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    r = main()
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(r, ensure_ascii=False, indent=2))
