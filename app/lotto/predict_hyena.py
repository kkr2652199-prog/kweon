"""2026-04-25 Layer 5-A: 하이에나 메타 두뇌 — 기존 5두뇌 25세트 union을 합의 점수로 재조합하여 1등 회수형 synthetic brain.

합의·풀(15)·조합(5005)은 메모리만 사용; fusion 가중은 FALLBACK, 그 외 5뇌는 DB Layer3(_load_layer3_weights_5).
"""
from __future__ import annotations

import logging
import random
from itertools import combinations

from app.lotto.feedback import _load_layer3_weights_5
from app.lotto.filters import tier1_filter

logger = logging.getLogger(__name__)

# fusion만 고정(비DB); stat~hyena는 _load_layer3_weights_5와 합쳐 6키 구성
FALLBACK_BRAIN_WEIGHTS: dict[str, float] = {
    "stat": 1.0,
    "markov": 1.0,
    "llm": 1.5,
    "lstm": 2.5,
    "hyena": 1.0,
    "fusion": 2.0,
}

# 합의 기여 두뇌 수 집계 시 synthetic hyena 제외
_KNOWN_CONTRIBUTING_TAGS: frozenset[str] = frozenset(
    {"stat", "markov", "llm", "lstm", "fusion"}
)

_log_unknown_tags: set[str] = set()


def _load_hyena_brain_weights() -> dict[str, float]:
    """5뇌(DB) + fusion(FALLBACK) = 6키. 예외 시 FALLBACK만."""
    try:
        w5 = _load_layer3_weights_5()
        return {**w5, "fusion": float(FALLBACK_BRAIN_WEIGHTS["fusion"])}
    except Exception:  # noqa: BLE001
        return dict(FALLBACK_BRAIN_WEIGHTS)


def _normalize_brain_tag(raw: str | None) -> str:
    t = (raw or "").strip()
    if t == "llm_fallback":
        return "llm"
    return t


def _weight_for_tag(tag: str | None, weights: dict[str, float]) -> float:
    t = _normalize_brain_tag(tag)
    w = float(weights.get(t, 0.0))
    if w == 0.0 and t and t not in _log_unknown_tags and t not in weights:
        _log_unknown_tags.add(t)
        logger.debug("하이에나: 알 수 없는 brain_tag 가중 0: %s", t)
    return w


def _compute_consensus_score(
    all_predictions: list[dict], weights: dict[str, float]
) -> dict[int, float]:
    """1~45 번호별 합의 점수: Σ(브레인가중 × 해당 세트에서 등장 1회당 1)."""
    try:
        if len(all_predictions) < 10:
            return {}
        scores: dict[int, float] = {n: 0.0 for n in range(1, 46)}
        for pred in all_predictions:
            w = _weight_for_tag(str(pred.get("brain_tag", "")), weights)
            if w <= 0.0:
                continue
            nums = pred.get("nums")
            if not isinstance(nums, (list, tuple)) or len(nums) < 1:
                continue
            for n in nums:
                if isinstance(n, int) and 1 <= n <= 45:
                    scores[n] += w
        return scores
    except Exception as e:  # noqa: BLE001
        logger.warning("합의 점수 계산 실패: %s", e)
        return {}


def _select_candidate_pool(consensus: dict[int, float], top_n: int = 15) -> list[int]:
    try:
        if not consensus:
            return []
        ranked = sorted(consensus.items(), key=lambda x: (-x[1], x[0]))[:top_n]
        if len(ranked) < 6:
            logger.warning("하이에나: 합의 상위 pool 부족 (%d개)", len(ranked))
            return [n for n, _ in ranked]
        return [n for n, _ in ranked]
    except Exception as e:  # noqa: BLE001
        logger.warning("후보 풀 선정 실패: %s", e)
        return []


def _evaluate_combinations(
    pool: list[int], consensus: dict[int, float]
) -> list[tuple[tuple[int, ...], float]]:
    try:
        out: list[tuple[tuple[int, ...], float]] = []
        for combo in combinations(pool, 6):
            t = float(sum(consensus.get(n, 0.0) for n in combo))
            out.append((tuple(sorted(combo)), t))
        out.sort(key=lambda x: -x[1])
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("조합 평가 실패: %s", e)
        return []


def _contributing_brain_count(combo: tuple[int, ...], all_predictions: list[dict]) -> int:
    """6개 번호에 대해 25세트 중 어느 쪽 뇌가 한 번이라도 해당 번호를 찍었는지 고유 두뇌 수."""
    try:
        cset = set(combo)
        present: set[str] = set()
        for pred in all_predictions:
            t = _normalize_brain_tag(str(pred.get("brain_tag", "")))
            if t not in _KNOWN_CONTRIBUTING_TAGS:
                continue
            nums = pred.get("nums")
            if not isinstance(nums, (list, tuple)):
                continue
            if cset & set(int(x) for x in nums if isinstance(x, int) and 1 <= x <= 45):
                present.add(t)
        return len(present)
    except Exception:  # noqa: BLE001
        return 0


def _confidence_from_score(
    total: float, max_s: float, k: int, max_attempts: int, bypass: bool
) -> float:
    if max_s <= 0.0:
        return 30.0
    base = min(99.0, 45.0 + 54.0 * (total / max_s))
    if bypass or max_attempts > 0:
        base = max(20.0, base - 5.0 * min(max_attempts, 3))
    return round(float(base) - 0.3 * (k - 1), 1)


def _build_sets_from_ranked(
    ranked: list[tuple[tuple[int, ...], float]],
    all_predictions: list[dict],
    n_sets: int,
) -> list[dict]:
    """필터·샘플·30회/우회로 n_sets 생성."""
    if not ranked or n_sets <= 0:
        return []
    top50 = ranked[:50]
    max_s = max(r[1] for r in ranked) if ranked else 1.0
    if max_s <= 0.0:
        max_s = 1.0

    results: list[dict] = []
    used: set[tuple[int, ...]] = set()
    bypass_log_count = 0
    # ----- 세트 1 -----
    chosen: tuple[int, ...] | None = None
    t1: float = 0.0
    bypass1 = False
    for cmb, t in ranked:
        nlist = list(cmb)
        if tier1_filter(nlist):
            chosen, t1 = cmb, t
            break
    if chosen is None and ranked:
        for cmb, t in ranked[:5]:
            logger.warning("하이에나: 1세트 tier1 전부 실패 → 상위5강제(필터 우회). combo=%s", cmb)
            chosen, t1, bypass1 = cmb, t, True
            bypass_log_count += 1
            break
    if chosen is None:
        return []
    used.add(chosen)
    nb = _contributing_brain_count(chosen, all_predictions)
    results.append(
        {
            "nums": list(chosen),
            "brain_tag": "hyena",
            "method": "하이에나두뇌",
            "confidence": _confidence_from_score(
                t1, max_s, 1, 0, bypass1
            ),
            "reasoning": (
                f"하이에나 합의점수 상위 15후보, 합계 점수 {t1:.2f}, "
                f"채택 {nb}개 두뇌(세트1)"
            )
            + (" (tier1_filter 우회)" if bypass1 else ""),
        }
    )

    # ----- 세트 2~5 -----
    weights = [max(r[1], 1e-9) for r in top50]
    for k in range(2, n_sets + 1):
        attempts = 0
        got: tuple[int, ...] | None = None
        tgot = 0.0
        bpass = False
        while attempts < 30 and got is None:
            attempts += 1
            if not top50:
                break
            idxs = list(range(len(top50)))
            pick = random.choices(
                idxs, weights=weights[: len(top50)], k=1
            )[0]
            cmb, t = top50[pick]
            if cmb in used:
                continue
            nlist = list(cmb)
            if not tier1_filter(nlist):
                continue
            got, tgot, bpass = cmb, t, False
        if got is None:
            for cmb, t in ranked[:5]:
                if cmb in used:
                    continue
                logger.warning(
                    "하이에나: %d세트 30회 만료 → 상위5강제(필터 우회). combo=%s",
                    k,
                    cmb,
                )
                got, tgot, bpass = cmb, t, True
                bypass_log_count += 1
                break
        if got is None:
            break
        used.add(got)
        nbb = _contributing_brain_count(got, all_predictions)
        results.append(
            {
                "nums": list(got),
                "brain_tag": "hyena",
                "method": "하이에나두뇌",
                "confidence": _confidence_from_score(
                    tgot, max_s, k, attempts, bpass
                ),
                "reasoning": (
                    f"하이에나 합의점수 상위 15후보, 합계 점수 {tgot:.2f}, "
                    f"채택 {nbb}개 두뇌(세트{k})."
                    + (
                        f" (tier1_bypass, tries={attempts})"
                        if bpass
                        else f" (tries={attempts})"
                    )
                ),
            }
        )

    if bypass_log_count >= 5:
        logger.warning(
            "하이에나: tier1 우회(강제) 누적 %d회 (임계 5+)", bypass_log_count
        )
    return results


def _hyena_predict_sets(all_predictions: list[dict], n_sets: int = 5) -> list[dict]:
    """5두뇌 25세트 → 하이에나 5세트(시도 중 예외는 빈 리스트, raise 없음)."""
    try:
        if len(all_predictions) < 10:
            logger.warning("하이에나: all_predictions < 10 → 중단 (len=%d)", len(all_predictions))
            return []
        hw = _load_hyena_brain_weights()
        consensus = _compute_consensus_score(all_predictions, hw)
        if not any(v > 0 for v in consensus.values()):
            logger.warning("하이에나: 합의 점수 전부 0")
            return []
        pool = _select_candidate_pool(consensus, 15)
        if len(pool) < 6:
            return []
        ranked = _evaluate_combinations(pool, consensus)
        if not ranked:
            return []
        return _build_sets_from_ranked(ranked, all_predictions, n_sets)
    except Exception as e:  # noqa: BLE001
        logger.warning("하이에나 예측 실패: %s", e)
        return []


