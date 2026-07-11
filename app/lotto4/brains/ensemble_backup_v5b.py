"""
v13_ensemble — 메타 뇌 (Weighted Voting + Confidence Gating)

8개 하위 뇌: 선수 4는 evolution 동적 가중치, 나머지는 DB 가중치.
선수 4 세트 리스코어(gap·diversity·ev·evolution) 후 상위 15 폴백.
"""

from __future__ import annotations

import importlib
import random
import sqlite3

from app.lotto4.brains import diversity_brain, ev_brain, evolution_brain, gap_brain
from app.lotto4.brains._utils import (
    generate_sets_with_filters,
    jaccard,
    smart_filter_relaxed,
)

# ensemble이 종합할 하위 뇌 (자기 자신 제외)
SUB_BRAINS: tuple[str, ...] = (
    "app.lotto4.brains.struct_brain",
    "app.lotto4.brains.cdm_brain",
    "app.lotto4.brains.seq_brain",
    "app.lotto4.brains.cond_prob_brain",
    "app.lotto4.brains.diversity_brain",
    "app.lotto4.brains.evolution_brain",
    "app.lotto4.brains.gap_brain",
    "app.lotto4.brains.ev_brain",
)

TAG_MAP: dict[str, str] = {
    "app.lotto4.brains.struct_brain": "v13_struct",
    "app.lotto4.brains.cdm_brain": "v13_cdm",
    "app.lotto4.brains.seq_brain": "v13_seq",
    "app.lotto4.brains.cond_prob_brain": "v13_cond_prob",
    "app.lotto4.brains.diversity_brain": "v13_diversity",
    "app.lotto4.brains.evolution_brain": "v13_evolution",
    "app.lotto4.brains.gap_brain": "v13_gap",
    "app.lotto4.brains.ev_brain": "v13_ev",
}

CHIEF_MODULES: frozenset[str] = frozenset(
    {
        "app.lotto4.brains.struct_brain",
        "app.lotto4.brains.cdm_brain",
        "app.lotto4.brains.seq_brain",
        "app.lotto4.brains.cond_prob_brain",
    }
)

CANDIDATE_POOL_SIZE = 15
NUM_SETS = 5
MIN_WEIGHT = 0.1
SUM_RANGE = (100, 175)
JACCARD_LIMIT = 0.5
MAX_RETRY = 200

RESCORE_W_GAP = 0.2
RESCORE_W_DIV = 0.2
RESCORE_W_EV = 0.3
RESCORE_W_EVO = 0.3


def _load_weights(db_path: str) -> dict[str, float]:
    """각 v13_* 뇌의 current_weight. 없으면 1.0, 하한 MIN_WEIGHT."""
    weights: dict[str, float] = {}
    try:
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                """
                SELECT brain_tag, current_weight FROM lotto_brain_weights_army4
                WHERE brain_tag LIKE 'v13_%'
                """
            ).fetchall()
        finally:
            conn.close()
        for tag, w in rows:
            if tag:
                weights[str(tag)] = max(float(w or 0), MIN_WEIGHT)
    except (OSError, sqlite3.Error, TypeError, ValueError):
        pass
    return weights


def _collect_sub_predictions(draw_no: int, db_path: str) -> list[tuple[str, list[list[int]]]]:
    out: list[tuple[str, list[list[int]]]] = []
    for mod_path in SUB_BRAINS:
        try:
            mod = importlib.import_module(mod_path)
            fn = getattr(mod, "predict", None)
            if not callable(fn):
                out.append((mod_path, []))
                continue
            raw = fn(draw_no, db_path)
            sets = raw if isinstance(raw, list) else []
        except Exception:
            sets = []
        out.append((mod_path, sets))
    return out


def _collect_chief_candidate_sets(
    sub_preds: list[tuple[str, list[list[int]]]], max_sets: int = 20
) -> list[list[int]]:
    chief_sets: list[list[int]] = []
    seen: set[tuple[int, ...]] = set()
    for mod_path, sets in sub_preds:
        if mod_path not in CHIEF_MODULES:
            continue
        for one in sets or []:
            if not isinstance(one, list) or len(one) != 6:
                continue
            try:
                st = sorted(int(x) for x in one)
            except (TypeError, ValueError):
                continue
            if len(st) != 6 or len(set(st)) != 6 or not all(1 <= x <= 45 for x in st):
                continue
            t = tuple(st)
            if t in seen:
                continue
            seen.add(t)
            chief_sets.append(list(st))
            if len(chief_sets) >= max_sets:
                return chief_sets
    return chief_sets


def predict(
    draw_no: int,
    db_path: str,
    weights_override: dict[str, float] | None = None,
) -> list[list[int]]:
    """동적 선수 가중(evolution) 투표 → 4종 리스코어 → 폴백."""
    weights_db = weights_override if weights_override is not None else _load_weights(db_path)
    dynamic_w = evolution_brain.get_dynamic_weights(draw_no, db_path)
    sub_preds = _collect_sub_predictions(draw_no, db_path)

    vote_score = [0.0] * 46
    for mod_path, sets in sub_preds:
        tag = TAG_MAP.get(mod_path, "")
        if mod_path in CHIEF_MODULES:
            w = float(dynamic_w.get(tag, 0.25))
        else:
            w = float(weights_db.get(tag, 1.0))
            w = max(w, MIN_WEIGHT)
        for one_set in sets or []:
            if not isinstance(one_set, list):
                continue
            for num in one_set:
                try:
                    n = int(num)
                except (TypeError, ValueError):
                    continue
                if 1 <= n <= 45:
                    vote_score[n] += w

    chief_sets = _collect_chief_candidate_sets(sub_preds, max_sets=20)

    if chief_sets:
        g_map = {tuple(sorted(a)): float(sc) for a, sc in gap_brain.rescore(chief_sets, draw_no, db_path)}
        d_map = {tuple(sorted(a)): float(sc) for a, sc in diversity_brain.rescore(chief_sets, draw_no, db_path)}
        e_map = {tuple(sorted(a)): float(sc) for a, sc in ev_brain.rescore(chief_sets, draw_no, db_path)}
        o_map = {tuple(sorted(a)): float(sc) for a, sc in evolution_brain.rescore(chief_sets, draw_no, db_path)}

        ranked: list[tuple[float, list[int]]] = []
        for s in chief_sets:
            t = tuple(s)
            cons = sum(vote_score[n] for n in s)
            fg = g_map.get(t, 0.0)
            fd = d_map.get(t, 0.0)
            fe = e_map.get(t, 0.0)
            fo = o_map.get(t, 0.0)
            final = (
                cons
                + RESCORE_W_GAP * fg
                + RESCORE_W_DIV * fd
                + RESCORE_W_EV * fe
                + RESCORE_W_EVO * fo
            )
            ranked.append((final, s))
        ranked.sort(key=lambda x: -x[0])

        picked: list[list[int]] = []
        for _, s in ranked:
            if not smart_filter_relaxed(s):
                continue
            if any(jaccard(set(s), set(p)) >= JACCARD_LIMIT for p in picked):
                continue
            picked.append(list(s))
            if len(picked) >= NUM_SETS:
                return picked[:NUM_SETS]

    pairs = [(vote_score[i], i) for i in range(1, 46)]
    pairs.sort(key=lambda x: (-x[0], x[1]))
    candidate_list = [num for _, num in pairs[:CANDIDATE_POOL_SIZE]]

    total = sum(vote_score[n] for n in candidate_list)
    if total <= 0:
        score_dict = {int(n): 1.0 for n in candidate_list}
    else:
        score_dict = {int(n): float(vote_score[n]) / total for n in candidate_list}

    rng_seed = draw_no * 404_321 + 91_817
    return generate_sets_with_filters(
        score_dict,
        n_sets=NUM_SETS,
        n_pick=6,
        sum_range=SUM_RANGE,
        jaccard_limit=JACCARD_LIMIT,
        max_retry=MAX_RETRY,
        rng=random.Random(rng_seed),
        smart_filter_mode="relaxed",
    )[:NUM_SETS]
