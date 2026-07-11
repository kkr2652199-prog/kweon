"""
백테스트(100~1222) 예측을 lotto_predictions_army4에 저장.
기존 v13 예측 중 해당 구간만 삭제 후 INSERT (1224 실전 등 구간 밖 행 보존).

스키마: models.init_lotto4_db — target_draw_no, method, num1~num6, confidence, reasoning,
        matched_count, bonus_matched, brain_tag
"""

from __future__ import annotations

import importlib
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from app.lotto4.models import init_lotto4_db
from app.lotto4.v13_weights_v2 import V13_BRAIN_METHOD

DB_PATH = str(ROOT / "data" / "lotto4.db")
START_DRAW = 100
END_DRAW = 1222

BRAINS: dict[str, str] = {
    "v13_struct": "app.lotto4.brains.struct_brain",
    "v13_cdm": "app.lotto4.brains.cdm_brain",
    "v13_ensemble": "app.lotto4.brains.ensemble",
    "v13_gap": "app.lotto4.brains.gap_brain",
    "v13_seq": "app.lotto4.brains.seq_brain",
    "v13_cond_prob": "app.lotto4.brains.cond_prob_brain",
    "v13_diversity": "app.lotto4.brains.diversity_brain",
    "v13_evolution": "app.lotto4.brains.evolution_brain",
    "v13_ev": "app.lotto4.brains.ev_brain",


def load_draws_with_bonus(db_path: str) -> dict[int, tuple[set[int], int | None]]:
    """{ draw_no: (당첨 6개 집합, bonus 또는 None) }"""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT draw_no, num1, num2, num3, num4, num5, num6, bonus
            FROM lotto_draws
            ORDER BY draw_no
            """
        ).fetchall()
    finally:
        conn.close()
    out: dict[int, tuple[set[int], int | None]] = {}
    for r in rows:
        dn = int(r[0])
        nums = {int(r[i]) for i in range(1, 7)}
        try:
            bo = int(r[7]) if r[7] is not None else None
        except (IndexError, TypeError, ValueError):
            bo = None
        out[dn] = (nums, bo)
    return out


def clear_backtest_v13_range(conn: sqlite3.Connection, start: int, end: int) -> int:
    cur = conn.execute(
        """
        DELETE FROM lotto_predictions_army4
        WHERE target_draw_no BETWEEN ? AND ?
          AND brain_tag LIKE 'v13_%'
        """,
        (start, end),
    )
    return int(cur.rowcount or 0)


def bonus_matched(pred: set[int], win: set[int], bonus: int | None) -> int:
    if bonus is None or len(pred & win) != 5:
        return 0
    return 1 if bonus in pred else 0


def main() -> None:
    init_lotto4_db()
    draws = load_draws_with_bonus(DB_PATH)
    draw_list = sorted(d for d in draws if START_DRAW <= d <= END_DRAW)
    if not draw_list:
        print("백테스트 구간에 당첨 데이터가 없습니다.")
        return

    print(f"백테스트 DB 저장: {draw_list[0]}~{draw_list[-1]} ({len(draw_list)}회차)")

    conn = sqlite3.connect(DB_PATH)
    try:
        deleted = clear_backtest_v13_range(conn, START_DRAW, END_DRAW)
        conn.commit()
        print(f"삭제: target_draw {START_DRAW}~{END_DRAW}, v13_% → {deleted}행")

        total_rows = 0
        t0 = time.perf_counter()

        for idx, draw_no in enumerate(draw_list):
            real_set, bonus = draws[draw_no]

            for tag, mod_path in BRAINS.items():
                try:
                    mod = importlib.import_module(mod_path)
                    pred_fn = getattr(mod, "predict", None)
                    if not callable(pred_fn):
                        raise RuntimeError("no predict")
                    sets = pred_fn(draw_no, DB_PATH)
                except Exception as e:  # noqa: BLE001
                    print(f"[ERROR] {tag} draw={draw_no}: {e}", flush=True)
                    continue

                method = V13_BRAIN_METHOD.get(tag, tag)
                for set_no, s in enumerate(sets or [], start=1):
                    if len(s) != 6:
                        continue
                    nums = sorted(int(x) for x in s)
                    pred_set = set(nums)
                    mc = len(pred_set & real_set)
                    bm = bonus_matched(pred_set, real_set, bonus)
                    conn.execute(
                        """
                        INSERT INTO lotto_predictions_army4
                        (target_draw_no, method, num1, num2, num3, num4, num5, num6,
                         confidence, reasoning, matched_count, bonus_matched, brain_tag)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            draw_no,
                            method,
                            nums[0],
                            nums[1],
                            nums[2],
                            nums[3],
                            nums[4],
                            nums[5],
                            round(0.5 + 0.01 * (set_no - 1), 4),
                            f"백테스트 {tag} 세트{set_no}",
                            mc,
                            bm,
                            tag,
                        ),
                    )
                    total_rows += 1

            if (idx + 1) % 100 == 0:
                conn.commit()
                elapsed = time.perf_counter() - t0
                print(f"  ... {idx + 1}/{len(draw_list)} 회차 ({elapsed:.0f}s)", flush=True)

        conn.commit()
        elapsed = time.perf_counter() - t0
        print(f"\n완료: INSERT {total_rows}행 (벽시계 {elapsed:.1f}s / {elapsed/60:.1f}분)")

        row = conn.execute(
            """
            SELECT COUNT(*), COUNT(DISTINCT target_draw_no), COUNT(DISTINCT brain_tag)
            FROM lotto_predictions_army4
            WHERE target_draw_no BETWEEN ? AND ? AND brain_tag LIKE 'v13_%'
            """,
            (START_DRAW, END_DRAW),
        ).fetchone()
        print(f"검증(구간): {row[0]}행, {row[1]}회차, {row[2]}뇌")

        n1224 = conn.execute(
            """
            SELECT COUNT(*) FROM lotto_predictions_army4
            WHERE target_draw_no = 1224 AND brain_tag LIKE 'v13_%'
            """
        ).fetchone()[0]
        print(f"1224 실전 보존: v13 행 {n1224}개")

        dist = conn.execute(
            """
            SELECT matched_count, COUNT(*) AS c
            FROM lotto_predictions_army4
            WHERE target_draw_no BETWEEN ? AND ? AND brain_tag LIKE 'v13_%'
            GROUP BY matched_count
            ORDER BY matched_count DESC
            """,
            (START_DRAW, END_DRAW),
        ).fetchall()
    finally:
        conn.close()

    print("\n적중 분포 (matched_count):")
    for mc, cnt in dist:
        print(f"  {mc}개: {cnt}행")


if __name__ == "__main__":
    main()
