"""4군 최신 회차 예측 갱신 — 캐시 삭제 후 v13 엔진 재실행.

사용: python tools/patch_predict_latest.py [target_draw_no]
기본 target = lotto_draws MAX + 1 (다음 추첨 회차)
"""
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


def _next_target_draw() -> int:
    conn = get_lotto4_db()
    try:
        row = conn.execute("SELECT MAX(draw_no) FROM lotto_draws").fetchone()
        return int(row[0] or 0) + 1
    finally:
        conn.close()


def main() -> None:
    init_lotto4_db()
    target = int(sys.argv[1]) if len(sys.argv) > 1 else _next_target_draw()

    conn = get_lotto4_db()
    try:
        conn.execute(
            """
            DELETE FROM lotto_predictions_army4
            WHERE target_draw_no = ? AND brain_tag LIKE 'v13_%'
            """,
            (target,),
        )
        conn.commit()
    finally:
        conn.close()

    r = run_prediction_v13(target)
    print("Status:", r.get("status"))
    print("Target:", r.get("target_draw_no"))
    print("Engine:", r.get("engine"))

    ap = r.get("all_predictions") or []
    by_brain: dict[str, list[list[int]]] = defaultdict(list)
    for row in ap:
        tag = str(row.get("brain_tag", "?"))
        by_brain[tag].append(list(row.get("nums") or []))

    print()
    print(f"=== {target}회차 v13 뇌별 5세트 ===")
    for tag in sorted(by_brain.keys()):
        for i, nums in enumerate(by_brain[tag], 1):
            print(f"  {tag} set{i}: {nums}")

    ens = by_brain.get("v13_ensemble", [])
    print()
    print("=== v13_ensemble (Commander) ===")
    for i, s in enumerate(ens, 1):
        print(f"  set{i}: {s}")


if __name__ == "__main__":
    main()
