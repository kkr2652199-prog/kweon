"""로또 예측 오케스트레이터 — app.testlotto 독립 패키지.
2026-04-20: Layer 1 - 5두뇌 독립 저장 (stat/markov/llm/lstm/fusion), brain_tag 컬럼 활용
2026-04-20: LLM 세트 source 기반 brain_tag 분기 (llm vs llm_fallback)
2026-04-25 Layer 3: run_backtest 내 update_brain_weights 호출 추가.
2026-04-25 Layer 3.5: update_brain_weights eta 1.5 적용.
2026-04-25 Layer 5-B: run_backtest 결과에 rank_distribution + lottery_score 추가.
2026-04-25 Layer 5-A: 하이에나 메타 두뇌 호출 추가 (fusion 직후, all_predictions.sort 직전).
2026-04-20 Layer 5-A2: run_prediction/run_backtest brain_filter, 하이에나 입력 DB·신규 병합.
"""
import logging
import random
from collections import Counter

from app.testlotto.data_service import _get_draws_before
from app.testlotto.feedback import _calculate_lottery_score
from app.testlotto.filters import tier1_filter
from app.testlotto.fusion import _vector_fusion_predict
from app.testlotto.models import get_lotto_db, init_lotto_db
from app.testlotto.predict_llm import _llm_predict
from app.testlotto.predict_lstm import get_lstm_prob_vector
from app.testlotto.predict_markov import _markov_predict
from app.testlotto.predict_statistical import _statistical_predict

from app.testlotto.brains.registry import DISPLAY_NAMES, METHOD_TO_TAG, PREDICT_BRAINS

logger = logging.getLogger(__name__)

BRAIN_REGISTRY: list[tuple[str, str]] = [
    (b["name"], b["tag"]) for b in PREDICT_BRAINS
]
BRAIN_METHODS = [m for m, _ in BRAIN_REGISTRY]
METHOD_TO_BRAIN_TAG: dict[str, str] = {**METHOD_TO_TAG, **{b["name"]: b["tag"] for b in PREDICT_BRAINS}}
DISPLAY_BRAIN_NAMES: dict[str, str] = DISPLAY_NAMES
SETS_PER_BRAIN = 5
ENABLE_SPECIAL_BRAINS = False
ELITE_THRESHOLDS = {3: "엘리트", 4: "천재", 5: "전설", 6: "신"}


def _predictions_row_to_enriched(r: dict) -> dict:
    return {
        "nums": [r["num1"], r["num2"], r["num3"], r["num4"], r["num5"], r["num6"]],
        "confidence": r["confidence"],
        "reasoning": r.get("reasoning", ""),
        "method": r["method"],
        "brain_tag": r.get("brain_tag")
        or METHOD_TO_BRAIN_TAG.get(r.get("method", ""), "legacy"),
        "matched_count": r["matched_count"],
        "bonus_matched": r.get("bonus_matched", 0),
    }


def _invoke_brain7_safe(target_draw_no: int) -> None:
    """7뇌 1등가자 — 6뇌 commit 이후 독립 호출. 실패해도 6뇌 무영향."""
    try:
        from app.testlotto.predict_brain7 import ensure_brain7_for_draw

        ensure_brain7_for_draw(target_draw_no)
    except Exception as e:  # noqa: BLE001
        logger.warning("[7뇌 1등가자] skip: %s", e)


def refresh_prediction_scores_for_target_draw(target_draw_no: int) -> bool:
    """`lotto_draws`에 target 회차 당첨이 있으면 `lotto_predictions` 적중·보너스를 갱신. 없으면 False."""
    init_lotto_db()
    conn = get_lotto_db()
    try:
        ar = conn.execute("SELECT * FROM lotto_draws WHERE draw_no = ?", (target_draw_no,)).fetchone()
        if not ar:
            return False
        a = dict(ar)
        actual_set = {a["num1"], a["num2"], a["num3"], a["num4"], a["num5"], a["num6"]}
        b = a["bonus"]
        rows = conn.execute(
            "SELECT id, num1, num2, num3, num4, num5, num6 FROM lotto_predictions "
            "WHERE target_draw_no = ?",
            (target_draw_no,),
        ).fetchall()
        for p in rows:
            d = dict(p)
            pr = {d["num1"], d["num2"], d["num3"], d["num4"], d["num5"], d["num6"]}
            matched = len(pr & actual_set)
            bonus_matched = 1 if b in pr else 0
            conn.execute(
                "UPDATE lotto_predictions SET matched_count = ?, bonus_matched = ? WHERE id = ?",
                (matched, bonus_matched, d["id"]),
            )
        conn.commit()
        return True
    finally:
        conn.close()


def _lstm_predict_sets(draws: list[dict], n_sets: int = 5) -> list[dict]:
    """LSTM 확률 벡터를 n_sets개의 {nums, confidence, reasoning} 세트로 변환.
    fusion.py의 가중 비복원 샘플링 로직을 LSTM 단독 벡터에 적용.
    """
    try:
        lstm_vec = get_lstm_prob_vector(draws)
    except Exception as e:  # noqa: BLE001
        logger.warning("LSTM 세트 생성 실패, 빈 리스트 반환: %s", e)
        return []

    is_uniform = all(
        abs(lstm_vec.get(n, 0) - (1 / 45)) < 1e-6 for n in range(1, 46)
    )

    results: list[dict] = []
    used: set[tuple[int, ...]] = set()
    attempts = 0
    pool_nums = list(range(1, 46))

    while len(results) < n_sets and attempts < 5000:
        attempts += 1
        pool = pool_nums[:]
        w = [lstm_vec.get(n, 1.0 / 45) for n in pool]
        nums: list[int] = []
        for _ in range(6):
            chosen = random.choices(pool, weights=w, k=1)[0]
            nums.append(chosen)
            idx = pool.index(chosen)
            pool.pop(idx)
            w.pop(idx)
        nums.sort()

        if not tier1_filter(nums):
            continue

        key = tuple(nums)
        if key in used:
            continue
        used.add(key)

        prob_sum = sum(lstm_vec.get(n, 0) for n in nums)
        confidence = round(min(prob_sum * 100 * 6, 99.9), 1)

        reasoning = (
            f"LSTM딥러닝v1(GPU, {len(draws)}회차학습), "
            f"{'uniform fallback' if is_uniform else '정상추론'}, "
            f"prob_sum={prob_sum:.4f}"
        )

        results.append(
            {
                "nums": nums,
                "confidence": confidence,
                "reasoning": reasoning,
            }
        )

    return results


# 하이에나 합의 입력: stat~fusion (DB 병합 시 brain_tag 일치)
_BASE_HYENA_SOURCE_TAGS: tuple[str, ...] = ("stat", "markov", "llm", "lstm", "fusion")


def _db_row_to_pred_dict(r: dict) -> dict:
    return {
        "nums": [r["num1"], r["num2"], r["num3"], r["num4"], r["num5"], r["num6"]],
        "confidence": r["confidence"],
        "reasoning": r.get("reasoning") or "",
        "method": r["method"],
        "brain_tag": r.get("brain_tag")
        or METHOD_TO_BRAIN_TAG.get(r.get("method", ""), "legacy"),
    }


def _delete_predictions_for_brain(conn, target_draw_no: int, brain_tag: str) -> None:
    if brain_tag == "llm":
        conn.execute(
            """
            DELETE FROM lotto_predictions
            WHERE target_draw_no = ? AND brain_tag IN ('llm', 'llm_fallback')
            """,
            (target_draw_no,),
        )
    elif brain_tag == "hyena":
        conn.execute(
            """
            DELETE FROM lotto_predictions
            WHERE target_draw_no = ? AND brain_tag = 'hyena'
            """,
            (target_draw_no,),
        )
    else:
        conn.execute(
            """
            DELETE FROM lotto_predictions
            WHERE target_draw_no = ? AND brain_tag = ?
            """,
            (target_draw_no, brain_tag),
        )


def _hyena_input_merged(
    conn,
    target_draw_no: int,
    fresh_by_tag: dict[str, list[dict]],
) -> list[dict]:
    """이번 실행에서 갱신한 태그는 fresh, 나머지는 DB에서 동일 회차 로드."""
    out: list[dict] = []
    for tag in _BASE_HYENA_SOURCE_TAGS:
        if tag in fresh_by_tag:
            out.extend(fresh_by_tag[tag])
            continue
        if tag == "llm":
            rows = conn.execute(
                """
                SELECT * FROM lotto_predictions
                WHERE target_draw_no = ? AND brain_tag IN ('llm', 'llm_fallback')
                """,
                (target_draw_no,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM lotto_predictions
                WHERE target_draw_no = ? AND brain_tag = ?
                """,
                (target_draw_no, tag),
            ).fetchall()
        for row in rows:
            out.append(_db_row_to_pred_dict(dict(row)))
    return out


def _build_cached_response(target_draw_no: int) -> dict:
    """DB에 저장된 예측을 응답 dict로 변환."""
    refresh_prediction_scores_for_target_draw(target_draw_no)
    conn = get_lotto_db()
    rows = conn.execute(
        "SELECT * FROM lotto_predictions WHERE target_draw_no = ? ORDER BY confidence DESC",
        (target_draw_no,),
    ).fetchall()
    conn.close()
    predictions = [dict(r) for r in rows]
    draws_n = len(_get_draws_before(target_draw_no))
    ar2 = get_lotto_db()
    drow = ar2.execute(
        "SELECT * FROM lotto_draws WHERE draw_no = ?", (target_draw_no,)
    ).fetchone()
    ar2.close()
    actual_nums: list[int] | None = None
    actual_b: int | None = None
    if drow:
        dd = dict(drow)
        actual_nums = sorted(
            [dd["num1"], dd["num2"], dd["num3"], dd["num4"], dd["num5"], dd["num6"]]
        )
        actual_b = dd["bonus"]
    enriched = [_predictions_row_to_enriched(r) for r in predictions]
    predict_only = [e for e in enriched if e.get("brain_tag") in ("stat", "markov", "review")]
    st = "기존 예측 반환 (1회 실행 원칙)"
    if actual_nums:
        st += " · 당첨·적중 자동 반영"
    out: dict = {
        "target_draw_no": target_draw_no,
        "status": st,
        "total_sets": len(enriched),
        "predictions": predictions,
        "all_predictions": enriched,
        "top5": (predict_only or enriched)[:5],
        "actual_numbers": actual_nums,
        "actual_bonus": actual_b,
        "brain_system": "testlotto_3predict_4aux",
    }
    if draws_n < 10:
        out["warning"] = f"데이터 부족으로 신뢰도가 낮습니다 (이전 데이터: {draws_n}회차)"
    return out


def run_prediction(target_draw_no: int, brain_filter: tuple[str, ...] = ()) -> dict:
    """테스트로또 3+4 뇌 체계 예측 (컨닝 방지: target_draw_no 이전 데이터만)."""
    from app.testlotto.brains.coordinator import run_coordinated_prediction

    return run_coordinated_prediction(target_draw_no, brain_filter)


def run_backtest(
    start_draw: int = 1100, end_draw: int = 0, brain_filter: tuple[str, ...] = ()
) -> dict:
    """과거 회차 범위를 역산 예측하여 적중률을 계산한다.
    - 피드백 자동 생성: 매 회차 예측 후 피드백 분석 저장
    - 중단/재개 지원: 이미 예측된 회차는 건너뛰고 결과만 수집
    - 진행 로그: 10회차마다 진행률 출력
    """
    conn = get_lotto_db()
    if end_draw <= 0:
        row = conn.execute("SELECT MAX(draw_no) FROM lotto_draws").fetchone()
        end_draw = row[0] if row and row[0] else start_draw
    conn.close()

    # 피드백 모듈 로드
    try:
        from app.testlotto.feedback import analyze_prediction_feedback, update_brain_weights

        has_feedback = True
    except ImportError:
        has_feedback = False
        logger.warning("lotto_feedback 모듈 없음 — 피드백 없이 진행")

    total_range = end_draw - start_draw + 1
    results = []

    for i, draw_no in enumerate(range(start_draw, end_draw + 1)):
        # 진행률 로그 (10회차마다)
        if i > 0 and i % 10 == 0:
            logger.info(
                "백테스트 진행: %d/%d (%.1f%%)", i, total_range, i / total_range * 100
            )

        try:
            result = run_prediction(draw_no, brain_filter=brain_filter)
        except Exception as e:
            logger.error("백테스트 %d회차 예측 실패: %s", draw_no, e)
            continue

        if "error" in result:
            continue

        # 최고 적중(동일 match 시 보너스 일치 우선) — 5적중 2·3등 구분
        conn2 = get_lotto_db()
        row_best = conn2.execute(
            """SELECT matched_count, bonus_matched FROM lotto_predictions
               WHERE target_draw_no = ?
               ORDER BY matched_count DESC, bonus_matched DESC LIMIT 1""",
            (draw_no,),
        ).fetchone()
        conn2.close()
        best_match = row_best[0] if row_best and row_best[0] is not None else 0
        best_bonus = int(row_best[1]) if row_best and row_best[1] is not None else 0

        # 피드백 자동 생성 (학습 핵심)
        if has_feedback and best_match >= 0:
            try:
                analyze_prediction_feedback(draw_no)
            except Exception as e:
                logger.debug("피드백 생성 스킵 %d회차: %s", draw_no, e)
            # Layer 3: 동적 가중치 갱신
            try:
                update_brain_weights(draw_no, last_n=50, eta=1.5, min_scored_draws=10)
            except Exception as e:
                logger.debug("가중치 갱신 스킵 %d회차: %s", draw_no, e)

        results.append(
            {
                "draw_no": draw_no,
                "best_match": best_match,
                "best_bonus": best_bonus,
            }
        )

    # 요약 통계
    match_dist = Counter(r["best_match"] for r in results)
    elite_draws = [r for r in results if r["best_match"] >= 3]

    rank_distribution: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 0: 0}
    total_lottery_score = 0
    best_lottery_score = 0
    elite2_count = 0
    for r in results:
        mc = int(r["best_match"])
        bm = int(r.get("best_bonus", 0) or 0)
        score = _calculate_lottery_score(mc, bm)
        total_lottery_score += score
        if score > best_lottery_score:
            best_lottery_score = score
        if mc == 6:
            rank_distribution[1] += 1
            elite2_count += 1
        elif mc == 5 and bm:
            rank_distribution[2] += 1
            elite2_count += 1
        elif mc == 5:
            rank_distribution[3] += 1
        elif mc == 4:
            rank_distribution[4] += 1
        elif mc == 3:
            rank_distribution[5] += 1
        else:
            rank_distribution[0] += 1

    n_tested = len(results)
    logger.info("백테스트 완료: %d회차, 3+적중 %d회", n_tested, len(elite_draws))

    return {
        "range": f"{start_draw}~{end_draw}",
        "total_tested": n_tested,
        "match_distribution": dict(match_dist),
        "rank_distribution": rank_distribution,
        "lottery_score_stats": {
            "total": total_lottery_score,
            "best": best_lottery_score,
            "avg": round(
                total_lottery_score / max(n_tested, 1),
                2,
            ),
        },
        "elite_draws": elite_draws,
        "elite_count": len(elite_draws),
        "elite2_count": elite2_count,
    }


# ═══════════════════════════════════════════
# 4. 두뇌 엘리트 시스템
# ═══════════════════════════════════════════


def get_brain_status() -> dict:
    """두뇌 엘리트 현황."""
    conn = get_lotto_db()

    # 전체 예측 통계
    _total = conn.execute("SELECT COUNT(*) FROM lotto_predictions").fetchone()[0]
    by_method = conn.execute(
        """SELECT method, COUNT(*) as cnt, AVG(matched_count) as avg_match,
                  MAX(matched_count) as best_match
           FROM lotto_predictions
           WHERE matched_count >= 0
           GROUP BY method"""
    ).fetchall()

    # 최고 적중 기록
    best = conn.execute(
        """SELECT * FROM lotto_predictions
           WHERE matched_count >= 0
           ORDER BY matched_count DESC, bonus_matched DESC, confidence DESC
           LIMIT 1"""
    ).fetchone()

    # 등급 결정
    best_match = 0
    if best:
        best_match = dict(best)["matched_count"]

    grade = "일반"
    for _threshold, name in sorted(ELITE_THRESHOLDS.items()):
        if best_match >= _threshold:
            grade = name

    # 두뇌별 강점 분석
    brain_profiles = []
    for orow in by_method:
        row = dict(orow)
        profile = {
            "method": row["method"],
            "total_predictions": row["cnt"],
            "avg_match": round(row["avg_match"], 2) if row["avg_match"] else 0,
            "best_match": row["best_match"],
        }
        # 강점 태그
        if row["avg_match"] and row["avg_match"] >= 2.0:
            profile["strength"] = "높은 평균 적중률"
        elif row["best_match"] and row["best_match"] >= 4:
            profile["strength"] = "폭발적 최고 기록"
        else:
            profile["strength"] = "안정적 분석"
        brain_profiles.append(profile)

    conn.close()
    from app.testlotto.brains.coordinator import get_brain_status_summary

    summary = get_brain_status_summary()
    return {
        "grade": grade,
        "grade_emoji": {
            "일반": "🧠",
            "엘리트": "⭐",
            "천재": "🔥",
            "전설": "👑",
            "신": "🌟",
        }.get(grade, "🧠"),
        "total_predictions": _total,
        "best_record": dict(best) if best else None,
        "brain_profiles": brain_profiles,
        "elite_thresholds": ELITE_THRESHOLDS,
        **summary,
    }


def get_hall_of_fame() -> dict:
    """적중 명예의 전당 — 3개 이상 적중한 모든 예측."""
    conn = get_lotto_db()
    rows = conn.execute(
        """SELECT p.*, d.num1 AS actual_1, d.num2 AS actual_2, d.num3 AS actual_3,
                  d.num4 AS actual_4, d.num5 AS actual_5, d.num6 AS actual_6,
                  d.bonus AS actual_bonus, d.draw_date
           FROM lotto_predictions p
           JOIN lotto_draws d ON p.target_draw_no = d.draw_no
           WHERE p.matched_count >= 3 AND p.brain_tag NOT IN ('miss_analysis','snake')
           ORDER BY p.matched_count DESC, p.bonus_matched DESC, p.target_draw_no DESC, p.confidence DESC"""
    ).fetchall()
    conn.close()

    hall: list[dict] = []
    for r in rows:
        r = dict(r)
        grade = "일반"
        for _threshold, name in sorted(ELITE_THRESHOLDS.items()):
            if r["matched_count"] >= _threshold:
                grade = name
        r["grade"] = grade
        hall.append(r)

    return {"hall_of_fame": hall}
