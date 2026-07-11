"""V11 라우터: /api/lotto2/v11/*"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/lotto2/v11", tags=["lotto2_v11"])


@router.post("/predict/{target_draw_no}")
async def api_predict_v11(target_draw_no: int):
    from app.lotto2.v11_engine import run_prediction_v11

    return run_prediction_v11(target_draw_no)


@router.post("/backtest_chunk")
async def api_backtest_v11(start_draw: int, end_draw: int, checkpoint_every: int = 25):
    from app.lotto2.v11_engine import run_v11_chunk_backtest

    return run_v11_chunk_backtest(start_draw, end_draw, checkpoint_every)


@router.get("/stats")
async def api_stats_v11(start_draw: int = 50, end_draw: int = 1221):
    from app.lotto2.models import get_lotto2_db

    conn = get_lotto2_db()
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
            FROM lotto_predictions_army2
            WHERE matched_count >= 0 AND brain_tag LIKE 'v11_%'
              AND target_draw_no BETWEEN ? AND ?
            GROUP BY brain_tag
            ORDER BY avg_m DESC
            """,
            (start_draw, end_draw),
        ).fetchall()
        return {"range": f"{start_draw}~{end_draw}", "v11_brains": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/weights")
async def api_weights_v11():
    from app.lotto2.v11_models import get_v11_brain_weights

    return {"v11_weights": get_v11_brain_weights()}


# ============= UI 호환 라우트 (STEP C-1) =============

@router.get("/brain/elite-tags")
async def api_v11_brain_elite_tags():
    """UI 필터: (A) 역대 1·2·3등 균형 충족 또는 (B) 역대 3등만 ≥15회 (2군 army2).

    (B)는 1·2등 기록이 없어도 3등 다득 뇌(예: v11_hyena)를 포함하기 위함.
    """
    from app.lotto2.models import get_lotto2_db

    conn = get_lotto2_db()
    try:
        rows = conn.execute(
            """
            SELECT brain_tag,
              SUM(CASE WHEN matched_count=6 THEN 1 ELSE 0 END) AS r1,
              SUM(CASE WHEN matched_count=5 AND bonus_matched=1 THEN 1 ELSE 0 END) AS r2,
              SUM(CASE WHEN matched_count=5 AND (bonus_matched=0 OR bonus_matched IS NULL)
                  THEN 1 ELSE 0 END) AS r3
            FROM lotto_predictions_army2
            WHERE brain_tag LIKE 'v11_%'
              AND brain_tag NOT IN ('v11_snake','miss_analysis')
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
async def api_v11_predictions_tier_wins(target_draw_no: int):
    """단일 회차: 1~5등 적중 예측 세트만 (읽기 전용, 2군 팝업용)."""
    from app.lotto.routes import _tier_wins_items_from_rows

    from app.lotto2.models import get_lotto2_db

    conn = get_lotto2_db()
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
            FROM lotto_predictions_army2
            WHERE target_draw_no = ?
              AND brain_tag LIKE 'v11_%'
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
async def api_v11_predictions_for_draw(target_draw_no: int):
    """단일 회차의 v11 예측 전부(드롭다운·캐시 LIMIT로 과거 회차가 빠지는 문제 방지)."""
    from app.lotto2.models import get_lotto2_db

    conn = get_lotto2_db()
    try:
        rows = conn.execute(
            """
            SELECT p.*, d.num1 AS actual_1, d.num2 AS actual_2, d.num3 AS actual_3,
                   d.num4 AS actual_4, d.num5 AS actual_5, d.num6 AS actual_6,
                   d.bonus AS actual_bonus
            FROM lotto_predictions_army2 p
            LEFT JOIN lotto_draws d ON p.target_draw_no = d.draw_no
            WHERE p.brain_tag LIKE 'v11_%' AND p.target_draw_no = ?
            ORDER BY p.brain_tag ASC, p.confidence DESC
            """,
            (target_draw_no,),
        ).fetchall()
        return {"predictions": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/predictions")
async def api_v11_predictions(limit: int = 100):
    """V11 예측 목록 (1군 /api/lotto/predictions 형식 호환)."""
    from app.lotto2.models import get_lotto2_db

    conn = get_lotto2_db()
    try:
        rows = conn.execute(
            """
            SELECT p.*, d.num1 AS actual_1, d.num2 AS actual_2, d.num3 AS actual_3,
                   d.num4 AS actual_4, d.num5 AS actual_5, d.num6 AS actual_6,
                   d.bonus AS actual_bonus
            FROM lotto_predictions_army2 p
            LEFT JOIN lotto_draws d ON p.target_draw_no = d.draw_no
            WHERE p.brain_tag LIKE 'v11_%'
            ORDER BY p.target_draw_no DESC, p.brain_tag ASC, p.confidence DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return {"predictions": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/draws")
async def api_v11_draws(limit: int = 50):
    """V11 회차 데이터 (1군과 동일 lotto_draws 공유)."""
    from app.lotto2.models import get_lotto2_db

    conn = get_lotto2_db()
    try:
        rows = conn.execute(
            "SELECT * FROM lotto_draws ORDER BY draw_no DESC LIMIT ?", (limit,)
        ).fetchall()
        return {"draws": [dict(r) for r in rows], "total": len(rows)}
    finally:
        conn.close()


@router.get("/brain/status")
async def api_v11_brain_status():
    """V11 6뇌 상태 — 1군 응답 형식 100% 호환.

    1군 brain_profiles[i] keys: brain_tag, method, total_predictions,
                                avg_match, best_match, rank1, rank2, rank3, rank4, rank5
    """
    from app.lotto2.models import get_lotto2_db

    BRAIN_METHOD = {
        "v11_stat": "시간여행자",
        "v11_markov": "탐정수사반장",
        "v11_combo": "지식박사",
        "v11_lstm": "예언자",
        "v11_fusion": "작전본부장",
        "v11_hyena": "하이에나",
    }

    conn = get_lotto2_db()
    try:
        rows = conn.execute(
            """
            SELECT brain_tag,
                   COUNT(*) AS total_predictions,
                   ROUND(AVG(matched_count), 3) AS avg_match,
                   MAX(matched_count) AS best_match,
                   SUM(CASE WHEN matched_count = 6 THEN 1 ELSE 0 END) AS rank1,
                   SUM(CASE WHEN matched_count = 5 AND bonus_matched = 1 THEN 1 ELSE 0 END) AS rank2,
                   SUM(CASE WHEN matched_count = 5 AND bonus_matched = 0 THEN 1 ELSE 0 END) AS rank3,
                   SUM(CASE WHEN matched_count = 4 THEN 1 ELSE 0 END) AS rank4,
                   SUM(CASE WHEN matched_count = 3 THEN 1 ELSE 0 END) AS rank5
            FROM lotto_predictions_army2
            WHERE matched_count >= 0 AND brain_tag LIKE 'v11_%'
            GROUP BY brain_tag
            ORDER BY avg_match DESC
            """
        ).fetchall()
        total_pred = conn.execute(
            "SELECT COUNT(*) FROM lotto_predictions_army2 WHERE brain_tag LIKE 'v11_%' AND matched_count >= 0"
        ).fetchone()[0]
        best_row = conn.execute(
            """
            SELECT brain_tag, target_draw_no, matched_count, bonus_matched
            FROM lotto_predictions_army2
            WHERE brain_tag LIKE 'v11_%' AND matched_count >= 0
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

        # brain_profiles에 1군 호환용 'method' 키 추가
        brain_profiles = []
        for r in rows:
            d = dict(r)
            d["method"] = BRAIN_METHOD.get(d["brain_tag"], d["brain_tag"])
            # 1군과 동일한 strength 규칙
            if d.get("avg_match") and d["avg_match"] >= 2.0:
                d["strength"] = "높은 평균 적중률"
            elif d.get("best_match") and d["best_match"] >= 4:
                d["strength"] = "폭발적 최고 기록"
            else:
                d["strength"] = "안정적 분석"
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
async def api_v11_hall_of_fame(limit: int = 5000):
    """V11 명예의 전당 — 1군과 동일 기준: 3개 이상 적중, 최신·고적중 우선.

    읽기 전용. limit은 1~50000으로 클램프.
    """
    from app.lotto2.models import get_lotto2_db

    safe_limit = max(1, min(int(limit), 50_000))
    conn = get_lotto2_db()
    try:
        rows = conn.execute(
            """
            SELECT p.*,
                   d.draw_date AS draw_date,
                   d.num1 AS actual_1, d.num2 AS actual_2, d.num3 AS actual_3,
                   d.num4 AS actual_4, d.num5 AS actual_5, d.num6 AS actual_6,
                   d.bonus AS actual_bonus
            FROM lotto_predictions_army2 p
            LEFT JOIN lotto_draws d ON p.target_draw_no = d.draw_no
            WHERE p.brain_tag LIKE 'v11_%' AND p.matched_count >= 3
            ORDER BY p.matched_count DESC, p.bonus_matched DESC, p.target_draw_no DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
        return {"hall_of_fame": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/dashboard-summary")
async def api_v11_dashboard_summary():
    """V11 대시보드 요약 — 1군 응답 형식 100% 호환.

    1군 brain_power[i] keys: brain, label, rank1, rank2, rank3, rank4, rank5
    1군 learning_range keys: start, end, total_draws
    1군 scores keys: rank1_cnt, rank2_cnt, rank3_cnt, rank4_cnt, rank5_cnt,
                     rank1_pct, rank2_pct, rank3_pct, rank4_pct, rank5_pct,
                     total_hit_pct
    """
    from app.lotto2.models import get_lotto2_db
    from app.lotto2.v11_models import V11_SEED_WEIGHTS, get_v11_brain_weights
    from datetime import datetime, timedelta

    # V11 두뇌 한글 라벨 (1군과 동일)
    BRAIN_LABEL = {
        "v11_stat": "🕰️ 시간여행자",
        "v11_markov": "🔍 탐정수사반장",
        "v11_combo": "🎓 지식박사",
        "v11_lstm": "🔮 예언자",
        "v11_fusion": "📋 작전본부장",
        "v11_hyena": "🦊 하이에나",
        "v11_snake": "🐍 뱀 합성두뇌",
    }

    conn = get_lotto2_db()
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

        # 3) total_predictions
        total_pred = conn.execute(
            "SELECT COUNT(*) FROM lotto_predictions_army2 WHERE brain_tag LIKE 'v11_%' AND matched_count >= 0"
        ).fetchone()[0]

        # 4) learning_range (1군 키: start, end, total_draws)
        lr = conn.execute(
            "SELECT MIN(target_draw_no) AS s, MAX(target_draw_no) AS e FROM lotto_predictions_army2 WHERE brain_tag LIKE 'v11_%'"
        ).fetchone()
        total_draws_row = conn.execute("SELECT COUNT(*) FROM lotto_draws").fetchone()[0]
        learning_range = {
            "start": lr["s"] or 0,
            "end": lr["e"] or 0,
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
                SELECT COUNT(*) AS c FROM lotto_predictions_army2
                WHERE brain_tag LIKE 'v11_%' AND {where_clause}
                """
            ).fetchone()
            rankings[rank_key + "_total"] = int(cnt_row["c"] or 0)
            rows = conn.execute(
                f"""
                SELECT brain_tag, target_draw_no, num1, num2, num3, num4, num5, num6, bonus_matched
                FROM lotto_predictions_army2
                WHERE brain_tag LIKE 'v11_%' AND {where_clause}
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
            FROM lotto_predictions_army2
            WHERE brain_tag LIKE 'v11_%' AND matched_count >= 0
            GROUP BY brain_tag
            """
        ).fetchall()
        stats_map = {r["brain_tag"]: dict(r) for r in brain_stats}

        brain_power = []
        for tag in (
            "v11_stat",
            "v11_markov",
            "v11_combo",
            "v11_lstm",
            "v11_fusion",
            "v11_hyena",
            "v11_snake",
        ):
            s = stats_map.get(tag, {})
            brain_power.append(
                {
                    "brain": tag,
                    "label": BRAIN_LABEL.get(tag, tag),
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
            FROM lotto_predictions_army2
            WHERE brain_tag LIKE 'v11_%' AND matched_count >= 0
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

        return {
            "next_draw_no": next_draw,
            "next_draw_date": next_date_str,
            "next_draw_weekday": next_weekday,
            "total_predictions": total_pred,
            "learning_range": learning_range,
            "rankings": rankings,
            "brain_power": brain_power,
            "scores": scores,
        }
    finally:
        conn.close()


@router.get("/draws/{draw_no}")
async def api_v11_draw_one(draw_no: int):
    """V11 단일 회차 조회 (1군 형식 호환). lotto_draws 공유 사용."""
    from app.lotto2.models import get_lotto2_db

    conn = get_lotto2_db()
    try:
        row = conn.execute("SELECT * FROM lotto_draws WHERE draw_no = ?", (draw_no,)).fetchone()
        if not row:
            return {"error": "not_found", "draw_no": draw_no}
        return {"draw": dict(row)}
    finally:
        conn.close()


@router.get("/stats/comprehensive")
async def api_v11_stats_comprehensive():
    """V11 종합 통계 — 1군 응답 형식 100% 호환.

    1군과 동일 로직을 그대로 재사용한다(읽기 전용).
    """
    from app.lotto.data_service import get_comprehensive_stats

    return get_comprehensive_stats()

