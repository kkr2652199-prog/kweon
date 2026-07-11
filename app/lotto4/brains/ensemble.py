"""
v13_ensemble — Hyena Commander v2 (6단계)

에이스 2뇌(seq·struct) 후보만 사용 → 18번 컨센서스 풀 → 18C6 전수 스코어
→ gap·diversity·ev 리스코어(배치) + 구조·컨센서스 → 최종 5세트.
v13_cdm / v13_cond_prob 는 앙상블 경로에서 호출하지 않음.
"""

from __future__ import annotations

import time
from itertools import combinations
from typing import Any, NamedTuple

import numpy as np

from app.lotto4.brains import diversity_brain, ev_brain, evolution_brain, gap_brain, stat_generator
from app.lotto4.brains.ev_brain import birthday_factor
from app.lotto4.brains import seq_brain, struct_brain
from app.lotto4.brains._utils import count_consecutive, jaccard, load_draws_before


class ComboScorePack(NamedTuple):
    """18C6 조합별 min-max 정규화 특성 (FINAL_SCORE 가중합만 바꿔 재선택 가능)."""

    draw_no: int
    pool18: list[int]
    all_combos: list[list[int]]
    struct_hits: list[int]
    nc: list[float]
    ns: list[float]
    ng: list[float]
    nd: list[float]
    ne: list[float]
    meta: dict[str, Any]


TOP_K_POOL = 18
NUM_SETS = 5
TOP_CANDIDATES = 500
JACCARD_LIMIT = 0.4

W_CONSENSUS = 0.30
W_STRUCT = 0.30
W_GAP = 0.10
W_DIV = 0.20
W_EV = 0.10


def _normalize_sets(raw: Any) -> list[list[int]]:
    out: list[list[int]] = []
    seen: set[tuple[int, ...]] = set()
    for one in raw or []:
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
        out.append(list(st))
    return out


def _player_weights(dynamic_w: dict[str, float]) -> dict[str, float]:
    w_seq = float(dynamic_w.get("v13_seq", 0.25))
    w_struct = float(dynamic_w.get("v13_struct", 0.25))
    s = w_seq + w_struct
    if s <= 0:
        return {"v13_seq": 0.5, "v13_struct": 0.5}
    return {"v13_seq": w_seq / s, "v13_struct": w_struct / s}


def _counts_per_number(sets: list[list[int]]) -> list[int]:
    c = [0] * 46
    for s in sets:
        for n in s:
            if 1 <= n <= 45:
                c[n] += 1
    return c


def _struct_soft_hits(nums: list[int], y_hat: np.ndarray) -> int:
    actual = struct_brain.struct_vector(nums)
    ok = 0
    if abs(float(actual[0]) - float(y_hat[0])) <= float(struct_brain.TOLS[0]):
        ok += 1
    for i in range(1, 7):
        if abs(float(actual[i]) - float(y_hat[i])) <= float(struct_brain.TOLS[i]):
            ok += 1
    return ok


def _batch_ev_scores(draw_no: int, db_path: str, all_combos: list[list[int]]) -> list[float]:
    """ev_brain.ev_score_for_set 과 동일 수식·컷, draw 로드는 1회."""
    cut = min(int(draw_no), 1223)
    draws = load_draws_before(db_path, cut)
    last_n: set[int] = set()
    prev_n: set[int] = set()
    if draws:
        last_n = {int(x) for x in draws[-1]["nums"]}
    if len(draws) >= 3:
        for d in draws[-3:-1]:
            prev_n.update(int(x) for x in d["nums"])

    out: list[float] = []
    for raw in all_combos:
        st = sorted({int(x) for x in raw if 1 <= int(x) <= 45})
        if len(st) != 6:
            out.append(0.0)
            continue
        pop = 1.0
        for n in st:
            pop *= birthday_factor(n)
            if n % 7 == 0:
                pop *= 1.4
            if n in last_n:
                pop *= 1.5
            elif n in prev_n:
                pop *= 1.2
        c = count_consecutive(st)
        if c >= 3:
            pop *= 1.5
        elif c >= 2:
            pop *= 1.2
        odds = sum(1 for n in st if n % 2 == 1)
        if odds == 6 or odds == 0:
            pop *= 1.3
        pop = max(pop, 1e-9)
        out.append(1.0 / pop)
    return out


def _minmax_vec(vals: list[float]) -> list[float]:
    if not vals:
        return []
    lo, hi = min(vals), max(vals)
    if hi <= lo:
        return [0.5] * len(vals)
    return [(float(v) - lo) / (hi - lo) for v in vals]


def _greedy_pick(
    order_idx: list[int],
    all_combos: list[list[int]],
    struct_hits: list[int],
    final_sc: list[float],
    min_struct: int,
) -> list[tuple[list[int], float, int]]:
    picked: list[tuple[list[int], float, int]] = []
    picked_sets: list[list[int]] = []
    for i in order_idx:
        if struct_hits[i] < min_struct:
            continue
        c = all_combos[i]
        if any(jaccard(set(c), set(p)) >= JACCARD_LIMIT for p in picked_sets):
            continue
        picked_sets.append(c)
        picked.append((c, final_sc[i], struct_hits[i]))
        if len(picked) >= NUM_SETS:
            break
    return picked


def build_consensus_state(
    draw_no: int,
    db_path: str,
    *,
    weights_override: dict[str, float] | None = None,
) -> dict[str, Any]:
    """단위 테스트·진단용: 컨센서스 풀 18·가중치·에이스 세트."""
    _ = weights_override
    dynamic_full = evolution_brain.get_dynamic_weights(draw_no, db_path)
    pw = _player_weights(dynamic_full)
    seq_sets = _normalize_sets(seq_brain.predict(draw_no, db_path))
    struct_sets = _normalize_sets(struct_brain.predict(draw_no, db_path))
    chief_sets = list(seq_sets)
    seen_t = {tuple(s) for s in chief_sets}
    for s in struct_sets:
        t = tuple(s)
        if t not in seen_t:
            seen_t.add(t)
            chief_sets.append(s)

    c_seq = _counts_per_number(seq_sets)
    c_struct = _counts_per_number(struct_sets)
    consensus = [0.0] * 46
    for n in range(1, 46):
        consensus[n] = pw["v13_seq"] * c_seq[n] + pw["v13_struct"] * c_struct[n]

    ranked_n = sorted(range(1, 46), key=lambda x: (-consensus[x], x))
    pool18 = ranked_n[:TOP_K_POOL]
    return {
        "dynamic_weights_full": dynamic_full,
        "player_weights": pw,
        "chief_sets": chief_sets,
        "consensus_scores": consensus,
        "pool18": pool18,
    }


def precompute_combo_scores(
    draw_no: int,
    db_path: str,
    *,
    weights_override: dict[str, float] | None = None,
) -> ComboScorePack:
    """18C6·리스코어까지 1회 계산. 그리드 서치 시 가중치만 바꿔 `pick_with_final_weights` 호출."""
    _ = weights_override
    st = build_consensus_state(draw_no, db_path, weights_override=weights_override)
    pool18: list[int] = st["pool18"]
    chief_sets: list[list[int]] = st["chief_sets"]
    consensus: list[float] = st["consensus_scores"]

    y_hat = struct_brain.predict_struct_vector(draw_no, db_path, skip_update=True)
    all_combos = [list(map(int, c)) for c in combinations(pool18, 6)]
    n_c = len(all_combos)

    meta: dict[str, Any] = {
        "pool18": list(pool18),
        "dynamic_weights_full": dict(st["dynamic_weights_full"]),
        "player_weights": dict(st["player_weights"]),
        "chief_sets": chief_sets,
    }

    if n_c == 0:
        meta["combo_eval_sec"] = 0.0
        return ComboScorePack(
            int(draw_no),
            list(pool18),
            [],
            [],
            [],
            [],
            [],
            [],
            [],
            meta,
        )

    t_combo0 = time.perf_counter()
    consensus_raw: list[float] = []
    struct_frac: list[float] = []
    struct_hits: list[int] = []
    for c in all_combos:
        consensus_raw.append(sum(consensus[n] for n in c))
        h = _struct_soft_hits(c, y_hat)
        struct_hits.append(h)
        struct_frac.append(h / 7.0)

    z = gap_brain.compute_z_scores(draw_no, db_path)
    gap_raw = [gap_brain.gap_score_for_set(list(c), z) for c in all_combos]

    recent = diversity_brain.load_recent_submission_sets(db_path, draw_no)
    div_refs = chief_sets if chief_sets else all_combos[: min(40, n_c)]
    div_raw = [
        diversity_brain.diversity_score_for_set(list(c), div_refs, recent)
        for c in all_combos
    ]

    ev_raw = _batch_ev_scores(draw_no, db_path, all_combos)

    nc = _minmax_vec(consensus_raw)
    ns = _minmax_vec(struct_frac)
    ng = _minmax_vec(gap_raw)
    nd = _minmax_vec(div_raw)
    ne = _minmax_vec(ev_raw)

    meta["combo_eval_sec"] = time.perf_counter() - t_combo0
    return ComboScorePack(
        int(draw_no),
        list(pool18),
        all_combos,
        struct_hits,
        nc,
        ns,
        ng,
        nd,
        ne,
        meta,
    )


def pick_with_final_weights(
    pack: ComboScorePack,
    final_score_weights: tuple[float, float, float, float, float] | None = None,
) -> tuple[list[tuple[list[int], float, int]], dict[str, Any]]:
    """`precompute_combo_scores` 결과에 FINAL_SCORE 가중치만 적용해 5세트 선택."""
    wc, ws, wg, wd, we = (
        final_score_weights
        if final_score_weights is not None
        else (W_CONSENSUS, W_STRUCT, W_GAP, W_DIV, W_EV)
    )
    pool18 = pack.pool18
    all_combos = pack.all_combos
    struct_hits = pack.struct_hits
    n_c = len(all_combos)
    meta = dict(pack.meta)

    if n_c == 0:
        pad = sorted(pool18[:6]) if len(pool18) >= 6 else list(range(1, 7))
        return (
            [(list(pad), 0.0, 0) for _ in range(NUM_SETS)],
            meta,
        )

    nc, ns, ng, nd, ne = pack.nc, pack.ns, pack.ng, pack.nd, pack.ne
    final_sc: list[float] = []
    for i in range(n_c):
        final_sc.append(
            wc * nc[i] + ws * ns[i] + wg * ng[i] + wd * nd[i] + we * ne[i]
        )

    order_all = sorted(range(n_c), key=lambda i: (-final_sc[i], all_combos[i]))

    def try_pick(min_struct: int, pool_limit: int) -> list[tuple[list[int], float, int]]:
        pool_idx = order_all[:pool_limit]
        return _greedy_pick(pool_idx, all_combos, struct_hits, final_sc, min_struct)

    picked = try_pick(6, TOP_CANDIDATES)
    if len(picked) < NUM_SETS:
        picked = try_pick(5, TOP_CANDIDATES)
    if len(picked) < NUM_SETS:
        picked = try_pick(4, TOP_CANDIDATES)
    if len(picked) < NUM_SETS:
        picked = []
        chosen: set[tuple[int, ...]] = set()
        for i in order_all:
            c = all_combos[i]
            t = tuple(c)
            if t in chosen:
                continue
            if any(jaccard(set(c), set(p)) >= JACCARD_LIMIT for p in chosen):
                continue
            chosen.add(t)
            picked.append((c, final_sc[i], struct_hits[i]))
            if len(picked) >= NUM_SETS:
                break
        if len(picked) < NUM_SETS:
            for i in order_all:
                c = all_combos[i]
                t = tuple(c)
                if t in chosen:
                    continue
                chosen.add(t)
                picked.append((c, final_sc[i], struct_hits[i]))
                if len(picked) >= NUM_SETS:
                    break

    return picked, meta


def pick_with_final_weights_lexsort(
    pack: ComboScorePack,
    final_score_weights: tuple[float, float, float, float, float] | None = None,
) -> tuple[list[tuple[list[int], float, int]], dict[str, Any]]:
    """그리드 서치용: 정렬을 `lexsort`로 가속(동점 시 조합 인덱스 기준 — `predict`의 번호튜플 2차 정렬과 다를 수 있음)."""
    wc, ws, wg, wd, we = (
        final_score_weights
        if final_score_weights is not None
        else (W_CONSENSUS, W_STRUCT, W_GAP, W_DIV, W_EV)
    )
    pool18 = pack.pool18
    all_combos = pack.all_combos
    struct_hits = pack.struct_hits
    n_c = len(all_combos)
    meta = dict(pack.meta)

    if n_c == 0:
        pad = sorted(pool18[:6]) if len(pool18) >= 6 else list(range(1, 7))
        return (
            [(list(pad), 0.0, 0) for _ in range(NUM_SETS)],
            meta,
        )

    nc = np.asarray(pack.nc, dtype=np.float64)
    final_sc = (
        wc * nc
        + ws * np.asarray(pack.ns, dtype=np.float64)
        + wg * np.asarray(pack.ng, dtype=np.float64)
        + wd * np.asarray(pack.nd, dtype=np.float64)
        + we * np.asarray(pack.ne, dtype=np.float64)
    )
    order_all = np.lexsort(
        (np.arange(n_c, dtype=np.int64), -final_sc)
    ).tolist()
    final_sc_list = final_sc.tolist()

    def try_pick(min_struct: int, pool_limit: int) -> list[tuple[list[int], float, int]]:
        pool_idx = order_all[:pool_limit]
        return _greedy_pick(
            pool_idx, all_combos, struct_hits, final_sc_list, min_struct
        )

    picked = try_pick(6, TOP_CANDIDATES)
    if len(picked) < NUM_SETS:
        picked = try_pick(5, TOP_CANDIDATES)
    if len(picked) < NUM_SETS:
        picked = try_pick(4, TOP_CANDIDATES)
    if len(picked) < NUM_SETS:
        picked = []
        chosen: set[tuple[int, ...]] = set()
        for i in order_all:
            c = all_combos[i]
            t = tuple(c)
            if t in chosen:
                continue
            if any(jaccard(set(c), set(p)) >= JACCARD_LIMIT for p in chosen):
                continue
            chosen.add(t)
            picked.append((c, final_sc_list[i], struct_hits[i]))
            if len(picked) >= NUM_SETS:
                break
        if len(picked) < NUM_SETS:
            for i in order_all:
                c = all_combos[i]
                t = tuple(c)
                if t in chosen:
                    continue
                chosen.add(t)
                picked.append((c, final_sc_list[i], struct_hits[i]))
                if len(picked) >= NUM_SETS:
                    break

    return picked, meta


def _eval_and_pick(
    draw_no: int,
    db_path: str,
    *,
    weights_override: dict[str, float] | None = None,
    final_score_weights: tuple[float, float, float, float, float] | None = None,
) -> tuple[list[tuple[list[int], float, int]], dict[str, Any]]:
    """18C6 전수 평가 후 선택. 반환: (picked_triples (set, final, struct_hits), 진단 dict)."""
    pack = precompute_combo_scores(
        draw_no, db_path, weights_override=weights_override
    )
    return pick_with_final_weights(pack, final_score_weights)


def _legacy_predict(
    draw_no: int,
    db_path: str,
    weights_override: dict[str, float] | None = None,
    *,
    final_score_weights: tuple[float, float, float, float, float] | None = None,
) -> list[list[int]]:
    """Hyena Commander v2 — 에이스 직접생성 + 18C6 (B안 이전)."""
    picked, meta = _eval_and_pick(
        draw_no,
        db_path,
        weights_override=weights_override,
        final_score_weights=final_score_weights,
    )
    pool18: list[int] = meta["pool18"]
    out = [p[0] for p in picked[:NUM_SETS]]
    while len(out) < NUM_SETS:
        out.append(sorted(pool18[:6]))
    return out[:NUM_SETS]


def _filter_weights(draw_no: int, db_path: str) -> tuple[float, float, float, float, float]:
    """evolution 동적 가중치 → 5뇌 필터 가중치 (합=1)."""
    dyn = evolution_brain.get_dynamic_weights(draw_no, db_path)
    w = (
        float(dyn.get("v13_seq", 0.25)),
        float(dyn.get("v13_struct", 0.25)),
        float(dyn.get("v13_ev", 0.20)),
        float(dyn.get("v13_gap", 0.15)),
        float(dyn.get("v13_diversity", 0.15)),
    )
    s = sum(w)
    if s <= 0:
        return (0.25, 0.25, 0.20, 0.15, 0.15)
    return tuple(x / s for x in w)  # type: ignore[return-value]


def _pick_diverse_top(
    ranked: list[tuple[list[int], float]],
    limit: int,
    jaccard_thresh: float,
) -> list[list[int]]:
    selected: list[list[int]] = []
    for combo, _sc in ranked:
        if len(selected) >= limit:
            break
        st = set(combo)
        if any(jaccard(st, set(s)) > jaccard_thresh for s in selected):
            continue
        selected.append(combo)
    return selected


def _legacy_B_predict(
    draw_no: int,
    db_path: str,
    weights_override: dict[str, float] | None = None,
    *,
    final_score_weights: tuple[float, float, float, float, float] | None = None,
) -> list[list[int]]:
    """B안 Commander: stat_generator 200후보 → 5뇌 ML필터 → top20 → Jaccard → 5세트."""
    _ = weights_override, final_score_weights
    candidates = stat_generator.generate_candidates(draw_no, db_path, 200)
    if not candidates:
        return _legacy_predict(draw_no, db_path)

    w_seq, w_struct, w_ev, w_gap, w_div = _filter_weights(draw_no, db_path)
    seq_scores = seq_brain.score_batch(candidates, draw_no, db_path)
    struct_scores = struct_brain.score_batch(candidates, draw_no, db_path)
    ev_scores = ev_brain.score_batch(candidates, draw_no, db_path)
    gap_scores = gap_brain.score_batch(candidates, draw_no, db_path)
    div_scores = diversity_brain.score_batch(candidates, draw_no, db_path)

    scored: list[tuple[list[int], float]] = []
    for i, combo in enumerate(candidates):
        nums = sorted(combo)
        fs = (
            w_seq * seq_scores[i]
            + w_struct * struct_scores[i]
            + w_ev * ev_scores[i]
            + w_gap * gap_scores[i]
            + w_div * div_scores[i]
        )
        scored.append((nums, fs))
    scored.sort(key=lambda x: (-x[1], x[0]))

    top20 = scored[:20]
    selected = _pick_diverse_top(top20, NUM_SETS, JACCARD_LIMIT)
    if len(selected) < NUM_SETS:
        extra = _pick_diverse_top(top20, NUM_SETS, 0.5)
        for combo in extra:
            if combo not in selected:
                selected.append(combo)
            if len(selected) >= NUM_SETS:
                break

    for combo, _ in top20:
        if len(selected) >= NUM_SETS:
            break
        if combo not in selected:
            selected.append(combo)

    while len(selected) < NUM_SETS:
        selected.append(sorted(range(1, 7)))
    return selected[:NUM_SETS]


def predict(
    draw_no: int,
    db_path: str,
    weights_override: dict[str, float] | None = None,
    *,
    final_score_weights: tuple[float, float, float, float, float] | None = None,
) -> list[list[int]]:
    """Phase 1 Commander: stat_generator → hyena 15C6 → 5세트."""
    from app.lotto4.brains import hyena_commander

    _ = weights_override, final_score_weights
    out = hyena_commander.predict(draw_no, db_path, NUM_SETS)
    if not out:
        return _legacy_B_predict(draw_no, db_path)
    while len(out) < NUM_SETS:
        out.append(sorted(range(1, 7)))
    return out[:NUM_SETS]


def predict_debug(
    draw_no: int,
    db_path: str,
    weights_override: dict[str, float] | None = None,
    *,
    final_score_weights: tuple[float, float, float, float, float] | None = None,
) -> dict[str, Any]:
    """단위 테스트용: 5세트 + FINAL_SCORE + 구조 적중 수."""
    picked, meta = _eval_and_pick(
        draw_no,
        db_path,
        weights_override=weights_override,
        final_score_weights=final_score_weights,
    )
    pool18: list[int] = meta["pool18"]
    details: list[dict[str, Any]] = []
    for s, fs, sh in picked[:NUM_SETS]:
        details.append({"nums": s, "final_score": fs, "struct_hits": sh})
    while len(details) < NUM_SETS:
        details.append(
            {
                "nums": sorted(pool18[:6]),
                "final_score": 0.0,
                "struct_hits": 0,
            }
        )
    return {
        "pool18": pool18,
        "dynamic_weights_full": meta["dynamic_weights_full"],
        "player_weights": meta["player_weights"],
        "combo_eval_sec": float(meta.get("combo_eval_sec") or 0.0),
        "sets": details,
    }


def benchmark_18c6_seconds(draw_no: int, db_path: str) -> float:
    """18C6 + 리스코어 블록만 시간 측정 (predict와 동일 부하)."""
    t0 = time.perf_counter()
    st = build_consensus_state(draw_no, db_path)
    pool18 = st["pool18"]
    chief_sets = st["chief_sets"]
    consensus = st["consensus_scores"]
    y_hat = struct_brain.predict_struct_vector(draw_no, db_path, skip_update=True)
    all_combos = [list(c) for c in combinations(pool18, 6)]
    z = gap_brain.compute_z_scores(draw_no, db_path)
    recent = diversity_brain.load_recent_submission_sets(db_path, draw_no)
    div_refs = chief_sets if chief_sets else all_combos[:40]
    for c in all_combos:
        _ = sum(consensus[n] for n in c)
        _struct_soft_hits(c, y_hat)
        gap_brain.gap_score_for_set(list(c), z)
        diversity_brain.diversity_score_for_set(list(c), div_refs, recent)
    _batch_ev_scores(draw_no, db_path, all_combos)
    return time.perf_counter() - t0
