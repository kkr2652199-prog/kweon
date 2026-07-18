"""보조 4뇌 신호·경고 분석 — 상세페이지 증거 보관용."""

from __future__ import annotations

import json
from typing import Any

from app.testlotto.brains.coordinator import AUX_MODULES
from app.testlotto.brains.registry import AUX_BRAINS, get_brain_meta
from app.testlotto.data_service import _get_draws_before

_AUX_BY_TAG = {b["tag"]: m for b, m in zip(AUX_BRAINS, AUX_MODULES)}


def _signal_level(score: float) -> str:
    if score >= 0.65:
        return "ok"
    if score >= 0.45:
        return "warn"
    return "alert"


def analyze_set_signals(
    nums: list[int],
    draws: list[dict],
    draw_no: int,
    *,
    context: str = "",
) -> list[dict[str, Any]]:
    """단일 번호 세트에 대해 보조 4뇌 신호 목록."""
    out: list[dict[str, Any]] = []
    for aux in AUX_BRAINS:
        tag = aux["tag"]
        mod = _AUX_BY_TAG[tag]
        score = float(mod.score_set(nums, draws, draw_no))
        desc = mod.describe(nums, draws, draw_no)
        meta = get_brain_meta(tag)
        out.append(
            {
                "aux_tag": tag,
                "aux_name": meta["name"],
                "short_desc": meta.get("short_desc", ""),
                "role": "aux",
                "signal_role": "신호/경고",
                "context": context,
                "score": round(score, 3),
                "signal": desc,
                "message": desc.split(":", 1)[-1].strip() if ":" in desc else desc,
                "level": _signal_level(score),
            }
        )
    return out


def build_brain_aux_json(
    best_nums: list[int],
    draws: list[dict],
    draw_no: int,
) -> list[dict[str, Any]]:
    """예측뇌 best 세트 1건 → aux_analysis_json 저장 형식."""
    return analyze_set_signals(best_nums, draws, draw_no, context="best_set")


def build_aux_brains_section(
    draw_no: int,
    actual_nums: list[int],
    predict_brains: list[dict[str, Any]],
    *,
    draws_before: list[dict] | None = None,
) -> list[dict[str, Any]]:
    """회차 단위 aux_brains API 섹션 (예측3뇌와 분리)."""
    draws = draws_before if draws_before is not None else _get_draws_before(draw_no)
    section: list[dict[str, Any]] = []

    for aux in AUX_BRAINS:
        tag = aux["tag"]
        mod = _AUX_BY_TAG[tag]
        meta = get_brain_meta(tag)

        actual_score = float(mod.score_set(actual_nums, draws, draw_no))
        actual_desc = mod.describe(actual_nums, draws, draw_no)

        on_predict: list[dict[str, Any]] = []
        for pb in predict_brains:
            best_no = int(pb.get("best_set_no") or 1)
            sets = pb.get("predicted_sets") or []
            best_set = next(
                (s for s in sets if int(s.get("set_no") or 0) == best_no),
                sets[0] if sets else None,
            )
            if not best_set:
                continue
            nums = list(best_set.get("nums") or [])
            score = float(mod.score_set(nums, draws, draw_no))
            desc = mod.describe(nums, draws, draw_no)
            on_predict.append(
                {
                    "predict_tag": pb.get("brain_tag"),
                    "predict_name": pb.get("brain_name"),
                    "best_set_no": best_no,
                    "score": round(score, 3),
                    "signal": desc,
                    "level": _signal_level(score),
                }
            )

        section.append(
            {
                "brain_tag": tag,
                "brain_name": meta["name"],
                "short_desc": meta.get("short_desc", ""),
                "role": "aux",
                "signal_role": "신호/경고",
                "scoring_note": "적중률 채점 대상 아님",
                "on_actual": {
                    "score": round(actual_score, 3),
                    "signal": actual_desc,
                    "level": _signal_level(actual_score),
                },
                "on_predict_brains": on_predict,
            }
        )
    return section


def most_confident_set(sets: list[dict[str, Any]]) -> tuple[int, float, int]:
    """(set_no, confidence, matched_count) — 신뢰도 최고 세트."""
    if not sets:
        return 0, 0.0, 0
    best = max(sets, key=lambda s: float(s.get("confidence") or 0))
    return (
        int(best.get("set_no") or 1),
        float(best.get("confidence") or 0),
        int(best.get("matched_count") or 0),
    )


def confidence_summary_line(
    brain_name: str,
    conf_set_no: int,
    confidence: float,
    matched_count: int,
) -> str:
    if not conf_set_no:
        return ""
    conf_txt = f"{confidence:.1f}%" if confidence else "—"
    return (
        f"{brain_name}는 {conf_set_no}번 세트에 가장 자신있어 했다 (신뢰도 {conf_txt})"
        f" → 실제 {matched_count}개 적중"
    )


def parse_aux_json(raw: str | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []
