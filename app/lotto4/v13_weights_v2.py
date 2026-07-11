"""4군 v13 가중치·뇌 순서 — 9뇌 독립 엔진 (lotto4.brains)."""

from __future__ import annotations

from app.lotto4.models import get_lotto4_db

# 레지스트리·UI·헤지 시드에는 9뇌 유지. predict 루프·DB 저장 행 수는 HIDDEN 제외.
V13_V2_HIDDEN_BRAINS: frozenset[str] = frozenset({"v13_cdm", "v13_cond_prob"})

# 백테스트·구버전 DB 행에 남은 태그 → 현행 v13 태그 (표시·필터 확장용, DB는 변경 안 함)
V13_LEGACY_TO_CANONICAL: dict[str, str] = {
    "v13_bayesian": "v13_cdm",
    "v13_graph": "v13_cond_prob",
    "v13_contrarian_v2": "v13_gap",
    "v13_gen": "v13_diversity",
    "v13_transformer": "v13_seq",
    "v13_trend": "v13_struct",
    "v13_rl": "v13_evolution",
    "v13_anti_popular": "v13_ev",
}


def canonical_v13_brain_tag(tag: str) -> str:
    t = (tag or "").strip().lower()
    return V13_LEGACY_TO_CANONICAL.get(t, t)


def expand_v13_brain_tags_for_filter(tag: str) -> frozenset[str]:
    """명예의 전당 등에서 뇌 필터용: 신·구 태그 동시 매칭."""
    c = canonical_v13_brain_tag(tag)
    out: set[str] = {c}
    for leg, cc in V13_LEGACY_TO_CANONICAL.items():
        if cc == c:
            out.add(leg)
    return frozenset(out)


V13_V2_BRAIN_ORDER: tuple[str, ...] = (
    "v13_struct",
    "v13_cdm",
    "v13_seq",
    "v13_cond_prob",
    "v13_diversity",
    "v13_evolution",
    "v13_gap",
    "v13_ev",
    "v13_ensemble",
)

V13_BRAIN_METHOD: dict[str, str] = {
    "v13_struct": "구조변수 XGBoost 회귀",
    "v13_cdm": "CDM 디리클레·다중윈도우",
    "v13_seq": "LSTM+Attention 시퀀스",
    "v13_cond_prob": "조건부확률 P(B|A)·P(C|A,B)",
    "v13_diversity": "다양성·십단위 커버",
    "v13_evolution": "진화·동적 신뢰도 메타",
    "v13_gap": "갭(Z-score) 리스코어",
    "v13_ensemble": "Attention MoE 메타",
    "v13_ev": "비인기·기대값(배당)",
}

V13_BRAIN_LABEL_UI: dict[str, str] = {
    "v13_struct": "📐 구조예측",
    "v13_cdm": "🎯 CDM",
    "v13_seq": "🧬 시퀀스",
    "v13_cond_prob": "🔗 조건부확률",
    "v13_diversity": "🌈 다양성",
    "v13_evolution": "🧬 진화",
    "v13_gap": "📉 갭분석",
    "v13_ensemble": "🧠 앙상블",
    "v13_ev": "💎 기대값",
}

V13_V2_PREDICT_ORDER: tuple[str, ...] = tuple(
    t for t in V13_V2_BRAIN_ORDER if t not in V13_V2_HIDDEN_BRAINS
)

SETS_PER_BRAIN_V2 = 5
V13_V2_TOTAL_ROWS = len(V13_V2_PREDICT_ORDER) * SETS_PER_BRAIN_V2

V13_V2_SEED_WEIGHTS: dict[str, float] = {tag: 1.0 for tag in V13_V2_BRAIN_ORDER}

# ---------------------------------------------------------------------------
# 회차별 헤지 — update_v13_v2_weights() 튜닝용 상수
#
# 직전 target_draw_no에서 채점된 해당 뇌 예측(보통 5세트)의 평균 matched_count 를 avg_mc 라 할 때,
#   delta = HEDGE_LEARNING_RATE * (avg_mc - HEDGE_REFERENCE_MATCH)
#   new_w = clip(old_w + delta, WEIGHT_CLIP_MIN, WEIGHT_CLIP_MAX)
#
# 배경: 무작위 한 장 기대 적중 ≈ 0.8.
# 2026-05-13 재조정: ref 과대로 전 뇌 CLIP_MIN 동반 수렴 방지 → ref 낮추고 lr·min 완화.
# ---------------------------------------------------------------------------
HEDGE_REFERENCE_MATCH = 0.85
HEDGE_LEARNING_RATE = 0.02
WEIGHT_CLIP_MIN = 0.3
WEIGHT_CLIP_MAX = 3.0


def init_v13_v2_seeds() -> None:
    conn = get_lotto4_db()
    try:
        for tag, weight in V13_V2_SEED_WEIGHTS.items():
            conn.execute(
                """
                INSERT OR IGNORE INTO lotto_brain_weights_army4 (brain_tag, current_weight)
                VALUES (?, ?)
                """,
                (tag, float(weight)),
            )
        conn.commit()
    finally:
        conn.close()


def get_v13_v2_brain_weights() -> dict[str, float]:
    conn = get_lotto4_db()
    try:
        ph = ",".join("?" * len(V13_V2_SEED_WEIGHTS))
        tags = tuple(V13_V2_SEED_WEIGHTS.keys())
        rows = conn.execute(
            f"""
            SELECT brain_tag, current_weight FROM lotto_brain_weights_army4
            WHERE brain_tag IN ({ph})
            """,
            tags,
        ).fetchall()
        out = {
            str(r["brain_tag"]): float(r["current_weight"])
            for r in rows
            if r["current_weight"] is not None
        }
        for tag, seed in V13_V2_SEED_WEIGHTS.items():
            out.setdefault(tag, seed)
        return out
    finally:
        conn.close()


def update_v13_v2_weights(target_draw_no: int) -> None:
    """간단 Hedge: 직전 회차 해당 뇌 평균 적중에 따라 가중치 미세 조정.

    당첨 번호가 아직 `lotto_draws`에 없으면 채점이 없으므로 가중치를 건드리지 않는다.
    (그대로 두면 AVG가 비어 0으로 처리되어 전 뇌가 불공정하게 감쇠했음.)
    """
    conn = get_lotto4_db()
    try:
        if not conn.execute(
            "SELECT 1 FROM lotto_draws WHERE draw_no = ? LIMIT 1",
            (target_draw_no,),
        ).fetchone():
            return
        for tag in V13_V2_BRAIN_ORDER:
            if tag in V13_V2_HIDDEN_BRAINS:
                continue
            r = conn.execute(
                """
                SELECT AVG(matched_count) FROM lotto_predictions_army4
                WHERE target_draw_no = ? AND brain_tag = ? AND matched_count >= 0
                """,
                (target_draw_no, tag),
            ).fetchone()
            avg_mc = float(r[0] if r[0] is not None else 0.0)
            row = conn.execute(
                "SELECT current_weight FROM lotto_brain_weights_army4 WHERE brain_tag = ?",
                (tag,),
            ).fetchone()
            if not row:
                continue
            w = float(row[0])
            delta = HEDGE_LEARNING_RATE * (avg_mc - HEDGE_REFERENCE_MATCH)
            nw = max(WEIGHT_CLIP_MIN, min(WEIGHT_CLIP_MAX, w + delta))
            conn.execute(
                "UPDATE lotto_brain_weights_army4 SET current_weight = ? WHERE brain_tag = ?",
                (nw, tag),
            )
        conn.commit()
    finally:
        conn.close()


def apply_hedge_step_to_weights(
    weights: dict[str, float],
    avg_matched_by_tag: dict[str, float],
    *,
    brain_order: tuple[str, ...] | None = None,
) -> dict[str, float]:
    """DB 없이 헤지 한 스텝만 적용 (시뮬·테스트용).

    avg_matched_by_tag: 뇌별 채점된 세트들의 평균 matched_count (9뇌 전부 권장).
    태그가 dict에 없으면 해당 뇌 가중치는 유지.
    """
    order = brain_order or V13_V2_BRAIN_ORDER
    out = {**weights}
    for tag in order:
        if tag not in avg_matched_by_tag:
            continue
        w0 = float(out.get(tag, V13_V2_SEED_WEIGHTS.get(tag, 1.0)))
        avg_mc = float(avg_matched_by_tag[tag])
        delta = HEDGE_LEARNING_RATE * (avg_mc - HEDGE_REFERENCE_MATCH)
        out[tag] = max(WEIGHT_CLIP_MIN, min(WEIGHT_CLIP_MAX, w0 + delta))
    return out


get_v13_brain_weights = get_v13_v2_brain_weights
