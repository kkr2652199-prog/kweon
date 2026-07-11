"""V13 라우터: /api/lotto4/v13/*"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api/lotto4/v13", tags=["lotto4_v13"])


def _ensure_draw_record_for_target(target_draw_no: int) -> bool:
    """DB에 없는 회차면 동행 API에서 당첨번호를 한 번 가져와 저장. 성공 시 True."""
    from app.lotto.data_service import fetch_single_draw, init_lotto_db, save_draw
    from app.lotto4.models import get_lotto4_db

    conn = get_lotto4_db()
    try:
        if conn.execute(
            "SELECT 1 FROM lotto_draws WHERE draw_no = ? LIMIT 1",
            (int(target_draw_no),),
        ).fetchone():
            return True
    finally:
        conn.close()

    init_lotto_db()
    draw = fetch_single_draw(int(target_draw_no))
    if not draw:
        return False
    save_draw(draw)
    return True


def _ensure_army4_scored_for_draw(target_draw_no: int) -> None:
    """당첨번호 확보 후 미채점(-1) 예측을 갱신 (1군 refresh_prediction_scores와 동일 역할)."""
    from app.lotto4.army4_draw_sync import refresh_army4_predictions_for_draw

    _ensure_draw_record_for_target(target_draw_no)
    refresh_army4_predictions_for_draw(int(target_draw_no))


@router.post("/predict/{target_draw_no}")
async def api_predict_v13(target_draw_no: int):
    from app.lotto4.v13_engine_v2 import run_prediction_v13

    return run_prediction_v13(target_draw_no)


@router.post("/backtest_chunk")
async def api_backtest_v13(start_draw: int, end_draw: int, checkpoint_every: int = 25):
    from app.lotto4.v13_engine_v2 import run_v13_chunk_backtest

    return run_v13_chunk_backtest(start_draw, end_draw, checkpoint_every)


@router.get("/stats")
async def api_stats_v13(start_draw: int = 50, end_draw: int = 1221):
    from app.lotto4.models import get_lotto4_db

    conn = get_lotto4_db()
    try:
        rows = conn.execute(
            """
            SELECT brain_tag, COUNT(1) AS n, ROUND(AVG(matched_count), 3) AS avg_m,
                   MAX(matched_count) AS best,
                   SUM(CASE WHEN matched_count=6 THEN 1 ELSE 0 END) AS r1,
                   SUM(CASE WHEN matched_count=5 AND bonus_matched=1 THEN 1 ELSE 0 END) AS r2,
                   SUM(CASE WHEN matched_count=5 AND bonus_matched=0 THEN 1 ELSE 0 END) AS r3,
                   SUM(CASE WHEN matched_count=4 THEN 1 ELSE 0 END) AS r4,
                   SUM(CASE WHEN matched_count=3 THEN 1 ELSE 0 END) AS r5
            FROM lotto_predictions_army4
            WHERE matched_count >= 0 AND brain_tag LIKE 'v13_%'
              AND target_draw_no BETWEEN ? AND ?
            GROUP BY brain_tag
            ORDER BY avg_m DESC
            """,
            (start_draw, end_draw),
        ).fetchall()
        return {"range": f"{start_draw}~{end_draw}", "v13_brains": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/weights")
async def api_weights_v13():
    from app.lotto4.v13_weights_v2 import get_v13_v2_brain_weights

    return {"v13_weights": get_v13_v2_brain_weights()}


# ============= UI 호환 라우트 (STEP C-1) =============

@router.get("/brain/elite-tags")
async def api_v13_brain_elite_tags():
    """엘리트 뇌 태그: 역대 1·2·3등 균형 또는 3등 다득."""

    from app.lotto4.models import get_lotto4_db

    conn = get_lotto4_db()
    try:
        rows = conn.execute(
            """
            SELECT brain_tag,
              SUM(CASE WHEN matched_count=6 THEN 1 ELSE 0 END) AS r1,
              SUM(CASE WHEN matched_count=5 AND bonus_matched=1 THEN 1 ELSE 0 END) AS r2,
              SUM(CASE WHEN matched_count=5 AND (bonus_matched=0 OR bonus_matched IS NULL)
                  THEN 1 ELSE 0 END) AS r3
            FROM lotto_predictions_army4
            WHERE brain_tag LIKE 'v13_%'
              AND brain_tag NOT IN ('miss_analysis')
            GROUP BY brain_tag
            HAVING (r1 >= 1 AND r2 >= 1 AND r3 >= 5)
                OR (r3 >= 15)
            ORDER BY brain_tag
            """
        ).fetchall()
        tags = [str(r[0]) for r in rows if r[0]]
        return {"tags": tags}
    finally:
        conn.close()


@router.get("/predictions/draw/{target_draw_no}/tier-wins")
async def api_v13_predictions_tier_wins(target_draw_no: int):
    """단일 회차: 1~5등 적중 예측 세트만 (읽기 전용, 4군 팝업용)."""
    from app.lotto.routes import _tier_wins_items_from_rows

    from app.lotto4.models import get_lotto4_db

    _ensure_army4_scored_for_draw(target_draw_no)

    conn = get_lotto4_db()
    try:
        draw_row = conn.execute(
            """
            SELECT draw_no, draw_date, num1, num2, num3, num4, num5, num6, bonus
            FROM lotto_draws WHERE draw_no = ?
            """,
            (target_draw_no,),
        ).fetchone()
        rows = conn.execute(
            """
            SELECT id, brain_tag, matched_count, bonus_matched, confidence,
                   num1, num2, num3, num4, num5, num6
            FROM lotto_predictions_army4
            WHERE target_draw_no = ?
              AND brain_tag LIKE 'v13_%'
              AND matched_count >= 3
            ORDER BY brain_tag ASC, confidence DESC
            """,
            (target_draw_no,),
        ).fetchall()
    finally:
        conn.close()

    items = _tier_wins_items_from_rows(rows)

    out: dict = {
        "draw_no": target_draw_no,
        "draw_date": None,
        "actual_numbers": None,
        "bonus": None,
        "items": items,
    }
    if draw_row:
        dr = dict(draw_row)
        out["draw_date"] = dr.get("draw_date")
        out["actual_numbers"] = [
            dr["num1"],
            dr["num2"],
            dr["num3"],
            dr["num4"],
            dr["num5"],
            dr["num6"],
        ]
        out["bonus"] = dr.get("bonus")

    return out


@router.get("/predictions/draw/{target_draw_no}")
async def api_v13_predictions_for_draw(target_draw_no: int):
    """단일 회차의 v13 예측 전부(탭별 건수 정확도용). bulk LIMIT 절단으로 역발상가 등이 빠지는 문제 방지."""
    from app.lotto4.models import get_lotto4_db

    _ensure_army4_scored_for_draw(target_draw_no)

    conn = get_lotto4_db()
    try:
        rows = conn.execute(
            """
            SELECT p.*, d.num1 AS actual_1, d.num2 AS actual_2, d.num3 AS actual_3,
                   d.num4 AS actual_4, d.num5 AS actual_5, d.num6 AS actual_6,
                   d.bonus AS actual_bonus
            FROM lotto_predictions_army4 p
            LEFT JOIN lotto_draws d ON p.target_draw_no = d.draw_no
            WHERE p.brain_tag LIKE 'v13_%' AND p.target_draw_no = ?
            ORDER BY p.brain_tag ASC, p.confidence DESC
            """,
            (target_draw_no,),
        ).fetchall()
        return {"predictions": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/predictions")
async def api_v13_predictions(limit: int = 100):
    """V11 예측 목록 (1군 /api/lotto/predictions 형식 호환)."""
    from app.lotto4.models import get_lotto4_db

    conn = get_lotto4_db()
    try:
        rows = conn.execute(
            """
            SELECT p.*, d.num1 AS actual_1, d.num2 AS actual_2, d.num3 AS actual_3,
                   d.num4 AS actual_4, d.num5 AS actual_5, d.num6 AS actual_6,
                   d.bonus AS actual_bonus
            FROM lotto_predictions_army4 p
            LEFT JOIN lotto_draws d ON p.target_draw_no = d.draw_no
            WHERE p.brain_tag LIKE 'v13_%'
            ORDER BY p.target_draw_no DESC, p.brain_tag ASC, p.confidence DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return {"predictions": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/draws")
async def api_v13_draws(
    limit: int = 50,
    page: int | None = Query(default=None),
    per_page: int = Query(default=50, ge=1, le=200),
    draw_no: int | None = Query(default=None),
):
    """회차 목록. page 지정 시 페이지네이션, draw_no 지정 시 해당 회차만."""
    from app.lotto4.models import get_lotto4_db

    conn = get_lotto4_db()
    try:
        cnt_row = conn.execute("SELECT COUNT(*) FROM lotto_draws").fetchone()
        total = int(cnt_row[0] or 0)
        if draw_no is not None:
            row = conn.execute("SELECT * FROM lotto_draws WHERE draw_no = ?", (draw_no,)).fetchone()
            if not row:
                return {
                    "draws": [],
                    "total": total,
                    "page": 1,
                    "per_page": 0,
                    "total_pages": 0,
                    "filter_draw_no": draw_no,
                }
            return {
                "draws": [dict(row)],
                "total": total,
                "page": 1,
                "per_page": 1,
                "total_pages": 1,
                "filter_draw_no": draw_no,
            }
        if page is not None:
            per = max(1, min(int(per_page), 200))
            p = max(1, int(page))
            off = (p - 1) * per
            rows = conn.execute(
                """
                SELECT * FROM lotto_draws
                ORDER BY draw_no DESC LIMIT ? OFFSET ?
                """,
                (per, off),
            ).fetchall()
            total_pages = max(1, (total + per - 1) // per) if total else 1
            return {
                "draws": [dict(r) for r in rows],
                "total": total,
                "page": p,
                "per_page": per,
                "total_pages": total_pages,
            }
        lim = max(1, min(int(limit), 200))
        rows = conn.execute(
            "SELECT * FROM lotto_draws ORDER BY draw_no DESC LIMIT ?",
            (lim,),
        ).fetchall()
        # limit-only 모드: 3군 호환용 total=전체 행 수, 페이지 메타 포함
        total_pages = max(1, (total + lim - 1) // lim) if total else 1
        return {
            "draws": [dict(r) for r in rows],
            "total": total,
            "limit": lim,
            "page": 1,
            "per_page": lim,
            "total_pages": total_pages,
        }
    finally:
        conn.close()


@router.get("/brain/status")
async def api_v13_brain_status():
    """4군 8뇌 상태 — brain_profiles에 method·적중 누적."""

    from app.lotto4.models import get_lotto4_db
    from app.lotto4.v13_weights_v2 import (
        V13_BRAIN_METHOD,
        V13_V2_BRAIN_ORDER,
        V13_V2_HIDDEN_BRAINS,
    )

    conn = get_lotto4_db()
    try:
        rows = conn.execute(
            """
            SELECT brain_tag,
                   COUNT(*) AS total_predictions,
                   ROUND(AVG(CASE WHEN matched_count >= 0 THEN matched_count ELSE NULL END), 3) AS avg_match,
                   MAX(CASE WHEN matched_count >= 0 THEN matched_count ELSE NULL END) AS best_match,
                   SUM(CASE WHEN matched_count = 6 THEN 1 ELSE 0 END) AS rank1,
                   SUM(CASE WHEN matched_count = 5 AND bonus_matched = 1 THEN 1 ELSE 0 END) AS rank2,
                   SUM(CASE WHEN matched_count = 5 AND bonus_matched = 0 THEN 1 ELSE 0 END) AS rank3,
                   SUM(CASE WHEN matched_count = 4 THEN 1 ELSE 0 END) AS rank4,
                   SUM(CASE WHEN matched_count = 3 THEN 1 ELSE 0 END) AS rank5
            FROM lotto_predictions_army4
            WHERE brain_tag LIKE 'v13_%' AND matched_count >= -1
            GROUP BY brain_tag
            ORDER BY avg_match DESC
            """
        ).fetchall()
        total_pred = conn.execute(
            "SELECT COUNT(*) FROM lotto_predictions_army4 WHERE brain_tag LIKE 'v13_%' AND matched_count >= -1"
        ).fetchone()[0]
        best_row = conn.execute(
            """
            SELECT brain_tag, target_draw_no, matched_count, bonus_matched
            FROM lotto_predictions_army4
            WHERE brain_tag LIKE 'v13_%' AND matched_count >= 0
            ORDER BY matched_count DESC, bonus_matched DESC
            LIMIT 1
            """
        ).fetchone()
        best_record = dict(best_row) if best_row else None

        best_match = best_record["matched_count"] if best_record else 0
        if best_match >= 6:
            grade, grade_emoji = "역전 신", "👑"
        elif best_match >= 5:
            grade, grade_emoji = "역전 마스터", "🏆"
        elif best_match >= 4:
            grade, grade_emoji = "역전 엘리트", "⭐"
        else:
            grade, grade_emoji = "역전 수련생", "🎯"

        elite_thresholds = {
            "rank1": 6,
            "rank2": 5,
            "rank3": 5,
            "rank4": 4,
            "rank5": 3,
        }

        row_map = {dict(record)["brain_tag"]: dict(record) for record in rows}

        wrows = conn.execute(
            """
            SELECT brain_tag, current_weight
            FROM lotto_brain_weights_army4
            WHERE brain_tag LIKE 'v13_%'
            """
        ).fetchall()
        weights = {dict(r)["brain_tag"]: float(dict(r)["current_weight"]) for r in wrows}

        lrows = conn.execute(
            """
            SELECT brain_tag, MAX(target_draw_no) AS last_draw
            FROM lotto_predictions_army4
            WHERE brain_tag LIKE 'v13_%'
            GROUP BY brain_tag
            """
        ).fetchall()
        last_draws = {dict(r)["brain_tag"]: int(dict(r)["last_draw"]) for r in lrows}

        # brain_profiles에 1군 호환용 'method' 키 추가 (8뇌 고정 순서)
        brain_profiles = []
        for tag in V13_V2_BRAIN_ORDER:
            if tag in row_map:
                d = dict(row_map[tag])
            else:
                d = {
                    "brain_tag": tag,
                    "total_predictions": 0,
                    "avg_match": None,
                    "best_match": None,
                    "rank1": 0,
                    "rank2": 0,
                    "rank3": 0,
                    "rank4": 0,
                    "rank5": 0,
                }
            d["method"] = V13_BRAIN_METHOD.get(tag, tag)
            if d.get("avg_match") and d["avg_match"] >= 2.0:
                d["strength"] = "높은 평균 적중률"
            elif d.get("best_match") and d["best_match"] >= 4:
                d["strength"] = "폭발적 최고 기록"
            else:
                d["strength"] = "안정적 분석"
            d["current_weight"] = weights.get(tag)
            if tag in V13_V2_HIDDEN_BRAINS:
                d["status"] = "hidden"
                d["active"] = False
                d["hidden"] = True
            else:
                d["status"] = "active"
                d["active"] = True
                d["hidden"] = False
            d["last_predict_draw"] = last_draws.get(tag)
            brain_profiles.append(d)

        return {
            "grade": grade,
            "grade_emoji": grade_emoji,
            "total_predictions": total_pred,
            "best_record": best_record,
            "brain_profiles": brain_profiles,
            "elite_thresholds": elite_thresholds,
        }
    finally:
        conn.close()


@router.get("/brain/hall-of-fame")
async def api_v13_hall_of_fame(limit: int = 5000):
    """V11 명예의 전당 — 1군과 동일 기준: 3개 이상 적중, 최신·고적중 우선.

    읽기 전용. limit은 1~50000으로 클램프.
    """
    from app.lotto4.models import get_lotto4_db

    safe_limit = max(1, min(int(limit), 50_000))
    conn = get_lotto4_db()
    try:
        rows = conn.execute(
            """
            SELECT p.*,
                   d.draw_date AS draw_date,
                   d.num1 AS actual_1, d.num2 AS actual_2, d.num3 AS actual_3,
                   d.num4 AS actual_4, d.num5 AS actual_5, d.num6 AS actual_6,
                   d.bonus AS actual_bonus
            FROM lotto_predictions_army4 p
            LEFT JOIN lotto_draws d ON p.target_draw_no = d.draw_no
            WHERE p.brain_tag LIKE 'v13_%' AND p.matched_count >= 3
            ORDER BY p.matched_count DESC, p.bonus_matched DESC, p.target_draw_no DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
        return {"hall_of_fame": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/dashboard-summary")
async def api_v13_dashboard_summary():
    """4군 대시보드 요약 — 1군 응답 형식 호환 (brain_power 8뇌).

    1군 brain_power[i] keys: brain, label, rank1, rank2, rank3, rank4, rank5
    1군 learning_range keys: start, end, total_draws
    1군 scores keys: rank1_cnt, rank2_cnt, rank3_cnt, rank4_cnt, rank5_cnt,
                     rank1_pct, rank2_pct, rank3_pct, rank4_pct, rank5_pct,
                     total_hit_pct
    """
    from app.lotto4.models import get_lotto4_db
    from app.lotto4.v13_weights_v2 import V13_BRAIN_LABEL_UI, V13_V2_BRAIN_ORDER

    from datetime import datetime, timedelta

    conn = get_lotto4_db()
    try:
        # 1) 다음 회차
        max_draw = conn.execute("SELECT MAX(draw_no) FROM lotto_draws").fetchone()[0] or 0
        next_draw = max_draw + 1

        # 2) 다음 추첨일
        latest = conn.execute(
            "SELECT draw_no, draw_date FROM lotto_draws ORDER BY draw_no DESC LIMIT 1"
        ).fetchone()
        next_date_str = ""
        next_weekday = "토"
        if latest and latest["draw_date"]:
            try:
                last_dt = datetime.strptime(latest["draw_date"], "%Y-%m-%d")
                next_dt = last_dt + timedelta(days=7)
                next_date_str = next_dt.strftime("%Y-%m-%d")
                weekdays = ["월", "화", "수", "목", "금", "토", "일"]
                next_weekday = weekdays[next_dt.weekday()]
            except Exception:
                pass

        # 3) total_predictions (미채점 -1 포함)
        total_pred = conn.execute(
            "SELECT COUNT(*) FROM lotto_predictions_army4 WHERE brain_tag LIKE 'v13_%' AND matched_count >= -1"
        ).fetchone()[0]

        # 4) learning_range (1군 키: start, end, total_draws)
        lr = conn.execute(
            "SELECT MIN(target_draw_no) AS s, MAX(target_draw_no) AS e FROM lotto_predictions_army4 WHERE brain_tag LIKE 'v13_%'"
        ).fetchone()
        total_draws_row = conn.execute("SELECT COUNT(*) FROM lotto_draws").fetchone()[0]
        s_raw = int(lr["s"] or 0)
        e_raw = int(lr["e"] or 0)
        md_int = int(max_draw or 0)
        # MAX(target)가 당첨표보다 큰 행이 있으면 진행률이 100% 초과로 깨짐 → 마지막 회차로 클램프
        e_clamped = min(e_raw, md_int) if md_int else e_raw
        learning_range = {
            "start": s_raw,
            "end": e_clamped,
            "total_draws": total_draws_row,
        }

        # 5) rankings (1등/2등/3등 회차) — 목록은 최근 50건, *_total은 DB 전체 건수
        rankings: dict = {"rank1": [], "rank2": [], "rank3": []}
        for rank_key, where_clause in [
            ("rank1", "matched_count = 6"),
            ("rank2", "matched_count = 5 AND bonus_matched = 1"),
            ("rank3", "matched_count = 5 AND bonus_matched = 0"),
        ]:
            cnt_row = conn.execute(
                f"""
                SELECT COUNT(*) AS c FROM lotto_predictions_army4
                WHERE brain_tag LIKE 'v13_%' AND {where_clause}
                """
            ).fetchone()
            rankings[rank_key + "_total"] = int(cnt_row["c"] or 0)
            rows = conn.execute(
                f"""
                SELECT brain_tag, target_draw_no, num1, num2, num3, num4, num5, num6, bonus_matched
                FROM lotto_predictions_army4
                WHERE brain_tag LIKE 'v13_%' AND {where_clause}
                ORDER BY target_draw_no DESC
                LIMIT 50
                """
            ).fetchall()
            rankings[rank_key] = [dict(r) for r in rows]

        # 6) brain_power (1군 호환: brain, label, rank1~rank5)
        brain_stats = conn.execute(
            """
            SELECT brain_tag,
                   COUNT(*) AS n,
                   SUM(CASE WHEN matched_count = 6 THEN 1 ELSE 0 END) AS r1,
                   SUM(CASE WHEN matched_count = 5 AND bonus_matched = 1 THEN 1 ELSE 0 END) AS r2,
                   SUM(CASE WHEN matched_count = 5 AND bonus_matched = 0 THEN 1 ELSE 0 END) AS r3,
                   SUM(CASE WHEN matched_count = 4 THEN 1 ELSE 0 END) AS r4,
                   SUM(CASE WHEN matched_count = 3 THEN 1 ELSE 0 END) AS r5
            FROM lotto_predictions_army4
            WHERE brain_tag LIKE 'v13_%' AND matched_count >= 0
            GROUP BY brain_tag
            """
        ).fetchall()
        stats_map = {r["brain_tag"]: dict(r) for r in brain_stats}

        brain_power = []
        for tag in V13_V2_BRAIN_ORDER:
            s = stats_map.get(tag, {})
            brain_power.append(
                {
                    "brain": tag,
                    "label": V13_BRAIN_LABEL_UI.get(tag, tag),
                    "rank1": int(s.get("r1", 0) or 0),
                    "rank2": int(s.get("r2", 0) or 0),
                    "rank3": int(s.get("r3", 0) or 0),
                    "rank4": int(s.get("r4", 0) or 0),
                    "rank5": int(s.get("r5", 0) or 0),
                }
            )

        # 7) scores (1군 키: rank*_cnt, rank*_pct, total_hit_pct)
        rank_row = conn.execute(
            """
            SELECT
                SUM(CASE WHEN matched_count = 6 THEN 1 ELSE 0 END) AS r1,
                SUM(CASE WHEN matched_count = 5 AND bonus_matched = 1 THEN 1 ELSE 0 END) AS r2,
                SUM(CASE WHEN matched_count = 5 AND bonus_matched = 0 THEN 1 ELSE 0 END) AS r3,
                SUM(CASE WHEN matched_count = 4 THEN 1 ELSE 0 END) AS r4,
                SUM(CASE WHEN matched_count = 3 THEN 1 ELSE 0 END) AS r5,
                COUNT(*) AS total
            FROM lotto_predictions_army4
            WHERE brain_tag LIKE 'v13_%' AND matched_count >= 0
            """
        ).fetchone()
        r1 = rank_row["r1"] or 0
        r2 = rank_row["r2"] or 0
        r3 = rank_row["r3"] or 0
        r4 = rank_row["r4"] or 0
        r5 = rank_row["r5"] or 0
        total = rank_row["total"] or 1
        total_hit = r1 + r2 + r3 + r4 + r5

        scores = {
            "rank1_cnt": r1,
            "rank2_cnt": r2,
            "rank3_cnt": r3,
            "rank4_cnt": r4,
            "rank5_cnt": r5,
            "rank1_pct": round(r1 / total * 100, 4),
            "rank2_pct": round(r2 / total * 100, 4),
            "rank3_pct": round(r3 / total * 100, 4),
            "rank4_pct": round(r4 / total * 100, 4),
            "rank5_pct": round(r5 / total * 100, 4),
            "total_hit_pct": round(total_hit / total * 100, 4),
        }

        from app.lotto4.strategy_x_logging import (
            STRATEGY_X_BRAIN_LABEL_UI,
            STRATEGY_X_FIVE_BRAIN_TAGS,
        )

        sx_total = conn.execute(
            """
            SELECT COUNT(*) FROM lotto_predictions_army4
            WHERE brain_tag IN ({})
              AND matched_count >= 0
            """.format(",".join("?" for _ in STRATEGY_X_FIVE_BRAIN_TAGS)),
            STRATEGY_X_FIVE_BRAIN_TAGS,
        ).fetchone()[0]
        sx_lr = conn.execute(
            """
            SELECT MIN(target_draw_no) AS s, MAX(target_draw_no) AS e
            FROM lotto_predictions_army4
            WHERE brain_tag IN ({})
            """.format(",".join("?" for _ in STRATEGY_X_FIVE_BRAIN_TAGS)),
            STRATEGY_X_FIVE_BRAIN_TAGS,
        ).fetchone()
        sx_stats = conn.execute(
            """
            SELECT brain_tag,
                   COUNT(*) AS n,
                   SUM(CASE WHEN matched_count = 6 THEN 1 ELSE 0 END) AS r1,
                   SUM(CASE WHEN matched_count = 5 AND bonus_matched = 1 THEN 1 ELSE 0 END) AS r2,
                   SUM(CASE WHEN matched_count = 5 AND bonus_matched = 0 THEN 1 ELSE 0 END) AS r3,
                   SUM(CASE WHEN matched_count = 4 THEN 1 ELSE 0 END) AS r4,
                   SUM(CASE WHEN matched_count = 3 THEN 1 ELSE 0 END) AS r5,
                   ROUND(AVG(matched_count), 3) AS avg_m
            FROM lotto_predictions_army4
            WHERE brain_tag IN ({}) AND matched_count >= 0
            GROUP BY brain_tag
            """.format(",".join("?" for _ in STRATEGY_X_FIVE_BRAIN_TAGS)),
            STRATEGY_X_FIVE_BRAIN_TAGS,
        ).fetchall()
        sx_map = {r["brain_tag"]: dict(r) for r in sx_stats}
        strategy_x_brain_power = []
        for tag in STRATEGY_X_FIVE_BRAIN_TAGS:
            s = sx_map.get(tag, {})
            strategy_x_brain_power.append(
                {
                    "brain": tag,
                    "label": STRATEGY_X_BRAIN_LABEL_UI.get(tag, tag),
                    "rank1": int(s.get("r1", 0) or 0),
                    "rank2": int(s.get("r2", 0) or 0),
                    "rank3": int(s.get("r3", 0) or 0),
                    "rank4": int(s.get("r4", 0) or 0),
                    "rank5": int(s.get("r5", 0) or 0),
                    "avg_matched": float(s.get("avg_m") or 0),
                }
            )

        return {
            "next_draw_no": next_draw,
            "next_draw_date": next_date_str,
            "next_draw_weekday": next_weekday,
            "total_predictions": total_pred,
            "learning_range": learning_range,
            "rankings": rankings,
            "brain_power": brain_power,
            "scores": scores,
            "strategy_x_total_predictions": int(sx_total or 0),
            "strategy_x_learning_range": {
                "start": int(sx_lr["s"] or 0),
                "end": int(sx_lr["e"] or 0),
            },
            "strategy_x_brain_power": strategy_x_brain_power,
        }
    finally:
        conn.close()


@router.get("/draws/{draw_no}")
async def api_v13_draw_one(draw_no: int):
    """단일 회차 조회. lotto_draws 사용."""
    from app.lotto4.models import get_lotto4_db

    conn = get_lotto4_db()
    try:
        row = conn.execute("SELECT * FROM lotto_draws WHERE draw_no = ?", (draw_no,)).fetchone()
        if not row:
            return {"error": "not_found", "draw_no": draw_no}
        return {"draw": dict(row)}
    finally:
        conn.close()


@router.get("/stats/comprehensive")
async def api_v13_stats_comprehensive():
    """V11 종합 통계 — 1군 응답 형식 100% 호환.

    1군과 동일 로직을 그대로 재사용한다(읽기 전용).
    """
    from app.lotto.data_service import get_comprehensive_stats

    return get_comprehensive_stats()


def _prediction_tier_rank(matched_count: int, bonus_matched: int | None) -> tuple[int, str]:
    mc = int(matched_count or 0)
    bm = int(bonus_matched or 0)
    if mc >= 6:
        return 1, "1등"
    if mc == 5 and bm:
        return 2, "2등"
    if mc == 5:
        return 3, "3등"
    if mc == 4:
        return 4, "4등"
    if mc == 3:
        return 5, "5등"
    return 0, "-"


@router.get("/hall-of-fame")
async def api_v13_hall_of_fame_full(
    rank: int = Query(default=0, ge=0, le=5),
    brain: str | None = Query(default=None),
    limit: int = Query(default=3000, ge=1, le=10000),
):
    """명예의 전당 UI: 등수·뇌 필터, 뇌별 집계, 적중 번호 목록."""
    from app.lotto4.models import get_lotto4_db

    from app.lotto4.v13_weights_v2 import expand_v13_brain_tags_for_filter

    conn = get_lotto4_db()
    try:
        wheres = ["p.matched_count >= 3", "p.brain_tag LIKE 'v13_%'"]
        params: list = []
        if brain:
            tags = expand_v13_brain_tags_for_filter(brain.strip())
            if not tags:
                wheres.append("1=0")
            else:
                ph = ",".join("?" * len(tags))
                wheres.append(f"LOWER(p.brain_tag) IN ({ph})")
                params.extend(sorted(tags))
        if rank == 1:
            wheres.append("p.matched_count = 6")
        elif rank == 2:
            wheres.append("p.matched_count = 5 AND IFNULL(p.bonus_matched,0) = 1")
        elif rank == 3:
            wheres.append("p.matched_count = 5 AND IFNULL(p.bonus_matched,0) = 0")
        elif rank == 4:
            wheres.append("p.matched_count = 4")
        elif rank == 5:
            wheres.append("p.matched_count = 3")
        where_sql = " AND ".join(wheres)
        q = f"""
            SELECT p.target_draw_no AS draw_no, p.brain_tag,
                   p.matched_count, p.bonus_matched, p.confidence,
                   p.num1, p.num2, p.num3, p.num4, p.num5, p.num6,
                   d.num1 AS w1, d.num2 AS w2, d.num3 AS w3,
                   d.num4 AS w4, d.num5 AS w5, d.num6 AS w6, d.bonus AS win_bonus
            FROM lotto_predictions_army4 p
            JOIN lotto_draws d ON p.target_draw_no = d.draw_no
            WHERE {where_sql}
            ORDER BY p.target_draw_no DESC, p.matched_count DESC, p.confidence DESC
            LIMIT ?
        """
        params.append(limit)
        rows = conn.execute(q, tuple(params)).fetchall()

        records = []
        for r in rows:
            dct = dict(r)
            pred = [dct["num1"], dct["num2"], dct["num3"], dct["num4"], dct["num5"], dct["num6"]]
            win = [dct["w1"], dct["w2"], dct["w3"], dct["w4"], dct["w5"], dct["w6"]]
            pred_s = set(pred)
            win_s = set(win)
            matched_nums = sorted(pred_s & win_s)
            tr, tlabel = _prediction_tier_rank(dct["matched_count"], dct.get("bonus_matched"))
            records.append(
                {
                    "draw_no": dct["draw_no"],
                    "brain_tag": dct["brain_tag"],
                    "matched_count": dct["matched_count"],
                    "bonus_matched": int(dct.get("bonus_matched") or 0),
                    "tier_rank": tr,
                    "tier_label": tlabel,
                    "confidence": dct.get("confidence"),
                    "numbers": pred,
                    "winning_numbers": win,
                    "matched_numbers": matched_nums,
                    "bonus_ball": dct.get("win_bonus"),
                }
            )

        brain_rows = conn.execute(
            """
            SELECT brain_tag,
                   SUM(CASE WHEN matched_count = 6 THEN 1 ELSE 0 END) AS r1,
                   SUM(CASE WHEN matched_count = 5 AND IFNULL(bonus_matched,0) = 1 THEN 1 ELSE 0 END) AS r2,
                   SUM(CASE WHEN matched_count = 5 AND IFNULL(bonus_matched,0) = 0 THEN 1 ELSE 0 END) AS r3,
                   SUM(CASE WHEN matched_count = 4 THEN 1 ELSE 0 END) AS r4,
                   SUM(CASE WHEN matched_count = 3 THEN 1 ELSE 0 END) AS r5,
                   COUNT(*) AS total_hits
            FROM lotto_predictions_army4
            WHERE matched_count >= 3 AND brain_tag LIKE 'v13_%'
            GROUP BY brain_tag
            ORDER BY brain_tag
            """
        ).fetchall()
        brain_summary = [dict(x) for x in brain_rows]

        return {
            "filters": {"rank": rank, "brain": brain},
            "records": records,
            "brain_summary": brain_summary,
        }
    finally:
        conn.close()


@router.get("/stats/comprehensive-full")
async def api_v13_stats_comprehensive_full():
    """lotto4.db 기반 종합 통계 + 최근 10·30·50회 부분 통계."""
    from app.lotto.data_service import (
        analyze_consecutive,
        analyze_number_frequency,
        analyze_odd_even,
        analyze_range_distribution,
        analyze_sum_range,
        get_all_draws,
        get_comprehensive_stats,
    )

    base = get_comprehensive_stats()
    if base.get("error"):
        return base

    draws = get_all_draws()

    def _pack(sub: list[dict]) -> dict:
        if not sub:
            return {"draw_count": 0}
        return {
            "draw_count": len(sub),
            "frequency": analyze_number_frequency(sub),
            "odd_even": analyze_odd_even(sub),
            "range_distribution": analyze_range_distribution(sub),
            "sum_range": analyze_sum_range(sub),
            "consecutive": analyze_consecutive(sub),
        }

    n = len(draws)
    base["trend_last_10"] = _pack(draws[max(0, n - 10) :])
    base["trend_last_30"] = _pack(draws[max(0, n - 30) :])
    base["trend_last_50"] = _pack(draws[max(0, n - 50) :])
    base["db_note"] = "lotto_draws from d:\\3kweon\\data\\lotto4.db (app.lotto.models.LOTTO_DB_PATH)"
    return base


@router.get("/stats/cooccur-3")
async def api_v13_stats_cooccur_3(top: int = Query(default=20, ge=1, le=500)):
    from app.lotto4.models import get_lotto4_db

    conn = get_lotto4_db()
    try:
        rows = conn.execute(
            """
            SELECT num1, num2, num3, count, last_draw_no, last_draw_date, updated_at
            FROM lotto_cooccur_3
            ORDER BY count DESC, num1, num2, num3
            LIMIT ?
            """,
            (top,),
        ).fetchall()
        return {"items": [dict(r) for r in rows], "top": top}
    finally:
        conn.close()


@router.get("/stats/cooccur-4")
async def api_v13_stats_cooccur_4(top: int = Query(default=20, ge=1, le=500)):
    from app.lotto4.models import get_lotto4_db

    conn = get_lotto4_db()
    try:
        rows = conn.execute(
            """
            SELECT num1, num2, num3, num4, count, last_draw_no, last_draw_date, updated_at
            FROM lotto_cooccur_4
            ORDER BY count DESC, num1, num2, num3, num4
            LIMIT ?
            """,
            (top,),
        ).fetchall()
        return {"items": [dict(r) for r in rows], "top": top}
    finally:
        conn.close()


@router.get("/stats/bonus")
async def api_v13_stats_bonus():
    from app.lotto4.models import get_lotto4_db

    conn = get_lotto4_db()
    try:
        rows = conn.execute(
            """
            SELECT bonus_no, total_count, last_draw_no, coappear_with, updated_at
            FROM lotto_bonus_stats
            ORDER BY total_count DESC, bonus_no
            """
        ).fetchall()
        return {"items": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/stats/number-freq")
async def api_v13_stats_number_freq():
    from app.lotto4.models import get_lotto4_db

    conn = get_lotto4_db()
    try:
        rows = conn.execute(
            """
            SELECT number, total_count, rank_most, rank_least, updated_at
            FROM lotto_number_freq
            ORDER BY number ASC
            """
        ).fetchall()
        return {"items": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/collect-status")
async def api_v13_collect_status():
    from app.lotto.data_service import get_collection_hint
    from app.lotto.models import init_lotto_db

    init_lotto_db()
    return get_collection_hint()


def _v13_lotto_draw_exists(draw_no: int) -> bool:
    from app.lotto.models import get_lotto_db, init_lotto_db

    init_lotto_db()
    conn = get_lotto_db()
    try:
        row = conn.execute("SELECT 1 FROM lotto_draws WHERE draw_no = ? LIMIT 1", (draw_no,)).fetchone()
        return row is not None
    finally:
        conn.close()


def _v13_probe_latest_official_after(db_max: int) -> int:
    """DB max 이후로 API가 응답하는 마지막 회차 번호(db_max 포함). 미개최면 db_max."""
    from app.lotto.data_service import fetch_single_draw

    n = int(db_max) + 1
    last_good = int(db_max)
    for _ in range(80):
        d = fetch_single_draw(n)
        if d:
            last_good = int(d["draw_no"])
            n = last_good + 1
        else:
            break
    return last_good


def _v13_collect_one_draw_no(draw_no: int, logger) -> tuple[bool, list[int], list[str]]:
    """단일 회차 수집. 성공 시 collected에 신규 저장 회차만 포함."""
    from app.lotto.data_service import fetch_single_draw, save_draw_full

    from app.lotto4.army4_draw_sync import refresh_army4_predictions_for_draw

    collected: list[int] = []
    errors: list[str] = []
    existed_before = _v13_lotto_draw_exists(draw_no)
    draw = fetch_single_draw(draw_no)
    if not draw:
        errors.append(f"{draw_no}회: API 응답 없음(미추첨·네트워크)")
        return False, collected, errors
    save_draw_full(draw)
    if not existed_before and _v13_lotto_draw_exists(draw_no):
        collected.append(int(draw["draw_no"]))
        try:
            sync = refresh_army4_predictions_for_draw(int(draw["draw_no"]))
            logger.info("army4 적중 갱신 %s: %s행", draw["draw_no"], sync.get("updated", 0))
        except Exception as e:  # noqa: BLE001
            logger.warning("army4 sync: %s", e)
            errors.append(f"{draw['draw_no']}회: army4 갱신 오류 ({e})")
    try:
        from app.lotto4.all_combos_service import sync_winner_for_draw

        wr = sync_winner_for_draw(draw)
        if wr.get("ok"):
            logger.info("all_combos 당첨 갱신 %s회 → combo_no %s", draw["draw_no"], wr.get("combo_no"))
    except Exception as e:  # noqa: BLE001
        logger.warning("all_combos sync: %s", e)
    return True, collected, errors


def _v13_collect_forward_from(next_no: int, logger) -> tuple[list[int], list[str]]:
    """next_no부터 연속으로 API 성공하는 동안 수집."""
    collected: list[int] = []
    errors: list[str] = []
    n = int(next_no)
    while True:
        ok, part, err = _v13_collect_one_draw_no(n, logger)
        if not ok:
            break
        collected.extend(part)
        if err:
            errors.extend(err)
        n += 1
    return collected, errors


@router.post("/collect-draws")
async def api_v13_collect_draws(request: Request):
    """동행복권 API 수집. body: {mode: single|all|latest, draw_no?: int} (draw_no는 single 전용)."""
    import logging

    from app.lotto.data_service import get_collection_hint, init_lotto_db

    logger = logging.getLogger(__name__)
    init_lotto_db()

    body: dict = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}

    mode = str(body.get("mode") or "single").strip().lower()
    hint_before = get_collection_hint()
    db_max = int(hint_before.get("max_draw_no") or 0)
    next_no = int(hint_before.get("next_draw_no") or 1)

    collected: list[int] = []
    errors: list[str] = []

    if mode == "all":
        c, e = _v13_collect_forward_from(next_no, logger)
        collected, errors = c, e
        ok = True
    elif mode == "latest":
        latest_off = _v13_probe_latest_official_after(db_max)
        if latest_off <= db_max:
            ok = True
        else:
            ok_one, part, err = _v13_collect_one_draw_no(latest_off, logger)
            ok = ok_one
            collected.extend(part)
            errors.extend(err)
    elif mode == "single":
        raw_no = body.get("draw_no")
        if raw_no is not None and str(raw_no).strip() != "":
            try:
                target = int(raw_no)
            except (TypeError, ValueError):
                ok = False
                errors.append("draw_no는 정수여야 합니다.")
                hint_after = get_collection_hint()
                return {
                    "ok": ok,
                    "collected": collected,
                    "count": 0,
                    "errors": errors,
                    "mode": mode,
                    "hint_before": hint_before,
                    "hint_after": hint_after,
                }
        else:
            target = next_no
        ok_one, part, err = _v13_collect_one_draw_no(target, logger)
        ok = ok_one
        collected.extend(part)
        errors.extend(err)
    else:
        ok = False
        errors.append(f"알 수 없는 mode: {mode}")

    hint_after = get_collection_hint()
    return {
        "ok": ok,
        "collected": collected,
        "count": len(collected),
        "errors": errors,
        "mode": mode,
        "hint_before": hint_before,
        "hint_after": hint_after,
    }


@router.get("/brain/weight-history")
async def api_v13_brain_weight_history(
    limit: int = Query(default=500, ge=1, le=10000),
    brain: str | None = Query(default=None),
):
    from app.lotto4.models import get_lotto4_db

    conn = get_lotto4_db()
    try:
        if brain:
            rows = conn.execute(
                """
                SELECT * FROM lotto_weight_log_army4
                WHERE LOWER(brain_tag) = LOWER(?)
                ORDER BY draw_no DESC, id DESC
                LIMIT ?
                """,
                (brain.strip(), limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM lotto_weight_log_army4
                ORDER BY draw_no DESC, brain_tag ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return {"entries": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/brain/nano-summary")
async def api_v13_brain_nano_summary():
    """뇌별 1~5등 건수 (나노 전적)."""
    from app.lotto4.models import get_lotto4_db

    conn = get_lotto4_db()
    try:
        rows = conn.execute(
            """
            SELECT brain_tag,
                   SUM(CASE WHEN matched_count = 6 THEN 1 ELSE 0 END) AS r1,
                   SUM(CASE WHEN matched_count = 5 AND IFNULL(bonus_matched,0) = 1 THEN 1 ELSE 0 END) AS r2,
                   SUM(CASE WHEN matched_count = 5 AND IFNULL(bonus_matched,0) = 0 THEN 1 ELSE 0 END) AS r3,
                   SUM(CASE WHEN matched_count = 4 THEN 1 ELSE 0 END) AS r4,
                   SUM(CASE WHEN matched_count = 3 THEN 1 ELSE 0 END) AS r5
            FROM lotto_predictions_army4
            WHERE brain_tag LIKE 'v13_%' AND matched_count >= 0
            GROUP BY brain_tag
            """
        ).fetchall()
        return {"brains": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/brain/ranks")
async def api_v13_brain_ranks():
    """가중치 기준 뇌 순위 (#1…)."""
    from app.lotto4.models import get_lotto4_db

    conn = get_lotto4_db()
    try:
        rows = conn.execute(
            """
            SELECT brain_tag, current_weight
            FROM lotto_brain_weights_army4
            WHERE brain_tag LIKE 'v13_%'
            ORDER BY current_weight DESC
            """
        ).fetchall()
        out = []
        for i, r in enumerate(rows, start=1):
            d = dict(r)
            d["rank"] = i
            out.append(d)
        return {"ranked": out}
    finally:
        conn.close()


def _jaccard(a: set[int], b: set[int]) -> float:
    if not a and not b:
        return 1.0
    u = a | b
    if not u:
        return 0.0
    return len(a & b) / len(u)


@router.get("/brain/analysis")
async def api_v13_brain_analysis():
    """뇌별 성능·다양성·쌍별 Jaccard (최근 예측 샘플)."""
    from collections import defaultdict

    from app.lotto4.models import get_lotto4_db

    conn = get_lotto4_db()
    try:
        perf = conn.execute(
            """
            SELECT brain_tag,
                   COUNT(*) AS n_pred,
                   ROUND(AVG(matched_count), 4) AS avg_mc,
                   MAX(matched_count) AS max_mc,
                   SUM(CASE WHEN matched_count >= 3 THEN 1 ELSE 0 END) AS hit_ge3
            FROM lotto_predictions_army4
            WHERE brain_tag LIKE 'v13_%' AND matched_count >= 0
            GROUP BY brain_tag
            """
        ).fetchall()
        perf_list = [dict(r) for r in perf]

        wrows = conn.execute(
            "SELECT brain_tag, current_weight FROM lotto_brain_weights_army4 WHERE brain_tag LIKE 'v13_%'"
        ).fetchall()
        weights = {dict(r)["brain_tag"]: float(dict(r)["current_weight"]) for r in wrows}

        rows = conn.execute(
            """
            SELECT target_draw_no, brain_tag, num1, num2, num3, num4, num5, num6, confidence
            FROM lotto_predictions_army4
            WHERE brain_tag LIKE 'v13_%'
            ORDER BY target_draw_no DESC, confidence DESC
            LIMIT 4000
            """
        ).fetchall()

        by_draw: dict[int, dict[str, set[int]]] = defaultdict(dict)
        for r in rows:
            dct = dict(r)
            dn = int(dct["target_draw_no"])
            tag = str(dct["brain_tag"])
            if tag in by_draw[dn]:
                continue
            by_draw[dn][tag] = {
                dct["num1"],
                dct["num2"],
                dct["num3"],
                dct["num4"],
                dct["num5"],
                dct["num6"],
            }

        tags = sorted({t for d in by_draw.values() for t in d})
        jaccard_pairs: list[dict] = []
        for i, ta in enumerate(tags):
            for tb in tags[i + 1 :]:
                sims = []
                for _dn, pmap in by_draw.items():
                    if ta in pmap and tb in pmap:
                        sims.append(_jaccard(pmap[ta], pmap[tb]))
                jaccard_pairs.append(
                    {
                        "brain_a": ta,
                        "brain_b": tb,
                        "avg_jaccard": round(sum(sims) / len(sims), 4) if sims else None,
                        "sample_draws": len(sims),
                    }
                )

        diversity: list[dict] = []
        for tag in tags:
            sums = []
            for _dn, pmap in by_draw.items():
                if tag not in pmap:
                    continue
                nums = pmap[tag]
                sums.append(sum(nums))
            diversity.append(
                {
                    "brain_tag": tag,
                    "sample_sets": len(sums),
                    "sum_mean": round(sum(sums) / len(sums), 2) if sums else None,
                    "sum_std": None,
                }
            )
        for d in diversity:
            tag = d["brain_tag"]
            sums = []
            for _dn, pmap in by_draw.items():
                if tag in pmap:
                    sums.append(sum(pmap[tag]))
            if len(sums) > 1:
                m = sum(sums) / len(sums)
                var = sum((s - m) ** 2 for s in sums) / (len(sums) - 1)
                d["sum_std"] = round(var**0.5, 2)

        for p in perf_list:
            p["current_weight"] = weights.get(p["brain_tag"])

        return {
            "performance": perf_list,
            "jaccard_pairs": jaccard_pairs,
            "diversity": diversity,
        }
    finally:
        conn.close()


# --- UI·문서 호환 별칭 (lotto3 스타일 경로) ---
@router.get("/dashboard")
async def api_v13_dashboard_alias():
    return await api_v13_dashboard_summary()


@router.get("/truth")
async def api_v13_truth():
    """엔진3: 로또의 진실 — 검증 raw JSON 기반 미신파괴 카드."""
    from app.lotto4.truth_data import get_truth_payload

    return get_truth_payload()


@router.post("/strategy_x/popularity/{target_draw_no}")
async def api_v13_strategy_x_popularity(target_draw_no: int):
    """전략 X 1뇌: 역사적 인기번호 기반 조합 생성 (5세트)."""
    from app.lotto4.brains.popularity_freq_brain import generate_popularity_sets

    return generate_popularity_sets(int(target_draw_no))


@router.post("/strategy_x/pair/{target_draw_no}")
async def api_v13_strategy_x_pair(target_draw_no: int):
    """전략 X 2뇌: 역사적 인기번호쌍 기반 조합 생성 (5세트)."""
    from app.lotto4.brains.popularity_pair_brain import generate_pair_sets

    return generate_pair_sets(int(target_draw_no))


@router.post("/strategy_x/shape/{target_draw_no}")
async def api_v13_strategy_x_shape(target_draw_no: int):
    """전략 X 3뇌: 역사적 당첨 형태 기반 조합 생성 (5세트)."""
    from app.lotto4.brains.shape_brain import generate_shape_sets

    return generate_shape_sets(int(target_draw_no))


@router.post("/strategy_x/hyena/{target_draw_no}")
async def api_v13_strategy_x_hyena(target_draw_no: int):
    """전략 X 하이에나: 5뇌 walk-forward 조율 (5세트) + 예측 로깅."""
    from app.lotto4.strategy_x_logging import generate_and_save_hyena

    return generate_and_save_hyena(int(target_draw_no))


@router.post("/strategy_x/cooccur/{target_draw_no}")
async def api_v13_strategy_x_cooccur(target_draw_no: int):
    """전략 X 5뇌: 동반출현 체인 기반 조합 생성 (5세트) + 예측 로깅."""
    from app.lotto4.strategy_x_logging import generate_and_save_cooccur

    return generate_and_save_cooccur(int(target_draw_no))


@router.post("/strategy_x/recommend/{target_draw_no}")
async def api_v13_strategy_x_recommend(target_draw_no: int):
    """전략 X 4뇌: 1~3뇌 신호 종합 최종 추천 (5세트) + 예측 로깅."""
    from app.lotto4.strategy_x_logging import generate_and_save_recommend

    return generate_and_save_recommend(int(target_draw_no))


@router.get("/strategy_x/stats")
async def api_v13_strategy_x_stats(
    start_draw: int = 262, end_draw: int = 1228
):
    """전략 X 5뇌 적중 통계 (대시보드 읽기용)."""
    from app.lotto4.models import get_lotto4_db
    from app.lotto4.strategy_x_logging import STRATEGY_X_FIVE_BRAIN_TAGS

    conn = get_lotto4_db()
    try:
        placeholders = ",".join("?" for _ in STRATEGY_X_FIVE_BRAIN_TAGS)
        rows = conn.execute(
            f"""
            SELECT brain_tag, COUNT(1) AS n, ROUND(AVG(matched_count), 3) AS avg_m,
                   MAX(matched_count) AS best,
                   SUM(CASE WHEN matched_count=6 THEN 1 ELSE 0 END) AS r1,
                   SUM(CASE WHEN matched_count=5 AND bonus_matched=1 THEN 1 ELSE 0 END) AS r2,
                   SUM(CASE WHEN matched_count=5 AND bonus_matched=0 THEN 1 ELSE 0 END) AS r3,
                   SUM(CASE WHEN matched_count=4 THEN 1 ELSE 0 END) AS r4,
                   SUM(CASE WHEN matched_count=3 THEN 1 ELSE 0 END) AS r5
            FROM lotto_predictions_army4
            WHERE matched_count >= 0 AND brain_tag IN ({placeholders})
              AND target_draw_no BETWEEN ? AND ?
            GROUP BY brain_tag
            ORDER BY brain_tag
            """,
            (*STRATEGY_X_FIVE_BRAIN_TAGS, int(start_draw), int(end_draw)),
        ).fetchall()
        return {
            "range": f"{start_draw}~{end_draw}",
            "strategy_x_brains": [dict(r) for r in rows],
            "brain_tags": list(STRATEGY_X_FIVE_BRAIN_TAGS),
        }
    finally:
        conn.close()


@router.get("/strategy_x/predictions/draw/{target_draw_no}")
async def api_v13_strategy_x_predictions_for_draw(target_draw_no: int):
    """단일 회차 strategy_x 5뇌 예측 (읽기 전용)."""
    from app.lotto4.brains.cooccur_brain_v13 import DISCLAIMER as COOCCUR_DISCLAIMER
    from app.lotto4.brains.hyena_coordinator_v13 import DISCLAIMER as HYENA_DISCLAIMER
    from app.lotto4.brains.popularity_freq_brain import DISCLAIMER as FREQ_DISCLAIMER
    from app.lotto4.brains.popularity_pair_brain import DISCLAIMER as PAIR_DISCLAIMER
    from app.lotto4.brains.shape_brain import DISCLAIMER as SHAPE_DISCLAIMER
    from app.lotto4.models import get_lotto4_db
    from app.lotto4.strategy_x_logging import (
        STRATEGY_X_BRAIN_LABEL_UI,
        STRATEGY_X_FIVE_BRAIN_TAGS,
    )

    disclaimers = {
        "strategy_x_popularity_freq": FREQ_DISCLAIMER,
        "strategy_x_popularity_pair": PAIR_DISCLAIMER,
        "strategy_x_shape": SHAPE_DISCLAIMER,
        "strategy_x_cooccur": COOCCUR_DISCLAIMER,
        "strategy_x_hyena": HYENA_DISCLAIMER,
    }

    conn = get_lotto4_db()
    try:
        placeholders = ",".join("?" for _ in STRATEGY_X_FIVE_BRAIN_TAGS)
        rows = conn.execute(
            f"""
            SELECT p.*, d.num1 AS actual_1, d.num2 AS actual_2, d.num3 AS actual_3,
                   d.num4 AS actual_4, d.num5 AS actual_5, d.num6 AS actual_6,
                   d.bonus AS actual_bonus
            FROM lotto_predictions_army4 p
            LEFT JOIN lotto_draws d ON p.target_draw_no = d.draw_no
            WHERE p.brain_tag IN ({placeholders}) AND p.target_draw_no = ?
            ORDER BY p.brain_tag ASC, p.method ASC
            """,
            (*STRATEGY_X_FIVE_BRAIN_TAGS, int(target_draw_no)),
        ).fetchall()
        brain_meta = {
            tag: {
                "label": STRATEGY_X_BRAIN_LABEL_UI.get(tag, tag),
                "disclaimer": disclaimers.get(tag, ""),
                "is_final": tag == "strategy_x_hyena",
            }
            for tag in STRATEGY_X_FIVE_BRAIN_TAGS
        }
        return {
            "target_draw_no": int(target_draw_no),
            "predictions": [dict(r) for r in rows],
            "brain_meta": brain_meta,
            "brain_order": list(STRATEGY_X_FIVE_BRAIN_TAGS),
        }
    finally:
        conn.close()


@router.get("/strategy_x/fullbacktest/stats")
async def api_v13_strategy_x_fullbacktest_stats(
    start_draw: int = 262, end_draw: int = 1228
):
    """lotto_fullbacktest_army4 strategy_x 5뇌 집계."""
    from app.lotto4.models import get_lotto4_db
    from app.lotto4.strategy_x_logging import STRATEGY_X_FIVE_BRAIN_TAGS

    conn = get_lotto4_db()
    try:
        placeholders = ",".join("?" for _ in STRATEGY_X_FIVE_BRAIN_TAGS)
        rows = conn.execute(
            f"""
            SELECT brain_tag, COUNT(1) AS n, ROUND(AVG(matched_count), 3) AS avg_m,
                   MAX(matched_count) AS best
            FROM lotto_fullbacktest_army4
            WHERE matched_count >= 0 AND brain_tag IN ({placeholders})
              AND draw_no BETWEEN ? AND ?
            GROUP BY brain_tag
            ORDER BY brain_tag
            """,
            (*STRATEGY_X_FIVE_BRAIN_TAGS, int(start_draw), int(end_draw)),
        ).fetchall()
        return {
            "range": f"{start_draw}~{end_draw}",
            "fullbacktest_brains": [dict(r) for r in rows],
        }
    finally:
        conn.close()


@router.get("/predictions/{target_draw_no:int}")
async def api_v13_predictions_path_alias(target_draw_no: int):
    return await api_v13_predictions_for_draw(target_draw_no)


@router.get("/tier-wins/{draw_no:int}")
async def api_v13_tier_wins_alias(draw_no: int):
    return await api_v13_predictions_tier_wins(draw_no)


def _draw_row_sorted_nums(row: dict) -> tuple[int, ...]:
    return tuple(
        sorted(
            int(row[f"num{i}"])
            for i in range(1, 7)
        )
    )


def _combo_item_from_draw_row(row: dict) -> dict:
    from app.lotto4.combinadic import TOTAL_COMBOS, combo_to_no

    nums = _draw_row_sorted_nums(row)
    return {
        "draw_no": int(row["draw_no"]),
        "draw_date": row.get("draw_date"),
        "numbers": list(nums),
        "bonus": row.get("bonus"),
        "combo_no": combo_to_no(nums),
        "combo_total": TOTAL_COMBOS,
        "first_prize": row.get("first_prize"),
        "first_winners": row.get("first_winners"),
    }


def _fetch_all_combo_draw_rows(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT draw_no, draw_date, num1, num2, num3, num4, num5, num6, bonus,
               first_prize, first_winners
        FROM lotto_draws
        ORDER BY draw_no ASC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _find_draws_with_numbers(conn, nums: tuple[int, ...]) -> list[dict]:
    target = tuple(sorted(nums))
    matches: list[dict] = []
    for row in _fetch_all_combo_draw_rows(conn):
        if _draw_row_sorted_nums(row) == target:
            matches.append(
                {
                    "draw_no": int(row["draw_no"]),
                    "draw_date": row.get("draw_date"),
                }
            )
    return matches


@router.get("/combo/draw/{draw_no:int}")
async def api_v13_combo_draw(draw_no: int):
    """회차당첨 + 814만 순위(combo_no) — lotto_draws 읽기 전용."""
    from app.lotto4.models import get_lotto4_db

    conn = get_lotto4_db()
    try:
        row = conn.execute(
            """
            SELECT draw_no, draw_date, num1, num2, num3, num4, num5, num6, bonus,
                   first_prize, first_winners
            FROM lotto_draws WHERE draw_no = ?
            """,
            (int(draw_no),),
        ).fetchone()
        if not row:
            return {"error": "not_found", "draw_no": draw_no}
        return {"draw": _combo_item_from_draw_row(dict(row))}
    finally:
        conn.close()


@router.get("/combo/all")
async def api_v13_combo_all(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    order: str = Query(default="draw_no_desc"),
    draw_no: int | None = Query(default=None),
    q: str | None = Query(default=None),
):
    """전체 회차 당첨 + combo_no 목록 (페이지네이션)."""
    from app.lotto4.models import get_lotto4_db

    conn = get_lotto4_db()
    try:
        items = [_combo_item_from_draw_row(r) for r in _fetch_all_combo_draw_rows(conn)]

        if draw_no is not None:
            items = [i for i in items if i["draw_no"] == int(draw_no)]
        elif q and str(q).strip():
            qs = str(q).strip()
            items = [i for i in items if qs in str(i["draw_no"])]

        order_key = str(order or "draw_no_desc").lower()
        sort_map = {
            "draw_no_asc": lambda x: x["draw_no"],
            "draw_no_desc": lambda x: -x["draw_no"],
            "combo_no_asc": lambda x: x["combo_no"],
            "combo_no_desc": lambda x: -x["combo_no"],
            "date_asc": lambda x: (x.get("draw_date") or "", x["draw_no"]),
            "date_desc": lambda x: (x.get("draw_date") or "", -x["draw_no"]),
        }
        key_fn = sort_map.get(order_key, sort_map["draw_no_desc"])
        items = sorted(items, key=key_fn)

        total = len(items)
        per = max(1, min(int(per_page), 200))
        p = max(1, int(page))
        total_pages = max(1, (total + per - 1) // per) if total else 0
        if total == 0:
            p = 1
        elif p > total_pages:
            p = total_pages
        start = (p - 1) * per
        page_items = items[start : start + per]

        return {
            "items": page_items,
            "total": total,
            "page": p,
            "per_page": per,
            "total_pages": total_pages,
            "order": order_key,
            "filter_draw_no": draw_no,
            "q": q,
        }
    finally:
        conn.close()


@router.get("/combo/lookup")
async def api_v13_combo_lookup(
    nums: str | None = Query(default=None),
    n1: int | None = Query(default=None),
    n2: int | None = Query(default=None),
    n3: int | None = Query(default=None),
    n4: int | None = Query(default=None),
    n5: int | None = Query(default=None),
    n6: int | None = Query(default=None),
):
    """임의 6번호 → 814만 순위 + 역대 당첨 출현 회차."""
    from fastapi import HTTPException

    from app.lotto4.combinadic import TOTAL_COMBOS, combo_to_no, no_to_combo
    from app.lotto4.models import get_lotto4_db

    raw: list[int] = []
    if nums and str(nums).strip():
        parts = [p.strip() for p in str(nums).replace(" ", "").split(",") if p.strip()]
        try:
            raw = [int(p) for p in parts]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="nums 형식 오류 (예: 1,2,3,4,5,6)") from exc
    else:
        params = [n1, n2, n3, n4, n5, n6]
        if any(v is None for v in params):
            raise HTTPException(status_code=400, detail="6개 번호가 필요합니다")
        raw = [int(v) for v in params if v is not None]

    try:
        sorted_nums = tuple(sorted(raw))
        combo_no = combo_to_no(sorted_nums)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    conn = get_lotto4_db()
    try:
        appearances = _find_draws_with_numbers(conn, sorted_nums)
    finally:
        conn.close()

    return {
        "numbers": list(sorted_nums),
        "combo_no": combo_no,
        "combo_total": TOTAL_COMBOS,
        "combo_rank_label": f"{combo_no:,} / {TOTAL_COMBOS:,}",
        "appeared": len(appearances) > 0,
        "appearance_count": len(appearances),
        "appearances": appearances,
        "verify_roundtrip": list(no_to_combo(combo_no)),
    }


@router.get("/allcombos/meta")
async def api_v13_allcombos_meta():
    """814만 테이블 준비 상태."""
    from app.lotto4.all_combos_service import get_meta

    return get_meta()


@router.get("/allcombos")
async def api_v13_allcombos(
    page: int | None = Query(default=None, ge=1),
    per_page: int = Query(default=120, ge=1, le=500),
    start: int = Query(default=1, ge=1),
    count: int = Query(default=120, ge=1, le=500),
    winners_only: bool = Query(default=False),
):
    """페이지네이션(page·per_page) 또는 start·count 윈도우."""
    from app.lotto4.all_combos_service import fetch_combo_page, fetch_combo_range, get_meta

    meta = get_meta()
    if not meta.get("ready"):
        return {
            "error": "not_ready",
            "message": "20분할 part DB 적재 필요 (tools/build_lotto_all_combos.py)",
            **meta,
        }
    if page is not None:
        return fetch_combo_page(page, per_page, winners_only=winners_only)
    return fetch_combo_range(start, count, winners_only=winners_only)


@router.get("/allcombos/jump")
async def api_v13_allcombos_jump(
    combo_no: int = Query(..., ge=1),
    per_page: int = Query(default=120, ge=1, le=500),
):
    """특정 순위 점프."""
    from app.lotto4.all_combos_service import fetch_combo_jump, get_meta

    meta = get_meta()
    if not meta.get("ready"):
        return {"error": "not_ready", **meta}
    return fetch_combo_jump(combo_no, per_page=per_page)


@router.get("/allcombos/search")
async def api_v13_allcombos_search(
    combo_no: int | None = Query(default=None, ge=1),
    per_page: int = Query(default=120, ge=1, le=500),
    nums: str | None = Query(default=None),
    n1: int | None = Query(default=None),
    n2: int | None = Query(default=None),
    n3: int | None = Query(default=None),
    n4: int | None = Query(default=None),
    n5: int | None = Query(default=None),
    n6: int | None = Query(default=None),
):
    """순위(combo_no) 또는 6번호 → 조합 조회."""
    from fastapi import HTTPException

    from app.lotto4.all_combos_service import (
        TOTAL_COMBOS,
        get_meta,
        search_combo_by_combo_no,
        search_combo_by_numbers,
    )

    meta = get_meta()
    if not meta.get("ready"):
        return {"error": "not_ready", **meta}

    if combo_no is not None:
        cno = int(combo_no)
        if cno < 1 or cno > TOTAL_COMBOS:
            raise HTTPException(status_code=400, detail=f"순위는 1~{TOTAL_COMBOS:,} 범위입니다")
        return search_combo_by_combo_no(cno, per_page=per_page)

    raw: list[int] = []
    if nums and str(nums).strip():
        text = str(nums).strip()
        parts = [p.strip() for p in text.replace(" ", "").split(",") if p.strip()]
        if len(parts) == 6:
            try:
                candidate = [int(p) for p in parts]
                if all(1 <= n <= 45 for n in candidate):
                    return search_combo_by_numbers(candidate, per_page=per_page)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="번호 형식 오류") from exc
        collapsed = text.replace(",", "").replace(" ", "")
        if collapsed.isdigit():
            cno = int(collapsed)
            if 1 <= cno <= TOTAL_COMBOS:
                return search_combo_by_combo_no(cno, per_page=per_page)
        try:
            raw = [int(p) for p in parts]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="nums 형식 오류") from exc
    else:
        params = [n1, n2, n3, n4, n5, n6]
        if any(v is None for v in params):
            raise HTTPException(
                status_code=400,
                detail="순위(combo_no) 또는 6개 번호가 필요합니다",
            )
        raw = [int(v) for v in params if v is not None]

    try:
        return search_combo_by_numbers(raw, per_page=per_page)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

