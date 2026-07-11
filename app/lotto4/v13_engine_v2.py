"""4군 v13 엔진 v2 — lotto4.brains 9뇌 직접 호출, army4 저장."""

from __future__ import annotations

import importlib
import logging
import random
from typing import Any

from app.lotto4.brains.ev_brain import predict as ev_predict  # noqa: F401
from app.lotto4.brains.evolution_brain import predict as evolution_predict  # noqa: F401
from app.lotto4.models import LOTTO_DB_PATH, get_lotto4_db
from app.lotto4._llm_isolation import assert_army1_predict_llm_not_loaded
from app.lotto4.v13_weights_v2 import (
    SETS_PER_BRAIN_V2,
    V13_BRAIN_METHOD,
    V13_V2_BRAIN_ORDER,
    V13_V2_HIDDEN_BRAINS,
    V13_V2_TOTAL_ROWS,
    init_v13_v2_seeds,
    update_v13_v2_weights,
)

logger = logging.getLogger(__name__)

QUARANTINED_BRAINS: frozenset[str] = frozenset({"v13_seq"})


def _quarantine_placeholder_sets(draw_no: int, brain_tag: str) -> list[list[int]]:
    """격리 뇌용 5세트 — 회차·뇌별 결정적 더미(서로 다름). 앙상블·합의 제외."""
    return _ensure_five_sets([], draw_no, f"{brain_tag}__quarantine")

BRAIN_REGISTRY: dict[str, str] = {
    "v13_struct": "app.lotto4.brains.struct_brain",
    "v13_cdm": "app.lotto4.brains.cdm_brain",
    "v13_seq": "app.lotto4.brains.seq_brain",
    "v13_cond_prob": "app.lotto4.brains.cond_prob_brain",
    "v13_gap": "app.lotto4.brains.gap_brain",
    "v13_diversity": "app.lotto4.brains.diversity_brain",
    "v13_evolution": "app.lotto4.brains.evolution_brain",
    "v13_ev": "app.lotto4.brains.ev_brain",
    "v13_ensemble": "app.lotto4.brains.ensemble",
}


def _load_predict(module_path: str):
    mod = importlib.import_module(module_path)
    fn = getattr(mod, "predict", None)
    if fn is None or not callable(fn):
        raise RuntimeError(f"{module_path} has no callable predict()")
    return fn


def _ensure_five_sets(raw: list[list[int]], draw_no: int, brain_tag: str) -> list[list[int]]:
    out: list[list[int]] = []
    seen: set[tuple[int, ...]] = set()
    for s in raw or []:
        if len(s) != 6 or len(set(s)) != 6:
            continue
        if not all(1 <= int(x) <= 45 for x in s):
            continue
        t = tuple(sorted(int(x) for x in s))
        if t in seen:
            continue
        seen.add(t)
        out.append(list(t))
    h = (draw_no * 1_000_003 + sum(ord(c) for c in brain_tag)) % (2**31)
    rng = random.Random(h)
    while len(out) < SETS_PER_BRAIN_V2:
        cand = sorted(rng.sample(range(1, 46), 6))
        t = tuple(cand)
        if t in seen:
            continue
        seen.add(t)
        out.append(cand)
    return out[:SETS_PER_BRAIN_V2]


def _score_predictions(target_draw_no: int) -> None:
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
            WHERE target_draw_no = ? AND brain_tag LIKE 'v13_%'
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


def _is_cached(conn: Any, target_draw_no: int) -> bool:
    row = conn.execute(
        """
        SELECT COUNT(*) AS c FROM lotto_predictions_army4
        WHERE target_draw_no = ? AND brain_tag LIKE 'v13_%'
        """,
        (target_draw_no,),
    ).fetchone()
    return int(row["c"] or 0) >= V13_V2_TOTAL_ROWS


def run_prediction_v13(target_draw_no: int) -> dict[str, Any]:
    init_v13_v2_seeds()
    db_path = str(LOTTO_DB_PATH)
    conn = get_lotto4_db()
    try:
        cached = _is_cached(conn, target_draw_no)
        if cached:
            pass
        else:
            ntrain = conn.execute(
                "SELECT COUNT(*) FROM lotto_draws WHERE draw_no < ?",
                (target_draw_no,),
            ).fetchone()[0]
    finally:
        conn.close()

    if cached:
        _score_predictions(target_draw_no)
        return {
            "status": "cached",
            "target_draw_no": target_draw_no,
            "v13_sets": V13_V2_TOTAL_ROWS,
            "all_predictions": [],
            "engine": "v2_brains",
        }

    if int(ntrain or 0) < 5:
        return {
            "status": "error",
            "reason": "insufficient_training_data",
            "n": int(ntrain or 0),
            "target_draw_no": target_draw_no,
            "engine": "v2_brains",
        }

    normalized: list[dict[str, Any]] = []
    for tag, mod_path in BRAIN_REGISTRY.items():
        if tag in V13_V2_HIDDEN_BRAINS:
            continue
        predict_fn = _load_predict(mod_path)
        try:
            raw = predict_fn(target_draw_no, db_path)
        except Exception as e:  # noqa: BLE001
            logger.warning("brain %s predict failed: %s", tag, e)
            raw = []
        if tag in QUARANTINED_BRAINS and not raw:
            sets = _quarantine_placeholder_sets(target_draw_no, tag)
            quarantine = True
        else:
            sets = _ensure_five_sets(raw if isinstance(raw, list) else [], target_draw_no, tag)
            quarantine = False
        method = V13_BRAIN_METHOD.get(tag, tag)
        for i, nums in enumerate(sets):
            normalized.append(
                {
                    "nums": nums,
                    "method": method,
                    "brain_tag": tag,
                    "confidence": round(0.5 + 0.01 * i, 4),
                    "reasoning": f"{method} 세트{i + 1}" + (" (격리·무효)" if quarantine else ""),
                    "quarantine": quarantine,
                }
            )

    if len(normalized) != V13_V2_TOTAL_ROWS:
        return {
            "status": "error",
            "reason": "incomplete_generation",
            "got": len(normalized),
            "target_draw_no": target_draw_no,
            "engine": "v2_brains",
        }

    conn = get_lotto4_db()
    try:
        conn.execute(
            "DELETE FROM lotto_predictions_army4 WHERE target_draw_no = ? AND brain_tag LIKE 'v13_%'",
            (target_draw_no,),
        )
        for r in normalized:
            nums = r["nums"]
            conn.execute(
                """
                INSERT INTO lotto_predictions_army4
                (target_draw_no, method, num1, num2, num3, num4, num5, num6,
                 confidence, reasoning, brain_tag, matched_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    -1,
                ),
            )
        conn.commit()
        _score_predictions(target_draw_no)
        update_v13_v2_weights(target_draw_no)
    finally:
        conn.close()

    assert_army1_predict_llm_not_loaded(f"run_prediction_v13({target_draw_no})")

    all_predictions = [
        {
            "nums": r["nums"],
            "method": r.get("method"),
            "brain_tag": r.get("brain_tag"),
            "confidence": r.get("confidence"),
            "reasoning": r.get("reasoning"),
        }
        for r in normalized
    ]
    return {
        "status": "ok",
        "target_draw_no": target_draw_no,
        "v13_sets": len(normalized),
        "all_predictions": all_predictions,
        "engine": "v2_brains",
    }


def run_v13_chunk_backtest(start_draw: int, end_draw: int, checkpoint_every: int = 25) -> dict[str, Any]:
    import time

    t0 = time.time()
    total_ok = 0
    total_error = 0
    error_draws: list[dict[str, Any]] = []
    checkpoints: list[dict[str, Any]] = []

    for n, draw_no in enumerate(range(start_draw, end_draw + 1), 1):
        try:
            r = run_prediction_v13(draw_no)
            status = r.get("status", "unknown")
            if status in ("ok", "cached"):
                total_ok += 1
            else:
                total_error += 1
                error_draws.append({"draw_no": draw_no, "status": status, "reason": r.get("reason")})
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
        "engine": "v2_brains",
    }


def run_v13_mini_backtest(start_draw: int = 1100, end_draw: int = 1221, chunk: int = 50) -> dict[str, Any]:
    from collections import defaultdict

    sums: dict[str, list[int]] = defaultdict(list)
    max_mc: dict[str, int] = defaultdict(int)

    for i, draw_no in enumerate(range(start_draw, end_draw + 1)):
        run_prediction_v13(draw_no)
        conn = get_lotto4_db()
        try:
            rows = conn.execute(
                """
                SELECT brain_tag, matched_count FROM lotto_predictions_army4
                WHERE target_draw_no = ? AND brain_tag LIKE 'v13_%'
                  AND matched_count >= 0
                """,
                (draw_no,),
            ).fetchall()
        finally:
            conn.close()
        for r in rows:
            tag = str(r["brain_tag"])
            mc = int(r["matched_count"] or 0)
            sums[tag].append(mc)
            max_mc[tag] = max(max_mc[tag], mc)
        if chunk and (i + 1) % chunk == 0:
            logger.info("mini_backtest progress: through draw %s (%s)", draw_no, i + 1)

    stats: dict[str, Any] = {}
    for tag in V13_V2_BRAIN_ORDER:
        arr = sums.get(tag, [])
        n = len(arr)
        stats[tag] = {
            "avg_mc": round(sum(arr) / n, 4) if n else 0.0,
            "max_mc": max_mc.get(tag, 0),
            "n_predictions": n,
        }
    stats["baseline_3g_m4_avg_mc"] = 1.502
    stats["range"] = f"{start_draw}~{end_draw}"
    stats["engine"] = "v2_brains"
    return stats
