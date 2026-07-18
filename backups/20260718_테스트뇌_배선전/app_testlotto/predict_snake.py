"""뱀 AI — 2군 35세트를 hyena식 합의로 메타 최적화 V8 (engine 시그니처 유지).

snake_predict_sets(miss_predictions, miss_pmf, n_sets)만 노출.
컷오프: miss_predictions[0]['_miss_cutoff_target_draw_no']로 DB 재로드 시
draw_no < target 과 engine의 _get_draws_before와 동일 시계열 유지.

V8: fusion+combo+weak 패턴, 가중치 균등화, 1군 30세트 대비 Jaccard<0.4만 채택.
"""
from __future__ import annotations

import logging
import random
from itertools import combinations

from app.testlotto.filters import tier1_filter

logger = logging.getLogger(__name__)

_ARMY1_TAGS: tuple[str, ...] = (
    "stat",
    "markov",
    "llm",
    "lstm",
    "fusion",
    "hyena",
)

# V8: 1군 닮음 완화 + miss_combo / miss_weak 우선
_SNAKE_BRAIN_WEIGHTS: dict[str, float] = {
    "miss_stat": 5.0,
    "miss_markov": 5.0,
    "miss_lstm": 5.0,
    "miss_stat2": 10.0,
    "miss_fusion": 5.0,
    "miss_combo": 50.0,
    "miss_weak": 30.0,
}


def _load_draws_before_cutoff(cutoff_target_draw_no: int) -> list[dict]:
    """engine._get_draws_before(target)와 동일: draw_no < cutoff."""
    if cutoff_target_draw_no <= 0:
        return []
    from app.testlotto.models import get_lotto_db

    conn = get_lotto_db()
    try:
        rows = conn.execute(
            "SELECT * FROM lotto_draws WHERE draw_no < ? ORDER BY draw_no",
            (cutoff_target_draw_no,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _load_army1_sets_for_target(target_draw_no: int) -> list[set[int]]:
    """예측 대상 회차의 1군 30세트 번호 집합(당회차 DB 예측)."""
    from app.testlotto.models import get_lotto_db

    ph = ",".join("?" * len(_ARMY1_TAGS))
    conn = get_lotto_db()
    try:
        rows = conn.execute(
            f"""
            SELECT num1, num2, num3, num4, num5, num6
            FROM lotto_predictions
            WHERE target_draw_no = ? AND brain_tag IN ({ph})
            """,
            (target_draw_no, *_ARMY1_TAGS),
        ).fetchall()
    finally:
        conn.close()
    out: list[set[int]] = []
    for r in rows:
        out.append(
            {int(r["num1"]), int(r["num2"]), int(r["num3"]), int(r["num4"]), int(r["num5"]), int(r["num6"])}
        )
    return out


def _is_diff_from_army1(
    combo: list[int], army1_sets: list[set[int]], threshold: float = 0.4
) -> bool:
    """1군 30세트와 Jaccard 유사도가 threshold 미만이면 True(차별화 통과)."""
    if not army1_sets:
        return True
    s = set(combo)
    for a1 in army1_sets:
        inter = len(s & a1)
        uni = len(s | a1)
        jac = inter / uni if uni else 0.0
        if jac >= threshold:
            return False
    return True


def _get_all_sub_brain_sets_for_cutoff(cutoff_target_draw_no: int) -> list[dict]:
    """컷오프 이전 draws로 2군 7서브뇌 35세트 생성 (V8)."""
    from app.testlotto.predict_missanalysis import (
        _analyze_miss_patterns,
        _get_miss_draws,
        _get_weak_draws,
        _neutral_patterns,
        _run_sub_combo,
        _run_sub_fusion,
        _run_sub_lstm,
        _run_sub_markov,
        _run_sub_stat,
        _run_sub_stat2_inverse,
        _run_sub_weak,
    )

    all_draws = _load_draws_before_cutoff(cutoff_target_draw_no)
    if len(all_draws) < 3:
        return []
    miss_draws = _get_miss_draws(all_draws)
    if len(miss_draws) < 3:
        return []
    patterns = _analyze_miss_patterns(miss_draws, all_draws)
    weak_draws = _get_weak_draws(all_draws)
    weak_patterns = (
        _analyze_miss_patterns(weak_draws, all_draws)
        if len(weak_draws) >= 3
        else _neutral_patterns()
    )

    all_sets: list[dict] = []
    all_sets.extend(_run_sub_stat(miss_draws, 5))
    all_sets.extend(_run_sub_markov(miss_draws, 5))
    all_sets.extend(_run_sub_lstm(miss_draws, 5))
    all_sets.extend(_run_sub_stat2_inverse(miss_draws, all_draws, 5))
    all_sets.extend(_run_sub_fusion(miss_draws, 5, patterns))
    all_sets.extend(_run_sub_combo(patterns, 5))
    all_sets.extend(_run_sub_weak(weak_patterns, 5))
    return all_sets


def snake_predict_sets(
    miss_predictions: list[dict],
    miss_pmf: dict[int, float] | None = None,
    n_sets: int = 5,
) -> list[dict]:
    """2군 35세트 기반 hyena식 메타 최적화 V8."""
    try:
        sub_sets: list[dict] = []
        cutoff: int | None = None
        if miss_predictions:
            raw = miss_predictions[0].get("_miss_cutoff_target_draw_no")
            if isinstance(raw, int) and raw > 0:
                cutoff = raw

        army1_sets: list[set[int]] = []
        if cutoff is not None:
            sub_sets = _get_all_sub_brain_sets_for_cutoff(cutoff)
            army1_sets = _load_army1_sets_for_target(cutoff)

        if len(sub_sets) < 20:
            sub_sets = list(miss_predictions)

        if len(sub_sets) < 3:
            logger.warning("뱀: 입력 부족 (%d)", len(sub_sets))
            return []

        _ = miss_pmf

        num_count: dict[int, float] = {}
        for pred in sub_sets:
            source = str(pred.get("source", ""))
            w = float(_SNAKE_BRAIN_WEIGHTS.get(source, 1.0))
            nums = pred.get("nums", [])
            for n in nums:
                if isinstance(n, int) and 1 <= n <= 45:
                    num_count[n] = num_count.get(n, 0.0) + w

        ranked = sorted(num_count.items(), key=lambda x: -x[1])
        pool = [n for n, _ in ranked[:15]]

        if len(pool) < 6:
            pool = list(range(1, 16))

        scored_combos: list[tuple[list[int], float]] = []
        for combo in combinations(pool, 6):
            score = float(sum(num_count.get(n, 0.0) for n in combo))
            scored_combos.append((list(combo), score))
        scored_combos.sort(key=lambda x: -x[1])

        if not scored_combos:
            return []

        results: list[dict] = []
        used: set[tuple[int, ...]] = set()
        for combo, score in scored_combos:
            if len(results) >= n_sets:
                break
            nums_sorted = sorted(combo)
            combo_key = tuple(nums_sorted)
            if combo_key in used:
                continue
            if not tier1_filter(nums_sorted):
                continue
            if not _is_diff_from_army1(nums_sorted, army1_sets, 0.4):
                continue
            used.add(combo_key)
            base_conf = 95.0 - len(results) * 3.0
            conf = round(max(min(base_conf, 95.0), 60.0), 1)
            results.append(
                {
                    "nums": nums_sorted,
                    "brain_tag": "snake",
                    "method": "뱀두뇌",
                    "confidence": conf,
                    "reasoning": (
                        f"뱀 V8 (35세트 합의, Jaccard<0.4 vs 1군, 점수{score:.1f})"
                    ),
                }
            )

        if len(results) < n_sets:
            weights = [max(num_count.get(n, 0.1), 0.01) for n in pool]
            for _ in range(len(results), n_sets):
                for _try in range(200):
                    p = list(pool)
                    w = list(weights)
                    nums: list[int] = []
                    for __ in range(6):
                        chosen = random.choices(p, weights=w, k=1)[0]
                        nums.append(chosen)
                        idx = p.index(chosen)
                        p.pop(idx)
                        w.pop(idx)
                    nums.sort()
                    if not tier1_filter(nums):
                        continue
                    if tuple(nums) in used:
                        continue
                    if not _is_diff_from_army1(nums, army1_sets, 0.4):
                        continue
                    used.add(tuple(nums))
                    base_c = 95.0 - len(results) * 3.0
                    conf_fill = round(max(min(base_c, 95.0), 60.0), 1)
                    results.append(
                        {
                            "nums": nums,
                            "brain_tag": "snake",
                            "method": "뱀두뇌",
                            "confidence": conf_fill,
                            "reasoning": f"뱀 V8 보충 (Jaccard<0.4, 세트{len(results) + 1})",
                        }
                    )
                    break

        return results
    except Exception as e:  # noqa: BLE001
        logger.warning("뱀 예측 실패: %s", e)
        return []
