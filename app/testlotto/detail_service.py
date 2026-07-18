"""테스트로또 상세페이지 데이터 — 회차·뇌별 복습/학습 스냅샷."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from app.testlotto.aux_analysis import (
    build_aux_brains_section,
    build_brain_aux_json,
    confidence_summary_line,
    most_confident_set,
    parse_aux_json,
)
from app.testlotto.draw_snapshot import build_analysis_board
from app.testlotto.num_explainer import build_wrong_note
from app.testlotto.brains.registry import AUX_BRAINS, DISPLAY_NAMES, PREDICT_BRAINS, get_short_desc
from app.testlotto.data_service import _get_draws_before
from app.testlotto.models import get_lotto_db
from app.testlotto.prize_tiers import get_prize_tiers
from app.testlotto.tier_utils import (
    best_tier_from_sets,
    enrich_predicted_sets,
    prediction_rank_tier,
)

PATTERN_LABELS: dict[str, str] = {
    "carry_over": "이월수",
    "ending_digit": "끝수",
    "consecutive": "연속수",
    "overdue": "미출(장기)",
    "odd_even": "홀짝 균형",
    "pair": "쌍수(동반출현)",
}

PHASE_REVIEW = "review"
PREDICT_BRAIN_TAGS = ("stat", "markov", "review")
TREND_THRESHOLD = 0.15


def _parse_json(raw: str | None, default: Any = None) -> Any:
    if not raw:
        return default if default is not None else []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else []


def _draw_nums(draw: dict) -> list[int]:
    return sorted(int(draw[f"num{k}"]) for k in range(1, 7))


def upsert_brain_page_from_review(
    draw_no: int,
    brain_tag: str,
    *,
    predicted: list[int],
    actual: list[int],
    matched_count: int,
    missed_patterns: list[str],
    feedback: dict[str, Any],
    weight_snapshot: dict[str, Any],
    feature_row: dict[str, Any] | None = None,
    predicted_sets: list[dict[str, Any]] | None = None,
    best_set_no: int = 1,
    bonus_matched: int = 0,
    tier_rank: int = 0,
    tier_label: str = "미적중",
    aux_analysis_json: list[dict[str, Any]] | None = None,
) -> None:
    """복습 1건 → 뇌별 상세페이지 스냅샷 저장."""
    pred_set = set(predicted)
    actual_set = set(actual)
    hit_nums = sorted(pred_set & actual_set)
    miss_nums = sorted(pred_set - actual_set)
    actual_miss = sorted(actual_set - pred_set)
    tier_label = tier_label or prediction_rank_tier(matched_count, bonus_matched)[1]

    narrative_parts = [
        f"{DISPLAY_NAMES.get(brain_tag, brain_tag)} · {draw_no}회 복습",
        f"{tier_label} · 적중 {matched_count}개 ({', '.join(map(str, hit_nums)) or '없음'})",
    ]
    if missed_patterns:
        labels = [PATTERN_LABELS.get(p, p) for p in missed_patterns]
        narrative_parts.append(f"놓친 패턴: {', '.join(labels)}")
    narrative = " · ".join(narrative_parts)

    detail_blob = {
        "missed_pattern_labels": [PATTERN_LABELS.get(p, p) for p in missed_patterns],
        "actual_missed_nums": actual_miss,
        "predicted_sets": predicted_sets or [],
        "best_set_no": best_set_no,
        "bonus_matched": int(bonus_matched),
        "tier_rank": int(tier_rank),
        "tier_label": tier_label,
    }

    conn = get_lotto_db()
    try:
        conn.execute(
            """
            INSERT INTO testlotto_brain_page (
                draw_no, brain_tag, phase,
                predicted_nums, predicted_sets_json, best_set_no,
                actual_nums, matched_count,
                missed_patterns, hit_nums, miss_nums,
                feature_snapshot, feedback_json, learn_snapshot_json,
                aux_analysis_json, narrative, detail_json, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, datetime('now','localtime'))
            ON CONFLICT(draw_no, brain_tag, phase) DO UPDATE SET
                predicted_nums=excluded.predicted_nums,
                predicted_sets_json=excluded.predicted_sets_json,
                best_set_no=excluded.best_set_no,
                actual_nums=excluded.actual_nums,
                matched_count=excluded.matched_count,
                missed_patterns=excluded.missed_patterns,
                hit_nums=excluded.hit_nums,
                miss_nums=excluded.miss_nums,
                feature_snapshot=excluded.feature_snapshot,
                feedback_json=excluded.feedback_json,
                learn_snapshot_json=excluded.learn_snapshot_json,
                aux_analysis_json=excluded.aux_analysis_json,
                narrative=excluded.narrative,
                detail_json=excluded.detail_json,
                updated_at=excluded.updated_at
            """,
            (
                draw_no,
                brain_tag,
                PHASE_REVIEW,
                json.dumps(predicted, ensure_ascii=False),
                json.dumps(predicted_sets or [], ensure_ascii=False),
                int(best_set_no),
                json.dumps(actual, ensure_ascii=False),
                matched_count,
                json.dumps(missed_patterns, ensure_ascii=False),
                json.dumps(hit_nums, ensure_ascii=False),
                json.dumps(miss_nums, ensure_ascii=False),
                json.dumps(feature_row or {}, ensure_ascii=False),
                json.dumps(feedback, ensure_ascii=False),
                json.dumps(weight_snapshot, ensure_ascii=False),
                json.dumps(aux_analysis_json or [], ensure_ascii=False),
                narrative,
                json.dumps(detail_blob, ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def sync_brain_pages_from_reviews(start: int = 2, end: int = 1231) -> int:
    """기존 brain_review → brain_page 백필."""
    conn = get_lotto_db()
    synced = 0
    try:
        rows = conn.execute(
            """
            SELECT r.*, d.num1, d.num2, d.num3, d.num4, d.num5, d.num6, d.bonus
            FROM testlotto_brain_review r
            JOIN lotto_draws d ON d.draw_no = r.draw_no
            WHERE r.draw_no BETWEEN ? AND ?
            ORDER BY r.draw_no, r.brain_tag
            """,
            (start, end),
        ).fetchall()
        feat_cache: dict[int, dict] = {}
        for row in rows:
            d = dict(row)
            draw_no = int(d["draw_no"])
            if draw_no not in feat_cache:
                fr = conn.execute(
                    "SELECT * FROM testlotto_draw_features WHERE draw_no = ?", (draw_no,)
                ).fetchone()
                feat_cache[draw_no] = dict(fr) if fr else {}
            actual = _draw_nums(d)
            bonus = int(d.get("bonus") or 0)
            predicted = _parse_json(d.get("predicted_nums"), [])
            predicted_sets = _parse_json(d.get("predicted_sets_json"), [])
            if not predicted_sets and predicted:
                predicted_sets = [
                    {
                        "set_no": 1,
                        "nums": predicted,
                        "matched_count": int(d.get("matched_count") or 0),
                    }
                ]
            predicted_sets = enrich_predicted_sets(predicted_sets, actual, bonus)
            best_info = best_tier_from_sets(predicted_sets)
            bm = int(d.get("bonus_matched") or best_info.get("bonus_matched") or 0)
            tr = int(best_info.get("tier_rank") or 0)
            tl = best_info.get("tier_label") or prediction_rank_tier(
                int(d.get("matched_count") or 0), bm
            )[1]
            missed = _parse_json(d.get("missed_patterns"), [])
            feedback = _parse_json(d.get("feedback_json"), {})
            weight_snap = _parse_json(d.get("weight_snapshot"), {})
            draws_before = _get_draws_before(draw_no)
            best_nums = list(
                next(
                    (s.get("nums") for s in predicted_sets if int(s.get("set_no") or 0) == int(d.get("best_set_no") or best_info.get("best_set_no") or 1)),
                    predicted,
                )
                or predicted
            )
            aux_json = build_brain_aux_json(best_nums, draws_before, draw_no)
            upsert_brain_page_from_review(
                draw_no,
                d["brain_tag"],
                predicted=predicted,
                predicted_sets=predicted_sets,
                best_set_no=int(d.get("best_set_no") or best_info.get("best_set_no") or 1),
                actual=actual,
                matched_count=int(d.get("matched_count") or 0),
                bonus_matched=bm,
                tier_rank=tr,
                tier_label=tl,
                missed_patterns=missed,
                feedback=feedback,
                weight_snapshot=weight_snap,
                feature_row=feat_cache.get(draw_no),
                aux_analysis_json=aux_json,
            )
            synced += 1
    finally:
        conn.close()
    return synced


def get_draw_detail(draw_no: int) -> dict[str, Any]:
    """단일 회차 상세 — 정답·분석그릇·뇌별 복습."""
    conn = get_lotto_db()
    try:
        draw = conn.execute("SELECT * FROM lotto_draws WHERE draw_no = ?", (draw_no,)).fetchone()
        if not draw:
            return {"error": f"{draw_no}회 당첨 데이터 없음"}
        draw_d = dict(draw)
        features = conn.execute(
            "SELECT * FROM testlotto_draw_features WHERE draw_no = ?", (draw_no,)
        ).fetchone()
        pages = conn.execute(
            """
            SELECT * FROM testlotto_brain_page
            WHERE draw_no = ? AND phase = ?
            ORDER BY brain_tag
            """,
            (draw_no, PHASE_REVIEW),
        ).fetchall()
        if not pages:
            reviews = conn.execute(
                "SELECT COUNT(*) FROM testlotto_brain_review WHERE draw_no = ?", (draw_no,)
            ).fetchone()[0]
            if reviews:
                sync_brain_pages_from_reviews(draw_no, draw_no)
                pages = conn.execute(
                    """
                    SELECT * FROM testlotto_brain_page
                    WHERE draw_no = ? AND phase = ?
                    ORDER BY brain_tag
                    """,
                    (draw_no, PHASE_REVIEW),
                ).fetchall()

        brains: list[dict[str, Any]] = []
        for p in pages:
            pd = dict(p)
            detail_blob = _parse_json(pd.get("detail_json"), {})
            predicted_sets = _parse_json(pd.get("predicted_sets_json"), [])
            if not predicted_sets:
                predicted_sets = detail_blob.get("predicted_sets") or []
            if not predicted_sets and pd.get("predicted_nums"):
                predicted_sets = [
                    {
                        "set_no": 1,
                        "nums": _parse_json(pd.get("predicted_nums"), []),
                        "matched_count": int(pd.get("matched_count") or 0),
                    }
                ]
            brains.append(
                {
                    "brain_tag": pd["brain_tag"],
                    "brain_name": DISPLAY_NAMES.get(pd["brain_tag"], pd["brain_tag"]),
                    "predicted_nums": _parse_json(pd.get("predicted_nums"), []),
                    "predicted_sets": predicted_sets,
                    "best_set_no": int(pd.get("best_set_no") or detail_blob.get("best_set_no") or 1),
                    "actual_nums": _parse_json(pd.get("actual_nums"), []),
                    "matched_count": int(pd.get("matched_count") or 0),
                    "hit_nums": _parse_json(pd.get("hit_nums"), []),
                    "miss_nums": _parse_json(pd.get("miss_nums"), []),
                    "missed_patterns": _parse_json(pd.get("missed_patterns"), []),
                    "missed_pattern_labels": detail_blob.get(
                        "missed_pattern_labels", []
                    ),
                    "feedback": _parse_json(pd.get("feedback_json"), {}),
                    "learn_snapshot": _parse_json(pd.get("learn_snapshot_json"), {}),
                    "aux_analysis": parse_aux_json(pd.get("aux_analysis_json")),
                    "narrative": pd.get("narrative") or "",
                    "updated_at": pd.get("updated_at"),
                }
            )

        actual_nums = _draw_nums(draw_d)
        bonus_num = int(draw_d.get("bonus") or 0)
        draws_before = _get_draws_before(draw_no)
        brain_verdicts: list[dict[str, Any]] = []
        aux_persist: list[tuple[str, list[dict[str, Any]]]] = []

        for b in brains:
            b["predicted_sets"] = enrich_predicted_sets(
                b.get("predicted_sets") or [], actual_nums, bonus_num
            )
            best_info = best_tier_from_sets(b["predicted_sets"])
            b["best_set_no"] = int(
                b.get("best_set_no") or best_info.get("best_set_no") or 1
            )
            b["matched_count"] = int(b.get("matched_count") or best_info.get("matched_count") or 0)
            b["bonus_matched"] = int(best_info.get("bonus_matched") or 0)
            b["tier_rank"] = int(best_info.get("tier_rank") or 0)
            b["tier_label"] = best_info.get("tier_label") or "미적중"
            b["short_desc"] = get_short_desc(b["brain_tag"])
            b["brain_role"] = "predict"

            conf_set_no, conf_val, conf_matched = most_confident_set(b["predicted_sets"])
            b["most_confident_set_no"] = conf_set_no
            b["most_confident_score"] = conf_val
            b["confidence_summary"] = confidence_summary_line(
                b["brain_name"], conf_set_no, conf_val, conf_matched
            )

            best_set = next(
                (
                    s
                    for s in b["predicted_sets"]
                    if int(s.get("set_no") or 0) == b["best_set_no"]
                ),
                b["predicted_sets"][0] if b["predicted_sets"] else None,
            )
            best_nums = list((best_set or {}).get("nums") or b.get("predicted_nums") or [])
            missed_labels = b.get("missed_pattern_labels") or [
                PATTERN_LABELS.get(p, p) for p in (b.get("missed_patterns") or [])
            ]
            b["wrong_note"] = build_wrong_note(
                b["brain_tag"],
                b["brain_name"],
                best_nums,
                actual_nums,
                best_set_no=b["best_set_no"],
                matched_count=b["matched_count"],
                tier_label=b["tier_label"],
                tier_rank=b["tier_rank"],
                hit_nums=b.get("hit_nums") or [],
                missed_pattern_labels=missed_labels,
                draws=draws_before,
            )

            aux_stored = b.get("aux_analysis") or []
            if not aux_stored:
                best_set = next(
                    (
                        s
                        for s in b["predicted_sets"]
                        if int(s.get("set_no") or 0) == b["best_set_no"]
                    ),
                    b["predicted_sets"][0] if b["predicted_sets"] else None,
                )
                if best_set:
                    aux_stored = build_brain_aux_json(
                        list(best_set.get("nums") or []), draws_before, draw_no
                    )
                    aux_persist.append((b["brain_tag"], aux_stored))
            b["aux_analysis"] = aux_stored

            brain_verdicts.append(
                {
                    "brain_tag": b["brain_tag"],
                    "brain_name": b["brain_name"],
                    "short_desc": b["short_desc"],
                    "tier_rank": b["tier_rank"],
                    "tier_label": b["tier_label"],
                    "matched_count": b["matched_count"],
                    "bonus_matched": b["bonus_matched"],
                    "best_set_no": b["best_set_no"],
                    "most_confident_set_no": conf_set_no,
                    "most_confident_score": conf_val,
                    "confidence_summary": b["confidence_summary"],
                    "has_review": True,
                }
            )

        if aux_persist:
            try:
                for tag, aux_data in aux_persist:
                    conn.execute(
                        """
                        UPDATE testlotto_brain_page
                        SET aux_analysis_json = ?, updated_at = datetime('now','localtime')
                        WHERE draw_no = ? AND brain_tag = ? AND phase = ?
                        """,
                        (
                            json.dumps(aux_data, ensure_ascii=False),
                            draw_no,
                            tag,
                            PHASE_REVIEW,
                        ),
                    )
                conn.commit()
            except Exception:
                pass

        for pb in PREDICT_BRAINS:
            tag = pb["tag"]
            if not any(v["brain_tag"] == tag for v in brain_verdicts):
                brain_verdicts.append(
                    {
                        "brain_tag": tag,
                        "brain_name": DISPLAY_NAMES.get(tag, tag),
                        "short_desc": get_short_desc(tag),
                        "tier_rank": 0,
                        "tier_label": "기록 없음",
                        "matched_count": 0,
                        "bonus_matched": 0,
                        "best_set_no": 0,
                        "most_confident_set_no": 0,
                        "most_confident_score": 0.0,
                        "confidence_summary": "",
                        "has_review": False,
                    }
                )
        brain_verdicts.sort(
            key=lambda v: (
                0 if v.get("has_review") else 1,
                int(v.get("tier_rank") or 99),
                -int(v.get("matched_count") or 0),
            )
        )

        feat_d = dict(features) if features else {}
        prize_tiers = get_prize_tiers(draw_no, auto_fetch=False)
        if not prize_tiers:
            prize_tiers = get_prize_tiers(draw_no, auto_fetch=True)

        archive_row = conn.execute(
            "SELECT * FROM testlotto_draw_detail WHERE draw_no = ?", (draw_no,)
        ).fetchone()
        win_stores = conn.execute(
            """
            SELECT tier_rank, store_name, pick_method, address, region
            FROM testlotto_draw_win_stores WHERE draw_no = ?
            ORDER BY tier_rank, store_name
            """,
            (draw_no,),
        ).fetchall()
        arch = dict(archive_row) if archive_row else {}
        win_types = {}
        if arch:
            from app.testlotto.draw_archive import WIN_TYPE_LABELS

            win_types = {
                WIN_TYPE_LABELS[i]: int(arch.get(f"win_type_{i}") or 0) for i in range(4)
            }

        draws_inclusive = draws_before + [draw_d]
        analysis_board = build_analysis_board(
            draw_no, actual_nums, bonus_num, draws_inclusive
        )

        return {
            "draw_no": draw_no,
            "draw_date": draw_d.get("draw_date"),
            "total_sales": int(arch.get("total_sales") or draw_d.get("total_sales") or 0),
            "cumulative_sales": int(arch.get("cumulative_sales") or 0),
            "total_winners": int(arch.get("total_winners") or 0),
            "win_types": win_types,
            "win_stores": [dict(s) for s in win_stores],
            "store_fetch_status": arch.get("store_fetch_status") or "",
            "actual_nums": actual_nums,
            "bonus": bonus_num,
            "prize_tiers": prize_tiers,
            "prize_tiers_complete": len(prize_tiers) >= 5,
            "archive_synced_at": arch.get("synced_at"),
            "features": {
                "carry_over_count": feat_d.get("carry_over_count"),
                "carry_over_nums": _parse_json(feat_d.get("carry_over_nums"), []),
                "consecutive_count": feat_d.get("consecutive_count"),
                "ending_digits": _parse_json(feat_d.get("ending_digits"), []),
                "ac_value": feat_d.get("ac_value"),
                "gap_overdue_nums": _parse_json(feat_d.get("gap_overdue_nums"), []),
                "sum_total": feat_d.get("sum_total"),
                "odd_count": feat_d.get("odd_count"),
                "even_count": feat_d.get("even_count"),
                "zone_low_mid_high": _parse_json(feat_d.get("zone_low_mid_high"), []),
                "combo_rank_814": feat_d.get("combo_rank_814"),
            },
            "analysis_board": analysis_board,
            "brains": brains,
            "brain_verdicts": brain_verdicts,
            "brain_order": [b["tag"] for b in PREDICT_BRAINS],
            "aux_brains": build_aux_brains_section(
                draw_no, actual_nums, brains, draws_before=draws_before
            ),
            "aux_brain_order": [b["tag"] for b in AUX_BRAINS],
            "brain_meta": {
                b["tag"]: {
                    "name": b["name"],
                    "role": b["role"],
                    "short_desc": b.get("short_desc", ""),
                }
                for b in PREDICT_BRAINS + AUX_BRAINS
            },
        }
    finally:
        conn.close()


def get_hit_draws(brain_tag: str, *, min_match: int = 3) -> list[int]:
    """뇌별 5등+(tier_rank 1~5) 이상인 복습 회차 목록 (최신순)."""
    conn = get_lotto_db()
    try:
        rows = conn.execute(
            """
            SELECT draw_no, matched_count, predicted_sets_json, bonus_matched
            FROM testlotto_brain_page
            WHERE brain_tag = ? AND phase = ?
            ORDER BY draw_no DESC
            """,
            (brain_tag, PHASE_REVIEW),
        ).fetchall()
        draw_rows = conn.execute(
            "SELECT draw_no, bonus FROM lotto_draws"
        ).fetchall()
        bonus_map = {int(r[0]): int(r[1] or 0) for r in draw_rows}
        actual_cache: dict[int, list[int]] = {}
        out: list[int] = []
        for r in rows:
            d = dict(r)
            draw_no = int(d["draw_no"])
            if draw_no not in actual_cache:
                dr = conn.execute(
                    "SELECT num1,num2,num3,num4,num5,num6 FROM lotto_draws WHERE draw_no=?",
                    (draw_no,),
                ).fetchone()
                actual_cache[draw_no] = (
                    sorted(int(dr[i]) for i in range(6)) if dr else []
                )
            sets = enrich_predicted_sets(
                _parse_json(d.get("predicted_sets_json"), []),
                actual_cache[draw_no],
                bonus_map.get(draw_no, 0),
            )
            best = best_tier_from_sets(sets)
            tr = int(best.get("tier_rank") or 0)
            mc = int(best.get("matched_count") or d.get("matched_count") or 0)
            if tr > 0 or mc >= min_match:
                out.append(draw_no)
        return out
    finally:
        conn.close()


def _tier5_plus_from_row(row: dict) -> bool:
    detail = _parse_json(row.get("detail_json"), {})
    tr = int(detail.get("tier_rank") or 0)
    if 1 <= tr <= 5:
        return True
    return int(row.get("matched_count") or 0) >= 3


def _build_brain_range_summary(
    points: list[dict[str, Any]],
    start: int,
    end: int,
    brain_tag: str,
) -> dict[str, Any]:
    """구간 1뇌 집계 — 추세·약점 top3·한 줄 진단 (READ ONLY)."""
    name = DISPLAY_NAMES.get(brain_tag, brain_tag)
    if not points:
        return {
            "brain_tag": brain_tag,
            "brain_name": name,
            "draw_count": 0,
            "avg_match": 0.0,
            "best_draw": None,
            "worst_draw": None,
            "tier5_plus_count": 0,
            "trend": "flat",
            "trend_label": "유지",
            "first_half_avg": 0.0,
            "second_half_avg": 0.0,
            "missed_pattern_top3": [],
            "narrative": f"{start}~{end}회 구간: {name} 복습 기록 없음.",
            "equity_curve": [],
        }

    sorted_pts = sorted(points, key=lambda p: int(p["draw_no"]))
    matches = [int(p.get("matched_count") or 0) for p in sorted_pts]
    avg = sum(matches) / len(matches)
    best_i = max(range(len(sorted_pts)), key=lambda i: (matches[i], -int(sorted_pts[i]["draw_no"])))
    worst_i = min(range(len(sorted_pts)), key=lambda i: (matches[i], int(sorted_pts[i]["draw_no"])))

    n = len(sorted_pts)
    mid = max(1, n // 2)
    first_pts = sorted_pts[:mid]
    second_pts = sorted_pts[mid:] if mid < n else sorted_pts[-1:]
    first_avg = sum(int(p.get("matched_count") or 0) for p in first_pts) / len(first_pts)
    second_avg = sum(int(p.get("matched_count") or 0) for p in second_pts) / len(second_pts)

    if second_avg > first_avg + TREND_THRESHOLD:
        trend, trend_label = "up", "상승"
    elif second_avg < first_avg - TREND_THRESHOLD:
        trend, trend_label = "down", "하락"
    else:
        trend, trend_label = "flat", "유지"

    pattern_counts: Counter[str] = Counter()
    for p in sorted_pts:
        for pat in _parse_json(p.get("missed_patterns"), []):
            if pat:
                pattern_counts[str(pat)] += 1
    top3 = [
        {"pattern": k, "label": PATTERN_LABELS.get(k, k), "count": int(v)}
        for k, v in pattern_counts.most_common(3)
    ]

    tier5_plus = sum(1 for p in sorted_pts if _tier5_plus_from_row(p))

    if top3:
        weak_str = f"{top3[0]['label']}({top3[0]['count']}회 놓침)"
    else:
        weak_str = "뚜렷한 약점 없음"
    narrative = (
        f"{start}~{end}회 구간: {name} 평균 {avg:.1f}개, {trend_label} 추세. "
        f"최대 약점은 {weak_str}."
    )

    return {
        "brain_tag": brain_tag,
        "brain_name": name,
        "draw_count": n,
        "avg_match": round(avg, 2),
        "best_draw": {
            "draw_no": int(sorted_pts[best_i]["draw_no"]),
            "matched_count": matches[best_i],
        },
        "worst_draw": {
            "draw_no": int(sorted_pts[worst_i]["draw_no"]),
            "matched_count": matches[worst_i],
        },
        "tier5_plus_count": tier5_plus,
        "trend": trend,
        "trend_label": trend_label,
        "first_half_avg": round(first_avg, 2),
        "second_half_avg": round(second_avg, 2),
        "missed_pattern_top3": top3,
        "narrative": narrative,
        "equity_curve": [
            {"draw_no": int(p["draw_no"]), "matched_count": int(p.get("matched_count") or 0)}
            for p in sorted_pts
        ],
    }


def _build_range_summary(
    all_rows: list[dict[str, Any]], start: int, end: int
) -> dict[str, Any]:
    """구간 3뇌 진단 summary."""
    by_brain: dict[str, list[dict[str, Any]]] = {tag: [] for tag in PREDICT_BRAIN_TAGS}
    for row in all_rows:
        tag = row.get("brain_tag")
        if tag in by_brain:
            by_brain[tag].append(row)

    brains = {
        tag: _build_brain_range_summary(by_brain[tag], start, end, tag)
        for tag in PREDICT_BRAIN_TAGS
    }
    narratives = [brains[tag]["narrative"] for tag in PREDICT_BRAIN_TAGS if brains[tag]["draw_count"]]
    return {
        "start": start,
        "end": end,
        "draw_span": end - start + 1,
        "brains": brains,
        "brain_order": list(PREDICT_BRAIN_TAGS),
        "combined_narrative": " · ".join(narratives) if narratives else f"{start}~{end}회 구간 복습 기록 없음.",
    }


def get_reviews_range(
    start: int,
    end: int,
    brain_tag: str | None = None,
    *,
    limit: int = 500,
    offset: int = 0,
) -> dict[str, Any]:
    """여러 회차 복습 목록 (상세페이지 타임라인·비교용)."""
    conn = get_lotto_db()
    try:
        clauses = ["draw_no BETWEEN ? AND ?", "phase = ?"]
        params: list[Any] = [start, end, PHASE_REVIEW]
        if brain_tag:
            clauses.append("brain_tag = ?")
            params.append(brain_tag)
        where = " AND ".join(clauses)
        total = conn.execute(
            f"SELECT COUNT(*) FROM testlotto_brain_page WHERE {where}", params
        ).fetchone()[0]
        if total == 0:
            rev_cnt = conn.execute(
                """
                SELECT COUNT(*) FROM testlotto_brain_review
                WHERE draw_no BETWEEN ? AND ?
                """ + (" AND brain_tag = ?" if brain_tag else ""),
                [start, end] + ([brain_tag] if brain_tag else []),
            ).fetchone()[0]
            if rev_cnt:
                sync_brain_pages_from_reviews(start, end)
                total = conn.execute(
                    f"SELECT COUNT(*) FROM testlotto_brain_page WHERE {where}", params
                ).fetchone()[0]

        rows = conn.execute(
            f"""
            SELECT draw_no, brain_tag, matched_count, missed_patterns,
                   narrative, predicted_nums, hit_nums, detail_json, updated_at
            FROM testlotto_brain_page
            WHERE {where}
            ORDER BY draw_no DESC, brain_tag
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()

        summary_rows = conn.execute(
            """
            SELECT draw_no, brain_tag, matched_count, missed_patterns, detail_json
            FROM testlotto_brain_page
            WHERE draw_no BETWEEN ? AND ? AND phase = ?
            ORDER BY draw_no ASC, brain_tag
            """,
            (start, end, PHASE_REVIEW),
        ).fetchall()

        items = []
        for r in rows:
            d = dict(r)
            items.append(
                {
                    "draw_no": d["draw_no"],
                    "brain_tag": d["brain_tag"],
                    "brain_name": DISPLAY_NAMES.get(d["brain_tag"], d["brain_tag"]),
                    "matched_count": int(d.get("matched_count") or 0),
                    "missed_patterns": _parse_json(d.get("missed_patterns"), []),
                    "narrative": d.get("narrative") or "",
                    "predicted_nums": _parse_json(d.get("predicted_nums"), []),
                    "hit_nums": _parse_json(d.get("hit_nums"), []),
                    "updated_at": d.get("updated_at"),
                }
            )
        summary = _build_range_summary([dict(r) for r in summary_rows], start, end)
        return {
            "start": start,
            "end": end,
            "brain_tag": brain_tag,
            "total": int(total),
            "limit": limit,
            "offset": offset,
            "items": items,
            "summary": summary,
        }
    finally:
        conn.close()


def get_brain_learning_summary(brain_tag: str) -> dict[str, Any]:
    """뇌별 누적 학습 요약 (상세페이지 사이드바)."""
    conn = get_lotto_db()
    try:
        learn = conn.execute(
            "SELECT * FROM testlotto_brain_learn_state WHERE brain_tag = ?", (brain_tag,)
        ).fetchone()
        weight = conn.execute(
            "SELECT * FROM testlotto_brain_weights WHERE brain_tag = ?", (brain_tag,)
        ).fetchone()
        stats = conn.execute(
            """
            SELECT COUNT(*) AS cnt,
                   AVG(matched_count) AS avg_match,
                   MAX(draw_no) AS max_draw,
                   MIN(draw_no) AS min_draw
            FROM testlotto_brain_page
            WHERE brain_tag = ? AND phase = ?
            """,
            (brain_tag, PHASE_REVIEW),
        ).fetchone()
        state = _parse_json(learn["state_json"] if learn else None, {})
        return {
            "brain_tag": brain_tag,
            "brain_name": DISPLAY_NAMES.get(brain_tag, brain_tag),
            "review_count": int(learn["review_count"]) if learn else 0,
            "last_draw_no": int(learn["last_draw_no"]) if learn else 0,
            "recent_avg_match": float(state.get("recent_avg_match") or 0),
            "adjustments": state.get("adjustments", {}),
            "miss_counts": state.get("miss_counts", {}),
            "current_weight": float(weight["current_weight"]) if weight else 1.0,
            "page_stats": {
                "records": int(stats["cnt"] or 0) if stats else 0,
                "avg_match": round(float(stats["avg_match"] or 0), 3) if stats else 0,
                "min_draw": int(stats["min_draw"] or 0) if stats else 0,
                "max_draw": int(stats["max_draw"] or 0) if stats else 0,
            },
        }
    finally:
        conn.close()
