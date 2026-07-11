# -*- coding: utf-8 -*-
"""1군 회차별 PostMortem 다차원 지표 — READ-ONLY 분석 전용.

lotto_testlotto.db는 query_only로 읽기만. 결과는 lotto_patterns_testlotto.db postmortem_draw에 저장.
미래 회차 예측·6뇌/lead1 생성 로직과 완전 분리 — 컨닝 역주입 없음.
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

POOL_BRAINS: tuple[str, ...] = ("stat", "markov", "llm", "lstm", "fusion")
SIX_BRAINS: tuple[str, ...] = POOL_BRAINS + ("hyena",)
ALL_BRAINS: tuple[str, ...] = SIX_BRAINS + ("lead1",)

POSTMORTEM_SCHEMA = """
CREATE TABLE IF NOT EXISTS postmortem_draw (
    draw_no             INTEGER PRIMARY KEY,
    draw_date           TEXT,
    winning_numbers     TEXT NOT NULL,
    bonus               INTEGER,
    pool_union_size     INTEGER NOT NULL,
    pool_cover          INTEGER NOT NULL,
    pool_missed         TEXT NOT NULL,
    lead1_union_size    INTEGER NOT NULL,
    lead1_pack          INTEGER NOT NULL,
    lead1_pack_missed   TEXT NOT NULL,
    pack_gap            INTEGER NOT NULL,
    pack_gap_nums       TEXT NOT NULL,
    pack_gap_brains     TEXT NOT NULL,
    lead1_best_hit      INTEGER NOT NULL,
    lead1_best_set      TEXT NOT NULL,
    brain_summary       TEXT NOT NULL,
    winning_stats       TEXT NOT NULL,
    lead1_union_stats   TEXT NOT NULL,
    built_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS postmortem_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_postmortem_built ON postmortem_draw(built_at);
"""


def _src_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(LOTTO_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _pat_conn(*, write: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(str(PATTERN_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    if write:
        conn.execute("PRAGMA query_only=OFF")
    else:
        conn.execute("PRAGMA query_only=ON")
    return conn


def init_postmortem_schema() -> None:
    """postmortem 테이블·인덱스 생성 (기존 원자 테이블 보존)."""
    conn = _pat_conn(write=True)
    try:
        conn.executescript(POSTMORTEM_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def combo_stats(nums: list[int]) -> dict[str, int]:
    """조합 특성 — 수치만 (홀짝·고저·번호대·연번쌍·합계)."""
    s = sorted(int(n) for n in nums)
    odd = sum(1 for n in s if n % 2 == 1)
    even = len(s) - odd
    low = sum(1 for n in s if n <= 22)
    high = len(s) - low
    z1 = sum(1 for n in s if 1 <= n <= 9)
    z2 = sum(1 for n in s if 10 <= n <= 19)
    z3 = sum(1 for n in s if 20 <= n <= 29)
    z4 = sum(1 for n in s if 30 <= n <= 39)
    z5 = sum(1 for n in s if 40 <= n <= 45)
    consec = sum(1 for i in range(len(s) - 1) if s[i + 1] - s[i] == 1)
    return {
        "odd": odd,
        "even": even,
        "low": low,
        "high": high,
        "zone_1_9": z1,
        "zone_10_19": z2,
        "zone_20_29": z3,
        "zone_30_39": z4,
        "zone_40_45": z5,
        "consec_pairs": consec,
        "sum": sum(s),
    }


def _load_brain_sets(
    conn: sqlite3.Connection, draw_no: int, brains: tuple[str, ...]
) -> tuple[dict[str, list[tuple[int, ...]]], dict[str, list[int]]]:
    ph = ",".join("?" * len(brains))
    rows = conn.execute(
        f"""
        SELECT brain_tag, num1, num2, num3, num4, num5, num6, matched_count
        FROM lotto_predictions
        WHERE target_draw_no=? AND brain_tag IN ({ph})
        ORDER BY brain_tag, id
        """,
        (draw_no, *brains),
    ).fetchall()
    out: dict[str, list[tuple[int, ...]]] = {b: [] for b in brains}
    hits: dict[str, list[int]] = {b: [] for b in brains}
    for r in rows:
        tag = str(r["brain_tag"])
        nums = tuple(sorted(int(r[i]) for i in range(1, 7)))
        out[tag].append(nums)
        hits[tag].append(int(r["matched_count"] or -1))
    return out, hits  # type: ignore[return-value]


def _union(sets: list[tuple[int, ...]]) -> set[int]:
    u: set[int] = set()
    for s in sets:
        u |= set(s)
    return u


def _brains_for_number(
    brain_sets: dict[str, list[tuple[int, ...]]], number: int, brains: tuple[str, ...]
) -> list[str]:
    found: list[str] = []
    for b in brains:
        if any(number in s for s in brain_sets.get(b, [])):
            found.append(b)
    return found


def compute_draw_postmortem(conn: sqlite3.Connection, draw_no: int) -> dict[str, Any] | None:
    """단일 회차 PostMortem 지표 계산. 데이터 부족 시 None."""
    row = conn.execute(
        "SELECT draw_no, draw_date, num1, num2, num3, num4, num5, num6, bonus "
        "FROM lotto_draws WHERE draw_no=? AND num1 IS NOT NULL",
        (draw_no,),
    ).fetchone()
    if not row:
        return None

    winning = sorted(int(row[i]) for i in range(2, 8))
    bonus = int(row[8])
    win_set = set(winning)
    draw_date = str(row[1] or "")

    pool_sets, _pool_hits = _load_brain_sets(conn, draw_no, POOL_BRAINS)
    if len(pool_sets) != len(POOL_BRAINS) or any(len(pool_sets[b]) < 1 for b in POOL_BRAINS):
        return None

    six_sets, _ = _load_brain_sets(conn, draw_no, SIX_BRAINS)
    lead1_sets, lead1_hits = _load_brain_sets(conn, draw_no, ("lead1",))
    if len(lead1_sets.get("lead1", [])) < 1:
        return None

    pool_union = _union([s for b in POOL_BRAINS for s in pool_sets[b]])
    lead1_union = _union(lead1_sets["lead1"])

    pool_hit = sorted(win_set & pool_union)
    pool_missed = sorted(win_set - pool_union)
    pool_cover = len(pool_hit)

    lead1_hit = sorted(win_set & lead1_union)
    lead1_missed = sorted(win_set - lead1_union)
    lead1_pack = len(lead1_hit)

    pack_gap_nums = sorted(set(pool_hit) - lead1_union)
    pack_gap = len(pack_gap_nums)
    pack_gap_brains = {
        str(n): _brains_for_number(pool_sets, n, POOL_BRAINS) for n in pack_gap_nums
    }

    lead1_best_hit = max((h for h in lead1_hits["lead1"] if h >= 0), default=-1)
    lead1_best_idx = lead1_hits["lead1"].index(lead1_best_hit) if lead1_best_hit >= 0 else 0
    lead1_best_set = sorted(lead1_sets["lead1"][lead1_best_idx])

    brain_summary: dict[str, Any] = {}
    for tag in ALL_BRAINS:
        sets = lead1_sets["lead1"] if tag == "lead1" else six_sets.get(tag, [])
        if not sets:
            continue
        u = _union(sets)
        hits = sorted(win_set & u)
        misses = sorted(win_set - u)
        matched = [h for h in (lead1_hits["lead1"] if tag == "lead1" else []) if h >= 0]
        if tag != "lead1":
            ph = conn.execute(
                "SELECT matched_count FROM lotto_predictions "
                "WHERE target_draw_no=? AND brain_tag=? AND matched_count>=0",
                (draw_no, tag),
            ).fetchall()
            matched = [int(r[0]) for r in ph]
        best = max(matched) if matched else 0
        brain_summary[tag] = {
            "hits": hits,
            "misses": misses,
            "union_hit": len(hits),
            "best_set_hit": best,
            "union_size": len(u),
        }

    return {
        "draw_no": draw_no,
        "draw_date": draw_date,
        "winning_numbers": winning,
        "bonus": bonus,
        "pool_union_size": len(pool_union),
        "pool_cover": pool_cover,
        "pool_missed": pool_missed,
        "lead1_union_size": len(lead1_union),
        "lead1_pack": lead1_pack,
        "lead1_pack_missed": lead1_missed,
        "pack_gap": pack_gap,
        "pack_gap_nums": pack_gap_nums,
        "pack_gap_brains": pack_gap_brains,
        "lead1_best_hit": lead1_best_hit,
        "lead1_best_set": lead1_best_set,
        "brain_summary": brain_summary,
        "winning_stats": combo_stats(winning),
        "lead1_union_stats": combo_stats(sorted(lead1_union)),
    }


def eligible_draws(conn: sqlite3.Connection, min_draw: int = 1, max_draw: int | None = None) -> list[int]:
    """당첨·5뇌·lead1 예측이 모두 있는 회차 목록."""
    ph = ",".join("?" * len(POOL_BRAINS))
    rows = conn.execute(
        f"""
        SELECT d.draw_no
        FROM lotto_draws d
        WHERE d.num1 IS NOT NULL AND d.draw_no >= ?
        GROUP BY d.draw_no
        HAVING (
            SELECT COUNT(DISTINCT p.brain_tag)
            FROM lotto_predictions p
            WHERE p.target_draw_no = d.draw_no
              AND p.brain_tag IN ({ph})
        ) = ?
        AND (
            SELECT COUNT(*) FROM lotto_predictions p2
            WHERE p2.target_draw_no = d.draw_no AND p2.brain_tag = 'lead1'
        ) >= 1
        ORDER BY d.draw_no
        """,
        (min_draw, *POOL_BRAINS, len(POOL_BRAINS)),
    ).fetchall()
    out = [int(r[0]) for r in rows]
    if max_draw is not None:
        out = [d for d in out if d <= max_draw]
    return out


def upsert_postmortem_row(conn: sqlite3.Connection, rec: dict[str, Any]) -> None:
    """postmortem_draw 1행 UPSERT."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        INSERT INTO postmortem_draw (
            draw_no, draw_date, winning_numbers, bonus,
            pool_union_size, pool_cover, pool_missed,
            lead1_union_size, lead1_pack, lead1_pack_missed,
            pack_gap, pack_gap_nums, pack_gap_brains,
            lead1_best_hit, lead1_best_set,
            brain_summary, winning_stats, lead1_union_stats, built_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(draw_no) DO UPDATE SET
            draw_date=excluded.draw_date,
            winning_numbers=excluded.winning_numbers,
            bonus=excluded.bonus,
            pool_union_size=excluded.pool_union_size,
            pool_cover=excluded.pool_cover,
            pool_missed=excluded.pool_missed,
            lead1_union_size=excluded.lead1_union_size,
            lead1_pack=excluded.lead1_pack,
            lead1_pack_missed=excluded.lead1_pack_missed,
            pack_gap=excluded.pack_gap,
            pack_gap_nums=excluded.pack_gap_nums,
            pack_gap_brains=excluded.pack_gap_brains,
            lead1_best_hit=excluded.lead1_best_hit,
            lead1_best_set=excluded.lead1_best_set,
            brain_summary=excluded.brain_summary,
            winning_stats=excluded.winning_stats,
            lead1_union_stats=excluded.lead1_union_stats,
            built_at=excluded.built_at
        """,
        (
            rec["draw_no"],
            rec["draw_date"],
            json.dumps(rec["winning_numbers"], ensure_ascii=False),
            rec["bonus"],
            rec["pool_union_size"],
            rec["pool_cover"],
            json.dumps(rec["pool_missed"], ensure_ascii=False),
            rec["lead1_union_size"],
            rec["lead1_pack"],
            json.dumps(rec["lead1_pack_missed"], ensure_ascii=False),
            rec["pack_gap"],
            json.dumps(rec["pack_gap_nums"], ensure_ascii=False),
            json.dumps(rec["pack_gap_brains"], ensure_ascii=False),
            rec["lead1_best_hit"],
            json.dumps(rec["lead1_best_set"], ensure_ascii=False),
            json.dumps(rec["brain_summary"], ensure_ascii=False),
            json.dumps(rec["winning_stats"], ensure_ascii=False),
            json.dumps(rec["lead1_union_stats"], ensure_ascii=False),
            now,
        ),
    )


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """DB Row → JSON-serializable dict."""
    d = dict(row)
    for key in (
        "winning_numbers", "pool_missed", "lead1_pack_missed",
        "pack_gap_nums", "pack_gap_brains", "lead1_best_set",
        "brain_summary", "winning_stats", "lead1_union_stats",
        "position_values", "transition_observation",
    ):
        if key in d and isinstance(d[key], str):
            d[key] = json.loads(d[key])
    return d


def load_postmortem(draw_no: int) -> dict[str, Any] | None:
    """postmortem_draw 1회차 READ-ONLY 조회."""
    if not PATTERN_DB.exists():
        return None
    conn = _pat_conn(write=False)
    try:
        row = conn.execute(
            "SELECT * FROM postmortem_draw WHERE draw_no=?", (draw_no,)
        ).fetchone()
        return row_to_dict(row) if row else None
    finally:
        conn.close()


def maybe_build_postmortem_after_scoring(scored_draw_no: int) -> dict[str, Any]:
    """당첨 확정·채점 후 PostMortem 1회차 UPSERT (자동 훅용).

    - lotto_testlotto.db: query_only READ
    - lotto_patterns_testlotto.db: postmortem_draw WRITE
    - 5뇌·lead1 미완 회차 skip
    - 예외 격리: 실패해도 호출자(예측 파이프라인)에 전파하지 않음
    """
    try:
        init_postmortem_schema()

        src = _src_conn()
        try:
            row = src.execute(
                "SELECT num1 FROM lotto_draws WHERE draw_no=? AND num1 IS NOT NULL",
                (scored_draw_no,),
            ).fetchone()
            if not row:
                return {
                    "built": False,
                    "reason": "draw_not_scored",
                    "draw_no": scored_draw_no,
                }
            rec = compute_draw_postmortem(src, scored_draw_no)
        finally:
            src.close()

        if not rec:
            return {
                "built": False,
                "reason": "insufficient_data",
                "draw_no": scored_draw_no,
            }

        pat = _pat_conn(write=True)
        try:
            upsert_postmortem_row(pat, rec)
            pat.execute(
                "INSERT INTO postmortem_meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (
                    "last_hook_build",
                    json.dumps({"draw_no": scored_draw_no}, ensure_ascii=False),
                ),
            )
            pat.commit()
        finally:
            pat.close()

        from app.testlotto.postmortem_position import maybe_build_position_after_scoring

        pos_result = maybe_build_position_after_scoring(scored_draw_no)

        logger.info(
            "[postmortem] auto-built draw=%d pool=%d/6 pack=%d/6 gap=%d",
            scored_draw_no,
            rec["pool_cover"],
            rec["lead1_pack"],
            rec["pack_gap"],
        )
        return {
            "built": True,
            "draw_no": scored_draw_no,
            "pool_cover": rec["pool_cover"],
            "lead1_pack": rec["lead1_pack"],
            "pack_gap": rec["pack_gap"],
            "position_built": pos_result.get("built", False),
        }
    except Exception as exc:  # noqa: BLE001 — 예측 파이프라인 격리
        logger.warning(
            "[postmortem] auto-build failed draw=%d: %s",
            scored_draw_no,
            exc,
            exc_info=True,
        )
        return {
            "built": False,
            "reason": str(exc),
            "draw_no": scored_draw_no,
        }
