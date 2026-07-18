# -*- coding: utf-8 -*-
"""PostMortem 구조 지표(간격·합계·홀짝·연번) — READ-ONLY 분석, patterns.db만 WRITE.

lead1 5세트 vs 당첨번호 구조 대조(사후 복기). F1/예측 역주입 금지.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from typing import Any

from app.config import DATA_DIR

logger = logging.getLogger(__name__)

LOTTO_DB = DATA_DIR / "lotto_testlotto.db"
PATTERN_DB = DATA_DIR / "lotto_patterns_testlotto.db"

STRUCTURE_STATS_SCHEMA = """
CREATE TABLE IF NOT EXISTS postmortem_structure_stats (
    stat_key       TEXT NOT NULL,
    max_data_draw  INTEGER NOT NULL,
    payload        TEXT NOT NULL,
    built_at       TEXT NOT NULL,
    PRIMARY KEY (stat_key, max_data_draw)
);
"""


def combo_structure(nums: list[int] | tuple[int, ...]) -> dict[str, Any]:
    """정렬 6개 번호의 구조 지표."""
    s = sorted(int(n) for n in nums)
    gaps = [s[i + 1] - s[i] for i in range(5)]
    odd = sum(1 for n in s if n % 2 == 1)
    even = 6 - odd
    low = sum(1 for n in s if n <= 22)
    high = 6 - low
    consec = sum(1 for i in range(5) if s[i + 1] - s[i] == 1)
    return {
        "gaps": gaps,
        "gap_mean": round(sum(gaps) / 5, 3),
        "sum": sum(s),
        "odd": odd,
        "even": even,
        "low": low,
        "high": high,
        "consec_pairs": consec,
        "pos_span": s[5] - s[0],
    }


def _pat_conn(*, write: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(str(PATTERN_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    if write:
        conn.execute("PRAGMA query_only=OFF")
    else:
        conn.execute("PRAGMA query_only=ON")
    return conn


def _src_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(LOTTO_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(r[1]) for r in rows}


def migrate_structure_schema() -> list[str]:
    """postmortem_draw 구조 JSON 컬럼 + 전역 stats 테이블."""
    conn = _pat_conn(write=True)
    added: list[str] = []
    try:
        cols = _table_columns(conn, "postmortem_draw")
        if "structure_winning" not in cols:
            conn.execute("ALTER TABLE postmortem_draw ADD COLUMN structure_winning TEXT")
            added.append("postmortem_draw.structure_winning")
        if "structure_lead1_contrast" not in cols:
            conn.execute(
                "ALTER TABLE postmortem_draw ADD COLUMN structure_lead1_contrast TEXT"
            )
            added.append("postmortem_draw.structure_lead1_contrast")
        conn.executescript(STRUCTURE_STATS_SCHEMA)
        conn.commit()
    finally:
        conn.close()
    return added


def _load_lead1_sets(
    conn: sqlite3.Connection, draw_no: int
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT num1,num2,num3,num4,num5,num6, matched_count
        FROM lotto_predictions
        WHERE target_draw_no=? AND brain_tag='lead1'
        ORDER BY id
        """,
        (draw_no,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        nums = tuple(sorted(int(r[i]) for i in range(6)))
        hit = int(r["matched_count"] if r["matched_count"] is not None else -1)
        st = combo_structure(nums)
        out.append({"nums": list(nums), "matched_count": hit, "structure": st})
    return out


def compute_draw_structure(
    src: sqlite3.Connection, draw_no: int
) -> dict[str, Any] | None:
    """당회차 당첨 구조 + lead1 5세트 best vs other 대조."""
    row = src.execute(
        "SELECT num1,num2,num3,num4,num5,num6 FROM lotto_draws "
        "WHERE draw_no=? AND num1 IS NOT NULL",
        (draw_no,),
    ).fetchone()
    if not row:
        return None

    winning = [int(row[i]) for i in range(6)]
    win_st = combo_structure(winning)
    win_st["note"] = "당회차 당첨 사후 기록 (예측 아님)"

    lead1 = _load_lead1_sets(src, draw_no)
    if not lead1:
        return None

    scored = [s for s in lead1 if s["matched_count"] >= 0]
    if not scored:
        return None
    best_hit = max(s["matched_count"] for s in scored)
    best_sets = [s for s in scored if s["matched_count"] == best_hit]
    other_sets = [s for s in scored if s["matched_count"] < best_hit]

    def _avg_metric(sets: list[dict], key: str) -> float | None:
        if not sets:
            return None
        vals = [s["structure"][key] for s in sets]
        return round(sum(vals) / len(vals), 3)

    contrast: dict[str, Any] = {
        "best_hit": best_hit,
        "best_count": len(best_sets),
        "other_count": len(other_sets),
        "best_avg": {
            "sum": _avg_metric(best_sets, "sum"),
            "odd": _avg_metric(best_sets, "odd"),
            "consec_pairs": _avg_metric(best_sets, "consec_pairs"),
            "gap_mean": _avg_metric(best_sets, "gap_mean"),
            "pos_span": _avg_metric(best_sets, "pos_span"),
        },
        "other_avg": {
            "sum": _avg_metric(other_sets, "sum"),
            "odd": _avg_metric(other_sets, "odd"),
            "consec_pairs": _avg_metric(other_sets, "consec_pairs"),
            "gap_mean": _avg_metric(other_sets, "gap_mean"),
            "pos_span": _avg_metric(other_sets, "pos_span"),
        },
    }
    if best_sets and other_sets:
        contrast["delta_best_minus_other"] = {
            k: round((contrast["best_avg"][k] or 0) - (contrast["other_avg"][k] or 0), 3)
            for k in contrast["best_avg"]
        }

    return {
        "draw_no": draw_no,
        "structure_winning": win_st,
        "structure_lead1_contrast": {
            "sets": lead1,
            "contrast": contrast,
        },
    }


def upsert_structure_columns(
    conn: sqlite3.Connection,
    draw_no: int,
    structure_winning: dict[str, Any],
    structure_lead1_contrast: dict[str, Any],
) -> bool:
    cur = conn.execute(
        """
        UPDATE postmortem_draw
        SET structure_winning=?, structure_lead1_contrast=?
        WHERE draw_no=?
        """,
        (
            json.dumps(structure_winning, ensure_ascii=False),
            json.dumps(structure_lead1_contrast, ensure_ascii=False),
            draw_no,
        ),
    )
    return cur.rowcount > 0


def upsert_global_structure_stats(
    conn: sqlite3.Connection,
    max_data_draw: int,
    payload: dict[str, Any],
    stat_key: str = "lead1_structure_contrast",
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        INSERT INTO postmortem_structure_stats(stat_key, max_data_draw, payload, built_at)
        VALUES (?,?,?,?)
        ON CONFLICT(stat_key, max_data_draw) DO UPDATE SET
            payload=excluded.payload, built_at=excluded.built_at
        """,
        (stat_key, max_data_draw, json.dumps(payload, ensure_ascii=False), now),
    )
