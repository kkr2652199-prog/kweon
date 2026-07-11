"""v13_evolution — 선수 4뇌 동적 신뢰도 / 진화 메타 뇌 (5단계-B)."""

from __future__ import annotations

import importlib
import math
import random
import sqlite3
from collections import defaultdict
from typing import Any

import numpy as np

from app.lotto4.brains import struct_brain
from app.lotto4.brains._utils import (
    jaccard,
    load_draws_before,
    smart_filter_relaxed,
    sum_filter,
    odd_even_filter,
    _weighted_draw_without_replacement,
)

# 메타 진화·로그는 풀백에 포함되는 필터 5뇌 (HIDDEN cdm/cond_prob 제외).
CHIEF_TAGS: tuple[str, ...] = (
    "v13_seq",
    "v13_struct",
    "v13_ev",
    "v13_gap",
    "v13_diversity",
)
QUARANTINED_BRAINS: tuple[str, ...] = ("v13_seq",)
CHIEF_MODULES: dict[str, str] = {
    "v13_seq": "app.lotto4.brains.seq_brain",
    "v13_struct": "app.lotto4.brains.struct_brain",
    "v13_ev": "app.lotto4.brains.ev_brain",
    "v13_gap": "app.lotto4.brains.gap_brain",
    "v13_diversity": "app.lotto4.brains.diversity_brain",
}

_LAST_CUT = 1223
LOOKBACK = 20
SIM_QUANTILE = 0.35
NUM_SETS = 5
JACCARD_LIMIT = 0.5
SUM_RANGE = (100, 175)


def _history_cut(draw_no: int) -> int:
    return min(int(draw_no), _LAST_CUT)


def _nums(draw: dict[str, Any]) -> list[int]:
    return [int(x) for x in draw["nums"]]


def context_ma5_before(target_draw: int, db_path: str) -> np.ndarray:
    """예측 대상 target_draw 직전까지 5회 당첨의 구조 평균 (sum,odd,high,ac)."""
    draws = load_draws_before(db_path, _history_cut(target_draw))
    if len(draws) < 5:
        return np.array([100.0, 3.0, 3.0, 7.0], dtype=np.float64)
    mats = []
    for d in draws[-5:]:
        v = struct_brain.struct_vector(_nums(d))
        mats.append(v[:4])
    return np.mean(np.stack(mats, axis=0), axis=0)


def _chief_matched_rows(conn: sqlite3.Connection, tag: str, tgt: int) -> list[tuple[Any, ...]]:
    """풀 백테스트 행 우선, 없으면 lotto_predictions_army4."""
    fb = conn.execute(
        """
        SELECT matched_count FROM lotto_fullbacktest_army4
        WHERE brain_tag = ? AND draw_no = ? AND matched_count >= 0
        """,
        (tag, int(tgt)),
    ).fetchall()
    if fb:
        return fb
    return conn.execute(
        """
        SELECT matched_count FROM lotto_predictions_army4
        WHERE brain_tag = ? AND target_draw_no = ? AND matched_count >= 0
        """,
        (tag, int(tgt)),
    ).fetchall()


def _avg_matched_for_draw(conn: sqlite3.Connection, tag: str, tgt: int) -> float | None:
    rows = _chief_matched_rows(conn, tag, tgt)
    if not rows:
        return None
    vals = [float(r[0]) for r in rows]
    return sum(vals) / len(vals)


def get_dynamic_weights(draw_no: int, db_path: str) -> dict[str, float]:
    """선수 4뇌 신뢰도, 합=1, 각 [0.1,0.5] 클립 후 재정규화."""
    d_no = int(draw_no)
    current_ctx = context_ma5_before(d_no, db_path)

    conn: sqlite3.Connection | None = None
    history: dict[str, list[tuple[int, float]]] = {t: [] for t in CHIEF_TAGS}
    contexts: dict[int, np.ndarray] = {}
    try:
        conn = sqlite3.connect(db_path)
        for delta in range(1, LOOKBACK + 1):
            tgt = d_no - delta
            if tgt < 1:
                continue
            ctx = context_ma5_before(tgt, db_path)
            contexts[tgt] = ctx
            for tag in CHIEF_TAGS:
                m = _avg_matched_for_draw(conn, tag, tgt)
                if m is not None:
                    history[tag].append((tgt, m))
    except (OSError, sqlite3.Error):
        pass
    finally:
        if conn is not None:
            conn.close()

    trust_raw: dict[str, float] = {}
    for tag in CHIEF_TAGS:
        pairs = history[tag]
        if len(pairs) < 3:
            trust_raw[tag] = 0.2
            continue
        mc_vals = [p[1] / 6.0 for p in pairs]
        base_trust = float(sum(mc_vals) / len(mc_vals))

        ctx_stack = np.stack([contexts[p[0]] for p in pairs], axis=0)
        sig = np.std(ctx_stack, axis=0) + 1e-6
        cur_n = (current_ctx - np.mean(ctx_stack, axis=0)) / sig
        mat_n = (ctx_stack - np.mean(ctx_stack, axis=0)) / sig
        dists = np.linalg.norm(mat_n - cur_n.reshape(1, -1), axis=1)
        thresh = float(np.quantile(dists, SIM_QUANTILE)) if len(dists) > 2 else 1.0
        sim_m = [pairs[i][1] / 6.0 for i in range(len(pairs)) if dists[i] <= max(thresh, 0.01)]
        if len(sim_m) >= 3:
            situation_trust = float(sum(sim_m) / len(sim_m))
        else:
            situation_trust = base_trust

        recent5 = [p[1] / 6.0 for p in pairs[:5]]
        older = mc_vals
        m5 = float(sum(recent5) / len(recent5)) if recent5 else base_trust
        m20 = float(sum(older) / len(older)) if older else base_trust
        trend_bonus = 0.0
        if m5 > m20 + 0.05:
            trend_bonus = 0.1
        elif m5 < m20 - 0.05:
            trend_bonus = -0.1

        t = 0.5 * base_trust + 0.3 * situation_trust + 0.2 * (base_trust + trend_bonus)
        trust_raw[tag] = max(0.01, min(1.0, t))

    s = sum(trust_raw.values())
    if s <= 0:
        out = {t: 0.2 for t in CHIEF_TAGS}
    else:
        out = {t: trust_raw[t] / s for t in CHIEF_TAGS}

    lo, hi = 0.1, 0.5
    clipped = {t: min(hi, max(lo, out[t])) for t in CHIEF_TAGS}
    sc = sum(clipped.values())
    if sc <= 0:
        weights = {t: 0.2 for t in CHIEF_TAGS}
    else:
        weights = {t: clipped[t] / sc for t in CHIEF_TAGS}

    for brain_tag in QUARANTINED_BRAINS:
        if brain_tag in weights:
            weights[brain_tag] = 0.0
            print(f"[EVOLUTION] {brain_tag} quarantine weight=0")

    total = sum(w for tag, w in weights.items() if tag not in QUARANTINED_BRAINS)
    if total > 0:
        for tag in weights:
            if tag not in QUARANTINED_BRAINS:
                weights[tag] = weights[tag] / total
    return weights


def rescore(
    candidate_sets: list[list[int]],
    draw_no: int,
    db_path: str,
) -> list[tuple[list[int], float]]:
    w = get_dynamic_weights(draw_no, db_path)
    chief_preds: dict[str, list[list[int]]] = {}
    for tag, mod_path in CHIEF_MODULES.items():
        try:
            mod = importlib.import_module(mod_path)
            fn = getattr(mod, "predict", None)
            if not callable(fn):
                chief_preds[tag] = []
                continue
            raw = fn(draw_no, db_path)
            chief_preds[tag] = raw if isinstance(raw, list) else []
        except Exception:
            chief_preds[tag] = []

    num_w: dict[int, float] = {}
    for tag, preds in chief_preds.items():
        wt = float(w.get(tag, 0.25))
        for p in preds or []:
            if not isinstance(p, list):
                continue
            for n in p:
                try:
                    ni = int(n)
                except (TypeError, ValueError):
                    continue
                if 1 <= ni <= 45:
                    num_w[ni] = max(num_w.get(ni, 0.0), wt)

    out: list[tuple[list[int], float]] = []
    for raw in candidate_sets:
        st = sorted({int(x) for x in raw if 1 <= int(x) <= 45})
        if len(st) != 6:
            continue
        overlap = 0.0
        for n in st:
            overlap += num_w.get(n, 0.0)
        bonus = 0.0
        for tag, preds in chief_preds.items():
            wt = float(w.get(tag, 0.25))
            for p in preds or []:
                if isinstance(p, list) and len(set(p) & set(st)) >= 4:
                    bonus += wt * 0.15
        evo = overlap + bonus
        out.append((list(st), evo))
    out.sort(key=lambda x: -x[1])
    return out


def predict(draw_no: int, db_path: str) -> list[list[int]]:
    w = get_dynamic_weights(draw_no, db_path)
    best_tag = max(CHIEF_TAGS, key=lambda t: w.get(t, 0.25))
    mod_path = CHIEF_MODULES[best_tag]
    mod = importlib.import_module(mod_path)
    fn = getattr(mod, "predict", None)
    base_sets: list[list[int]] = []
    if callable(fn):
        try:
            raw = fn(draw_no, db_path)
            base_sets = raw if isinstance(raw, list) else []
        except Exception:
            base_sets = []

    freq: defaultdict[int, float] = defaultdict(float)
    for p in base_sets:
        if isinstance(p, list):
            for n in p:
                if 1 <= int(n) <= 45:
                    freq[int(n)] += 1.0

    if not freq:
        for n in range(1, 46):
            freq[n] = 1.0
    wmap = {n: max(0.05, math.sqrt(freq[n]) * w[best_tag]) for n in range(1, 46)}
    for t in CHIEF_TAGS:
        if t == best_tag:
            continue
        wt = w.get(t, 0.25) * 0.35
        for n in range(1, 46):
            wmap[n] += wt * 0.02

    rng = random.Random(draw_no * 499_993 + 67)
    sets: list[list[int]] = []
    for _ in range(5000):
        if len(sets) >= NUM_SETS:
            break
        cand = _weighted_draw_without_replacement(rng, wmap, 6)
        if len(cand) != 6:
            continue
        cand = sorted(cand)
        if not sum_filter(cand, SUM_RANGE[0], SUM_RANGE[1]):
            continue
        if not odd_even_filter(cand):
            continue
        if not smart_filter_relaxed(cand):
            continue
        st = set(cand)
        if any(jaccard(st, set(p)) >= JACCARD_LIMIT for p in sets):
            continue
        sets.append(cand)
    while len(sets) < NUM_SETS:
        sets.append(sorted(rng.sample(range(1, 46), 6)))
    return sets[:NUM_SETS]


def update_trust(completed_draw_no: int, db_path: str) -> None:
    """채점 완료 회차 completed_draw_no 기준 로그 저장."""
    nxt = int(completed_draw_no) + 1
    tw = get_dynamic_weights(nxt, db_path)
    ctx = context_ma5_before(int(completed_draw_no), db_path)
    cx_sum, cx_odd, cx_high, cx_ac = float(ctx[0]), float(ctx[1]), float(ctx[2]), float(ctx[3])

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(db_path, timeout=300.0)
        conn.execute("PRAGMA busy_timeout = 300000")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lotto_evolution_trust_army4 (
                brain_tag TEXT NOT NULL,
                draw_no INTEGER NOT NULL,
                matched_count INTEGER DEFAULT 0,
                trust_score REAL DEFAULT 0.25,
                context_sum REAL,
                context_odd REAL,
                context_high REAL,
                context_ac REAL,
                created_at TEXT DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (brain_tag, draw_no)
            )
            """
        )
        for tag in CHIEF_TAGS:
            rows = _chief_matched_rows(conn, tag, int(completed_draw_no))
            mc = int(round(sum(float(r[0]) for r in rows) / len(rows))) if rows else 0
            conn.execute(
                """
                INSERT OR REPLACE INTO lotto_evolution_trust_army4
                (brain_tag, draw_no, matched_count, trust_score,
                 context_sum, context_odd, context_high, context_ac)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (tag, int(completed_draw_no), mc, float(tw.get(tag, 0.25)), cx_sum, cx_odd, cx_high, cx_ac),
            )
        conn.commit()
    finally:
        if conn is not None:
            conn.close()
