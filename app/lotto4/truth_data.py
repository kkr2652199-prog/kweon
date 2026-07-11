"""로또의 진실 — 검증 raw JSON 로더 (엔진3 미신파괴)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
_TOOLS = _ROOT / "tools"

# 출처: 보고서·JSON 없을 때 fallback (주석으로 API 응답 sources에 표기)
_FALLBACK = {
    "baseline_theory": 0.7894,
    "gap_strategy_avg": 0.7923,
    "cooccur_strategy_avg": 0.7931,
    "random_avg": 0.8107,
    "number_popularity_spearman": 0.2602,
    "hyena_before_leak": 2.0532,
    "hyena_after_honest": 0.8164,
}


def _read_json(name: str) -> dict[str, Any] | None:
    path = _TOOLS / name
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _load_truth_metrics() -> dict[str, Any]:
    sources: list[str] = []
    baseline = _FALLBACK["baseline_theory"]
    gap_avg = _FALLBACK["gap_strategy_avg"]
    cooccur_avg = _FALLBACK["cooccur_strategy_avg"]
    random_avg = _FALLBACK["random_avg"]
    spearman = _FALLBACK["number_popularity_spearman"]
    hyena_before = _FALLBACK["hyena_before_leak"]
    hyena_after = _FALLBACK["hyena_after_honest"]

    cooccur_gap = _read_json("_cooccur_gap_backtest.json")
    if cooccur_gap:
        sources.append("tools/_cooccur_gap_backtest.json")
        baseline = float(cooccur_gap.get("baseline_theory", baseline))
        gap_avg = float(cooccur_gap["gap"]["avg_matched"])
        cooccur_avg = float(cooccur_gap["cooccur"]["avg_matched"])
        random_avg = float(cooccur_gap["random"]["avg_matched"])

    pop = _read_json("_number_popularity_recon.json")
    if pop:
        sources.append("tools/_number_popularity_recon.json")
        spearman = float(pop["step4"]["number_avg_winner_spearman"])

    army3 = _read_json("_army3_backtest_run.json")
    if army3:
        sources.append("tools/_army3_backtest_run.json")
        for row in army3.get("step0", []):
            if row.get("brain_tag") == "v12_hyena":
                hyena_before = float(row["avg_mc"])
                break
        for row in army3.get("step3", []):
            if row.get("brain_tag") == "v12_hyena":
                hyena_after = float(row["avg_mc"])
                break

    if not sources:
        sources.append("fallback: 보고서 확정 상수 (JSON 미발견)")

    return {
        "baseline_theory": round(baseline, 4),
        "gap_strategy_avg": round(gap_avg, 4),
        "cooccur_strategy_avg": round(cooccur_avg, 4),
        "random_avg": round(random_avg, 4),
        "number_popularity_spearman": round(spearman, 4),
        "hyena_before_leak": round(hyena_before, 4),
        "hyena_after_honest": round(hyena_after, 4),
        "sources": sources,
    }


def get_truth_payload() -> dict[str, Any]:
    m = _load_truth_metrics()
    b = m["baseline_theory"]
    return {
        "banner": "로또는 예측할 수 없습니다. 우리는 그 진실 위에서 함께합니다.",
        "baseline_theory": b,
        "sources": m["sources"],
        "cards": [
            {
                "id": "gambler_fallacy",
                "title": "도박사의 오류",
                "subtitle": "「나올 차례」 번호는 없습니다",
                "bars": [
                    {"label": "출현간격 전략", "value": m["gap_strategy_avg"], "role": "strategy"},
                    {"label": "순수 랜덤", "value": m["random_avg"], "role": "random"},
                    {"label": "무작위 이론값", "value": b, "role": "baseline"},
                ],
                "description": (
                    "나올 차례 번호는 없습니다. 공은 과거를 기억하지 못합니다. "
                    f"walk-forward 백테(6~1225): 출현간격 전략 avg {m['gap_strategy_avg']:.4f}, "
                    f"랜덤 {m['random_avg']:.4f} — 전략이 랜덤보다 낮음."
                ),
                "source_note": "tools/_cooccur_gap_backtest.json · gap",
            },
            {
                "id": "hot_cooccur_myth",
                "title": "핫넘버 / 동반출현 미신",
                "subtitle": "자주 함께 나온 쌍도 미래를 맞추지 못합니다",
                "bars": [
                    {"label": "동반출현 전략", "value": m["cooccur_strategy_avg"], "role": "strategy"},
                    {"label": "순수 랜덤", "value": m["random_avg"], "role": "random"},
                    {"label": "무작위 이론값", "value": b, "role": "baseline"},
                ],
                "description": (
                    "자주 함께 나온 번호 조합도 미래 적중을 높이지 못합니다. "
                    f"동반출현 walk-forward avg {m['cooccur_strategy_avg']:.4f} vs 랜덤 {m['random_avg']:.4f}. "
                    f"번호 인기도 순위 시간 안정성 Spearman {m['number_popularity_spearman']:.4f} (약함)."
                ),
                "source_note": "_cooccur_gap_backtest.json + _number_popularity_recon.json",
            },
            {
                "id": "ai_leak_trap",
                "title": "복잡한 AI 예측의 함정",
                "subtitle": "정교해 보여도 검증하면 무작위입니다",
                "bars": [
                    {"label": "LSTM 누수 (stale .pt)", "value": m["hyena_before_leak"], "role": "leak"},
                    {"label": "정직 walk-forward", "value": m["hyena_after_honest"], "role": "honest"},
                    {"label": "무작위 이론값", "value": b, "role": "baseline"},
                ],
                "description": (
                    "정교해 보이는 예측도 검증하면 무작위입니다. 우리는 이를 직접 증명했습니다. "
                    f"3군 hyena: 누수 artifact {m['hyena_before_leak']:.4f} → 격리 후 {m['hyena_after_honest']:.4f} "
                    f"(이론 {b:.4f} 근처)."
                ),
                "source_note": "tools/_army3_backtest_run.json · v12_hyena",
            },
        ],
    }
