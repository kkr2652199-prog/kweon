"""V10 분할 백테스트 모듈.

청크 단위로 회차별 재학습 + 예측 + 채점.
체크포인트 raw 출력. 중단 가능.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

LOTTO_DB_PATH = Path(__file__).parent.parent.parent / "data" / "lotto4.db"


def run_chunk_backtest(start_draw: int, end_draw: int, checkpoint_every: int = 50) -> dict:
    """V10 회차 청크 백테스트.

    Args:
        start_draw: 시작 회차
        end_draw: 끝 회차 (포함)
        checkpoint_every: 체크포인트 출력 주기

    Returns:
        elapsed, total_ok, total_error, error_draws, checkpoints
    """
    from app.lotto2.engine_v10 import run_prediction_v10

    t0 = time.time()
    total_ok = 0
    total_error = 0
    error_draws = []
    checkpoints = []

    for n, draw_no in enumerate(range(start_draw, end_draw + 1), 1):
        try:
            r = run_prediction_v10(draw_no)
            status = r.get("status", "unknown")
            if status in ("ok", "cached"):
                total_ok += 1
            else:
                total_error += 1
                error_draws.append(
                    {"draw_no": draw_no, "status": status, "reason": r.get("reason")}
                )
        except Exception as e:  # noqa: BLE001
            total_error += 1
            error_draws.append({"draw_no": draw_no, "exception": str(e)[:200]})

        if n % checkpoint_every == 0:
            elapsed = time.time() - t0
            checkpoints.append(
                {
                    "n_done": n,
                    "current_draw": draw_no,
                    "elapsed_sec": round(elapsed, 1),
                    "ok": total_ok,
                    "error": total_error,
                    "rate_sec_per_draw": round(elapsed / n, 3),
                }
            )

    elapsed_total = time.time() - t0
    return {
        "range": f"{start_draw}~{end_draw}",
        "elapsed_sec": round(elapsed_total, 1),
        "elapsed_min": round(elapsed_total / 60, 2),
        "total_ok": total_ok,
        "total_error": total_error,
        "error_draws_first10": error_draws[:10],
        "checkpoints": checkpoints,
    }


def get_v10_stats(start_draw: int, end_draw: int) -> dict:
    """V10 누적 등수 조회."""
    conn = sqlite3.connect(str(LOTTO_DB_PATH))
    try:
        rows = conn.execute(
            """
            SELECT brain_tag, COUNT(*) AS n,
                   ROUND(AVG(matched_count), 3) AS avg_m,
                   MAX(matched_count) AS best,
                   SUM(CASE WHEN matched_count=6 THEN 1 ELSE 0 END) AS r1,
                   SUM(CASE WHEN matched_count=5 AND bonus_matched=1 THEN 1 ELSE 0 END) AS r2,
                   SUM(CASE WHEN matched_count=5 AND bonus_matched=0 THEN 1 ELSE 0 END) AS r3,
                   SUM(CASE WHEN matched_count=4 THEN 1 ELSE 0 END) AS r4,
                   SUM(CASE WHEN matched_count=3 THEN 1 ELSE 0 END) AS r5
            FROM lotto_predictions_army2
            WHERE matched_count >= 0
              AND brain_tag LIKE 'v10_%'
              AND target_draw_no BETWEEN ? AND ?
            GROUP BY brain_tag
            ORDER BY avg_m DESC
            """,
            (start_draw, end_draw),
        ).fetchall()
        return {
            "range": f"{start_draw}~{end_draw}",
            "stats": [
                {
                    "brain_tag": r[0],
                    "n": r[1],
                    "avg_m": r[2],
                    "best": r[3],
                    "r1": r[4],
                    "r2": r[5],
                    "r3": r[6],
                    "r4": r[7],
                    "r5": r[8],
                }
                for r in rows
            ],
        }
    finally:
        conn.close()

