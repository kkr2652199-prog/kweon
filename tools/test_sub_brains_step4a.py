"""5단계-A — gap_brain / diversity_brain 단위 테스트."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from app.lotto4.brains._utils import jaccard
from app.lotto4.brains import diversity_brain, gap_brain

DB_PATH = str(ROOT / "data" / "lotto4.db")


def main() -> None:
    fails: list[str] = []
    draw_no = 1224

    # --- 갭분석뇌 ---
    sets_g = gap_brain.predict(draw_no, DB_PATH)
    if len(sets_g) != 5:
        fails.append(f"gap predict: 기대 5세트, 실제 {len(sets_g)}")
    for i, s in enumerate(sets_g):
        if len(s) != 6 or len(set(s)) != 6 or not all(1 <= x <= 45 for x in s):
            fails.append(f"gap 세트{i+1} 형식 오류")

    z = gap_brain.compute_z_scores(draw_no, DB_PATH)
    ranked = sorted(z.items(), key=lambda x: -x[1])
    top5 = ranked[:5]
    bottom5 = sorted(z.items(), key=lambda x: x[1])[:5]
    print("갭분석 5세트:", sets_g)
    print("Z-score Top5 (번호, z):", top5)
    print("Z-score Bottom5 (번호, z):", bottom5)

    test_sets = [[3, 7, 12, 25, 33, 41], [5, 11, 22, 28, 39, 44], [2, 9, 18, 27, 36, 45]]
    gr = gap_brain.rescore(test_sets, draw_no, DB_PATH)
    if len(gr) != 3 or not all(isinstance(x, tuple) and len(x) == 2 for x in gr):
        fails.append("gap rescore: (세트, float) 3개 기대")

    # --- 다양성뇌 ---
    sets_d = diversity_brain.predict(draw_no, DB_PATH)
    if len(sets_d) != 5:
        fails.append(f"diversity predict: 기대 5세트, 실제 {len(sets_d)}")
    for i, s in enumerate(sets_d):
        if len(s) != 6 or len(set(s)) != 6:
            fails.append(f"diversity 세트{i+1} 형식")
            continue
        if len({n // 10 for n in s}) < 3:
            fails.append(f"diversity 세트{i+1}: 십단위 커버리지 < 3 → {s}")
    for i in range(len(sets_d)):
        for j in range(i + 1, len(sets_d)):
            jac = jaccard(set(sets_d[i]), set(sets_d[j]))
            if jac >= 0.5:
                fails.append(f"diversity Jaccard 세트{i+1},{j+1}={jac:.3f}")

    print("\n다양성 5세트:", sets_d)
    print(
        "십단위 커버리지:",
        [len({n // 10 for n in s}) for s in sets_d],
    )

    dr = diversity_brain.rescore(test_sets, draw_no, DB_PATH)
    if len(dr) != 3:
        fails.append("diversity rescore 개수")

    dup_in = [[1, 2, 3, 4, 5, 6], [1, 2, 3, 4, 5, 7], [10, 11, 12, 13, 14, 15]]
    fd = diversity_brain.filter_duplicates(dup_in, draw_no, DB_PATH)
    if len(fd) != 2:
        fails.append(f"filter_duplicates: 기대 2세트, 실제 {len(fd)}")

    if fails:
        print("\n실패:")
        for f in fails:
            print(" ", f)
        print("\n[FAIL] 서브뇌 5단계-A 단위 테스트 일부 실패")
    else:
        print("\n[OK] 서브뇌 5단계-A 단위 테스트 전부 통과")


if __name__ == "__main__":
    main()
