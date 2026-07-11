"""V10 라우터: /api/lotto2/v10/* prefix.

V9 라우터(/api/lotto2/*)는 그대로 보존.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/lotto2/v10", tags=["lotto2_v10"])


@router.post("/predict/{target_draw_no}")
async def api_predict_v10(target_draw_no: int):
    from app.lotto2.engine_v10 import run_prediction_v10

    return run_prediction_v10(target_draw_no)


@router.get("/status")
async def api_status_v10():
    from app.lotto2.models import get_lotto2_db

    conn = get_lotto2_db()
    try:
        rows = conn.execute(
            """
            SELECT brain_tag, COUNT(*) AS n, AVG(matched_count) AS avg_m,
                   SUM(CASE WHEN matched_count = 6 THEN 1 ELSE 0 END) AS r1,
                   SUM(CASE WHEN matched_count = 5 AND bonus_matched = 1 THEN 1 ELSE 0 END) AS r2,
                   SUM(CASE WHEN matched_count = 5 AND bonus_matched = 0 THEN 1 ELSE 0 END) AS r3
            FROM lotto_predictions_army2
            WHERE matched_count >= 0 AND brain_tag LIKE 'v10_%'
            GROUP BY brain_tag
            """
        ).fetchall()
        return {"v10_brains": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.post("/backtest_chunk")
async def api_backtest_chunk_v10(start_draw: int, end_draw: int, checkpoint_every: int = 50):
    from app.lotto2.backtest_v10 import run_chunk_backtest

    return run_chunk_backtest(start_draw, end_draw, checkpoint_every)


@router.get("/stats")
async def api_stats_v10(start_draw: int = 50, end_draw: int = 1221):
    from app.lotto2.backtest_v10 import get_v10_stats

    return get_v10_stats(start_draw, end_draw)

