"""하이에나(cooccur_favor) era별·누적효과 walk-forward 백테스트 (R13)."""

from __future__ import annotations

import json
import random
import statistics
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.lotto4.brains.cooccur_brain_v13 import CooccurState, generate_cooccur_sets
from app.lotto4.brains.coordinator_brain import NUM_SETS, RNG_SEED_MUL, _draw_coordinator_set
from app.lotto4.brains.hyena_coordinator_v13 import SOURCE_TAGS, generate_hyena_sets
from app.lotto4.brains.popularity_freq_brain import generate_popularity_sets
from app.lotto4.brains.popularity_pair_brain import generate_pair_sets
from app.lotto4.brains.shape_brain import (
    _segment_summary,
    extract_shape_metrics,
    generate_shape_sets,
)

DB = Path(r"d:\3kweon\data\lotto4.db")
OUT = Path(r"d:\3kweon\tools\_strategy_x_hyena_era_backtest.json")

ERA_RANGES = {"A": (1, 87), "B": (88, 261), "C": (262, 1228)}
MIN_TRAIN_DRAWS = 80
LOOKBACK = 50
SCHEME = "cooccur_favor"
ACCUM_EARLY = (262, 600)
ACCUM_LATE = (601, 1228)
TRUNC_CAP = 600


def _load_draws() -> list[dict[str, Any]]:
    import sqlite3

    conn = sqlite3.connect(DB)
    try:
        rows = conn.execute(
            """
            SELECT drw_no, n1, n2, n3, n4, n5, n6, winner_cnt, era
            FROM lotto4_winners_full
            WHERE winner_cnt > 0
            ORDER BY drw_no
            """
        ).fetchall()
        return [
            {
                "drw_no": int(r[0]),
                "nums": [int(r[i]) for i in range(1, 7)],
                "winner_cnt": int(r[7]),
                "era": str(r[8]),
            }
            for r in rows
        ]
    finally:
        conn.close()


def _top30_rows(train: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not train:
        return []
    sorted_by_w = sorted(train, key=lambda d: d["winner_cnt"], reverse=True)
    k = max(1, int(len(sorted_by_w) * 0.30))
    threshold = sorted_by_w[k - 1]["winner_cnt"]
    return [d for d in train if d["winner_cnt"] >= threshold]


def _build_number_weights(top30: list[dict[str, Any]]) -> dict[int, float]:
    if not top30:
        return {n: 1.0 / 45.0 for n in range(1, 46)}
    from collections import Counter

    k = len(top30)
    freq: Counter[int] = Counter()
    for d in top30:
        for n in d["nums"]:
            freq[n] += 1
    return {n: max(freq.get(n, 0) / k, 0.01) for n in range(1, 46)}


def _build_pair_weights(top30: list[dict[str, Any]]) -> dict[tuple[int, int], float]:
    if not top30:
        return {(a, b): 0.001 for a in range(1, 46) for b in range(a + 1, 46)}
    k = len(top30)
    pf: dict[tuple[int, int], int] = defaultdict(int)
    for d in top30:
        for a, b in combinations(sorted(d["nums"]), 2):
            pf[(a, b)] += 1
    return {
        (a, b): max(pf.get((a, b), 0) / k, 0.001)
        for a in range(1, 46)
        for b in range(a + 1, 46)
    }


def _build_shape_profile(top30: list[dict[str, Any]]) -> dict[str, Any]:
    if not top30:
        return {"sum6": {"p5": 100, "p95": 175}}
    return _segment_summary([extract_shape_metrics(d["nums"]) for d in top30])


def _wf_coord(drw_no: int, nw, pw, sp) -> list[list[int]]:
    sets, existing = [], []
    for set_no in range(1, NUM_SETS + 1):
        seed = int(drw_no) * RNG_SEED_MUL + set_no * 211
        rng = random.Random(seed)
        nums = _draw_coordinator_set(rng, nw, pw, sp, existing)
        if nums is None:
            nums = sorted(rng.sample(range(1, 46), 6))
        existing.append(nums)
        sets.append(nums)
    return sets


def _collect(drw_no: int, wf: dict) -> dict[str, dict]:
    return {
        "strategy_x_popularity_freq": generate_popularity_sets(drw_no),
        "strategy_x_popularity_pair": generate_pair_sets(drw_no),
        "strategy_x_shape": generate_shape_sets(drw_no),
        "strategy_x_cooccur": generate_cooccur_sets(
            drw_no, state=wf["cooccur_state"].copy(), draw_count=wf["draw_count"]
        ),
        "strategy_x_coordinator": {
            "sets": [
                {"set_no": i + 1, "numbers": s}
                for i, s in enumerate(
                    _wf_coord(drw_no, wf["number_weights"], wf["pair_weights"], wf["shape_profile"])
                )
            ]
        },
    }


def _pop_sum(sets: list[list[int]], nw: dict[int, float]) -> float:
    if not sets:
        return 0.0
    return statistics.mean(
        round(sum(nw.get(int(n), 0.0) for n in s), 4) for s in sets
    )


def _hit_avg(sets: list[list[int]], actual: list[int]) -> float:
    if not sets:
        return 0.0
    return sum(len(set(s) & set(actual)) for s in sets) / len(sets)


def run() -> dict[str, Any]:
    draws = _load_draws()
    draw_by_no = {d["drw_no"]: d for d in draws}
    co_state = CooccurState()
    trust_hist: dict[str, list[float]] = {t: [] for t in SOURCE_TAGS}

    era_pops: dict[str, list[float]] = {e: [] for e in ERA_RANGES}
    era_hits: dict[str, list[float]] = {e: [] for e in ERA_RANGES}
    accum_early_pops: list[float] = []
    accum_late_pops: list[float] = []
    accum_early_hits: list[float] = []
    accum_late_hits: list[float] = []
    trunc_pops: list[float] = []
    full_pops_for_trunc_window: list[float] = []
    rnd_pops: list[float] = []
    rnd_hits: list[float] = []

    evaluated_by_era: dict[str, int] = {e: 0 for e in ERA_RANGES}
    skipped = 0

    for drw_no in range(1, 1229):
        if drw_no not in draw_by_no:
            continue
        train_full = [d for d in draws if d["drw_no"] < drw_no]
        if len(train_full) < MIN_TRAIN_DRAWS:
            skipped += 1
            co_state.add_draw(draw_by_no[drw_no]["nums"])
            continue

        era = draw_by_no[drw_no]["era"]
        top30 = _top30_rows(train_full)
        nw = _build_number_weights(top30)
        wf = {
            "number_weights": nw,
            "pair_weights": _build_pair_weights(top30),
            "shape_profile": _build_shape_profile(top30),
            "cooccur_state": co_state.copy(),
            "draw_count": len(train_full),
        }
        trust = {
            t: round(statistics.mean(trust_hist[t][-LOOKBACK:]), 4)
            if trust_hist[t]
            else 0.5
            for t in SOURCE_TAGS
        }
        outputs = _collect(drw_no, wf)
        hyena = generate_hyena_sets(
            drw_no,
            wf_context=wf,
            draws=draws,
            use_db_logs=False,
            brain_trust_override=trust,
            brain_outputs_override=outputs,
            weight_scheme=SCHEME,
        )
        hsets = [s["numbers"] for s in hyena.get("sets") or [] if s.get("numbers")]
        actual = draw_by_no[drw_no]["nums"]
        pop = _pop_sum(hsets, nw)
        hit = _hit_avg(hsets, actual)

        era_pops[era].append(pop)
        era_hits[era].append(hit)
        evaluated_by_era[era] += 1

        if ACCUM_EARLY[0] <= drw_no <= ACCUM_EARLY[1]:
            accum_early_pops.append(pop)
            accum_early_hits.append(hit)
        if ACCUM_LATE[0] <= drw_no <= ACCUM_LATE[1]:
            accum_late_pops.append(pop)
            accum_late_hits.append(hit)

        if drw_no >= 800:
            train_trunc = [d for d in train_full if d["drw_no"] <= TRUNC_CAP]
            if len(train_trunc) >= MIN_TRAIN_DRAWS:
                t30 = _top30_rows(train_trunc)
                nw_t = _build_number_weights(t30)
                trunc_pops.append(_pop_sum(hsets, nw_t))
                full_pops_for_trunc_window.append(pop)

        rnd = [
            sorted(random.Random(drw_no * 99991 + i * 37).sample(range(1, 46), 6))
            for i in range(1, NUM_SETS + 1)
        ]
        rnd_pops.append(_pop_sum(rnd, nw))
        rnd_hits.append(_hit_avg(rnd, actual))

        for tag, payload in outputs.items():
            for nums in [s["numbers"] for s in payload.get("sets") or [] if s.get("numbers")]:
                trust_hist[tag].append(round(sum(nw.get(int(n), 0.0) for n in nums), 4))

        co_state.add_draw(actual)

    era_table = []
    for e, (lo, hi) in ERA_RANGES.items():
        era_table.append(
            {
                "era": e,
                "range": f"{lo}~{hi}",
                "evaluated": evaluated_by_era[e],
                "popularity_sum": round(statistics.mean(era_pops[e]), 4)
                if era_pops[e]
                else None,
                "hit_avg": round(statistics.mean(era_hits[e]), 4)
                if era_hits[e]
                else None,
            }
        )

    early_pop = round(statistics.mean(accum_early_pops), 4) if accum_early_pops else None
    late_pop = round(statistics.mean(accum_late_pops), 4) if accum_late_pops else None
    accum_improves = (
        late_pop is not None
        and early_pop is not None
        and late_pop > early_pop
    )

    trunc_avg = round(statistics.mean(trunc_pops), 4) if trunc_pops else None
    full_win_avg = round(statistics.mean(full_pops_for_trunc_window), 4) if full_pops_for_trunc_window else None

    return {
        "scheme": SCHEME,
        "min_train": MIN_TRAIN_DRAWS,
        "skipped_pretrain": skipped,
        "era_table": era_table,
        "accumulation_effect": {
            "early_C_262_600": {
                "n": len(accum_early_pops),
                "popularity_sum": early_pop,
                "hit_avg": round(statistics.mean(accum_early_hits), 4)
                if accum_early_hits
                else None,
            },
            "late_C_601_1228": {
                "n": len(accum_late_pops),
                "popularity_sum": late_pop,
                "hit_avg": round(statistics.mean(accum_late_hits), 4)
                if accum_late_hits
                else None,
            },
            "delta_pop_late_minus_early": round(late_pop - early_pop, 4)
            if late_pop and early_pop
            else None,
            "data_accumulation_pop_boost": accum_improves,
        },
        "truncated_train_test_draw800plus": {
            "train_cap_draw": TRUNC_CAP,
            "eval_draws": len(trunc_pops),
            "pop_with_trunc_train_262_600": trunc_avg,
            "pop_with_full_train": full_win_avg,
            "delta_full_minus_trunc": round(full_win_avg - trunc_avg, 4)
            if trunc_avg and full_win_avg
            else None,
        },
        "random_baseline_all": {
            "popularity_sum": round(statistics.mean(rnd_pops), 4),
            "hit_avg": round(statistics.mean(rnd_hits), 4),
        },
        "r2_hit_honest": "모든 era 적중은 random 0.81 전후 무작위 수준 기대",
    }


def main() -> None:
    result = run()
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {OUT}")
    for row in result["era_table"]:
        print(row)


if __name__ == "__main__":
    main()
