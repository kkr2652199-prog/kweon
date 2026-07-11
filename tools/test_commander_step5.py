"""
Hyena Commander v2 — 6단계 단위 테스트 (지시서 STEP 5).
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from app.lotto4 import v13_engine_v2 as engine
from app.lotto4.brains import ensemble
from app.lotto4.brains import cdm_brain, cond_prob_brain
from app.lotto4.brains._utils import jaccard
from app.lotto4.brains.evolution_brain import CHIEF_TAGS, LOOKBACK
from app.lotto4.models import get_lotto4_db

DB_PATH = str(ROOT / "data" / "lotto4.db")
DRAW = 1224


def _clear_v13_cache(draw_no: int) -> None:
    conn = get_lotto4_db()
    try:
        conn.execute(
            """
            DELETE FROM lotto_predictions_army4
            WHERE target_draw_no = ? AND brain_tag LIKE 'v13_%'
            """,
            (draw_no,),
        )
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    errs: list[str] = []

    dbg = ensemble.predict_debug(DRAW, DB_PATH)
    combo_sec = float(dbg.get("combo_eval_sec") or 0.0)
    print(f"18C6+리스코어 블록: {combo_sec:.3f}s", flush=True)
    if combo_sec >= 5.0:
        errs.append(f"18C6 평가·정규화 블록 {combo_sec:.3f}s (기대 <5s)")

    sets = [row["nums"] for row in dbg["sets"]]
    if len(sets) != 5:
        errs.append(f"세트 수: 기대 5, 실제 {len(sets)}")

    for i, row in enumerate(dbg["sets"]):
        s = row["nums"]
        h = int(row["struct_hits"])
        if h < 6:
            errs.append(f"세트 {i + 1} 구조 충족 {h}/7 (기대 ≥6)")
        print(f"  세트{i + 1}: {s}  struct_ok={h}/7", flush=True)

    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            jv = jaccard(set(sets[i]), set(sets[j]))
            if jv >= 0.4:
                errs.append(
                    f"Jaccard 세트 {i + 1} vs {j + 1}: {jv:.3f} (기대 <0.4)"
                )

    pool18 = dbg["pool18"]
    print("\n컨센서스 풀 (18):", pool18, flush=True)
    if len(pool18) != 18:
        errs.append(f"pool18 길이 {len(pool18)}")

    print("\ndynamic_weights (전체 선수):", dbg["dynamic_weights_full"], flush=True)
    print("player_weights (seq/struct):", dbg["player_weights"], flush=True)
    for row in dbg["sets"]:
        print(
            f"  FINAL_SCORE={row['final_score']:.6f}  struct_hits={row['struct_hits']}/7  nums={row['nums']}",
            flush=True,
        )

    dw = dbg["dynamic_weights_full"]
    vals = [float(dw.get(t, 0.0)) for t in CHIEF_TAGS]
    if LOOKBACK >= 20 and len(set(round(v, 6) for v in vals)) == 1:
        print(
            "  참고: dynamic_weights 2선수 동일 (이력 부족 시 균등 폴백일 수 있음)",
            flush=True,
        )

    _clear_v13_cache(DRAW)
    with mock.patch.object(cdm_brain, "predict") as m_cdm, mock.patch.object(
        cond_prob_brain, "predict"
    ) as m_cp:
        engine.run_prediction_v13(DRAW)
    if m_cdm.called:
        errs.append("cdm_brain.predict 가 호출됨 (HIDDEN)")
    if m_cp.called:
        errs.append("cond_prob_brain.predict 가 호출됨 (HIDDEN)")
    print("\nHIDDEN predict 호출: cdm=", m_cdm.called, "cond_prob=", m_cp.called, flush=True)

    if errs:
        print("\n실패:", flush=True)
        for e in errs:
            print(" -", e, flush=True)
        raise SystemExit(1)

    print("\n✅ 총사령관 6단계 단위 테스트 전부 통과", flush=True)


if __name__ == "__main__":
    main()
