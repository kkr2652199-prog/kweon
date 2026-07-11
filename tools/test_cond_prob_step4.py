"""조건부확률 뇌 단위 검증."""
from __future__ import annotations

import os
import sys
from itertools import combinations as comb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from app.lotto4.brains.cond_prob_brain import get_top_pairs, predict_detailed

DB_PATH = str(ROOT / "data" / "lotto4.db")


def main() -> None:
    results = predict_detailed(1224, DB_PATH)
    assert len(results) == 5, f"세트 수 불일치: {len(results)}"
    for r in results:
        assert len(r["nums"]) == 6, f"번호 개수 불일치: {r['nums']}"
        assert r["brain_tag"] == "v13_cond_prob"
        assert all(1 <= n <= 45 for n in r["nums"]), f"범위 이탈: {r['nums']}"
        assert len(set(r["nums"])) == 6, f"중복 번호: {r['nums']}"
        print(f"  세트: {r['nums']}  confidence: {r['confidence']}  {r['reasoning']}")

    for a, b in comb([tuple(r["nums"]) for r in results], 2):
        inter = len(set(a) & set(b))
        union = len(set(a) | set(b))
        jaccard = inter / union if union > 0 else 0
        assert jaccard < 0.5, f"Jaccard 과다: {a} vs {b} = {jaccard:.3f}"

    top_pairs = get_top_pairs(DB_PATH, 1224, top_n=10)
    assert len(top_pairs) == 10
    print("\n  Top10 쌍:")
    for p in top_pairs:
        print(
            f"    {p['pair']} -> P(B|A)={p['p_b_given_a']}, "
            f"P(A|B)={p['p_a_given_b']}, avg={p['avg']}"
        )

    print("\nOK cond_prob unit tests passed")


if __name__ == "__main__":
    main()
