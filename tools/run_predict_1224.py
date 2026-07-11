"""1224 실전 예측: v13 캐시 삭제 후 재생성, 40세트 전부 출력."""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from app.lotto4.models import get_lotto4_db, init_lotto4_db
from app.lotto4.v13_engine_v2 import run_prediction_v13


def main() -> None:
    init_lotto4_db()
    conn = get_lotto4_db()
    try:
        conn.execute(
            """
            DELETE FROM lotto_predictions_army4
            WHERE target_draw_no = 1224 AND brain_tag LIKE 'v13_%'
            """
        )
        conn.commit()
    finally:
        conn.close()

    r = run_prediction_v13(1224)
    print("Status:", r.get("status"))
    print("Target:", r.get("target_draw_no"))
    ap = r.get("all_predictions") or []
    by_brain: dict[str, list[list[int]]] = defaultdict(list)
    for row in ap:
        tag = str(row.get("brain_tag", "?"))
        by_brain[tag].append(list(row.get("nums") or []))

    print()
    print("=== 1224회차 8뇌 × 5세트 (40세트) ===")
    for tag in sorted(by_brain.keys()):
        for i, nums in enumerate(by_brain[tag], 1):
            print(f"  {tag} 세트{i}: {nums}")

    ens = by_brain.get("v13_ensemble", [])
    print()
    print("=== 최종 추천 (v13_ensemble 5세트, 갱신 가중치 반영) ===")
    for i, s in enumerate(ens, 1):
        print(f"  세트{i}: {s}")


if __name__ == "__main__":
    main()
