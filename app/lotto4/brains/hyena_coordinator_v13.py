"""전략 X 하이에나 조율뇌 — 5뇌 후보 풀 + 과거 인기적합도 가중 consensus.

실전: walk-forward만 (R13). lotto_predictions_army4 N 이전 로그 우선, 없으면 재생성.
R2: 당첨 확률 향상 주장 금지.
"""

from __future__ import annotations

import random
import sqlite3
from collections import Counter, defaultdict
from typing import Any, Callable

from app.lotto4.brains._utils import _weighted_draw_without_replacement, jaccard
from app.lotto4.brains.coordinator_brain import (
    NUM_SETS,
    RNG_SEED_MUL as COORD_RNG_MUL,
    _draw_coordinator_set,
    generate_recommend_sets,
)
from app.lotto4.brains.cooccur_brain_v13 import (
    CooccurState,
    generate_cooccur_sets,
)
from app.lotto4.brains.popularity_freq_brain import (
    avg_popularity_score,
    generate_popularity_sets,
    load_popularity_weights,
)
from app.lotto4.brains.popularity_pair_brain import (
    _pair_key,
    generate_pair_sets,
    load_pair_weights,
)
from app.lotto4.brains.shape_brain import (
    _matches_shape,
    extract_shape_metrics,
    generate_shape_sets,
    load_shape_profile,
)
from app.lotto4.anomaly_pair_signal_walkforward import (
    apply_anomaly_boost,
    compute_anomaly_pairs_before,
)
from app.lotto4.gap_signal_walkforward import apply_gap_boost, compute_gap_before
from app.lotto4.models import LOTTO_DB_PATH, get_lotto4_db
from app.lotto4.unpopularity_signal_walkforward import (
    apply_unpop_boost,
    compute_unpopularity_before,
)

NUM_SETS_HYENA = 5
JACCARD_LIMIT = 0.5
LOOKBACK = 50
MIN_LOG_SAMPLES = 5
RNG_SEED_MUL = 20260622

DISCLAIMER = (
    "5뇌(인기·쌍·형태·동반출현·조율) 후보와 N 이전 과거 인기적합도 가중 consensus입니다. "
    "미래를 예측하지 않으며 당첨 확률은 모든 조합이 동일합니다."
)
BRAIN_TAG = "strategy_x_hyena"

SOURCE_TAGS: tuple[str, ...] = (
    "strategy_x_popularity_freq",
    "strategy_x_popularity_pair",
    "strategy_x_shape",
    "strategy_x_cooccur",
    "strategy_x_coordinator",
)

WEIGHT_SCHEMES: tuple[str, ...] = ("equal", "cooccur_favor", "top2_focus")
DEFAULT_WEIGHT_SCHEME = "cooccur_favor"

# 정적 배율 (cooccur 우대형 / 균등형)
_SCHEME_STATIC_MUL: dict[str, dict[str, float]] = {
    "equal": {t: 1.0 for t in SOURCE_TAGS},
    "cooccur_favor": {
        "strategy_x_cooccur": 2.8,
        "strategy_x_coordinator": 1.5,
        "strategy_x_popularity_pair": 0.9,
        "strategy_x_popularity_freq": 0.7,
        "strategy_x_shape": 0.25,
    },
}

# 약한 뇌 보완 상한 (cooccur 우대형)
_SUPPLEMENT_TAGS = frozenset(
    {"strategy_x_shape", "strategy_x_popularity_freq"}
)

ANALYSIS_LABEL = "analysis_lookahead_only_NOT_PREDICTION"


def _brain_generators() -> dict[str, Callable[[int], dict[str, Any]]]:
    return {
        "strategy_x_popularity_freq": generate_popularity_sets,
        "strategy_x_popularity_pair": generate_pair_sets,
        "strategy_x_shape": generate_shape_sets,
        "strategy_x_cooccur": generate_cooccur_sets,
        "strategy_x_coordinator": generate_recommend_sets,
    }


def _nums_from_row(row: tuple) -> list[int]:
    return sorted(int(row[i]) for i in range(2, 8))


def _load_logs_before(
    target_draw_no: int,
    lookback: int = LOOKBACK,
    db_path: str | None = None,
) -> dict[int, dict[str, list[list[int]]]]:
    """target_draw_no 미만 회차 strategy_x 로그 (hyena 제외)."""
    path = db_path or str(LOTTO_DB_PATH)
    start = max(1, int(target_draw_no) - int(lookback))
    end = int(target_draw_no)
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute(
            """
            SELECT target_draw_no, brain_tag, num1, num2, num3, num4, num5, num6
            FROM lotto_predictions_army4
            WHERE target_draw_no >= ? AND target_draw_no < ?
              AND brain_tag LIKE 'strategy_x_%'
              AND brain_tag != ?
            ORDER BY target_draw_no, brain_tag
            """,
            (start, end, BRAIN_TAG),
        ).fetchall()
    finally:
        conn.close()
    out: dict[int, dict[str, list[list[int]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for r in rows:
        d = int(r[0])
        tag = str(r[1])
        out[d][tag].append(_nums_from_row(r))
    return dict(out)


def _pop_weights_walkforward(
    draw_no: int,
    draws: list[dict[str, Any]],
) -> dict[int, float]:
    train = [d for d in draws if d["drw_no"] < draw_no]
    if not train:
        return {n: 1.0 / 45.0 for n in range(1, 46)}
    sorted_by_w = sorted(train, key=lambda d: d["winner_cnt"], reverse=True)
    k = max(1, int(len(sorted_by_w) * 0.30))
    threshold = sorted_by_w[k - 1]["winner_cnt"]
    top30 = [d for d in train if d["winner_cnt"] >= threshold]
    if not top30:
        return {n: 1.0 / 45.0 for n in range(1, 46)}
    freq: Counter[int] = Counter()
    for d in top30:
        for n in d["nums"]:
            freq[n] += 1
    kk = len(top30)
    return {n: max(freq.get(n, 0) / kk, 0.01) for n in range(1, 46)}


def compute_brain_trust(
    target_draw_no: int,
    *,
    draws: list[dict[str, Any]] | None = None,
    logs_before: dict[int, dict[str, list[list[int]]]] | None = None,
    lookback: int = LOOKBACK,
    regenerate_fn: Callable[[int, str], list[list[int]]] | None = None,
) -> dict[str, float]:
    """N 이전 로그·재생성으로 각 뇌의 과거 인기적합도 기여도 (R13)."""
    td = int(target_draw_no)
    trust: dict[str, float] = {t: 0.0 for t in SOURCE_TAGS}
    counts: dict[str, int] = {t: 0 for t in SOURCE_TAGS}

    if logs_before is None:
        logs_before = _load_logs_before(td, lookback)

    draw_list = draws or []
    draw_by_no = {d["drw_no"]: d for d in draw_list} if draw_list else {}

    for d in sorted(logs_before.keys()):
        if d >= td:
            continue
        tag_sets = logs_before[d]
        if draw_list:
            pop_w = _pop_weights_walkforward(d, draw_list)
        else:
            pop_w = load_popularity_weights()

        for tag in SOURCE_TAGS:
            sets = tag_sets.get(tag)
            if not sets and regenerate_fn is not None:
                sets = regenerate_fn(d, tag)
            if not sets:
                continue
            for nums in sets:
                trust[tag] += avg_popularity_score(nums, pop_w)
                counts[tag] += 1

    # 로그 부족 시 regenerate로 보강
    if regenerate_fn is not None and draw_list:
        start = max(1, td - lookback)
        for d in range(start, td):
            if d not in draw_by_no:
                continue
            pop_w = _pop_weights_walkforward(d, draw_list)
            for tag in SOURCE_TAGS:
                if counts[tag] >= MIN_LOG_SAMPLES:
                    continue
                sets = regenerate_fn(d, tag)
                for nums in sets:
                    trust[tag] += avg_popularity_score(nums, pop_w)
                    counts[tag] += 1

    result: dict[str, float] = {}
    for tag in SOURCE_TAGS:
        if counts[tag] > 0:
            result[tag] = round(trust[tag] / counts[tag], 4)
        else:
            result[tag] = 0.5
    return result


def apply_trust_weight_scheme(
    raw_trust: dict[str, float],
    scheme: str,
) -> dict[str, float]:
    """과거 인기적합도 기여도에 스킴 배율 적용 (walk-forward, R13)."""
    sch = scheme if scheme in WEIGHT_SCHEMES else DEFAULT_WEIGHT_SCHEME
    base = {t: max(float(raw_trust.get(t, 0.5)), 0.01) for t in SOURCE_TAGS}

    if sch == "top2_focus":
        ranked = sorted(SOURCE_TAGS, key=lambda t: base[t], reverse=True)
        top2 = set(ranked[:2])
        multipliers = {t: (1.6 if t in top2 else 0.3) for t in SOURCE_TAGS}
    else:
        multipliers = _SCHEME_STATIC_MUL.get(sch, _SCHEME_STATIC_MUL["equal"])

    out: dict[str, float] = {}
    for tag in SOURCE_TAGS:
        eff = base[tag] * multipliers.get(tag, 1.0)
        if sch == "cooccur_favor" and tag in _SUPPLEMENT_TAGS:
            eff = min(eff, base[tag] * 0.35)
        out[tag] = round(max(eff, 0.01), 4)
    return out


def _collect_brain_outputs(
    target_draw_no: int,
    *,
    wf_context: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """5뇌 + coordinator 출력 수집."""
    td = int(target_draw_no)
    outputs: dict[str, dict[str, Any]] = {}

    outputs["strategy_x_popularity_freq"] = generate_popularity_sets(td)
    outputs["strategy_x_popularity_pair"] = generate_pair_sets(td)
    outputs["strategy_x_shape"] = generate_shape_sets(td)

    if wf_context and "cooccur_state" in wf_context:
        outputs["strategy_x_cooccur"] = generate_cooccur_sets(
            td,
            state=wf_context["cooccur_state"].copy(),
            draw_count=wf_context.get("draw_count"),
        )
    else:
        outputs["strategy_x_cooccur"] = generate_cooccur_sets(td)

    if wf_context and all(
        k in wf_context
        for k in ("number_weights", "pair_weights", "shape_profile")
    ):
        sets: list[dict[str, Any]] = []
        existing: list[list[int]] = []
        nw = wf_context["number_weights"]
        pw = wf_context["pair_weights"]
        sp = wf_context["shape_profile"]
        for set_no in range(1, NUM_SETS + 1):
            seed = td * COORD_RNG_MUL + set_no * 211
            rng = random.Random(seed)
            nums = _draw_coordinator_set(rng, nw, pw, sp, existing)
            if nums is None:
                continue
            existing.append(nums)
            sets.append({"set_no": set_no, "numbers": nums})
        outputs["strategy_x_coordinator"] = {
            "target_draw_no": td,
            "brain": "strategy_x_coordinator",
            "sets": sets,
        }
    else:
        outputs["strategy_x_coordinator"] = generate_recommend_sets(td)

    return outputs


def _build_pool_weights(
    outputs: dict[str, dict[str, Any]],
    brain_trust: dict[str, float],
) -> tuple[dict[int, float], dict[int, int]]:
    pool: dict[int, float] = defaultdict(float)
    consensus: Counter[int] = Counter()
    for tag, payload in outputs.items():
        tw = max(float(brain_trust.get(tag, 0.5)), 0.01)
        for item in payload.get("sets") or []:
            nums = item.get("numbers") or []
            for n in nums:
                ni = int(n)
                if 1 <= ni <= 45:
                    pool[ni] += tw
                    consensus[ni] += 1
    return dict(pool), dict(consensus)


def _hyena_chain_pick(
    rng: random.Random,
    picked: list[int],
    pool_weight: dict[int, float],
    consensus: dict[int, int],
    pair_weights: dict[tuple[int, int], float],
    number_weights: dict[int, float],
) -> int | None:
    available = [n for n in range(1, 46) if n not in picked]
    if not available:
        return None
    weights: dict[int, float] = {}
    for c in available:
        w = pool_weight.get(c, 0.0) + number_weights.get(c, 0.01) * 0.3
        w *= 1.0 + 0.15 * consensus.get(c, 0)
        for p in picked:
            w += pair_weights.get(_pair_key(c, p), 0.001) * 2.0
        weights[c] = max(float(w), 0.001)
    one = _weighted_draw_without_replacement(rng, weights, 1)
    return one[0] if one else None


def _draw_hyena_set(
    rng: random.Random,
    pool_weight: dict[int, float],
    consensus: dict[int, int],
    pair_weights: dict[tuple[int, int], float],
    number_weights: dict[int, float],
    shape_profile: dict[str, Any],
    existing: list[list[int]],
    jaccard_limit: float = JACCARD_LIMIT,
) -> list[int] | None:
    ranked = sorted(
        pool_weight.items(),
        key=lambda x: (-x[1] - 0.1 * consensus.get(x[0], 0), x[0]),
    )
    if not ranked:
        return None

    for _ in range(300):
        seed_nums = [ranked[0][0]]
        if len(ranked) > 1 and rng.random() < 0.5:
            seed_nums.append(ranked[1][0])
        picked = list(dict.fromkeys(seed_nums))
        ok = True
        while len(picked) < 6:
            n = _hyena_chain_pick(
                rng,
                picked,
                pool_weight,
                consensus,
                pair_weights,
                number_weights,
            )
            if n is None:
                ok = False
                break
            picked.append(n)
        if not ok or len(picked) != 6:
            continue
        nums = sorted(picked)
        metrics = extract_shape_metrics(nums)
        if not _matches_shape(metrics, shape_profile):
            continue
        st = set(nums)
        if any(jaccard(st, set(prev)) >= jaccard_limit for prev in existing):
            continue
        return nums
    return None


def generate_hyena_sets(
    target_draw_no: int,
    *,
    wf_context: dict[str, Any] | None = None,
    draws: list[dict[str, Any]] | None = None,
    use_db_logs: bool = True,
    brain_trust_override: dict[str, float] | None = None,
    brain_outputs_override: dict[str, dict[str, Any]] | None = None,
    weight_scheme: str = DEFAULT_WEIGHT_SCHEME,
    gap_blend: float = 0.0,
    unpop_blend: float = 0.0,
    anomaly_blend: float = 0.0,
    unpop_profile: dict[str, Any] | None = None,
    anomaly_data: dict[str, Any] | None = None,
    jaccard_limit: float = JACCARD_LIMIT,
) -> dict[str, Any]:
    """walk-forward 하이에나 5세트 생성."""
    td = int(target_draw_no)
    jac_lim = float(jaccard_limit)
    sch = weight_scheme if weight_scheme in WEIGHT_SCHEMES else DEFAULT_WEIGHT_SCHEME

    def _regen(d: int, tag: str) -> list[list[int]]:
        ctx = None
        if draws and wf_context:
            ctx = {
                **wf_context,
                "draw_count": len([x for x in draws if x["drw_no"] < d]),
            }
        outs = _collect_brain_outputs(d, wf_context=ctx)
        return [
            s["numbers"]
            for s in outs.get(tag, {}).get("sets") or []
            if s.get("numbers")
        ]

    if brain_trust_override is not None:
        raw_trust = brain_trust_override
    else:
        logs = _load_logs_before(td) if use_db_logs else {}
        raw_trust = compute_brain_trust(
            td,
            draws=draws,
            logs_before=logs if logs else None,
            regenerate_fn=_regen if draws else None,
        )
    brain_trust = apply_trust_weight_scheme(raw_trust, sch)

    outputs = brain_outputs_override or _collect_brain_outputs(
        td, wf_context=wf_context
    )
    pool_weight, consensus = _build_pool_weights(outputs, brain_trust)

    if float(gap_blend) > 0:
        gap_data = compute_gap_before(td)
        pool_weight = apply_gap_boost(
            pool_weight, gap_data["gaps"], blend=float(gap_blend)
        )

    if float(unpop_blend) > 0:
        profile = unpop_profile or compute_unpopularity_before(td)
        pool_weight = apply_unpop_boost(
            pool_weight, profile, blend=float(unpop_blend)
        )

    if float(anomaly_blend) > 0:
        adata = anomaly_data or compute_anomaly_pairs_before(td)
        pool_weight = apply_anomaly_boost(
            pool_weight, adata, blend=float(anomaly_blend)
        )

    if wf_context and "number_weights" in wf_context:
        number_weights = wf_context["number_weights"]
        pair_weights = wf_context["pair_weights"]
        shape_profile = wf_context["shape_profile"]
    else:
        number_weights = load_popularity_weights()
        pair_weights = load_pair_weights()
        shape_profile = load_shape_profile()

    sets: list[dict[str, Any]] = []
    existing: list[list[int]] = []

    for set_no in range(1, NUM_SETS_HYENA + 1):
        seed = td * RNG_SEED_MUL + set_no * 197
        rng = random.Random(seed)
        nums = _draw_hyena_set(
            rng,
            pool_weight,
            consensus,
            pair_weights,
            number_weights,
            shape_profile,
            existing,
            jaccard_limit=jac_lim,
        )
        if nums is None:
            continue
        existing.append(nums)
        pop_score = avg_popularity_score(nums, number_weights)
        sets.append(
            {
                "set_no": set_no,
                "numbers": nums,
                "popularity_score": pop_score,
                "pool_consensus_max": max(consensus.get(n, 0) for n in nums),
            }
        )

    return {
        "target_draw_no": td,
        "brain": BRAIN_TAG,
        "mode": "walk_forward",
        "weight_scheme": sch,
        "gap_blend": float(gap_blend),
        "unpop_blend": float(unpop_blend),
        "anomaly_blend": float(anomaly_blend),
        "jaccard_limit": jac_lim,
        "raw_brain_trust": raw_trust,
        "disclaimer": DISCLAIMER,
        "brain_trust": brain_trust,
        "brain_outputs_summary": {
            tag: len(payload.get("sets") or [])
            for tag, payload in outputs.items()
        },
        "sets": sets,
    }


def analyze_union_hits_lookahead(
    target_draw_no: int,
    actual_nums: list[int],
    *,
    wf_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """[분석 전용, 예측 아님] look-ahead: 실제 당첨번호로 5뇌 보완성 측정."""
    actual = set(int(n) for n in actual_nums)
    outputs = _collect_brain_outputs(int(target_draw_no), wf_context=wf_context)

    per_brain: dict[str, Any] = {}
    union_all: set[int] = set()
    for tag, payload in outputs.items():
        best_hit = 0
        best_set: list[int] = []
        for item in payload.get("sets") or []:
            nums = item.get("numbers") or []
            hit = len(set(nums) & actual)
            if hit > best_hit:
                best_hit = hit
                best_set = nums
            union_all.update(int(n) for n in nums)
        per_brain[tag] = {
            "best_hit": best_hit,
            "best_set": best_set,
        }

    return {
        "label": ANALYSIS_LABEL,
        "warning": "분석 전용, 예측 아님 — 실제 당첨번호를 본 look-ahead 측정",
        "target_draw_no": int(target_draw_no),
        "per_brain_best_hit": per_brain,
        "union_unique_numbers": len(union_all),
        "union_hit_count": len(union_all & actual),
        "union_hit_numbers": sorted(union_all & actual),
    }


def generate(target_draw_no: int) -> dict[str, Any]:
    return generate_hyena_sets(int(target_draw_no))
