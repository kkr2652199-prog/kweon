"""전략 X 5뇌 era_C 전회차 walk-forward 적재 (predictions + fullbacktest)."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.lotto4.brains.cooccur_brain_v13 import CooccurState, generate_cooccur_sets
from app.lotto4.brains.hyena_coordinator_v13 import generate_hyena_sets
from app.lotto4.brains.popularity_freq_brain import generate_popularity_sets
from app.lotto4.brains.popularity_pair_brain import generate_pair_sets
from app.lotto4.brains.shape_brain import generate_shape_sets
from app.lotto4.models import LOTTO_DB_PATH
from app.lotto4.strategy_x_logging import (
    STRATEGY_X_FIVE_BRAIN_TAGS,
    save_strategy_x_cooccur,
    save_strategy_x_hyena,
    save_strategy_x_popularity_freq,
    save_strategy_x_pair,
    save_strategy_x_shape,
)

ERA_C_START = 262
ERA_C_END = 1228
SETS_PER_BRAIN = 5
EXPECTED_ROWS_PER_DRAW = len(STRATEGY_X_FIVE_BRAIN_TAGS) * SETS_PER_BRAIN


def score_line(
    nums: list[int], win: set[int], bonus: int
) -> tuple[int, str, int]:
    st = set(int(n) for n in nums)
    hit = sorted(win & st)
    mc = len(hit)
    matched_txt = ",".join(str(x) for x in hit) if hit else ""
    b = 1 if (mc == 5 and bonus in st) else 0
    return mc, matched_txt, b


def load_all_winner_draws(db_path: str | None = None) -> list[dict[str, Any]]:
    """하이에나 trust walk-forward용 전 era 당첨 목록."""
    path = str(db_path or LOTTO_DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT drw_no, n1, n2, n3, n4, n5, n6, winner_cnt
            FROM lotto4_winners_full
            WHERE winner_cnt > 0
            ORDER BY drw_no
            """
        ).fetchall()
        return [
            {
                "drw_no": int(r["drw_no"]),
                "nums": [int(r[f"n{i}"]) for i in range(1, 7)],
                "winner_cnt": int(r["winner_cnt"]),
            }
            for r in rows
        ]
    finally:
        conn.close()


def load_era_c_draws(db_path: str | None = None) -> list[dict[str, Any]]:
    path = str(db_path or LOTTO_DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT drw_no, n1, n2, n3, n4, n5, n6, winner_cnt
            FROM lotto4_winners_full
            WHERE era = 'C' AND winner_cnt > 0
              AND drw_no BETWEEN ? AND ?
            ORDER BY drw_no
            """,
            (ERA_C_START, ERA_C_END),
        ).fetchall()
        return [
            {
                "drw_no": int(r["drw_no"]),
                "nums": [int(r[f"n{i}"]) for i in range(1, 7)],
                "winner_cnt": int(r["winner_cnt"]),
            }
            for r in rows
        ]
    finally:
        conn.close()


def load_actual_draw(
    conn: sqlite3.Connection, draw_no: int
) -> tuple[set[int], int] | None:
    row = conn.execute(
        """
        SELECT num1, num2, num3, num4, num5, num6, bonus
        FROM lotto_draws
        WHERE draw_no = ?
        """,
        (int(draw_no),),
    ).fetchone()
    if not row:
        return None
    win = {int(row[i]) for i in range(6)}
    return win, int(row[6])


def _generate_five_brains(
    drw_no: int,
    *,
    co_state: CooccurState,
    draw_count: int,
    draws: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    wf = {
        "cooccur_state": co_state.copy(),
        "draw_count": draw_count,
    }
    return {
        STRATEGY_X_FIVE_BRAIN_TAGS[0]: generate_popularity_sets(drw_no),
        STRATEGY_X_FIVE_BRAIN_TAGS[1]: generate_pair_sets(drw_no),
        STRATEGY_X_FIVE_BRAIN_TAGS[2]: generate_shape_sets(drw_no),
        STRATEGY_X_FIVE_BRAIN_TAGS[3]: generate_cooccur_sets(
            drw_no,
            state=co_state.copy(),
            draw_count=draw_count,
        ),
        STRATEGY_X_FIVE_BRAIN_TAGS[4]: generate_hyena_sets(
            drw_no,
            wf_context=wf,
            draws=draws,
            use_db_logs=True,
            weight_scheme="cooccur_favor",
            gap_blend=0.0,
        ),
    }


def _save_five_brains(
    drw_no: int, payloads: dict[str, dict[str, Any]]
) -> dict[str, int]:
    savers = {
        STRATEGY_X_FIVE_BRAIN_TAGS[0]: save_strategy_x_popularity_freq,
        STRATEGY_X_FIVE_BRAIN_TAGS[1]: save_strategy_x_pair,
        STRATEGY_X_FIVE_BRAIN_TAGS[2]: save_strategy_x_shape,
        STRATEGY_X_FIVE_BRAIN_TAGS[3]: save_strategy_x_cooccur,
        STRATEGY_X_FIVE_BRAIN_TAGS[4]: save_strategy_x_hyena,
    }
    counts: dict[str, int] = {}
    for tag, saver in savers.items():
        meta = saver(drw_no, payloads[tag])
        counts[tag] = int(meta.get("total_rows") or 0)
    return counts


def _upsert_fullbacktest_for_draw(
    conn: sqlite3.Connection,
    drw_no: int,
    win: set[int],
    bonus: int,
) -> int:
    placeholders = ",".join("?" for _ in STRATEGY_X_FIVE_BRAIN_TAGS)
    conn.execute(
        f"""
        DELETE FROM lotto_fullbacktest_army4
        WHERE draw_no = ? AND brain_tag IN ({placeholders})
        """,
        (int(drw_no), *STRATEGY_X_FIVE_BRAIN_TAGS),
    )
    rows = conn.execute(
        f"""
        SELECT brain_tag, num1, num2, num3, num4, num5, num6, method
        FROM lotto_predictions_army4
        WHERE target_draw_no = ?
          AND brain_tag IN ({placeholders})
        ORDER BY brain_tag, method
        """,
        (int(drw_no), *STRATEGY_X_FIVE_BRAIN_TAGS),
    ).fetchall()

    n = 0
    set_counters: dict[str, int] = {}
    for r in rows:
        tag = str(r[0])
        nums = [int(r[i]) for i in range(1, 7)]
        set_counters[tag] = set_counters.get(tag, 0) + 1
        set_no = set_counters[tag]
        mc, mt, bm = score_line(nums, win, bonus)
        num_txt = ",".join(str(x) for x in nums)
        conn.execute(
            """
            INSERT OR REPLACE INTO lotto_fullbacktest_army4
            (draw_no, brain_tag, set_no, numbers, matched_count,
             matched_numbers, bonus_matched)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (int(drw_no), tag, set_no, num_txt, mc, mt, bm),
        )
        conn.execute(
            """
            UPDATE lotto_predictions_army4
            SET matched_count = ?, bonus_matched = ?
            WHERE target_draw_no = ? AND brain_tag = ? AND method = ?
            """,
            (mc, bm, int(drw_no), tag, str(r[7])),
        )
        n += 1
    return n


def _init_cooccur_state_before(
    conn: sqlite3.Connection, start_draw: int
) -> CooccurState:
    """start_draw 미만 당첨으로 cooccur 증분 상태 초기화 (R13)."""
    st = CooccurState()
    rows = conn.execute(
        """
        SELECT num1, num2, num3, num4, num5, num6
        FROM lotto_draws
        WHERE draw_no < ?
        ORDER BY draw_no
        """,
        (int(start_draw),),
    ).fetchall()
    for r in rows:
        st.add_draw([int(r[i]) for i in range(6)])
    return st


def run_fullbackfill(
    *,
    db_path: str | None = None,
    start_draw: int = ERA_C_START,
    end_draw: int = ERA_C_END,
    checkpoint_every: int = 25,
    force: bool = False,
) -> dict[str, Any]:
    """era_C walk-forward 5뇌 predictions + fullbacktest 적재."""
    path = str(db_path or LOTTO_DB_PATH)
    draws = load_era_c_draws(path)
    all_draws = load_all_winner_draws(path)
    draw_by_no = {d["drw_no"]: d for d in draws}
    targets = [d for d in range(int(start_draw), int(end_draw) + 1) if d in draw_by_no]

    conn = sqlite3.connect(path, timeout=300.0)
    conn.execute("PRAGMA busy_timeout = 300000")
    processed = 0
    skipped = 0
    fb_rows = 0
    pred_rows = 0
    errors: list[str] = []

    co_state = _init_cooccur_state_before(conn, int(start_draw))

    try:
        for drw_no in targets:
            train_count = conn.execute(
                "SELECT COUNT(*) FROM lotto_draws WHERE draw_no < ?",
                (drw_no,),
            ).fetchone()[0]
            actual = load_actual_draw(conn, drw_no)
            if actual is None:
                skipped += 1
                co_state.add_draw(draw_by_no[drw_no]["nums"])
                continue

            if not force:
                ph = ",".join("?" for _ in STRATEGY_X_FIVE_BRAIN_TAGS)
                existing = conn.execute(
                    f"""
                    SELECT COUNT(*) FROM lotto_predictions_army4
                    WHERE target_draw_no = ? AND brain_tag IN ({ph})
                    """,
                    (drw_no, *STRATEGY_X_FIVE_BRAIN_TAGS),
                ).fetchone()[0]
                fb_existing = conn.execute(
                    f"""
                    SELECT COUNT(*) FROM lotto_fullbacktest_army4
                    WHERE draw_no = ? AND brain_tag IN ({ph})
                    """,
                    (drw_no, *STRATEGY_X_FIVE_BRAIN_TAGS),
                ).fetchone()[0]
                if existing >= EXPECTED_ROWS_PER_DRAW and fb_existing >= EXPECTED_ROWS_PER_DRAW:
                    skipped += 1
                    co_state.add_draw(draw_by_no[drw_no]["nums"])
                    continue

            try:
                payloads = _generate_five_brains(
                    drw_no,
                    co_state=co_state,
                    draw_count=train_count,
                    draws=all_draws,
                )
                counts = _save_five_brains(drw_no, payloads)
                pred_rows += sum(counts.values())
                win, bonus = actual
                fb_rows += _upsert_fullbacktest_for_draw(conn, drw_no, win, bonus)
                conn.commit()
                processed += 1
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                errors.append(f"draw={drw_no}: {exc}")

            co_state.add_draw(draw_by_no[drw_no]["nums"])

            if processed and processed % int(checkpoint_every) == 0:
                print(
                    f"[checkpoint] processed={processed} draw={drw_no} "
                    f"pred_rows+={pred_rows} fb_rows+={fb_rows}",
                    flush=True,
                )
    finally:
        conn.close()

    return {
        "start_draw": start_draw,
        "end_draw": end_draw,
        "targets": len(targets),
        "processed": processed,
        "skipped": skipped,
        "prediction_rows_written": pred_rows,
        "fullbacktest_rows_written": fb_rows,
        "expected_rows_per_draw": EXPECTED_ROWS_PER_DRAW,
        "brain_tags": list(STRATEGY_X_FIVE_BRAIN_TAGS),
        "errors": errors[:20],
        "error_count": len(errors),
    }
