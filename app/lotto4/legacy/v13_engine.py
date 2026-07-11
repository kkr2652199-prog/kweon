"""V11 엔진: V9 6뇌 구조 + 진화 강화 + 1군 fusion 패턴.

학습 데이터 = 1군 미당첨 + 최근 50회 (틈새공략 + 트렌드 보강)
"""

from __future__ import annotations

import logging

from app.lotto4.legacy.predict_constraint import army4_constraint_predict
from app.lotto4.legacy.predict_lstm import army4_lstm_predict
from app.lotto4.legacy.predict_sumrange import army4_sumrange_predict
from app.lotto4.legacy.predict_cooccur import army4_cooccur_predict
from app.lotto4.legacy.predict_cdm import army4_cdm_predict
from app.lotto4.legacy.v13_fusion_v5 import v13_fusion_v5_predict as v13_fusion_predict
from app.lotto4.legacy.v13_snake import v13_snake_predict_sets
from app.lotto4.legacy.v13_models import (
    get_v13_training_draws,
    get_recent_winning_sets,
    v13_pass_win_avoid,
    V13_WIN_AVOID_N,
    init_v13_seeds,
    update_v13_weights,
    get_v13_brain_weights,
)
from app.lotto4.legacy.predict_dead_zone import apply_dead_zone_to_row

logger = logging.getLogger(__name__)
SETS_PER_BRAIN_V13 = 5

# V12-A: 1군 hyena FALLBACK 가중치 (llm→combo, lstm 그대로)
_V11_HYENA_FALLBACK_WEIGHTS: dict[str, float] = {
    "v13_stat": 1.0,
    "v13_run": 1.0,
    "v13_offset": 1.0,
    "v13_contrarian": 1.5,
    "v13_lstm": 2.5,
    "v13_hyena": 1.0,
    "v13_fusion": 2.0,
}
_V11_HYENA_CONTRIBUTING: frozenset[str] = frozenset(
    {"v13_stat", "v13_run", "v13_offset", "v13_contrarian", "v13_lstm", "v13_fusion"}
)

# 패치 H — 하위 4뇌(stat/run/offset/contrarian) 합의 제외. 독립 예측은 유지.
_EXCLUDE_LOWER4_FROM_CONSENSUS: frozenset[str] = frozenset(
    {"v13_stat", "v13_run", "v13_offset", "v13_contrarian"}
)


def _retag(predictions: list[dict], new_tag: str, new_method: str) -> list[dict]:
    """V9 함수 호출 결과의 brain_tag/method를 V11용으로 재태깅."""
    out: list[dict] = []
    for p in predictions:
        q = dict(p)
        q["brain_tag"] = new_tag
        q["method"] = new_method
        out.append(q)
    return out


def _v13_merged_hyena_weights() -> dict[str, float]:
    """DB 가중치 전부 반영. v13_fusion 포함 (시드/예외 시 FALLBACK은 초기 dict)."""
    out = dict(_V11_HYENA_FALLBACK_WEIGHTS)
    try:
        dbw = get_v13_brain_weights()
        for k, v in dbw.items():
            out[k] = float(v)
    except Exception:  # noqa: BLE001
        pass
    return out


def _v13_compute_consensus_score(
    all_predictions: list[dict],
    weights: dict[str, float],
) -> dict[int, float]:
    """1~45 가중 합의 (1군 _compute_consensus_score 미러)."""
    consensus: dict[int, float] = {n: 0.0 for n in range(1, 46)}
    for p in all_predictions:
        tag = str(p.get("brain_tag", ""))
        w = float(weights.get(tag, 0.0))
        if tag in _EXCLUDE_LOWER4_FROM_CONSENSUS:
            w = 0.0
        if w <= 0.0:
            continue
        nums = p.get("nums", [])
        if not isinstance(nums, (list, tuple)):
            continue
        for n in nums:
            try:
                ni = int(n)
            except (TypeError, ValueError):
                continue
            if 1 <= ni <= 45:
                consensus[ni] += w
    return consensus


def _v13_select_candidate_pool(consensus: dict[int, float], pool_size: int = 15) -> list[int]:
    """상위 pool_size개 (점수 내림차순, 동점 시 번호 오름차순)."""
    ranked = sorted(consensus.items(), key=lambda x: (-x[1], x[0]))
    return [n for n, _s in ranked[:pool_size]]


def _v13_evaluate_combinations(
    pool_nums: list[int],
    consensus: dict[int, float],
) -> list[tuple[tuple[int, ...], float]]:
    """15C6=5005 전수, tier1 없음 (1군 _evaluate_combinations)."""
    from itertools import combinations

    out: list[tuple[tuple[int, ...], float]] = []
    for combo in combinations(pool_nums, 6):
        t = float(sum(consensus.get(n, 0.0) for n in combo))
        out.append((tuple(sorted(combo)), t))
    out.sort(key=lambda x: -x[1])
    return out


def _v13_contributing_brain_count(
    combo: tuple[int, ...], all_predictions: list[dict]
) -> int:
    """5기저뇌 기여 수 (hyena·snake 제외)."""
    cset = set(combo)
    present: set[str] = set()
    for pred in all_predictions:
        t = str(pred.get("brain_tag", ""))
        if t not in _V11_HYENA_CONTRIBUTING:
            continue
        nums = pred.get("nums")
        if not isinstance(nums, (list, tuple)):
            continue
        nset = {int(x) for x in nums if isinstance(x, int) and 1 <= x <= 45}
        if cset & nset:
            present.add(t)
    return len(present)


def _v13_confidence_from_score(
    total: float, max_s: float, k: int, max_attempts: int, bypass: bool
) -> float:
    """1군 _confidence_from_score를 0~1 스케일로 환산 (V11 DB와 호환)."""
    if max_s <= 0.0:
        return 0.30
    base = min(0.99, 0.45 + 0.54 * (total / max_s))
    if bypass or max_attempts > 0:
        base = max(0.20, base - 0.05 * min(max_attempts, 3))
    return round(float(base) - 0.003 * (k - 1), 2)


def _v13_build_sets_from_ranked(
    ranked: list[tuple[tuple[int, ...], float]],
    all_predictions: list[dict],
    n_sets: int,
    target_draw_no: int,
) -> list[dict]:
    """1군 _build_sets_from_ranked: tier1 + 상위5 우회 + top50 가중 30회."""
    import random

    from app.lotto.filters import tier1_filter

    if not ranked or n_sets <= 0:
        return []
    top50 = ranked[:50]
    max_s = max(r[1] for r in ranked) if ranked else 1.0
    if max_s <= 0.0:
        max_s = 1.0

    results: list[dict] = []
    used: set[tuple[int, ...]] = set()
    bypass_log_count = 0
    win_sets = get_recent_winning_sets(target_draw_no, V13_WIN_AVOID_N) if target_draw_no else []
    win_st: dict[str, int | bool] = {"fail_count": 0, "bypass": False}

    chosen: tuple[int, ...] | None = None
    t1: float = 0.0
    bypass1 = False
    for cmb, t in ranked:
        nlist = list(cmb)
        if not tier1_filter(nlist):
            continue
        if not v13_pass_win_avoid(nlist, win_sets, win_st):
            continue
        chosen, t1 = cmb, t
        break
    if chosen is None and ranked:
        for cmb, t in ranked[:5]:
            if not v13_pass_win_avoid(list(cmb), win_sets, win_st):
                continue
            logger.warning("V11 hyena: 1세트 tier1 전부 실패 → 상위5 강제. combo=%s", cmb)
            chosen, t1, bypass1 = cmb, t, True
            bypass_log_count += 1
            break
    if chosen is None:
        return []

    used.add(chosen)
    nb = _v13_contributing_brain_count(chosen, all_predictions)
    results.append(
        {
            "nums": list(chosen),
            "brain_tag": "v13_hyena",
            "method": "V11하이에나두뇌",
            "confidence": _v13_confidence_from_score(t1, max_s, 1, 0, bypass1),
            "reasoning": (
                f"V12-A 5005, 합계 {t1:.2f}, 기여뇌 {nb}개(세트1)"
                + (" (tier1 우회)" if bypass1 else "")
            ),
        }
    )

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
            pick = random.choices(idxs, weights=weights[: len(top50)], k=1)[0]
            cmb, t = top50[pick]
            if cmb in used:
                continue
            nlist = list(cmb)
            if not tier1_filter(nlist):
                continue
            if not v13_pass_win_avoid(nlist, win_sets, win_st):
                continue
            got, tgot, bpass = cmb, t, False
        if got is None:
            for cmb, t in ranked[:5]:
                if cmb in used:
                    continue
                if not v13_pass_win_avoid(list(cmb), win_sets, win_st):
                    continue
                logger.warning("V11 hyena: %d세트 30회 만료 → 상위5 강제. combo=%s", k, cmb)
                got, tgot, bpass = cmb, t, True
                bypass_log_count += 1
                break
        if got is None:
            break
        used.add(got)
        nbb = _v13_contributing_brain_count(got, all_predictions)
        results.append(
            {
                "nums": list(got),
                "brain_tag": "v13_hyena",
                "method": "V11하이에나두뇌",
                "confidence": _v13_confidence_from_score(tgot, max_s, k, attempts, bpass),
                "reasoning": (
                    f"V12-A 5005, 점수 {tgot:.2f}, 기여뇌 {nbb}개(세트{k})"
                    + (f" (tier1_bypass tries={attempts})" if bpass else f" (tries={attempts})")
                ),
            }
        )

    if bypass_log_count >= 5:
        logger.warning("V11 hyena: tier1 우회 누적 %d회", bypass_log_count)

    return results


def _v13_hyena_predict(
    all_predictions: list[dict], n_sets: int = 5, target_draw_no: int = 0,
) -> list[dict]:
    """V12-A: 1군 hyena 5005 전수 파이프라인 미러링."""
    try:
        if len(all_predictions) < 10:
            return []
        hw = _v13_merged_hyena_weights()
        consensus = _v13_compute_consensus_score(all_predictions, hw)
        if not any(v > 0 for v in consensus.values()):
            return []
        pool_nums = _v13_select_candidate_pool(consensus, 15)
        if len(pool_nums) < 6:
            return []
        ranked = _v13_evaluate_combinations(pool_nums, consensus)
        if not ranked:
            return []
        return _v13_build_sets_from_ranked(ranked, all_predictions, n_sets, target_draw_no)
    except Exception as e:  # noqa: BLE001
        logger.warning("V11 hyena 예측 실패: %s", e)
        return []


def run_prediction_v13(target_draw_no: int) -> dict:
    """V11 단일 회차 예측 (V9와 분리, brain_tag='v13_*')."""
    init_v13_seeds()

    from app.lotto4.models import get_lotto4_db

    conn = get_lotto4_db()
    try:
        existing = conn.execute(
            "SELECT brain_tag FROM lotto_predictions_army4 WHERE target_draw_no = ? AND brain_tag LIKE 'v13_%'",
            (target_draw_no,),
        ).fetchall()
    finally:
        conn.close()

    if existing and len(existing) >= 40:  # 기저 6×5 + hyena 5 + snake 5 = 40
        return {
            "status": "cached",
            "target_draw_no": target_draw_no,
            "v13_sets": len(existing),
            "all_predictions": [],
        }

    training = get_v13_training_draws(target_draw_no)
    if len(training) < 5:
        return {
            "status": "error",
            "reason": "insufficient_training_data",
            "n": len(training),
            "target_draw_no": target_draw_no,
        }

    fresh: list[dict] = []
    fresh.extend(_retag(army4_cdm_predict(training, SETS_PER_BRAIN_V13, target_draw_no), "v13_stat", "📊 베이지안CDM"))
    fresh.extend(
        _retag(
            army4_cooccur_predict(training, SETS_PER_BRAIN_V13, target_draw_no),
            "v13_run",
            "🕸️ 공동출현그래프",
        )
    )
    fresh.extend(
        _retag(
            army4_sumrange_predict(training, SETS_PER_BRAIN_V13, target_draw_no),
            "v13_offset",
            "📐 번호합범위",
        )
    )
    fresh.extend(
        _retag(
            army4_constraint_predict(training, SETS_PER_BRAIN_V13, target_draw_no),
            "v13_contrarian",
            "🎯 제약만족샘플러",
        )
    )
    fresh.extend(_retag(army4_lstm_predict(training, SETS_PER_BRAIN_V13, target_draw_no), "v13_lstm", "V11LSTM두뇌"))
    fresh.extend(v13_fusion_predict(training, target_draw_no, SETS_PER_BRAIN_V13))

    hyena_sets = _v13_hyena_predict(fresh, SETS_PER_BRAIN_V13, target_draw_no)
    fresh.extend(hyena_sets)

    # V12-B: Snake 합성 두뇌 (1군 셋트와 Jaccard < 0.4 차별화)
    try:
        snake_sets = v13_snake_predict_sets(fresh, target_draw_no, n_sets=SETS_PER_BRAIN_V13)
        fresh.extend(snake_sets)
        logger.info(
            "v13_snake: generated %d sets for target=%d",
            len(snake_sets), target_draw_no,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("v13_snake failed for target=%d: %s", target_draw_no, e)

    if not fresh:
        return {"status": "error", "reason": "no_sets_generated", "target_draw_no": target_draw_no}

    for r in fresh:
        apply_dead_zone_to_row(r)

    conn = get_lotto4_db()
    try:
        conn.execute(
            "DELETE FROM lotto_predictions_army4 WHERE target_draw_no = ? AND brain_tag LIKE 'v13_%'",
            (target_draw_no,),
        )
        for r in fresh:
            nums = r.get("nums", [])
            if len(nums) != 6:
                continue
            conn.execute(
                """
                INSERT INTO lotto_predictions_army4
                (target_draw_no, method, num1, num2, num3, num4, num5, num6,
                 confidence, reasoning, brain_tag)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target_draw_no,
                    r.get("method", "?"),
                    nums[0],
                    nums[1],
                    nums[2],
                    nums[3],
                    nums[4],
                    nums[5],
                    r.get("confidence", 0.5),
                    r.get("reasoning", ""),
                    r.get("brain_tag", "v13_unknown"),
                ),
            )
        conn.commit()
        _score_v13_predictions(target_draw_no)
        update_v13_weights(target_draw_no)
    finally:
        conn.close()

    all_predictions: list[dict] = []
    for r in fresh:
        nums = list(r.get("nums") or [])
        if len(nums) != 6:
            continue
        all_predictions.append(
            {
                "nums": nums,
                "method": r.get("method", "?"),
                "brain_tag": r.get("brain_tag", "v13_unknown"),
                "confidence": r.get("confidence", 0.5),
                "reasoning": r.get("reasoning", ""),
                "dz_var": r.get("dz_var"),
                "dz_prime_cnt": r.get("dz_prime_cnt"),
                "dz_z3_cnt": r.get("dz_z3_cnt"),
                "dz_delta_conf": r.get("dz_delta_conf"),
                "dz_filter_passed": r.get("dz_filter_passed"),
            }
        )

    return {
        "status": "ok",
        "target_draw_no": target_draw_no,
        "v13_sets": len(fresh),
        "all_predictions": all_predictions,
    }


def _score_v13_predictions(target_draw_no: int) -> None:
    """V11 예측 채점."""
    from app.lotto4.models import get_lotto4_db

    conn = get_lotto4_db()
    try:
        actual = conn.execute(
            "SELECT num1, num2, num3, num4, num5, num6, bonus FROM lotto_draws WHERE draw_no = ?",
            (target_draw_no,),
        ).fetchone()
        if not actual:
            return
        actual_set = {actual[i] for i in range(6)}
        bonus = actual[6]
        rows = conn.execute(
            """
            SELECT id, num1, num2, num3, num4, num5, num6
            FROM lotto_predictions_army4
            WHERE target_draw_no = ?
              AND brain_tag LIKE 'v13_%'
            """,
            (target_draw_no,),
        ).fetchall()
        for r in rows:
            pred_set = {r[i + 1] for i in range(6)}
            matched = len(pred_set & actual_set)
            bonus_m = 1 if bonus in pred_set else 0
            conn.execute(
                "UPDATE lotto_predictions_army4 SET matched_count = ?, bonus_matched = ? WHERE id = ?",
                (matched, bonus_m, r[0]),
            )
        conn.commit()
    finally:
        conn.close()


def run_v13_chunk_backtest(start_draw: int, end_draw: int, checkpoint_every: int = 25) -> dict:
    """V11 청크 백테스트."""
    import time

    t0 = time.time()
    total_ok = 0
    total_error = 0
    error_draws: list[dict] = []
    checkpoints: list[dict] = []

    for n, draw_no in enumerate(range(start_draw, end_draw + 1), 1):
        try:
            r = run_prediction_v13(draw_no)
            status = r.get("status", "unknown")
            if status in ("ok", "cached"):
                total_ok += 1
            else:
                total_error += 1
                error_draws.append(
                    {"draw_no": draw_no, "status": status, "reason": r.get("reason")}
                )
        except Exception as e:  # noqa: BLE001
            total_error += 1
            error_draws.append({"draw_no": draw_no, "exception": str(e)[:200]})

        if n % checkpoint_every == 0:
            elapsed = time.time() - t0
            checkpoints.append(
                {
                    "n_done": n,
                    "current_draw": draw_no,
                    "elapsed_sec": round(elapsed, 1),
                    "ok": total_ok,
                    "error": total_error,
                    "rate_sec_per_draw": round(elapsed / n, 3),
                }
            )

    elapsed_total = time.time() - t0
    return {
        "range": f"{start_draw}~{end_draw}",
        "elapsed_sec": round(elapsed_total, 1),
        "elapsed_min": round(elapsed_total / 60, 2),
        "total_ok": total_ok,
        "total_error": total_error,
        "error_draws_first10": error_draws[:10],
        "checkpoints": checkpoints,
    }

