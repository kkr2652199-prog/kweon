"""V9 2군 API: /api/lotto2/* prefix."""
import sqlite3

from fastapi import APIRouter

from app.lotto2.models import get_lotto2_db

router = APIRouter(prefix="/api/lotto2", tags=["lotto2"])


@router.post("/predict/{target_draw_no}")
async def api_predict_army2(target_draw_no: int):
    from app.lotto2.engine import run_prediction_army2

    return run_prediction_army2(target_draw_no)


@router.post("/backtest")
async def api_backtest_army2(start_draw: int = 1100, end_draw: int = 0):
    from app.lotto2.engine import run_backtest_army2

    if end_draw == 0:
        conn = get_lotto2_db()
        try:
            row = conn.execute("SELECT MAX(draw_no) FROM lotto_draws").fetchone()
            end_draw = int(row[0] or 0) if row else 0
        finally:
            conn.close()
    return run_backtest_army2(start_draw, end_draw)


@router.get("/predictions")
async def api_get_predictions_army2(limit: int = 100):
    conn = get_lotto2_db()
    try:
        rows = conn.execute(
            """
            SELECT p.*, d.num1 as actual_1, d.num2 as actual_2, d.num3 as actual_3,
                   d.num4 as actual_4, d.num5 as actual_5, d.num6 as actual_6,
                   d.bonus as actual_bonus
            FROM lotto_predictions_army2 p
            LEFT JOIN lotto_draws d ON p.target_draw_no = d.draw_no
            ORDER BY p.target_draw_no DESC, p.confidence DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return {"predictions": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/brain/weights")
async def api_brain_weights_army2():
    conn = get_lotto2_db()
    try:
        rows = conn.execute(
            "SELECT * FROM lotto_brain_weights_army2 ORDER BY current_weight DESC"
        ).fetchall()
        return {"weights": [dict(r) for r in rows]}
    except sqlite3.Error:
        return {"weights": []}
    finally:
        conn.close()


@router.get("/brain/status")
async def api_brain_status_army2():
    conn = get_lotto2_db()
    try:
        rows = conn.execute(
            """
            SELECT brain_tag, COUNT(*) AS n, AVG(matched_count) AS avg_m,
                   SUM(CASE WHEN matched_count = 6 THEN 1 ELSE 0 END) AS r1,
                   SUM(CASE WHEN matched_count = 5 AND bonus_matched = 1
                       THEN 1 ELSE 0 END) AS r2,
                   SUM(CASE WHEN matched_count = 5 AND bonus_matched = 0
                       THEN 1 ELSE 0 END) AS r3
            FROM lotto_predictions_army2 WHERE matched_count >= 0
            GROUP BY brain_tag
            """
        ).fetchall()
        return {"brains": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/draws")
async def api_get_draws_army2(limit: int = 50):
    """1군과 동일 데이터(lotto_draws 공유, 읽기)."""
    conn = get_lotto2_db()
    try:
        rows = conn.execute(
            "SELECT * FROM lotto_draws ORDER BY draw_no DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return {"draws": [dict(r) for r in rows], "total": len(rows)}
    finally:
        conn.close()
