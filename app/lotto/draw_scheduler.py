"""토요일 추첨 후 당첨번호 자동 수집 스케줄러."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_scheduler = None


def _job_collect_latest() -> None:
    from app.lotto.data_service import collect_latest_forward

    try:
        result = collect_latest_forward(max_probe=5)
        if result.get("collected"):
            try:
                from app.lotto.data_service import get_lotto_db
                from app.lotto4.all_combos_service import sync_winner_for_draw

                conn = get_lotto_db()
                try:
                    for draw_no in result["collected"]:
                        row = conn.execute(
                            "SELECT * FROM lotto_draws WHERE draw_no = ?",
                            (int(draw_no),),
                        ).fetchone()
                        if row:
                            sync_winner_for_draw(dict(row))
                finally:
                    conn.close()
            except Exception as e:  # noqa: BLE001
                logger.warning("all_combos scheduled sync: %s", e)
        logger.info(
            "scheduled lotto collect: count=%s collected=%s errors=%s",
            result.get("count"),
            result.get("collected"),
            result.get("errors"),
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("scheduled lotto collect failed: %s", e)


def start_draw_collect_scheduler() -> None:
    """서버 기동 시 호출. 토 21:10~23:40 / 일 10:00 백업."""
    global _scheduler
    if _scheduler is not None:
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.warning("apscheduler 미설치 — 자동 수집 스케줄러 비활성")
        return

    _scheduler = BackgroundScheduler(timezone="Asia/Seoul")
    _scheduler.add_job(
        _job_collect_latest,
        CronTrigger(day_of_week="sat", hour="21-23", minute="10,40"),
        id="lotto_collect_sat",
        replace_existing=True,
    )
    _scheduler.add_job(
        _job_collect_latest,
        CronTrigger(day_of_week="sun", hour=10, minute=0),
        id="lotto_collect_sun_backup",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("lotto draw collect scheduler started (Asia/Seoul)")


def stop_draw_collect_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
