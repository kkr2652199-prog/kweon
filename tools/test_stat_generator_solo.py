"""stat_generator 단독 성능 테스트 (1회성, DB 읽기 전용)."""

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.lotto4.brains.stat_generator import generate_candidates

db_path = os.path.abspath("d:/3kweon/data/lotto4.db")
conn = sqlite3.connect(db_path)

START, END = 1100, 1222
results = []


def struct_score_simple(combo):
    nums = sorted(combo)
    total = sum(nums)
    odd = sum(1 for n in nums if n % 2 == 1)
    high = sum(1 for n in nums if n >= 23)
    score = 0.0
    score += 1.0 - abs(total - 137.5) / 75.0
    score += 1.0 - abs(odd - 3) / 3.0
    score += 1.0 - abs(high - 3) / 3.0
    return score


for draw_no in range(START, END + 1):
    row = conn.execute(
        "SELECT num1,num2,num3,num4,num5,num6 FROM lotto_draws WHERE draw_no=?",
        (draw_no,),
    ).fetchone()
    if not row:
        continue
    actual = set(row)

    candidates = generate_candidates(draw_no, db_path, 200)
    if not candidates:
        continue

    pick_first5 = candidates[:5]
    sorted_by_struct = sorted(candidates, key=struct_score_simple, reverse=True)
    pick_struct5 = sorted_by_struct[:5]
    all_hits = [len(actual & set(c)) for c in candidates]

    hits_first5 = [len(actual & set(c)) for c in pick_first5]
    hits_struct5 = [len(actual & set(c)) for c in pick_struct5]

    results.append(
        {
            "draw": draw_no,
            "actual": sorted(actual),
            "first5_avg": sum(hits_first5) / len(hits_first5),
            "first5_max": max(hits_first5),
            "struct5_avg": sum(hits_struct5) / len(hits_struct5),
            "struct5_max": max(hits_struct5),
            "all200_avg": sum(all_hits) / len(all_hits),
            "all200_max": max(all_hits),
            "all200_hit4plus": sum(1 for h in all_hits if h >= 4),
        }
    )

conn.close()

print("=== stat_generator 단독 성능 (draw {}-{}) ===".format(START, END))
print()

n = len(results)
first5_avg = sum(r["first5_avg"] for r in results) / n
struct5_avg = sum(r["struct5_avg"] for r in results) / n
all200_avg = sum(r["all200_avg"] for r in results) / n
all200_max_max = max(r["all200_max"] for r in results)
all200_hit4_total = sum(r["all200_hit4plus"] for r in results)
first5_hit4 = sum(1 for r in results if r["first5_max"] >= 4)
struct5_hit4 = sum(1 for r in results if r["struct5_max"] >= 4)

print("| 선택 방식 | avg | 4+적중 회차 | max |")
print("|-----------|-----|------------|-----|")
print(
    "| 첫 5세트 (순서) | {:.4f} | {} | {} |".format(
        first5_avg, first5_hit4, max(r["first5_max"] for r in results)
    )
)
print(
    "| 구조점수 상위 5 | {:.4f} | {} | {} |".format(
        struct5_avg, struct5_hit4, max(r["struct5_max"] for r in results)
    )
)
print(
    "| 200세트 전체 | {:.4f} | {} | {} |".format(
        all200_avg, all200_hit4_total, all200_max_max
    )
)
print()
print("비교 기준:")
print("  랜덤 6/45: 0.800")
print("  B안 ensemble: 0.797")
print("  이전 에이스: 0.828")
print("  3군: 1.502")
print()

print("=== 200세트 중 4+ 적중 발생 회차 ===")
for r in results:
    if r["all200_hit4plus"] > 0:
        print(
            "draw {}: 4+적중 {}건, max {}, actual {}".format(
                r["draw"], r["all200_hit4plus"], r["all200_max"], r["actual"]
            )
        )

out_path = "d:/3kweon/reports/stat_generator_solo_results.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print()
print("결과 저장: {}".format(out_path))
