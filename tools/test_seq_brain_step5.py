"""시퀀스뇌 (LSTM+Attention) 단위 검증."""
from __future__ import annotations

import os
import sys
from itertools import combinations as comb
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

DB_PATH = str(ROOT / "data" / "lotto4.db")


def main() -> None:
    from app.lotto4.brains.seq_brain import TEMPS, get_prob_vector, predict

    results = predict(1224, DB_PATH)
    assert len(results) == 5, f"세트 수 불일치: {len(results)}"
    for r in results:
        assert len(r) == 6
        assert len(set(r)) == 6
        assert all(1 <= n <= 45 for n in r)
        print(f"  세트: {r}")

    for a, b in comb([tuple(r) for r in results], 2):
        inter = len(set(a) & set(b))
        union = len(set(a) | set(b))
        j = inter / union if union else 0
        assert j < 0.5, f"Jaccard 과다: {j:.3f}"

    pv = get_prob_vector(1224, DB_PATH)
    assert abs(pv.sum() - 1.0) < 0.01, f"확률합 이상: {pv.sum()}"

    top10 = sorted(range(1, 46), key=lambda i: -pv[i - 1])[:10]
    print(f"  Top10 번호: {top10}")

    p = np.clip(pv, 1e-9, 1.0)
    s05 = np.power(p, 1.0 / TEMPS[0])
    s05 /= s05.sum()
    s15 = np.power(p, 1.0 / TEMPS[-1])
    s15 /= s15.sum()
    std05 = float(np.std(s05))
    std15 = float(np.std(s15))
    assert std05 > std15, f"온도 분산이 기대와 다름 std0.5={std05} std1.5={std15}"

    print("OK seq_brain unit tests passed")


if __name__ == "__main__":
    main()
