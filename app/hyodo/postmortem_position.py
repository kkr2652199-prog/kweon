# -*- coding: utf-8 -*-
"""PostMortem 7구간(위치) + 5밴드 전이 지표 — READ-ONLY 분석, patterns.db만 WRITE.

pos1~pos6: 정렬 당첨번호, pos7: 보너스.
전이/연관성은 max_data_draw=N-1 walk-forward. 당회차 position_values는 사후 복기용.
F1/6뇌 예측 로직과 완전 분리 — 역주입 금지.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter
from datetime import datetime
from typing import Any

from app.config import DATA_DIR

logger = logging.getLogger(__name__)

LOTTO_DB = DATA_DIR / "lotto_hyodo.db"
PATTERN_DB = DATA_DIR / "lotto_patterns_hyodo.db"

BAND_NAMES: tuple[str, ...] = ("1_9", "10_19", "20_29", "30_39", "40_45")
POSITION_KEYS: tuple[str, ...] = (
    "pos1", "pos2", "pos3", "pos4", "pos5", "pos6", "pos7_bonus",
)

POSITION_MIGRATE_SQL = """
ALTER TABLE postmortem_draw ADD COLUMN position_values TEXT;
ALTER TABLE postmortem_draw ADD COLUMN transition_observation TEXT;
"""

POSITION_STATS_SCHEMA = """
CREATE TABLE IF NOT EXISTS postmortem_position_stats (
    stat_key       TEXT NOT NULL,
    max_data_draw  INTEGER NOT NULL,
    payload        TEXT NOT NULL,
    built_at       TEXT NOT NULL,
    PRIMARY KEY (stat_key, max_data_draw)
);
CREATE INDEX IF NOT EXISTS idx_pos_stats_draw ON postmortem_position_stats(max_data_draw);
"""


def band_of(n: int) -> str:
    """5밴드 (combo_stats와 동일 경계)."""
    v = int(n)
    if v <= 9:
        return "1_9"
    if v <= 19:
        return "10_19"
    if v <= 29:
        return "20_29"
    if v <= 39:
        return "30_39"
    return "40_45"


def band_distribution(main6: list[int]) -> dict[str, int]:
    """6개 당첨번호의 5밴드 분포."""
    dist = {b: 0 for b in BAND_NAMES}
    for n in main6:
        dist[band_of(n)] += 1
    return dist


def _row_to_positions(row: sqlite3.Row) -> tuple[list[int], int]:
    nums = [int(row[f"num{i}"]) for i in range(1, 7)]
    return nums, int(row["bonus"])


def compute_position_values(main6: list[int], bonus: int) -> dict[str, Any]:
    """당회차 pos1~pos6 + pos7(bonus) 사후 기록."""
    s = sorted(int(n) for n in main6)
    out: dict[str, Any] = {
        "note": "당회차 당첨번호 사후 기록 (예측 아님)",
    }
    for i, n in enumerate(s, start=1):
        key = f"pos{i}"
        out[key] = n
        out[f"{key}_band"] = band_of(n)
    out["pos7_bonus"] = int(bonus)
    out["pos7_band"] = band_of(bonus)
    out["pos1_pos6_span"] = s[-1] - s[0]
    out["pos1_pos6_sum"] = sum(s)
    return out


def compute_transition_observation(
    prev_main6: list[int],
    prev_bonus: int,
    curr_main6: list[int],
    curr_bonus: int,
    draw_no: int,
) -> dict[str, Any]:
    """N-1 vs N 직전회차 대비 관측. max_data_draw=N-1."""
    max_data = draw_no - 1
    prev_s = sorted(int(n) for n in prev_main6)
    curr_s = sorted(int(n) for n in curr_main6)
    prev_set = set(prev_s)
    curr_set = set(curr_s)
    overlap = sorted(prev_set & curr_set)

    prev_dist = band_distribution(prev_s)
    curr_dist = band_distribution(curr_s)
    band_shift = {b: curr_dist[b] - prev_dist[b] for b in BAND_NAMES}

    pos_delta: dict[str, dict[str, int]] = {}
    for i in range(6):
        pk = f"pos{i + 1}"
        pos_delta[pk] = {
            "prev": prev_s[i],
            "curr": curr_s[i],
            "delta": curr_s[i] - prev_s[i],
            "prev_band": band_of(prev_s[i]),
            "curr_band": band_of(curr_s[i]),
        }
    pos_delta["pos7_bonus"] = {
        "prev": int(prev_bonus),
        "curr": int(curr_bonus),
        "delta": int(curr_bonus) - int(prev_bonus),
        "prev_band": band_of(prev_bonus),
        "curr_band": band_of(curr_bonus),
    }

    return {
        "max_data_draw": max_data,
        "prev_draw": max_data,
        "curr_draw": draw_no,
        "note": "전이/연관성은 1~(N-1) 누적 기준, 직전회차(N-1) 대비 관측",
        "overlap_count": len(overlap),
        "overlap_numbers": overlap,
        "prev_band_dist": prev_dist,
        "curr_band_dist": curr_dist,
        "band_shift": band_shift,
        "pos_delta": pos_delta,
        "pos1_pos6_span_delta": (curr_s[-1] - curr_s[0]) - (prev_s[-1] - prev_s[0]),
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


def migrate_position_schema() -> list[str]:
    """postmortem_draw JSON 컬럼 + postmortem_position_stats 테이블 추가."""
    conn = _pat_conn(write=True)
    added: list[str] = []
    try:
        cols = _table_columns(conn, "postmortem_draw")
        if "position_values" not in cols:
            conn.execute("ALTER TABLE postmortem_draw ADD COLUMN position_values TEXT")
            added.append("postmortem_draw.position_values")
        if "transition_observation" not in cols:
            conn.execute(
                "ALTER TABLE postmortem_draw ADD COLUMN transition_observation TEXT"
            )
            added.append("postmortem_draw.transition_observation")
        conn.executescript(POSITION_STATS_SCHEMA)
        if "postmortem_position_stats" not in {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }:
            added.append("postmortem_position_stats (created)")
        conn.commit()
    finally:
        conn.close()
    return added


def load_draw_row(conn: sqlite3.Connection, draw_no: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT draw_no, num1, num2, num3, num4, num5, num6, bonus "
        "FROM lotto_draws WHERE draw_no=? AND num1 IS NOT NULL",
        (draw_no,),
    ).fetchone()


def compute_draw_position_metrics(
    src: sqlite3.Connection, draw_no: int
) -> dict[str, Any] | None:
    """단일 회차 position_values + transition_observation."""
    row = load_draw_row(src, draw_no)
    if not row:
        return None
    main6, bonus = _row_to_positions(row)
    pos_vals = compute_position_values(main6, bonus)

    trans: dict[str, Any] | None = None
    if draw_no > 1:
        prev = load_draw_row(src, draw_no - 1)
        if prev:
            p_main, p_bonus = _row_to_positions(prev)
            trans = compute_transition_observation(
                p_main, p_bonus, main6, bonus, draw_no
            )
    return {
        "draw_no": draw_no,
        "position_values": pos_vals,
        "transition_observation": trans,
    }


def upsert_position_columns(
    conn: sqlite3.Connection,
    draw_no: int,
    position_values: dict[str, Any],
    transition_observation: dict[str, Any] | None,
) -> bool:
    """기존 postmortem_draw 행의 position JSON만 UPDATE (19컬럼 무손상)."""
    cur = conn.execute(
        """
        UPDATE postmortem_draw
        SET position_values=?, transition_observation=?
        WHERE draw_no=?
        """,
        (
            json.dumps(position_values, ensure_ascii=False),
            json.dumps(transition_observation, ensure_ascii=False)
            if transition_observation
            else None,
            draw_no,
        ),
    )
    return cur.rowcount > 0


def build_global_position_stats(
    src: sqlite3.Connection, max_data_draw: int
) -> dict[str, dict[str, Any]]:
    """draw 1..max_data_draw 기준 전역 누적 통계."""
    rows = src.execute(
        """
        SELECT draw_no, num1, num2, num3, num4, num5, num6, bonus
        FROM lotto_draws
        WHERE draw_no <= ? AND num1 IS NOT NULL
        ORDER BY draw_no
        """,
        (max_data_draw,),
    ).fetchall()

    pos_values: dict[str, list[int]] = {k: [] for k in POSITION_KEYS}
    pos_bands: dict[str, Counter[str]] = {k: Counter() for k in POSITION_KEYS}
    band_pair_counts: Counter[tuple[str, str]] = Counter()
    spans: list[int] = []
    pos1_vals: list[int] = []
    pos6_vals: list[int] = []

    prev_main: list[int] | None = None
    prev_bonus: int | None = None

    for row in rows:
        main6, bonus = _row_to_positions(row)
        s = sorted(main6)
        pos_values["pos1"].append(s[0])
        pos_values["pos6"].append(s[5])
        pos1_vals.append(s[0])
        pos6_vals.append(s[5])
        spans.append(s[5] - s[0])
        for i in range(6):
            pk = f"pos{i + 1}"
            pos_values[pk].append(s[i])
            pos_bands[pk][band_of(s[i])] += 1
        pos_values["pos7_bonus"].append(bonus)
        pos_bands["pos7_bonus"][band_of(bonus)] += 1

        if prev_main is not None:
            prev_s = sorted(prev_main)
            for i in range(6):
                band_pair_counts[(band_of(prev_s[i]), band_of(s[i]))] += 1
            band_pair_counts[(band_of(int(prev_bonus)), band_of(bonus))] += 1
        prev_main = main6
        prev_bonus = bonus

    n = len(rows)
    position_summary: dict[str, Any] = {"draw_count": n, "max_data_draw": max_data_draw}
    for pk in POSITION_KEYS:
        vals = pos_values[pk]
        if not vals:
            continue
        bands = pos_bands[pk]
        mode_band = bands.most_common(1)[0][0] if bands else None
        position_summary[pk] = {
            "mean": round(sum(vals) / len(vals), 3),
            "min": min(vals),
            "max": max(vals),
            "mode_band": mode_band,
            "band_freq": dict(bands),
        }

    # pos1-pos6 상관 (간격·합)
    span_mean = round(sum(spans) / len(spans), 3) if spans else 0
    pos1_pos6_gap_mean = (
        round(sum(p6 - p1 for p1, p6 in zip(pos1_vals, pos6_vals)) / len(spans), 3)
        if spans
        else 0
    )

    matrix: dict[str, dict[str, int]] = {
        b: {b2: 0 for b2 in BAND_NAMES} for b in BAND_NAMES
    }
    for (b_from, b_to), cnt in band_pair_counts.items():
        matrix[b_from][b_to] += cnt

    return {
        "position_summary": {
            **position_summary,
            "pos1_pos6_span_mean": span_mean,
            "pos1_pos6_gap_mean": pos1_pos6_gap_mean,
        },
        "band_transition_matrix": {
            "max_data_draw": max_data_draw,
            "transition_pairs": sum(band_pair_counts.values()),
            "matrix": matrix,
            "raw_counts": {f"{a}->{b}": c for (a, b), c in band_pair_counts.items()},
        },
        "position_correlation": _correlation_snapshot(pos1_vals, pos6_vals, spans),
    }


def _correlation_snapshot(
    pos1: list[int], pos6: list[int], spans: list[int]
) -> dict[str, Any]:
    """pos1·pos6·span 간 Pearson r (관측용)."""
    n = len(pos1)
    if n < 3:
        return {"n": n, "note": "표본 부족"}

    def _pearson(xs: list[float], ys: list[float]) -> float | None:
        m_x = sum(xs) / len(xs)
        m_y = sum(ys) / len(ys)
        num = sum((x - m_x) * (y - m_y) for x, y in zip(xs, ys))
        den_x = sum((x - m_x) ** 2 for x in xs) ** 0.5
        den_y = sum((y - m_y) ** 2 for y in ys) ** 0.5
        if den_x == 0 or den_y == 0:
            return None
        return round(num / (den_x * den_y), 4)

    p1 = [float(x) for x in pos1]
    p6 = [float(x) for x in pos6]
    sp = [float(x) for x in spans]
    return {
        "n": n,
        "pos1_pos6_r": _pearson(p1, p6),
        "pos1_span_r": _pearson(p1, sp),
        "pos6_span_r": _pearson(p6, sp),
    }


def upsert_global_position_stats(
    conn: sqlite3.Connection,
    max_data_draw: int,
    stats: dict[str, dict[str, Any]],
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for stat_key, payload in stats.items():
        conn.execute(
            """
            INSERT INTO postmortem_position_stats(stat_key, max_data_draw, payload, built_at)
            VALUES (?,?,?,?)
            ON CONFLICT(stat_key, max_data_draw) DO UPDATE SET
                payload=excluded.payload,
                built_at=excluded.built_at
            """,
            (
                stat_key,
                max_data_draw,
                json.dumps(payload, ensure_ascii=False),
                now,
            ),
        )


def maybe_build_position_after_scoring(scored_draw_no: int) -> dict[str, Any]:
    """자동 훅: position 지표 UPSERT (예외 격리)."""
    try:
        migrate_position_schema()
        src = _src_conn()
        try:
            metrics = compute_draw_position_metrics(src, scored_draw_no)
        finally:
            src.close()
        if not metrics:
            return {"built": False, "reason": "no_draw_data", "draw_no": scored_draw_no}

        pat = _pat_conn(write=True)
        try:
            ok = upsert_position_columns(
                pat,
                scored_draw_no,
                metrics["position_values"],
                metrics.get("transition_observation"),
            )
            pat.commit()
        finally:
            pat.close()

        src2 = _src_conn()
        try:
            gstats = build_global_position_stats(src2, scored_draw_no)
        finally:
            src2.close()
        pat2 = _pat_conn(write=True)
        try:
            upsert_global_position_stats(pat2, scored_draw_no, gstats)
            pat2.commit()
        finally:
            pat2.close()

        if not ok:
            return {
                "built": False,
                "reason": "postmortem_row_missing",
                "draw_no": scored_draw_no,
            }
        logger.info(
            "[postmortem_position] built draw=%d max_data=%s",
            scored_draw_no,
            metrics.get("transition_observation", {}).get("max_data_draw"),
        )
        return {"built": True, "draw_no": scored_draw_no}
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[postmortem_position] build failed draw=%d: %s",
            scored_draw_no,
            exc,
            exc_info=True,
        )
        return {"built": False, "reason": str(exc), "draw_no": scored_draw_no}
