"""2군 미당첨분석 V8 — V7 패턴 학습 + 약한 회차(max<=2) 전용 패턴(miss_weak).

공개 API (engine 호환):
  - miss_analysis_predict(all_draws, n_sets=5) -> list[dict]
  - get_miss_analysis_prob_vector(all_draws) -> dict[int, float]

서브뇌: stat, markov, lstm, combo(패턴), fusion(패턴 반영, patterns=None이면 V6 동일).
약한 회차: _get_weak_draws + _run_sub_weak (predict_snake 35세트 합의용).
_run_sub_stat2_inverse는 predict_snake 합의용으로 유지(miss 파이프라인에서는 미사용).

컨닝 방지: miss_analysis_predict 반환 dict에 _miss_cutoff_target_draw_no 부착.
"""
from __future__ import annotations

import logging
import random
from collections import defaultdict
from itertools import combinations
from typing import Any

from app.lotto.filters import tier1_filter

logger = logging.getLogger(__name__)

SETS_PER_SUB_BRAIN = 5
_BRAIN_TAGS_1ST = ("stat", "markov", "llm", "lstm", "fusion", "hyena")
_PAIR_DB_BONUS = 2.5
_ZONE_DB_BONUS = 1.8
_FUSION_PATTERN_ALPHA = 0.12
_PROB_PAIR_GAMMA = 0.08


def _nums_from_draw(d: dict) -> list[int]:
    return sorted(int(d[f"num{i}"]) for i in range(1, 7))


def _zone_idx(n: int) -> int:
    if n <= 9:
        return 0
    if n <= 19:
        return 1
    if n <= 29:
        return 2
    if n <= 39:
        return 3
    return 4


def _zone_tuple(nums: list[int]) -> tuple[int, int, int, int, int]:
    z = [0, 0, 0, 0, 0]
    for n in nums:
        z[_zone_idx(n)] += 1
    return (z[0], z[1], z[2], z[3], z[4])


def _pair_key(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _get_miss_draws(all_draws: list[dict]) -> list[dict]:
    """6뇌 최고 적중 <= 4인 회차(3등 미만 = 미당첨)만 필터."""
    from app.lotto.models import get_lotto_db

    placeholders = ",".join("?" * len(_BRAIN_TAGS_1ST))
    conn = get_lotto_db()
    try:
        rows = conn.execute(
            f"""
            SELECT target_draw_no
            FROM lotto_predictions
            WHERE brain_tag IN ({placeholders})
              AND matched_count >= 0
            GROUP BY target_draw_no
            HAVING MAX(matched_count) <= 4
            """,
            _BRAIN_TAGS_1ST,
        ).fetchall()
    finally:
        conn.close()
    miss_nos = {int(r[0]) for r in rows}
    return [d for d in all_draws if int(d.get("draw_no", 0)) in miss_nos]


def _get_weak_draws(all_draws: list[dict]) -> list[dict]:
    """6뇌 최고 적중 <= 2인 회차(1군 약세)만 필터 — snake V8 miss_weak 전용."""
    from app.lotto.models import get_lotto_db

    placeholders = ",".join("?" * len(_BRAIN_TAGS_1ST))
    conn = get_lotto_db()
    try:
        rows = conn.execute(
            f"""
            SELECT target_draw_no
            FROM lotto_predictions
            WHERE brain_tag IN ({placeholders})
              AND matched_count >= 0
            GROUP BY target_draw_no
            HAVING MAX(matched_count) <= 2
            """,
            _BRAIN_TAGS_1ST,
        ).fetchall()
    finally:
        conn.close()
    weak_nos = {int(r[0]) for r in rows}
    return [d for d in all_draws if int(d.get("draw_no", 0)) in weak_nos]


def _neutral_patterns() -> dict[str, Any]:
    """약한 회차 표본 부족 시 combo/weak 생성용 중립 패턴."""
    return {
        "pair_scores": {},
        "zone_scores": {},
        "consec_target": 0.45,
        "num_freq": {n: 1.0 / 45.0 for n in range(1, 46)},
    }


def _analyze_weak_patterns(
    weak_draws: list[dict], all_draws: list[dict] | None = None
) -> dict[str, Any]:
    """약한 회차 전용: miss 패턴 분석 + 당첨 합 평균 sum_target (V8 정찰용)."""
    ad = all_draws if all_draws is not None else weak_draws
    base = _analyze_miss_patterns(weak_draws, ad)
    sums: list[int] = []
    for d in weak_draws:
        sums.append(sum(int(d[f"num{i}"]) for i in range(1, 7)))
    sum_target = float(sum(sums) / len(sums)) if sums else 138.0
    out = dict(base)
    out["sum_target"] = sum_target
    return out


def _analyze_miss_patterns(
    miss_draws: list[dict], all_draws: list[dict]
) -> dict[str, Any]:
    """미당첨 당첨에서 pair/zone/연번/번호빈도 추출 + 1군 DB 예측 대비 보너스."""
    draw_nos_allowed = {int(d["draw_no"]) for d in all_draws}
    pair_cnt: dict[tuple[int, int], int] = defaultdict(int)
    zone_cnt: dict[tuple[int, int, int, int, int], int] = defaultdict(int)
    num_cnt: dict[int, int] = defaultdict(int)
    consec_flags: list[float] = []

    for d in miss_draws:
        nums = _nums_from_draw(d)
        for a, b in combinations(nums, 2):
            pair_cnt[_pair_key(a, b)] += 1
        zt = _zone_tuple(nums)
        zone_cnt[zt] += 1
        for n in nums:
            num_cnt[n] += 1
        has_consec = any(nums[i + 1] - nums[i] == 1 for i in range(5))
        consec_flags.append(1.0 if has_consec else 0.0)

    n_miss = max(1, len(miss_draws))
    obs_consec_ratio = sum(consec_flags) / n_miss
    consec_target = max(0.28, min(0.72, 0.45 * obs_consec_ratio + 0.28))

    total_pairs = sum(pair_cnt.values()) or 1
    pair_scores: dict[tuple[int, int], float] = {
        k: float(v) / total_pairs for k, v in pair_cnt.items()
    }
    total_z = sum(zone_cnt.values()) or 1
    zone_scores: dict[tuple[int, int, int, int, int], float] = {
        k: float(v) / total_z for k, v in zone_cnt.items()
    }

    nn = sum(num_cnt.values()) or 1
    num_freq: dict[int, float] = {n: num_cnt.get(n, 0) / nn for n in range(1, 46)}
    s_nf = sum(num_freq.values()) or 1.0
    num_freq = {n: num_freq.get(n, 0.0) / s_nf for n in range(1, 46)}

    draw_nos = sorted(
        {int(d["draw_no"]) for d in miss_draws} & draw_nos_allowed
    )
    pred_by_draw: dict[int, list[list[int]]] = defaultdict(list)
    if draw_nos:
        from app.lotto.models import get_lotto_db

        ph = ",".join("?" * len(draw_nos))
        bh = ",".join("?" * len(_BRAIN_TAGS_1ST))
        conn = get_lotto_db()
        try:
            q = (
                f"SELECT target_draw_no, num1, num2, num3, num4, num5, num6 "
                f"FROM lotto_predictions WHERE target_draw_no IN ({ph}) "
                f"AND brain_tag IN ({bh})"
            )
            args = list(draw_nos) + list(_BRAIN_TAGS_1ST)
            for row in conn.execute(q, args):
                tno = int(row["target_draw_no"])
                pred_by_draw[tno].append(
                    sorted(
                        int(row[f"num{i}"])
                        for i in range(1, 7)
                    )
                )
        finally:
            conn.close()

    pair_bonus: dict[tuple[int, int], float] = defaultdict(float)
    zone_bonus: dict[tuple[int, int, int, int, int], float] = defaultdict(float)

    for d in miss_draws:
        tno = int(d["draw_no"])
        nums = _nums_from_draw(d)
        act_pairs = {_pair_key(a, b) for a, b in combinations(nums, 2)}
        act_zone = _zone_tuple(nums)
        preds = pred_by_draw.get(tno, [])
        if not preds:
            continue
        pred_pair_raw: dict[tuple[int, int], int] = defaultdict(int)
        pred_zone_raw: dict[tuple[int, int, int, int, int], int] = defaultdict(int)
        for pn in preds:
            for a, b in combinations(pn, 2):
                pred_pair_raw[_pair_key(a, b)] += 1
            pred_zone_raw[_zone_tuple(pn)] += 1
        pp_total = sum(pred_pair_raw.values()) or 1
        pred_pair_norm = {k: v / pp_total for k, v in pred_pair_raw.items()}
        pz_total = sum(pred_zone_raw.values()) or 1
        pred_zone_norm = {k: v / pz_total for k, v in pred_zone_raw.items()}

        uniform_p = 1.0 / 15.0
        for pk in act_pairs:
            gap = max(0.0, uniform_p - pred_pair_norm.get(pk, 0.0))
            pair_bonus[pk] += gap * _PAIR_DB_BONUS
        gap_z = max(0.0, (1.0 / max(1, len(pred_zone_norm))) - pred_zone_norm.get(act_zone, 0.0))
        zone_bonus[act_zone] += gap_z * _ZONE_DB_BONUS / max(1, len(zone_cnt))

    for pk, b in pair_bonus.items():
        pair_scores[pk] = pair_scores.get(pk, 0.0) + b
    for zk, b in zone_bonus.items():
        zone_scores[zk] = zone_scores.get(zk, 0.0) + b

    return {
        "pair_scores": pair_scores,
        "zone_scores": zone_scores,
        "consec_target": consec_target,
        "num_freq": num_freq,
    }


def _weighted_choice_zone(
    zone_scores: dict[tuple[int, int, int, int, int], float], rng: random.Random
) -> tuple[int, int, int, int, int]:
    valid = [(z, w) for z, w in zone_scores.items() if sum(z) == 6]
    if not valid:
        return _random_valid_zone(rng)
    zs = [v[0] for v in valid]
    ws = [v[1] for v in valid]
    s = float(sum(ws)) or 1.0
    ws2 = [w / s for w in ws]
    return rng.choices(list(zs), weights=ws2, k=1)[0]


def _random_valid_zone(rng: random.Random) -> tuple[int, int, int, int, int]:
    """비음 정수 5튜플 합=6 균등 랜덤 분할 (stars-and-bars)."""
    n, k = 6, 5
    inner = sorted(rng.sample(range(1, n + k), k - 1))
    a = [0] + inner + [n + k]
    return tuple(a[i + 1] - a[i] - 1 for i in range(k))


def _nums_in_band(band: int) -> list[int]:
    bands = (range(1, 10), range(10, 20), range(20, 30), range(30, 40), range(40, 46))
    return list(bands[band])


def _pair_marginal_from_scores(
    pair_scores: dict[tuple[int, int], float],
) -> dict[int, float]:
    out: dict[int, float] = defaultdict(float)
    for (a, b), sc in pair_scores.items():
        out[a] += sc
        out[b] += sc
    return dict(out)


def _generate_combo_set(
    patterns: dict[str, Any],
    n_sets: int,
    *,
    source: str = "miss_combo",
    reasoning_tag: str = "2군조합패턴",
) -> list[dict]:
    pair_scores: dict[tuple[int, int], float] = patterns["pair_scores"]
    zone_scores: dict[tuple[int, int, int, int, int], float] = patterns["zone_scores"]
    consec_target: float = float(patterns["consec_target"])
    num_freq: dict[int, float] = patterns["num_freq"]
    rng = random.Random()
    results: list[dict] = []
    attempts = 0
    set_idx = 0
    while len(results) < n_sets and attempts < 8000:
        attempts += 1
        want_consec = rng.random() < consec_target
        zt = _weighted_choice_zone(zone_scores, rng)
        chosen: list[int] = []
        for band, need in enumerate(zt):
            if need <= 0:
                continue
            pool = [n for n in _nums_in_band(band) if n not in chosen]
            if len(pool) < need:
                chosen = []
                break
            for _ in range(need):
                w = []
                for n in pool:
                    base = max(1e-9, num_freq.get(n, 1.0 / 45.0))
                    pb = 1.0
                    for m in chosen:
                        pk = _pair_key(n, m)
                        pb += 0.35 * pair_scores.get(pk, 0.0)
                    w.append(base * pb)
                pick = rng.choices(pool, weights=w, k=1)[0]
                chosen.append(pick)
                pool.remove(pick)
        if len(chosen) != 6:
            continue
        chosen.sort()
        if want_consec and not any(chosen[i + 1] - chosen[i] == 1 for i in range(5)):
            if rng.random() < 0.62:
                continue
        if not tier1_filter(chosen):
            continue
        if any(r["nums"] == chosen for r in results):
            continue
        set_idx = len(results)
        conf = min(99.0, 92.0 - set_idx * 2)
        results.append(
            {
                "nums": chosen,
                "confidence": conf,
                "reasoning": (
                    f"{reasoning_tag} (세트{set_idx + 1}, 연번목표 {consec_target:.2f})"
                ),
                "source": source,
            }
        )
    return results


def _run_sub_combo(patterns: dict[str, Any], n_sets: int) -> list[dict]:
    try:
        return _generate_combo_set(
            patterns, n_sets, source="miss_combo", reasoning_tag="2군조합패턴"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[2군combo] %s", e)
        return []


def _run_sub_weak(weak_patterns: dict[str, Any], n_sets: int) -> list[dict]:
    """2군 weak: 1군 약한 회차 당첨 패턴 기반 조합 (snake V8 합의)."""
    try:
        return _generate_combo_set(
            weak_patterns,
            n_sets,
            source="miss_weak",
            reasoning_tag="2군약한회차",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[2군weak] %s", e)
        return []


def _run_sub_stat(miss_draws: list[dict], n_sets: int) -> list[dict]:
    try:
        from app.lotto.predict_statistical import _statistical_predict

        results = _statistical_predict(miss_draws, n_sets)
        for r in results:
            r["source"] = "miss_stat"
        return results
    except Exception as e:  # noqa: BLE001
        logger.warning("[2군stat] %s", e)
        return []


def _run_sub_markov(miss_draws: list[dict], n_sets: int) -> list[dict]:
    try:
        from app.lotto.predict_markov import _markov_predict

        results = _markov_predict(miss_draws, n_sets)
        for r in results:
            r["source"] = "miss_markov"
        return results
    except Exception as e:  # noqa: BLE001
        logger.warning("[2군markov] %s", e)
        return []


def _run_sub_lstm(miss_draws: list[dict], n_sets: int) -> list[dict]:
    try:
        from app.lotto.predict_lstm import get_lstm_prob_vector

        pmf = get_lstm_prob_vector(miss_draws)
        results: list[dict] = []
        attempts = 0
        while len(results) < n_sets and attempts < 5000:
            attempts += 1
            pool = list(range(1, 46))
            w = [pmf.get(n, 1.0 / 45.0) for n in pool]
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
            if any(r["nums"] == nums for r in results):
                continue
            conf = min(99.0, 95.0 - len(results) * 2)
            results.append(
                {
                    "nums": nums,
                    "confidence": conf,
                    "reasoning": f"2군LSTM (꽝{len(miss_draws)}회차, 세트{len(results) + 1})",
                    "source": "miss_lstm",
                }
            )
        return results
    except Exception as e:  # noqa: BLE001
        logger.warning("[2군lstm] %s", e)
        return []


def _run_sub_stat2_inverse(
    miss_draws: list[dict], all_draws: list[dict], n_sets: int
) -> list[dict]:
    """2군 stat2: snake 25세트용 역가중치 (miss 파이프라인 V7에서는 미사용)."""
    try:
        from app.lotto.predict_statistical import get_statistical_prob_vector
        from app.lotto.predict_markov import get_markov_prob_vector
        from app.lotto.predict_lstm import get_lstm_prob_vector

        stat_pmf_full = get_statistical_prob_vector(all_draws)
        markov_pmf_full = get_markov_prob_vector(all_draws)
        lstm_pmf_full = get_lstm_prob_vector(all_draws)
        full_pmf: dict[int, float] = {}
        for n in range(1, 46):
            full_pmf[n] = (
                stat_pmf_full.get(n, 0)
                + markov_pmf_full.get(n, 0)
                + lstm_pmf_full.get(n, 0)
            ) / 3.0
        miss_stat_pmf = get_statistical_prob_vector(miss_draws)
        inverse_pmf: dict[int, float] = {}
        for n in range(1, 46):
            miss_weight = miss_stat_pmf.get(n, 1.0 / 45.0)
            full_weight = full_pmf.get(n, 1.0 / 45.0)
            if full_weight > 0:
                inverse_pmf[n] = miss_weight / (full_weight * 45.0)
            else:
                inverse_pmf[n] = miss_weight
        total = sum(inverse_pmf.values())
        if total > 0:
            inverse_pmf = {n: v / total for n, v in inverse_pmf.items()}
        else:
            inverse_pmf = {n: 1.0 / 45.0 for n in range(1, 46)}
        results: list[dict] = []
        attempts = 0
        while len(results) < n_sets and attempts < 5000:
            attempts += 1
            pool = list(range(1, 46))
            w = [inverse_pmf.get(n, 1.0 / 45.0) for n in pool]
            nums = []
            for _ in range(6):
                chosen = random.choices(pool, weights=w, k=1)[0]
                nums.append(chosen)
                idx = pool.index(chosen)
                pool.pop(idx)
                w.pop(idx)
            nums.sort()
            if not tier1_filter(nums):
                continue
            if any(r["nums"] == nums for r in results):
                continue
            conf = min(99.0, 90.0 - len(results) * 2)
            results.append(
                {
                    "nums": nums,
                    "confidence": conf,
                    "reasoning": f"2군역가중치 (틈새공략, 세트{len(results) + 1})",
                    "source": "miss_stat2",
                }
            )
        return results
    except Exception as e:  # noqa: BLE001
        logger.warning("[2군stat2] %s", e)
        return []


def _fused_pmf_miss(miss_draws: list[dict]) -> dict[int, float]:
    from app.lotto.predict_statistical import get_statistical_prob_vector
    from app.lotto.predict_markov import get_markov_prob_vector
    from app.lotto.predict_lstm import get_lstm_prob_vector

    stat_pmf = get_statistical_prob_vector(miss_draws)
    markov_pmf = get_markov_prob_vector(miss_draws)
    lstm_pmf = get_lstm_prob_vector(miss_draws)
    fused: dict[int, float] = {}
    for n in range(1, 46):
        fused[n] = (
            stat_pmf.get(n, 0) + markov_pmf.get(n, 0) + lstm_pmf.get(n, 0)
        ) / 3.0
    total = sum(fused.values())
    if total > 0:
        fused = {n: v / total for n, v in fused.items()}
    return fused


def _run_sub_fusion(
    miss_draws: list[dict], n_sets: int, patterns: dict[str, Any] | None = None
) -> list[dict]:
    """2군 fusion: patterns=None이면 V6 PMF만(snake). 있으면 pair/num_freq 반영."""
    try:
        fused = _fused_pmf_miss(miss_draws)
        if patterns is None:
            adj = fused
        else:
            pair_scores: dict[tuple[int, int], float] = patterns["pair_scores"]
            num_freq: dict[int, float] = patterns["num_freq"]
            pmarg = _pair_marginal_from_scores(pair_scores)
            adj = {}
            for n in range(1, 46):
                base = fused.get(n, 1.0 / 45.0)
                nf = num_freq.get(n, 1.0 / 45.0) * 45.0
                pk = 1.0 + _FUSION_PATTERN_ALPHA * (nf - 1.0)
                pk *= 1.0 + _PROB_PAIR_GAMMA * pmarg.get(n, 0.0)
                adj[n] = base * max(0.05, pk)
            t = sum(adj.values())
            if t > 0:
                adj = {n: v / t for n, v in adj.items()}
            else:
                adj = fused

        zt_pref = _weighted_choice_zone(patterns["zone_scores"], random.Random()) if patterns else None
        consec_t = float(patterns["consec_target"]) if patterns else 0.0

        results: list[dict] = []
        attempts = 0
        while len(results) < n_sets and attempts < 6000:
            attempts += 1
            want_consec = patterns is not None and random.random() < consec_t
            pool = list(range(1, 46))
            nums: list[int] = []
            for _ in range(6):
                if patterns is not None and nums:
                    w = []
                    for n in pool:
                        pb = adj.get(n, 1.0 / 45.0)
                        for m in nums:
                            pk2 = _pair_key(n, m)
                            pb *= 1.0 + 0.2 * patterns["pair_scores"].get(pk2, 0.0)
                        w.append(pb)
                else:
                    w = [adj.get(n, 1.0 / 45.0) for n in pool]
                chosen = random.choices(pool, weights=w, k=1)[0]
                nums.append(chosen)
                idx = pool.index(chosen)
                pool.pop(idx)
            nums.sort()
            if patterns is not None and zt_pref is not None:
                if _zone_tuple(nums) != zt_pref and random.random() < 0.55:
                    continue
            if want_consec and not any(nums[i + 1] - nums[i] == 1 for i in range(5)):
                if random.random() < 0.4:
                    continue
            if not tier1_filter(nums):
                continue
            if any(r["nums"] == nums for r in results):
                continue
            conf = min(99.0, 93.0 - len(results) * 2)
            results.append(
                {
                    "nums": nums,
                    "confidence": conf,
                    "reasoning": f"2군퓨전V7 (꽝{len(miss_draws)}회차, 세트{len(results) + 1})"
                    if patterns
                    else f"2군퓨전 (꽝{len(miss_draws)}회차 합산, 세트{len(results) + 1})",
                    "source": "miss_fusion",
                }
            )
        return results
    except Exception as e:  # noqa: BLE001
        logger.warning("[2군fusion] %s", e)
        return []


def get_miss_analysis_prob_vector(all_draws: list[dict]) -> dict[int, float]:
    """꽝 PMF + pair_scores·num_freq 가중 marginal."""
    miss_draws = _get_miss_draws(all_draws)
    if len(miss_draws) < 3:
        return {n: 1.0 / 45.0 for n in range(1, 46)}
    try:
        patterns = _analyze_miss_patterns(miss_draws, all_draws)
        fused = _fused_pmf_miss(miss_draws)
        pair_scores: dict[tuple[int, int], float] = patterns["pair_scores"]
        num_freq: dict[int, float] = patterns["num_freq"]
        pmarg = _pair_marginal_from_scores(pair_scores)
        out: dict[int, float] = {}
        for n in range(1, 46):
            base = fused.get(n, 1.0 / 45.0)
            nf = num_freq.get(n, 1.0 / 45.0) * 45.0
            out[n] = base * (1.0 + _FUSION_PATTERN_ALPHA * (nf - 1.0))
            out[n] *= 1.0 + _PROB_PAIR_GAMMA * pmarg.get(n, 0.0)
        tot = sum(out.values())
        if tot > 0:
            return {n: out[n] / tot for n in range(1, 46)}
        return fused
    except Exception:  # noqa: BLE001
        return {n: 1.0 / 45.0 for n in range(1, 46)}


def miss_analysis_predict(all_draws: list[dict], n_sets: int = 5) -> list[dict]:
    """2군 5서브뇌(stat/markov/lstm/combo/fusion) 각 5세트 → confidence 상위 n_sets."""
    if not all_draws:
        logger.warning("2군: all_draws 비어 있음")
        return []
    cutoff_target = max(int(d["draw_no"]) for d in all_draws) + 1
    miss_draws = _get_miss_draws(all_draws)
    if len(miss_draws) < 3:
        logger.warning("2군: 꽝 회차 부족 (%d)", len(miss_draws))
        return []
    patterns = _analyze_miss_patterns(miss_draws, all_draws)
    all_results: list[dict] = []
    all_results.extend(_run_sub_stat(miss_draws, SETS_PER_SUB_BRAIN))
    all_results.extend(_run_sub_markov(miss_draws, SETS_PER_SUB_BRAIN))
    all_results.extend(_run_sub_lstm(miss_draws, SETS_PER_SUB_BRAIN))
    all_results.extend(_run_sub_combo(patterns, SETS_PER_SUB_BRAIN))
    all_results.extend(_run_sub_fusion(miss_draws, SETS_PER_SUB_BRAIN, patterns))
    logger.info(
        "2군 V8: stat=%d markov=%d lstm=%d combo=%d fusion=%d 총=%d",
        sum(1 for r in all_results if r.get("source") == "miss_stat"),
        sum(1 for r in all_results if r.get("source") == "miss_markov"),
        sum(1 for r in all_results if r.get("source") == "miss_lstm"),
        sum(1 for r in all_results if r.get("source") == "miss_combo"),
        sum(1 for r in all_results if r.get("source") == "miss_fusion"),
        len(all_results),
    )
    all_results.sort(key=lambda x: -float(x.get("confidence", 0)))
    out = all_results[:n_sets]
    for r in out:
        r["_miss_cutoff_target_draw_no"] = cutoff_target
    return out
