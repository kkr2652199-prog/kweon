"""로또 분석 API — app.testlotto 독립 패키지."""
from fastapi import APIRouter, BackgroundTasks

router = APIRouter(prefix="/api/testlotto", tags=["testlotto"])


def _prediction_rank_tier(matched_count: int, bonus_matched: int | None) -> tuple[int, str]:
    """matched_count·bonus_matched → (1~5 또는 0, 한글 등급)."""
    bm = 1 if bonus_matched == 1 else 0
    if matched_count == 6:
        return 1, "1등"
    if matched_count == 5 and bm == 1:
        return 2, "2등"
    if matched_count == 5:
        return 3, "3등"
    if matched_count == 4:
        return 4, "4등"
    if matched_count == 3:
        return 5, "5등"
    return 0, ""


def _tier_wins_items_from_rows(rows: list) -> list[dict]:
    """lotto_predictions 행 목록 → 1~5등 항목만 정렬된 리스트."""
    items: list[dict] = []
    for r in rows:
        d = dict(r)
        mc = int(d.get("matched_count") or -1)
        raw_bm = d.get("bonus_matched")
        try:
            bm_int = int(raw_bm) if raw_bm is not None else 0
        except (TypeError, ValueError):
            bm_int = 0
        rank, label = _prediction_rank_tier(mc, bm_int)
        if rank == 0:
            continue
        items.append(
            {
                "id": int(d["id"]),
                "brain_tag": str(d.get("brain_tag") or "legacy"),
                "rank": rank,
                "rank_label": label,
                "matched_count": mc,
                "bonus_matched": bm_int,
                "confidence": d.get("confidence"),
                "nums": [
                    int(d["num1"]),
                    int(d["num2"]),
                    int(d["num3"]),
                    int(d["num4"]),
                    int(d["num5"]),
                    int(d["num6"]),
                ],
            }
        )
    items.sort(key=lambda x: (x["rank"], x["brain_tag"], -(float(x["confidence"] or 0))))
    return items


def _prediction_row_brain_tag(row: dict) -> str:
    """brain_tag 우선, legacy면 method로 영문 태그 복원."""
    from app.testlotto.engine import METHOD_TO_BRAIN_TAG

    bt = (row.get("brain_tag") or "").strip() or "legacy"
    if bt and bt != "legacy":
        return bt
    return METHOD_TO_BRAIN_TAG.get(row.get("method") or "", "legacy")


def _dashboard_hot_numbers(conn, last_draws: int = 50, top_n: int = 5) -> list[int]:
    from collections import Counter

    rows = conn.execute(
        """
        SELECT num1, num2, num3, num4, num5, num6
        FROM lotto_draws
        ORDER BY draw_no DESC
        LIMIT ?
        """,
        (last_draws,),
    ).fetchall()
    cnt: Counter[int] = Counter()
    for r in rows:
        d = dict(r)
        for k in ("num1", "num2", "num3", "num4", "num5", "num6"):
            cnt[int(d[k])] += 1
    return [n for n, _ in cnt.most_common(top_n)]


# ═══════════════════════════════════════════
# 데이터 수집
# ═══════════════════════════════════════════

@router.get("/collection-hint")
async def api_collection_hint():
    """DB 최대·다음 회차·예정 추첨일(자동) — 수집 전/후 안내."""
    from app.testlotto.data_service import get_collection_hint

    return get_collection_hint()


@router.get("/last-fetch-all")
async def api_last_fetch_all():
    """백그라운드 `fetch_all_draws` 직전 완료 결과(없으면 null)."""
    from app.testlotto.data_service import get_last_fetch_all_result

    r = get_last_fetch_all_result()
    return {"result": r}


@router.post("/fetch-all")
async def api_fetch_all(background_tasks: BackgroundTasks):
    """1회차~최신까지 전체 수집 (백그라운드)."""
    from app.testlotto.data_service import fetch_all_draws

    background_tasks.add_task(fetch_all_draws, delay=0.3)
    return {
        "status": "수집 시작됨",
        "message": "백그라운드에서 진행 중. 잠시 후 자동으로 완료 요약이 표시됩니다.",
    }


@router.post("/fetch-latest")
async def api_fetch_latest():
    """최신 1회차만 수집. 미수집 시 `get_collection_hint`로 다음 추첨일(추정)을 함께 반환."""
    from app.testlotto.data_service import fetch_latest_draw, get_collection_hint

    result = fetch_latest_draw()
    if result:
        return {"status": "성공", "draw": result}
    hint = get_collection_hint()
    return {
        "status": "신규 회차 없음",
        "next_draw_no": hint["next_draw_no"],
        "next_draw_date": hint["next_draw_date"],
    }


@router.get("/draws")
async def api_get_draws(limit: int = 20, offset: int = 0):
    """회차 목록 조회 (최신순)."""
    from app.testlotto.models import get_lotto_db

    conn = get_lotto_db()
    rows = conn.execute(
        "SELECT * FROM lotto_draws ORDER BY draw_no DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM lotto_draws").fetchone()[0]
    conn.close()
    return {"draws": [dict(r) for r in rows], "total": total}


@router.get("/draws/{draw_no}")
async def api_get_draw(draw_no: int):
    """특정 회차 상세 조회."""
    from app.testlotto.models import get_lotto_db

    conn = get_lotto_db()
    row = conn.execute("SELECT * FROM lotto_draws WHERE draw_no = ?", (draw_no,)).fetchone()
    conn.close()
    if row:
        return dict(row)
    return {"error": f"{draw_no}회차 데이터 없음"}


# ═══════════════════════════════════════════
# 통계 분석
# ═══════════════════════════════════════════

@router.get("/stats/comprehensive")
async def api_comprehensive_stats():
    """전체 종합 통계."""
    from app.testlotto.data_service import get_comprehensive_stats

    return get_comprehensive_stats()


@router.get("/stats/frequency")
async def api_frequency():
    """번호별 출현 빈도."""
    from app.testlotto.data_service import analyze_number_frequency

    return analyze_number_frequency()


@router.get("/stats/pairs")
async def api_pairs(top_n: int = 30):
    """동반출현 번호 쌍."""
    from app.testlotto.data_service import analyze_pair_frequency

    return analyze_pair_frequency(top_n=top_n)


@router.get("/stats/range")
async def api_range():
    """구간별 분포."""
    from app.testlotto.data_service import analyze_range_distribution

    return analyze_range_distribution()


@router.get("/stats/odd-even")
async def api_odd_even():
    """홀짝 비율."""
    from app.testlotto.data_service import analyze_odd_even

    return analyze_odd_even()


@router.get("/stats/sum")
async def api_sum():
    """합계 분석."""
    from app.testlotto.data_service import analyze_sum_range

    return analyze_sum_range()


@router.get("/stats/consecutive")
async def api_consecutive():
    """연속번호 분석."""
    from app.testlotto.data_service import analyze_consecutive

    return analyze_consecutive()


# ═══════════════════════════════════════════
# 두뇌 예측 + 엘리트 시스템
# ═══════════════════════════════════════════
# 주의: /predict/backtest 는 /predict/{target_draw_no} 보다 먼저 등록해야 "backtest"가 회차로 파싱되지 않음.

@router.post("/predict/backtest")
async def api_backtest(start_draw: int = 1100, end_draw: int = 0):
    """과거 회차 범위를 역산 예측하여 적중률을 계산한다.
    end_draw=0이면 최신 회차까지."""
    from app.testlotto.engine import run_backtest

    result = run_backtest(start_draw, end_draw)
    return result

@router.post("/predict/{target_draw_no}")
async def api_predict(target_draw_no: int):
    """특정 회차에 대한 두뇌 예측을 실행한다.
    컨닝 방지: target_draw_no 이전 데이터만 LLM에게 제공."""
    from app.testlotto.engine import run_prediction

    result = run_prediction(target_draw_no)
    return result


@router.get("/brain/status")
async def api_brain_status():
    """두뇌 엘리트 현황 — 등급, 적중 이력, 강점/약점."""
    from app.testlotto.engine import get_brain_status

    return get_brain_status()

@router.get("/brain/hall-of-fame")
async def api_hall_of_fame():
    """적중 명예의 전당 — 가장 많이 맞춘 예측 TOP 10."""
    from app.testlotto.engine import get_hall_of_fame

    return get_hall_of_fame()


@router.get("/brain/elite-tags")
async def api_brain_elite_tags():
    """UI 필터: 아래 둘 중 하나를 만족한 brain_tag.

    (A) 역대 1등≥1, 2등≥1, 3등≥5를 동시에 만족
    (B) 역대 3등(5개 일치·보너스 불일치)만 ≥15회 — 1·2등 이력 없어도 고적중으로 간주

    집계 정의는 대시보드와 동일 계열(스네이크·miss 등 제외).
    """
    from app.testlotto.models import get_lotto_db

    conn = get_lotto_db()
    try:
        rows = conn.execute(
            """
            SELECT brain_tag,
              SUM(CASE WHEN matched_count=6 THEN 1 ELSE 0 END) AS r1,
              SUM(CASE WHEN matched_count=5 AND bonus_matched=1 THEN 1 ELSE 0 END) AS r2,
              SUM(CASE WHEN matched_count=5 AND (bonus_matched=0 OR bonus_matched IS NULL)
                  THEN 1 ELSE 0 END) AS r3
            FROM lotto_predictions
            WHERE brain_tag NOT IN ('llm_fallback','miss_analysis','snake')
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
async def api_predictions_tier_wins(target_draw_no: int):
    """단일 회차: 1~5등 적중 예측 세트만 반환(읽기 전용, UI 팝업용).

    집계 제외는 `/predictions/draw/{n}` 과 동일(`miss_analysis`, `snake`).
    """
    from app.testlotto.models import get_lotto_db

    conn = get_lotto_db()
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
            FROM lotto_predictions
            WHERE target_draw_no = ?
              AND brain_tag NOT IN ('miss_analysis','snake')
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
async def api_predictions_for_draw(target_draw_no: int):
    """단일 회차의 기저 6뇌 예측 전부(드롭다운 선택 시 캐시 LIMIT·created_at 정렬로 과거 회차가 빠지는 문제 방지)."""
    from app.testlotto.models import get_lotto_db

    conn = get_lotto_db()
    rows = conn.execute(
        """SELECT p.*, d.num1 AS actual_1, d.num2 AS actual_2, d.num3 AS actual_3,
                  d.num4 AS actual_4, d.num5 AS actual_5, d.num6 AS actual_6, d.bonus AS actual_bonus
           FROM lotto_predictions p
           LEFT JOIN lotto_draws d ON p.target_draw_no = d.draw_no
           WHERE p.brain_tag NOT IN ('miss_analysis','snake')
             AND p.target_draw_no = ?
           ORDER BY p.brain_tag ASC, p.confidence DESC""",
        (target_draw_no,),
    ).fetchall()
    conn.close()
    return {"predictions": [dict(r) for r in rows]}


@router.get("/predictions")
async def api_predictions(limit: int = 20):
    """예측 이력 조회."""
    from app.testlotto.models import get_lotto_db

    conn = get_lotto_db()
    rows = conn.execute(
        """SELECT p.*, d.num1 AS actual_1, d.num2 AS actual_2, d.num3 AS actual_3,
                  d.num4 AS actual_4, d.num5 AS actual_5, d.num6 AS actual_6, d.bonus AS actual_bonus
           FROM lotto_predictions p
           LEFT JOIN lotto_draws d ON p.target_draw_no = d.draw_no
           WHERE p.brain_tag NOT IN ('miss_analysis','snake')
           ORDER BY p.target_draw_no DESC, p.brain_tag ASC, p.confidence DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return {"predictions": [dict(r) for r in rows]}


@router.get("/dashboard-summary")
async def api_dashboard_summary():
    """대시보드 요약 — 다음 추첨, 학습 현황, 랭킹, 점수."""
    import datetime as dt

    from app.testlotto.models import get_lotto_db

    SPECIAL_TAGS = ("miss_analysis", "snake")

    def _weekday_kr(d: dt.date) -> str:
        # 월=0 ... 일=6
        return ["월", "화", "수", "목", "금", "토", "일"][d.weekday()]

    conn = get_lotto_db()
    try:
        # next draw: 최신 회차 기준 + KST 20:45 이후면 다음다음 회차로 넘긴다.
        row = conn.execute(
            "SELECT draw_no, draw_date FROM lotto_draws ORDER BY draw_no DESC LIMIT 1"
        ).fetchone()
        last_no = int(row[0]) if row else 0
        from datetime import datetime, timedelta, timezone

        KST = timezone(timedelta(hours=9))

        def get_draw_date(draw_no: int) -> datetime:
            """회차 번호로 추첨 날짜 계산 (1회=2002-12-07 토)."""
            first_draw = datetime(2002, 12, 7, tzinfo=KST)
            return first_draw + timedelta(weeks=draw_no - 1)

        now = datetime.now(KST)

        # 다음 회차 = last + 1
        next_no = last_no + 1
        next_date_candidate = get_draw_date(next_no)
        next_draw_time = datetime(
            next_date_candidate.year,
            next_date_candidate.month,
            next_date_candidate.day,
            20,
            45,
            0,
            tzinfo=KST,
        )
        # 다음 회차의 추첨 시각도 이미 지났으면 +1 더 (2회차 뒤를 보여줌)
        if now > next_draw_time:
            next_no += 1

        next_date = get_draw_date(next_no).date()

        total_predictions = conn.execute(
            "SELECT COUNT(1) FROM lotto_predictions WHERE brain_tag NOT IN ('miss_analysis','snake')"
        ).fetchone()[0]
        lr = conn.execute(
            "SELECT MIN(target_draw_no), MAX(target_draw_no) FROM lotto_predictions WHERE brain_tag NOT IN ('miss_analysis','snake')"
        ).fetchone()
        lr_start = int(lr[0]) if lr and lr[0] is not None else 0
        lr_end = int(lr[1]) if lr and lr[1] is not None else 0
        # 최신 회차는 MAX(draw_no)가 더 정확하다(중간 결측이 있어도 최신값 유지).
        total_draws = conn.execute("SELECT MAX(draw_no) FROM lotto_draws").fetchone()[0] or 0

        def _rank_rows(where_sql: str, params: tuple = ()) -> list[dict]:
            q = f"""
            SELECT target_draw_no, brain_tag, method, num1, num2, num3, num4, num5, num6
            FROM lotto_predictions
            WHERE {where_sql} AND brain_tag NOT IN ('miss_analysis','snake')
            ORDER BY target_draw_no DESC, confidence DESC
            """
            out = []
            for r in conn.execute(q, params).fetchall():
                d = dict(r)
                out.append(
                    {
                        "draw_no": int(d["target_draw_no"]),
                        "brain": (d.get("brain_tag") or d.get("method") or "legacy"),
                        "numbers": [
                            int(d["num1"]),
                            int(d["num2"]),
                            int(d["num3"]),
                            int(d["num4"]),
                            int(d["num5"]),
                            int(d["num6"]),
                        ],
                    }
                )
            return out

        rankings = {
            "rank1": _rank_rows("matched_count = 6"),
            "rank2": _rank_rows("matched_count = 5 AND bonus_matched = 1"),
            "rank3": _rank_rows("matched_count = 5 AND (bonus_matched = 0 OR bonus_matched IS NULL)"),
        }

        # brain power
        bp_rows = conn.execute(
            """
            SELECT brain_tag,
              SUM(CASE WHEN matched_count=6 THEN 1 ELSE 0 END) AS r1,
              SUM(CASE WHEN matched_count=5 AND bonus_matched=1 THEN 1 ELSE 0 END) AS r2,
              SUM(CASE WHEN matched_count=5 AND (bonus_matched=0 OR bonus_matched IS NULL) THEN 1 ELSE 0 END) AS r3,
              SUM(CASE WHEN matched_count=4 THEN 1 ELSE 0 END) AS r4,
              SUM(CASE WHEN matched_count=3 THEN 1 ELSE 0 END) AS r5
            FROM lotto_predictions
            WHERE brain_tag NOT IN ('llm_fallback','miss_analysis','snake')
            GROUP BY brain_tag
            ORDER BY r1 DESC, r2 DESC, r3 DESC, r4 DESC, r5 DESC
            """
        ).fetchall()
        brain_power = []
        for r in bp_rows:
            tag = r[0]
            r1 = int(r[1] or 0)
            r2 = int(r[2] or 0)
            r3 = int(r[3] or 0)
            r4 = int(r[4] or 0)
            r5 = int(r[5] or 0)
            if r1 > 0:
                label = "최강"
            elif r2 > 0:
                label = "강함"
            elif r3 >= 10:
                label = "우수"
            elif r3 > 0:
                label = "보통"
            else:
                label = "기본"
            brain_power.append(
                {
                    "brain": str(tag),
                    "rank1": r1,
                    "rank2": r2,
                    "rank3": r3,
                    "rank4": r4,
                    "rank5": r5,
                    "label": label,
                }
            )

        # scores
        if total_predictions <= 0:
            total_predictions = 1
        c6 = conn.execute(
            "SELECT COUNT(1) FROM lotto_predictions WHERE matched_count=6 AND brain_tag NOT IN ('miss_analysis','snake')"
        ).fetchone()[0]
        c5b = conn.execute(
            "SELECT COUNT(1) FROM lotto_predictions WHERE matched_count=5 AND bonus_matched=1 AND brain_tag NOT IN ('miss_analysis','snake')"
        ).fetchone()[0]
        c5 = conn.execute(
            "SELECT COUNT(1) FROM lotto_predictions WHERE matched_count=5 AND (bonus_matched=0 OR bonus_matched IS NULL) AND brain_tag NOT IN ('miss_analysis','snake')"
        ).fetchone()[0]
        c4 = conn.execute(
            "SELECT COUNT(1) FROM lotto_predictions WHERE matched_count=4 AND brain_tag NOT IN ('miss_analysis','snake')"
        ).fetchone()[0]
        c3 = conn.execute(
            "SELECT COUNT(1) FROM lotto_predictions WHERE matched_count=3 AND brain_tag NOT IN ('miss_analysis','snake')"
        ).fetchone()[0]
        c3p = conn.execute(
            "SELECT COUNT(1) FROM lotto_predictions WHERE matched_count>=3 AND brain_tag NOT IN ('miss_analysis','snake')"
        ).fetchone()[0]

        scores = {
            "rank1_pct": c6 / total_predictions * 100.0,
            "rank1_cnt": int(c6),
            "rank2_pct": c5b / total_predictions * 100.0,
            "rank2_cnt": int(c5b),
            "rank3_pct": c5 / total_predictions * 100.0,
            "rank3_cnt": int(c5),
            "rank4_pct": c4 / total_predictions * 100.0,
            "rank4_cnt": int(c4),
            "rank5_pct": c3 / total_predictions * 100.0,
            "rank5_cnt": int(c3),
            "total_hit_pct": c3p / total_predictions * 100.0,
        }

        return {
            "next_draw_no": next_no,
            "next_draw_date": next_date.isoformat(),
            "next_draw_weekday": _weekday_kr(next_date),
            "total_predictions": int(total_predictions),
            "learning_range": {"start": lr_start, "end": lr_end, "total_draws": int(total_draws)},
            "rankings": rankings,
            "brain_power": brain_power,
            "scores": scores,
        }
    finally:
        conn.close()


@router.get("/walkforward/progress")
async def api_walkforward_progress():
    """복습 루프 진행 현황."""
    from app.testlotto.walkforward import get_review_progress

    return get_review_progress()


@router.post("/walkforward/review")
async def api_walkforward_review(
    start: int = 2,
    end: int = 1231,
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    """회차 구간 복습 루프 (예측→채점→오답분석→피드백)."""
    from app.testlotto.walkforward import run_review_loop

    if end - start > 200:
        def _job():
            run_review_loop(start, end)

        background_tasks.add_task(_job)
        return {"status": "started", "start": start, "end": end, "mode": "background"}
    return run_review_loop(start, end)


@router.post("/walkforward/future")
async def api_walkforward_future(future_draw: int = 1232, full_review: bool = False):
    """복습 경험 반영 후 미래 회차 예측."""
    from app.testlotto.walkforward import run_future_after_review

    return run_future_after_review(future_draw, run_full_review_first=full_review)


@router.get("/detail/draw/{draw_no}")
async def api_detail_draw(draw_no: int):
    """단일 회차 상세 — 정답·분석·뇌별 복습."""
    from app.testlotto.detail_service import get_draw_detail

    return get_draw_detail(draw_no)


@router.get("/detail/draws-hit")
async def api_detail_draws_hit(brain_tag: str = "stat", min_match: int = 3):
    """뇌별 최소 5등(3개) 이상 적중 복습 회차 목록."""
    from app.testlotto.detail_service import get_hit_draws

    draws = get_hit_draws(brain_tag, min_match=min_match)
    return {"brain_tag": brain_tag, "min_match": min_match, "draws": draws, "total": len(draws)}


@router.get("/detail/reviews")
async def api_detail_reviews(
    start: int = 2,
    end: int = 1231,
    brain_tag: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """여러 회차 복습 목록 + 구간 진단 summary (추세·약점·내러티브)."""
    from app.testlotto.detail_service import get_reviews_range

    return get_reviews_range(start, end, brain_tag, limit=limit, offset=offset)


@router.get("/detail/reviews/set-distribution")
async def api_detail_set_distribution(start: int = 2, end: int = 1231):
    """구간 뇌×세트(1~5) 적중 분포 — READ ONLY, 사후선택 경고 포함."""
    from app.testlotto.detail_service import get_set_hit_distribution

    return get_set_hit_distribution(start, end)


@router.get("/detail/brain/{brain_tag}/summary")
async def api_detail_brain_summary(brain_tag: str):
    """뇌별 누적 학습 요약."""
    from app.testlotto.detail_service import get_brain_learning_summary

    return get_brain_learning_summary(brain_tag)


@router.post("/detail/sync-tiers")
async def api_detail_sync_tiers(start: int = 1220, end: int = 1231):
    """1~5등 당첨 정보 lt645 백필."""
    from app.testlotto.prize_tiers import sync_prize_tiers_range

    return sync_prize_tiers_range(start, end)


@router.post("/archive/sync")
async def api_archive_sync(start: int = 1, end: int = 20, fetch_stores: bool = True):
    """동행복권 lt645 정밀 당첨 이력 백필 (등수·판매·당첨유형·판매점)."""
    from app.testlotto.draw_archive import sync_draw_archive_range

    return sync_draw_archive_range(start, end, fetch_stores=fetch_stores)


@router.get("/archive/draw/{draw_no}")
async def api_archive_draw(draw_no: int):
    """회차 정밀 당첨 이력 조회."""
    from app.testlotto.draw_archive import get_draw_archive

    return get_draw_archive(draw_no)


@router.post("/detail/sync-pages")
async def api_detail_sync_pages(start: int = 2, end: int = 1231):
    """brain_review → brain_page 백필."""
    from app.testlotto.detail_service import sync_brain_pages_from_reviews

    n = sync_brain_pages_from_reviews(start, end)
    return {"synced": n, "start": start, "end": end}
