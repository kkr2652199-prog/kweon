"""CDM 뇌 단위 검증 (경로 기반 predict, 엔진 규약)."""
from __future__ import annotations

import os
import sys
import sqlite3
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from app.lotto4.brains.cdm_brain import predict, update_alpha

DB = str(ROOT / "data" / "lotto4.db")


def main() -> None:
    results = predict(1224, DB)
    assert len(results) == 5, f"세트 수 불일치: {len(results)}"
    for r in results:
        assert len(r) == 6, f"번호 개수 불일치: {r}"
        assert all(1 <= n <= 45 for n in r)
        print(f"  세트: {r}")

    conn = sqlite3.connect(DB)
    try:
        rows = conn.execute(
            "SELECT draw_no, num1, num2, num3, num4, num5, num6 "
            "FROM lotto_draws WHERE draw_no < 1224 ORDER BY draw_no"
        ).fetchall()
    finally:
        conn.close()

    draws = [{"draw_no": r[0], "nums": [r[1], r[2], r[3], r[4], r[5], r[6]]} for r in rows]
    alpha_state = update_alpha(draws)
    print(f"  Top10: {alpha_state['top10']}")
    print(f"  Top10 확률합: {alpha_state['prob_sum_top10']}")
    print(f"  총 회차: {alpha_state['total_draws']}")

    for a, b in combinations([tuple(r) for r in results], 2):
        inter = len(set(a) & set(b))
        union = len(set(a) | set(b))
        j = inter / union if union > 0 else 0
        assert j < 0.6, f"Jaccard 과다: {a} vs {b} = {j:.3f}"

    print("OK CDM unit tests passed")


if __name__ == "__main__":
    main()
