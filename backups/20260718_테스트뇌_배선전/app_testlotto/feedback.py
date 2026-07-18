"""로또 두뇌 피드백 분석 — app.testlotto 독립 패키지.
2026-04-20: Layer 2-c — brain_tag 기반 집계 추가 (brain_tag_performance 저장, get_brain_tag_ranking 신규)
2026-04-25 Layer 3: update_brain_weights() 추가 — Hedge 알고리즘 기반 동적 가중치 갱신.
2026-04-25 Layer 3.5: eta 0.3 → 1.5 강화 (LSTM 비중 36% → 69%, 1티어 비대칭 앙상블).
2026-04-25 Layer 5-B: Lottery-Aware Scoring 도입 — 등수 점수 (1등 100, 2등 50, 3등 30, 4등 10, 5등 3) + Hedge η에 보너스 신호 반영.
2026-04-25 Layer 5-B 보정: Hedge 시그널을 avg_lottery_score/10 → avg_match + avg_lottery_score/30 하이브리드로 전환 (LSTM 비중 32.8% → 74.0% 회복).
2026-04-20 Layer 5-A2: hyena Hedge + _load_layer3_weights_5 (5뇌); fusion용 _load_brain_weights_from_db는 4뇌·시그니처 불변.
"""
import json
import logging
import math
from collections import Counter
from app.testlotto.models import get_lotto_db

logger = logging.getLogger(__name__)

# init_lotto_db 시드와 동일 (testlotto_brain_weights 기본값; fusion fallback은 4뇌만 사용)
SEED_WEIGHTS: dict[str, float] = {
    "stat": 1.5,
    "markov": 1.0,
    "llm": 2.5,
    "lstm": 2.0,
    "hyena": 1.0,
}
# fusion.py 등: 4뇌만 (hyena 제외). _load_brain_weights_from_db 검증/반환에 사용 — LAYER3와 독립.
_FUSION_DB_BRAIN_TAGS: tuple[str, ...] = ("stat", "markov", "llm", "lstm")
LAYER3_BRAIN_TAGS: tuple[str, ...] = ("stat", "markov", "llm", "lstm", "hyena")
EXCLUDED_UPDATE_TAGS: frozenset[str] = frozenset({"fusion", "legacy", "llm_fallback"})


def analyze_prediction_feedback(target_draw_no: int) -> dict | None:
    """
    특정 회차의 예측 결과를 분석하여 피드백 생성.
    - 어떤 두뇌가 가장 잘 맞췄는지
    - 적중 번호의 공통 특성 (홀짝, 구간, 합계)
    - 실패 번호의 공통 특성
    """
    conn = get_lotto_db()

    # 실제 당첨번호 조회
    draw = conn.execute(
        "SELECT * FROM lotto_draws WHERE draw_no = ?",
        (target_draw_no,),
    ).fetchone()
    if not draw:
        conn.close()
        return None
    draw = dict(draw)
    actual = {draw[f"num{i}"] for i in range(1, 7)}

    # 해당 회차 예측 조회
    preds = conn.execute(
        "SELECT * FROM lotto_predictions WHERE target_draw_no = ? ORDER BY confidence DESC",
        (target_draw_no,),
    ).fetchall()
    if not preds:
        conn.close()
        return None
    preds = [dict(p) for p in preds]

    # 두뇌별 성적
    method_stats = {}
    for p in preds:
        m = p["method"]
        if m not in method_stats:
            method_stats[m] = {"total": 0, "best": 0, "sum_match": 0}
        method_stats[m]["total"] += 1
        method_stats[m]["sum_match"] += p["matched_count"]
        if p["matched_count"] > method_stats[m]["best"]:
            method_stats[m]["best"] = p["matched_count"]

    for m in method_stats:
        s = method_stats[m]
        s["avg_match"] = round(s["sum_match"] / s["total"], 2) if s["total"] > 0 else 0

    # ── brain_tag 기반 집계 (Layer 2-c 신규) ──
    # method는 UI 호환용 한글, brain_tag는 진화 계산용 영문
    brain_stats: dict = {}
    for p in preds:
        # brain_tag 누락 레코드(legacy) 안전 처리
        bt = p["brain_tag"] if ("brain_tag" in p.keys() and p["brain_tag"]) else "legacy"
        if bt not in brain_stats:
            brain_stats[bt] = {"total": 0, "best": 0, "sum_match": 0}
        brain_stats[bt]["total"] += 1
        mc = p["matched_count"] if p["matched_count"] is not None else -1
        if mc >= 0:
            brain_stats[bt]["sum_match"] += mc
            if mc > brain_stats[bt]["best"]:
                brain_stats[bt]["best"] = mc
    for bt in brain_stats:
        s = brain_stats[bt]
        s["avg_match"] = round(s["sum_match"] / s["total"], 2) if s["total"] > 0 else 0

    # 적중 번호 분석: 예측에서 실제 당첨번호와 겹친 번호들
    hit_numbers = Counter()
    miss_numbers = Counter()
    for p in preds:
        pred_nums = {p[f"num{i}"] for i in range(1, 7)}
        hits = pred_nums & actual
        misses = pred_nums - actual
        for n in hits:
            hit_numbers[n] += 1
        for n in misses:
            miss_numbers[n] += 1

    # 적중 번호 특성
    hit_traits: dict = {}
    if hit_numbers:
        hit_list = [n for n, _ in hit_numbers.most_common()]
        hit_traits["numbers"] = hit_list
        hit_traits["avg"] = round(sum(hit_list) / len(hit_list), 1)
        hit_traits["odd_ratio"] = round(
            sum(1 for n in hit_list if n % 2 == 1) / len(hit_list), 2
        )
        hit_traits["ranges"] = list({(n - 1) // 10 for n in hit_list})

    # 미적중 번호 중 과다 선택된 번호 (함정 번호)
    trap_numbers = [n for n, cnt in miss_numbers.most_common(5) if cnt >= 3]

    feedback = {
        "target_draw_no": target_draw_no,
        "actual_numbers": sorted(actual),
        "method_performance": method_stats,
        "brain_tag_performance": brain_stats,  # Layer 2-c 신규
        "hit_traits": hit_traits,
        "trap_numbers": trap_numbers,
        "total_predictions": len(preds),
    }

    # lotto_analysis에 저장
    # 기존 피드백 삭제 후 새로 삽입 (중복 방지)
    conn.execute(
        "DELETE FROM lotto_analysis WHERE draw_no = ? AND analysis_type = 'prediction_feedback'",
        (target_draw_no,),
    )
    conn.execute(
        "INSERT INTO lotto_analysis (draw_no, analysis_type, data_json) VALUES (?, ?, ?)",
        (target_draw_no, "prediction_feedback", json.dumps(feedback, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()

    logger.info(
        "피드백 저장: %d회차, 두뇌 %d종, 적중번호 %d개",
        target_draw_no,
        len(method_stats),
        len(hit_numbers),
    )
    return feedback


def get_feedback_summary(last_n: int = 20) -> dict:
    """
    최근 N개 회차의 피드백을 종합하여 두뇌별 성적과 패턴 반환.
    _statistical_predict, _hybrid_predict에서 가중치 조정에 활용.
    """
    conn = get_lotto_db()
    rows = conn.execute(
        """SELECT data_json FROM lotto_analysis
           WHERE analysis_type = 'prediction_feedback'
           ORDER BY draw_no DESC LIMIT ?""",
        (last_n,),
    ).fetchall()
    conn.close()

    if not rows:
        return {"has_feedback": False}

    method_totals = {}
    brain_tag_totals: dict = {}
    all_trap_numbers = Counter()
    all_hit_numbers = Counter()

    for row in rows:
        fb = json.loads(row[0])
        for method, stats in fb.get("method_performance", {}).items():
            if method not in method_totals:
                method_totals[method] = {"draws": 0, "sum_best": 0, "sum_avg": 0}
            method_totals[method]["draws"] += 1
            method_totals[method]["sum_best"] += stats.get("best", 0)
            method_totals[method]["sum_avg"] += stats.get("avg_match", 0)
        for bt, stats in fb.get("brain_tag_performance", {}).items():
            if bt not in brain_tag_totals:
                brain_tag_totals[bt] = {"draws": 0, "sum_best": 0, "sum_avg": 0.0}
            brain_tag_totals[bt]["draws"] += 1
            brain_tag_totals[bt]["sum_best"] += stats.get("best", 0)
            brain_tag_totals[bt]["sum_avg"] += stats.get("avg_match", 0)
        for n in fb.get("trap_numbers", []):
            all_trap_numbers[n] += 1
        for n in fb.get("hit_traits", {}).get("numbers", []):
            all_hit_numbers[n] += 1

    # 두뇌별 종합 성적
    brain_ranking = {}
    for method, t in method_totals.items():
        brain_ranking[method] = {
            "draws": t["draws"],
            "avg_best": round(t["sum_best"] / t["draws"], 2) if t["draws"] > 0 else 0,
            "avg_match": round(t["sum_avg"] / t["draws"], 2) if t["draws"] > 0 else 0,
        }

    # brain_tag별 종합 성적 (Layer 2-c)
    brain_tag_ranking: dict = {}
    for bt, t in brain_tag_totals.items():
        draws = t["draws"] if t["draws"] > 0 else 1
        brain_tag_ranking[bt] = {
            "draws": t["draws"],
            "avg_best": round(t["sum_best"] / draws, 2),
            "avg_match": round(t["sum_avg"] / draws, 2),
        }

    return {
        "has_feedback": True,
        "brain_ranking": brain_ranking,
        "brain_tag_ranking": brain_tag_ranking,
        "frequent_traps": [n for n, _ in all_trap_numbers.most_common(10)],
        "frequent_hits": [n for n, _ in all_hit_numbers.most_common(10)],
        "feedback_count": len(rows),
    }


def generate_all_feedback() -> int:
    """
    예측이 있고 당첨번호도 있는 모든 회차에 대해 피드백 생성.
    이미 피드백이 있는 회차는 건너뜀.
    """
    conn = get_lotto_db()

    # 피드백이 이미 있는 회차
    existing = set()
    rows = conn.execute(
        "SELECT draw_no FROM lotto_analysis WHERE analysis_type = 'prediction_feedback'"
    ).fetchall()
    for r in rows:
        existing.add(r[0])

    # 예측이 있고 matched_count >= 0인 회차 (채점 완료된 것만)
    targets = conn.execute(
        """SELECT DISTINCT target_draw_no FROM lotto_predictions
           WHERE matched_count >= 0
           ORDER BY target_draw_no"""
    ).fetchall()
    conn.close()

    count = 0
    for row in targets:
        draw_no = row[0]
        if draw_no in existing:
            continue
        result = analyze_prediction_feedback(draw_no)
        if result:
            count += 1

    logger.info("피드백 일괄 생성 완료: %d개 회차", count)
    return count


def _calculate_lottery_score(matched_count: int, bonus_matched: int) -> int:
    """한국 로또 등수 기반 점수 계산.

    1등(6적중)=100, 2등(5적중+보너스)=50, 3등(5적중)=30,
    4등(4적중)=10, 5등(3적중)=3, 그 외=0.
    """
    if matched_count < 0:
        return 0
    if matched_count == 6:
        return 100
    if matched_count == 5:
        return 50 if bonus_matched else 30
    if matched_count == 4:
        return 10
    if matched_count == 3:
        return 3
    return 0


def get_brain_tag_ranking(last_n: int = 50, max_draw_no: int | None = None) -> dict:
    """
    brain_tag별 성적 집계 — Layer 3 동적 가중치 전용.
    lotto_predictions 테이블을 직접 집계 (JSON 우회).

    컨닝 방지: matched_count >= 0 조건으로 채점 완료된 과거 예측만 사용.
    max_draw_no 지정 시 해당 회차 이하만 집계(walk-forward 백필·N회차 갱신용).

    Args:
        last_n: 최근 N개 target_draw_no (기본 50)
        max_draw_no: 상한 회차(포함). None이면 DB 전체 최신 기준.

    Returns:
        {
            'has_data': bool,
            'rankings': {
                'stat': {
                    'total', 'avg_match', 'best_match', 'sum_match',
                    'avg_lottery_score', 'best_lottery_score', 'sum_lottery_score',
                    'bonus_hit_rate', 'rank_distribution' (1~5등 횟수)
                },
                'markov': {...},
                'llm', 'lstm', 'fusion' 등: 호출자가 fusion 등 필터
            },
            'scored_draws': int,
        }
    """
    from app.testlotto.models import get_lotto_db

    conn = get_lotto_db()
    try:
        # 최근 N개 채점된 target_draw_no (컨닝 방지: matched_count >= 0만)
        if max_draw_no is not None:
            recent_targets = conn.execute(
                """SELECT DISTINCT target_draw_no FROM lotto_predictions
                   WHERE matched_count >= 0 AND target_draw_no <= ?
                   ORDER BY target_draw_no DESC
                   LIMIT ?""",
                (max_draw_no, last_n),
            ).fetchall()
        else:
            recent_targets = conn.execute(
                """SELECT DISTINCT target_draw_no FROM lotto_predictions
                   WHERE matched_count >= 0
                   ORDER BY target_draw_no DESC
                   LIMIT ?""",
                (last_n,),
            ).fetchall()

        if not recent_targets:
            return {"has_data": False, "rankings": {}, "scored_draws": 0}

        target_ids = [r[0] for r in recent_targets]
        placeholders = ",".join(["?"] * len(target_ids))

        rows = conn.execute(
            f"""SELECT brain_tag, matched_count, bonus_matched
                FROM lotto_predictions
                WHERE target_draw_no IN ({placeholders})
                  AND matched_count >= 0""",
            target_ids,
        ).fetchall()

        agg: dict = {}
        for row in rows:
            bt = row[0] or "legacy"
            mc = int(row[1]) if row[1] is not None else 0
            bm = int(row[2]) if row[2] is not None else 0
            score = _calculate_lottery_score(mc, bm)
            if bt not in agg:
                agg[bt] = {
                    "total": 0,
                    "sum_match": 0,
                    "best_match": 0,
                    "sum_score": 0,
                    "best_score": 0,
                    "bonus_hits": 0,
                    "rank_count": {1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
                }
            a = agg[bt]
            a["total"] += 1
            a["sum_match"] += mc
            a["best_match"] = max(a["best_match"], mc)
            a["sum_score"] += score
            a["best_score"] = max(a["best_score"], score)
            if bm:
                a["bonus_hits"] += 1
            if mc == 6:
                a["rank_count"][1] += 1
            elif mc == 5 and bm:
                a["rank_count"][2] += 1
            elif mc == 5:
                a["rank_count"][3] += 1
            elif mc == 4:
                a["rank_count"][4] += 1
            elif mc == 3:
                a["rank_count"][5] += 1

        rankings: dict = {}
        for bt, a in agg.items():
            total = a["total"] if a["total"] > 0 else 1
            rankings[bt] = {
                "total": a["total"],
                "avg_match": round(a["sum_match"] / total, 3),
                "best_match": a["best_match"],
                "sum_match": a["sum_match"],
                "avg_lottery_score": round(a["sum_score"] / total, 3),
                "best_lottery_score": a["best_score"],
                "sum_lottery_score": a["sum_score"],
                "bonus_hit_rate": round(a["bonus_hits"] / total, 3),
                "rank_distribution": dict(a["rank_count"]),
            }

        return {
            "has_data": True,
            "rankings": rankings,
            "scored_draws": len(target_ids),
        }
    finally:
        conn.close()


def update_brain_weights(
    target_draw_no: int,
    last_n: int = 50,
    eta: float = 1.5,
    min_scored_draws: int = 10,
    *,
    force: bool = False,
) -> dict:
    """
    Hedge: new_weight[bt] = base_weight[bt] * exp(eta * (avg_match + avg_lottery_score/30)) — Layer 5-B 보정.
    recent_avg_match 컬럼에는 기존과 같이 avg_match(평균 적중 개수)를 저장.
    testlotto_brain_weights에 stat/markov/llm/lstm/hyena만 UPDATE (INSERT 금지).
    total_predictions / total_matches는 get_brain_tag_ranking 집계의 total / sum_match에 대응.

    컨닝 방지: target_draw_no 이하 채점 데이터만 사용(max_draw_no=target_draw_no).
    멱등성: last_updated_draw >= target_draw_no 이면 skip(force=True 시 재갱신).
    """
    try:
        conn_chk = get_lotto_db()
        try:
            ph = ",".join("?" * len(LAYER3_BRAIN_TAGS))
            row = conn_chk.execute(
                f"SELECT MAX(last_updated_draw) FROM testlotto_brain_weights "
                f"WHERE brain_tag IN ({ph})",
                LAYER3_BRAIN_TAGS,
            ).fetchone()
            max_updated = int(row[0] or 0)
        finally:
            conn_chk.close()

        if not force and max_updated >= target_draw_no:
            return {
                "updated": False,
                "reason": "already_updated",
                "target_draw_no": target_draw_no,
                "last_updated_draw": max_updated,
            }

        r = get_brain_tag_ranking(last_n, max_draw_no=target_draw_no)
        scored = r.get("scored_draws") or 0
        if not r.get("has_data") or scored < min_scored_draws:
            return {
                "updated": False,
                "reason": "insufficient_data",
                "scored_draws": scored,
            }

        rankings: dict = r.get("rankings") or {}

        conn = get_lotto_db()
        try:
            for bt in LAYER3_BRAIN_TAGS:
                if bt not in rankings or bt in EXCLUDED_UPDATE_TAGS:
                    continue
                rec = rankings[bt]
                avg_m = float(rec["avg_match"])
                total_pred = int(rec["total"])
                total_match_sum = int(rec["sum_match"])
                base = SEED_WEIGHTS[bt]
                raw_match = float(rec.get("avg_match", 0) or 0.0)
                raw_score = float(rec.get("avg_lottery_score", 0) or 0.0)
                # 하이브리드 시그널: avg_match 보존 + 등수 보너스 가산
                score_signal = raw_match + raw_score / 30.0
                nw = base * math.exp(eta * score_signal)
                conn.execute(
                    """
                    UPDATE testlotto_brain_weights
                    SET current_weight = ?,
                        recent_avg_match = ?,
                        total_predictions = ?,
                        total_matches = ?,
                        last_updated_draw = ?,
                        updated_at = datetime('now', 'localtime')
                    WHERE brain_tag = ?
                    """,
                    (nw, avg_m, total_pred, total_match_sum, target_draw_no, bt),
                )
            conn.commit()
        finally:
            conn.close()

        # 갱신 후 Layer3 5행 읽어 반환 weights 구성 (fusion 4키 로더 미사용)
        final_w = _load_layer3_weights_5()
        logger.info(
            "Layer 3 weights updated: target=%d, weights=%s",
            target_draw_no,
            final_w,
        )
        return {
            "updated": True,
            "target_draw_no": target_draw_no,
            "scored_draws": scored,
            "weights": final_w,
            "raw_avg_match": {
                b: float((rankings.get(b) or {}).get("avg_match", 0) or 0)
                for b in LAYER3_BRAIN_TAGS
            },
            "raw_avg_lottery_score": {
                b: float((rankings.get(b) or {}).get("avg_lottery_score", 0) or 0)
                for b in LAYER3_BRAIN_TAGS
            },
            "score_signals": {
                b: float((rankings.get(b) or {}).get("avg_match", 0) or 0)
                + float((rankings.get(b) or {}).get("avg_lottery_score", 0) or 0)
                / 30.0
                for b in LAYER3_BRAIN_TAGS
            },
        }
    except Exception as e:  # noqa: BLE001
        return {"updated": False, "reason": str(e)}


def maybe_update_brain_weights_after_scoring(target_draw_no: int) -> dict:
    """당첨번호 확정·채점 후 brain_weights 자동 갱신 훅.

    - lotto_draws에 당첨번호(num1) 없으면 skip
    - update_brain_weights 멱등 호출 (중복 갱신 방지)
    - 6뇌/lead1 예측값은 READ-ONLY (본 함수는 testlotto_brain_weights만 UPDATE)
    """
    conn = get_lotto_db()
    try:
        row = conn.execute(
            "SELECT num1 FROM lotto_draws WHERE draw_no = ?", (target_draw_no,)
        ).fetchone()
        if not row or row[0] is None:
            return {"updated": False, "reason": "draw_not_scored", "target_draw_no": target_draw_no}
    finally:
        conn.close()

    result = update_brain_weights(
        target_draw_no, last_n=50, eta=1.5, min_scored_draws=10,
    )
    if result.get("updated"):
        logger.info(
            "[brain_weights] auto-updated draw=%d weights=%s",
            target_draw_no,
            result.get("weights"),
        )
    else:
        logger.debug(
            "[brain_weights] skip draw=%d reason=%s",
            target_draw_no,
            result.get("reason"),
        )
    return result


def _load_brain_weights_from_db() -> dict[str, float]:
    """fusion Layer 3: current_weight 4행 조회. 실패 시 models 시드 dict와 동일 값 fallback."""
    seed = {k: float(SEED_WEIGHTS[k]) for k in _FUSION_DB_BRAIN_TAGS}
    try:
        conn = get_lotto_db()
        try:
            rows = conn.execute(
                """
                SELECT brain_tag, current_weight FROM testlotto_brain_weights
                WHERE brain_tag IN ('stat', 'markov', 'llm', 'lstm')
                """
            ).fetchall()
        finally:
            conn.close()
        if len(rows) < 4:
            logger.warning("testlotto_brain_weights DB 조회 실패 — 시드값 fallback")
            return seed
        got: dict[str, float] = {str(r[0]): float(r[1]) for r in rows}
        for bt in _FUSION_DB_BRAIN_TAGS:
            if bt not in got:
                logger.warning("testlotto_brain_weights DB 조회 실패 — 시드값 fallback")
                return seed
        return {bt: got[bt] for bt in _FUSION_DB_BRAIN_TAGS}
    except Exception:  # noqa: BLE001
        logger.warning("testlotto_brain_weights DB 조회 실패 — 시드값 fallback")
        return seed


def _load_layer3_weights_5() -> dict[str, float]:
    """Layer3 Hedge: stat/markov/llm/lstm/hyena 5행 current_weight. 실패 시 SEED_WEIGHTS(5키) fallback."""
    seed = {k: float(SEED_WEIGHTS[k]) for k in LAYER3_BRAIN_TAGS}
    try:
        conn = get_lotto_db()
        try:
            rows = conn.execute(
                """
                SELECT brain_tag, current_weight FROM testlotto_brain_weights
                WHERE brain_tag IN ('stat', 'markov', 'llm', 'lstm', 'hyena')
                """
            ).fetchall()
        finally:
            conn.close()
        if len(rows) < 5:
            logger.warning("testlotto_brain_weights Layer3 5행 미충족 — 시드값 fallback")
            return seed
        got: dict[str, float] = {str(r[0]): float(r[1]) for r in rows}
        for bt in LAYER3_BRAIN_TAGS:
            if bt not in got:
                logger.warning("testlotto_brain_weights Layer3 조회 불완전 — 시드값 fallback")
                return seed
        return {bt: got[bt] for bt in LAYER3_BRAIN_TAGS}
    except Exception:  # noqa: BLE001
        logger.warning("testlotto_brain_weights Layer3 조회 실패 — 시드값 fallback")
        return seed
