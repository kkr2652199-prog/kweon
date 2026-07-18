"""테스트로또 3+4 뇌 코디네이터 — 예측3뇌 생성 → 보조4뇌 채점 → DB저장."""

from __future__ import annotations

import logging

from app.testlotto.brains import aux_balance_keeper, aux_miss_detective, aux_pattern_spotlight, aux_referee
from app.testlotto.brains import predict_flow_shaman, predict_review_king, predict_stat_fairy
from app.testlotto.brains.registry import AUX_BRAINS, PREDICT_BRAINS, SETS_PER_PREDICT_BRAIN
from app.testlotto.data_service import _get_draws_before
from app.testlotto.learn_state import get_referee_weights
from app.testlotto.models import get_lotto_db, init_lotto_db

logger = logging.getLogger(__name__)

PREDICT_MODULES = {
    "stat": predict_stat_fairy,
    "markov": predict_flow_shaman,
    "review": predict_review_king,
}

AUX_MODULES = [
    aux_miss_detective,
    aux_pattern_spotlight,
    aux_balance_keeper,
    aux_referee,
]

AUX_WEIGHTS = [0.25, 0.25, 0.25, 0.25]
PREDICT_TAGS = [b["tag"] for b in PREDICT_BRAINS]


def _delete_predictions_for_brain(conn, target_draw_no: int, brain_tag: str) -> None:
    conn.execute(
        "DELETE FROM lotto_predictions WHERE target_draw_no = ? AND brain_tag = ?",
        (target_draw_no, brain_tag),
    )


def _aux_composite_score(nums: list[int], draws: list[dict], target_draw_no: int) -> float:
    total = 0.0
    for mod, w in zip(AUX_MODULES, AUX_WEIGHTS):
        total += w * mod.score_set(nums, draws, target_draw_no)
    return total


def _apply_aux_scoring(candidates: list[dict], draws: list[dict], target_draw_no: int) -> list[dict]:
    ref_weights = get_referee_weights()
    out: list[dict] = []
    for c in candidates:
        aux_score = _aux_composite_score(c["nums"], draws, target_draw_no)
        base = float(c.get("confidence", 60))
        brain_w = ref_weights.get(c.get("brain_tag", ""), 1.0 / 3)
        final_conf = min(99.5, base * 0.5 * brain_w + aux_score * 40 + base * 0.1)
        aux_notes = " | ".join(
            m.describe(c["nums"], draws, target_draw_no) for m in AUX_MODULES
        )
        out.append(
            {
                **c,
                "confidence": round(final_conf, 1),
                "reasoning": f"{c.get('reasoning', '')} [보조4뇌:{aux_score:.2f}] {aux_notes}",
            }
        )
    return out


def run_coordinated_prediction(target_draw_no: int, brain_filter: tuple[str, ...] = ()) -> dict:
    """3 미래예측 뇌 × 5세트 + 4 보조 뇌 채점."""
    init_lotto_db()
    conn = get_lotto_db()
    bf = brain_filter

    def run(tag: str) -> bool:
        return (not bf) or (tag in bf)

    existing = conn.execute(
        "SELECT brain_tag FROM lotto_predictions WHERE target_draw_no = ?",
        (target_draw_no,),
    ).fetchall()
    tags_in_db = {r[0] for r in existing}
    if existing and (not bf) and all(t in tags_in_db for t in PREDICT_TAGS):
        conn.close()
        from app.testlotto.engine import _build_cached_response

        return _build_cached_response(target_draw_no)

    draws = _get_draws_before(target_draw_no)
    if not draws:
        conn.close()
        return {"error": f"이전 당첨 데이터가 없습니다. {target_draw_no}회차 이전 회차를 먼저 수집하세요."}

    candidates: list[dict] = []
    for brain in PREDICT_BRAINS:
        tag = brain["tag"]
        if not run(tag):
            continue
        mod = PREDICT_MODULES[tag]
        _delete_predictions_for_brain(conn, target_draw_no, tag)
        sets = mod.predict_sets(draws, SETS_PER_PREDICT_BRAIN)
        candidates.extend(sets)
        logger.info("[테스트로또] %s %d세트", brain["name"], len(sets))

    if not candidates:
        conn.rollback()
        conn.close()
        return {"error": "생성할 예측이 없습니다 (brain_filter·이전 데이터 확인)."}

    scored = _apply_aux_scoring(candidates, draws, target_draw_no)
    scored.sort(key=lambda x: x["confidence"], reverse=True)

    actual_row = conn.execute(
        "SELECT * FROM lotto_draws WHERE draw_no = ?", (target_draw_no,)
    ).fetchone()
    actual_nums: set[int] | None = None
    actual_bonus = 0
    if actual_row:
        actual = dict(actual_row)
        actual_nums = {
            actual["num1"],
            actual["num2"],
            actual["num3"],
            actual["num4"],
            actual["num5"],
            actual["num6"],
        }
        actual_bonus = actual["bonus"]

    for pred in scored:
        matched = -1
        bonus_matched = 0
        if actual_nums:
            pred_set = set(pred["nums"])
            matched = len(pred_set & actual_nums)
            bonus_matched = 1 if actual_bonus in pred_set else 0
        conn.execute(
            """INSERT INTO lotto_predictions
               (target_draw_no, method, brain_tag, num1, num2, num3, num4, num5, num6,
                confidence, reasoning, matched_count, bonus_matched)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                target_draw_no,
                pred["method"],
                pred.get("brain_tag", "legacy"),
                pred["nums"][0],
                pred["nums"][1],
                pred["nums"][2],
                pred["nums"][3],
                pred["nums"][4],
                pred["nums"][5],
                pred["confidence"],
                pred["reasoning"],
                matched,
                bonus_matched,
            ),
        )

    conn.commit()
    conn.close()

    from app.testlotto.engine import _build_cached_response

    out = _build_cached_response(target_draw_no)
    out["status"] = "예측 완료 (3+4뇌 체계)"
    out["brain_system"] = "testlotto_3predict_4aux"
    if len(draws) < 10:
        out["warning"] = f"데이터 부족 (이전 {len(draws)}회)"
    return out


def get_brain_status_summary() -> dict:
    """두뇌 상태 API용 3+4 체계 요약."""
    return {
        "system": "testlotto_3predict_4aux",
        "predict_brains": PREDICT_BRAINS,
        "aux_brains": AUX_BRAINS,
        "sets_per_predict_brain": SETS_PER_PREDICT_BRAIN,
        "total_predict_sets": SETS_PER_PREDICT_BRAIN * len(PREDICT_BRAINS),
    }
