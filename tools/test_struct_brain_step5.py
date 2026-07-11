"""4단계 STEP 5 — 구조예측뇌(struct_brain) 단위 검증."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from app.lotto4.brains._utils import jaccard
from app.lotto4.brains.struct_brain import (
    TOLS,
    predict,
    predict_struct_vector,
    struct_vector,
)

DB_PATH = str(ROOT / "data" / "lotto4.db")


def _count_soft(actual, y_hat) -> int:
    ok = 0
    if abs(actual[0] - y_hat[0]) <= TOLS[0]:
        ok += 1
    for i in range(1, 7):
        if abs(actual[i] - y_hat[i]) <= TOLS[i]:
            ok += 1
    return ok


def _sdist(actual, y_hat) -> float:
    import numpy as np

    return float(sum(abs(actual[i] - y_hat[i]) / TOLS[i] for i in range(7)))


def main() -> None:
    draw_no = 1224
    y_hat = predict_struct_vector(draw_no, DB_PATH)
    names = ("sum", "odd", "high", "ac", "consec", "decade", "tail")
    parts = [f"{n}={y_hat[i]:.3g}" for i, n in enumerate(names)]
    print("예측 구조:", ", ".join(parts))

    sets = predict(draw_no, DB_PATH)
    fails: list[str] = []

    if len(sets) != 5:
        fails.append(f"세트 개수: 기대 5, 실제 {len(sets)}")

    for i, s in enumerate(sets):
        if len(s) != 6 or len(set(s)) != 6:
            fails.append(f"세트{i+1}: 6개 중복없음 위반")
            continue
        if not all(1 <= x <= 45 for x in s):
            fails.append(f"세트{i+1}: 범위 위반")
        act = struct_vector(s)
        m = _count_soft(act, y_hat)
        if m < 5:
            fails.append(f"세트{i+1}: 구조 조건 {m}/7 (<5)")

    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            jac = jaccard(set(sets[i]), set(sets[j]))
            if jac >= 0.5:
                fails.append(f"Jaccard 세트{i+1}·{j+1}={jac:.3f} (>=0.5)")

    print("\n5세트 번호·구조·struct_distance:")
    for i, s in enumerate(sets):
        act = struct_vector(s)
        d = _sdist(act, y_hat)
        print(
            f"  [{i+1}] {s} | "
            f"sum={act[0]:.0f} odd={act[1]:.0f} high={act[2]:.0f} "
            f"ac={act[3]:.0f} c={act[4]:.0f} dec={act[5]:.0f} tailv={act[6]:.0f} | dist={d:.4f}"
        )

    if fails:
        print("\n실패:")
        for f in fails:
            print(" ", f)
        print("\n[FAIL] 구조예측뇌 단위 테스트 일부 실패")
    else:
        print("\n[OK] 구조예측뇌 단위 테스트 전부 통과")


if __name__ == "__main__":
    main()
