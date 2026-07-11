"""814만 전체 조합 — 20분할 part DB (d:\\3kweon\\data\\combos\\, 로컬 전용)."""

from __future__ import annotations

import logging
import math
import sqlite3
from pathlib import Path
from typing import Any, Iterator

from app.lotto4.combinadic import TOTAL_COMBOS, combo_to_no
from app.lotto4.models import get_lotto4_db

logger = logging.getLogger(__name__)

TABLE = "lotto_all_combos"
PART_COUNT = 20
PART_SIZE = math.ceil(TOTAL_COMBOS / PART_COUNT)  # 407_253
COMBOS_DIR = Path(r"d:\3kweon\data\combos")
BATCH_SIZE = 25_000

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS lotto_all_combos (
    combo_no    INTEGER PRIMARY KEY,
    num1        INTEGER NOT NULL,
    num2        INTEGER NOT NULL,
    num3        INTEGER NOT NULL,
    num4        INTEGER NOT NULL,
    num5        INTEGER NOT NULL,
    num6        INTEGER NOT NULL,
    total       INTEGER NOT NULL,
    is_winner   INTEGER NOT NULL DEFAULT 0,
    win_draw_no INTEGER,
    win_date    TEXT
);
CREATE INDEX IF NOT EXISTS idx_lac_is_winner ON lotto_all_combos(is_winner);
"""


def part_no_for_combo(combo_no: int) -> int:
    return ((int(combo_no) - 1) // PART_SIZE) + 1


def part_combo_range(part_no: int) -> tuple[int, int]:
    p = int(part_no)
    start = (p - 1) * PART_SIZE + 1
    end = min(p * PART_SIZE, TOTAL_COMBOS)
    return start, end


def part_db_path(part_no: int) -> Path:
    return COMBOS_DIR / f"lotto_part_{int(part_no):02d}.db"


def open_part(part_no: int) -> sqlite3.Connection:
    path = part_db_path(part_no)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def ensure_part_table(conn: sqlite3.Connection) -> None:
    conn.executescript(_CREATE_SQL)


def iter_all_combos() -> Iterator[tuple[int, tuple[int, ...], int]]:
    """lex 순서로 814만 조합 생성 (combo_no 1-based)."""
    combo = [1, 2, 3, 4, 5, 6]
    combo_no = 1
    while True:
        yield combo_no, tuple(combo), sum(combo)
        if combo_no >= TOTAL_COMBOS:
            break
        i = 5
        while i >= 0 and combo[i] == 45 - (5 - i):
            i -= 1
        combo[i] += 1
        for j in range(i + 1, 6):
            combo[j] = combo[j - 1] + 1
        combo_no += 1


def _draw_sorted_nums(row: dict | sqlite3.Row) -> tuple[int, ...]:
    return tuple(sorted(int(row[f"num{i}"]) for i in range(1, 7)))


def row_to_item(row: sqlite3.Row | dict) -> dict[str, Any]:
    d = dict(row)
    return {
        "combo_no": int(d["combo_no"]),
        "numbers": [int(d[f"num{i}"]) for i in range(1, 7)],
        "total": int(d["total"]),
        "is_winner": bool(int(d.get("is_winner") or 0)),
        "win_draw_no": d.get("win_draw_no"),
        "win_date": d.get("win_date"),
    }


def rollback_lotto4_single_table() -> dict[str, Any]:
    """lotto4.db 내 단일 lotto_all_combos 제거·용량 원복."""
    import os

    from app.lotto4.models import LOTTO_DB_PATH

    before = os.path.getsize(LOTTO_DB_PATH) if LOTTO_DB_PATH.is_file() else 0
    conn = get_lotto4_db()
    try:
        has = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (TABLE,),
        ).fetchone()
        dropped = bool(has)
        if dropped:
            conn.execute(f"DROP TABLE IF EXISTS {TABLE}")
            conn.commit()
    finally:
        conn.close()

    conn = sqlite3.connect(str(LOTTO_DB_PATH))
    try:
        conn.execute("VACUUM")
        conn.commit()
    finally:
        conn.close()

    after = os.path.getsize(LOTTO_DB_PATH) if LOTTO_DB_PATH.is_file() else 0
    return {
        "ok": True,
        "dropped": dropped,
        "size_before_mb": round(before / 1024 / 1024, 1),
        "size_after_mb": round(after / 1024 / 1024, 1),
    }


def _count_part_rows(part_no: int) -> int:
    path = part_db_path(part_no)
    if not path.is_file():
        return 0
    conn = sqlite3.connect(str(path))
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()
        return int(row[0] or 0)
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def _count_part_winners(part_no: int) -> int:
    path = part_db_path(part_no)
    if not path.is_file():
        return 0
    conn = sqlite3.connect(str(path))
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM {TABLE} WHERE is_winner=1").fetchone()
        return int(row[0] or 0)
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def get_meta() -> dict[str, Any]:
    total = sum(_count_part_rows(p) for p in range(1, PART_COUNT + 1))
    winners = sum(_count_part_winners(p) for p in range(1, PART_COUNT + 1))
    parts_ready = sum(
        1 for p in range(1, PART_COUNT + 1) if part_db_path(p).is_file()
    )
    return {
        "ready": total == TOTAL_COMBOS and parts_ready == PART_COUNT,
        "count": total,
        "combo_total": TOTAL_COMBOS,
        "winners": winners,
        "part_count": PART_COUNT,
        "part_size": PART_SIZE,
        "parts_ready": parts_ready,
        "storage": str(COMBOS_DIR),
        "storage_note": "로컬 전용 - Drive 동기화 금지",
    }


def _mark_winners_on_part(part_no: int, draws: list[sqlite3.Row]) -> int:
    start, end = part_combo_range(part_no)
    conn = open_part(part_no)
    try:
        conn.execute(
            f"UPDATE {TABLE} SET is_winner=0, win_draw_no=NULL, win_date=NULL WHERE is_winner=1"
        )
        updated = 0
        for dr in draws:
            cno = combo_to_no(_draw_sorted_nums(dr))
            if start <= cno <= end:
                conn.execute(
                    f"""
                    UPDATE {TABLE}
                    SET is_winner=1, win_draw_no=?, win_date=?
                    WHERE combo_no=?
                    """,
                    (int(dr["draw_no"]), dr["draw_date"], cno),
                )
                updated += 1
        conn.commit()
        return updated
    finally:
        conn.close()


def _load_all_draws() -> list[sqlite3.Row]:
    conn = get_lotto4_db()
    try:
        return conn.execute(
            """
            SELECT draw_no, draw_date, num1, num2, num3, num4, num5, num6
            FROM lotto_draws
            ORDER BY draw_no
            """
        ).fetchall()
    finally:
        conn.close()


def build_all_combos_parts(*, force: bool = False) -> dict[str, Any]:
    """20분할 part DB 생성 + 당첨 플래그."""
    COMBOS_DIR.mkdir(parents=True, exist_ok=True)
    rollback = rollback_lotto4_single_table()

    meta = get_meta()
    if meta["ready"] and not force:
        return {
            "ok": True,
            "skipped": True,
            "rollback": rollback,
            **meta,
        }

    if force:
        for p in range(1, PART_COUNT + 1):
            path = part_db_path(p)
            if path.is_file():
                path.unlink()

    draws = _load_all_draws()
    part_stats: list[dict[str, Any]] = []
    sql = f"""
        INSERT INTO {TABLE}
        (combo_no, num1, num2, num3, num4, num5, num6, total, is_winner, win_draw_no, win_date)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """

    current_part = 0
    conn: sqlite3.Connection | None = None
    batch: list[tuple] = []
    inserted_by_part: dict[int, int] = {p: 0 for p in range(1, PART_COUNT + 1)}

    for combo_no, nums, total in iter_all_combos():
        p = part_no_for_combo(combo_no)
        if p != current_part:
            if conn and batch:
                conn.executemany(sql, batch)
                inserted_by_part[current_part] += len(batch)
                batch.clear()
                conn.commit()
            if conn:
                conn.close()
            current_part = p
            conn = sqlite3.connect(str(part_db_path(p)))
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=OFF")
            ensure_part_table(conn)
            conn.execute(f"DELETE FROM {TABLE}")
            conn.commit()

        batch.append((combo_no, *nums, total, 0, None, None))
        if len(batch) >= BATCH_SIZE:
            assert conn is not None
            conn.executemany(sql, batch)
            inserted_by_part[current_part] += len(batch)
            batch.clear()
            if inserted_by_part[current_part] % 500_000 < BATCH_SIZE:
                conn.commit()
                logger.info("part %02d 적재 %s", current_part, inserted_by_part[current_part])

    if conn and batch:
        conn.executemany(sql, batch)
        inserted_by_part[current_part] += len(batch)
        conn.commit()

    if conn:
        conn.close()

    winners_total = 0
    for p in range(1, PART_COUNT + 1):
        w = _mark_winners_on_part(p, draws)
        winners_total += w
        start, end = part_combo_range(p)
        cnt = _count_part_rows(p)
        part_stats.append(
            {
                "part": p,
                "combo_range": [start, end],
                "rows": cnt,
                "winners_marked": w,
                "file_mb": round(part_db_path(p).stat().st_size / 1024 / 1024, 1),
            }
        )

    final_meta = get_meta()
    return {
        "ok": final_meta["ready"],
        "skipped": False,
        "rollback": rollback,
        "parts": part_stats,
        "winners": winners_total,
        **final_meta,
    }


def sync_winner_for_draw(draw: dict) -> dict[str, Any]:
    """신규 당첨 → 해당 part DB만 UPDATE."""
    meta = get_meta()
    if not meta.get("ready"):
        return {"ok": False, "reason": "parts_not_ready", **meta}

    nums = _draw_sorted_nums(draw)
    cno = combo_to_no(nums)
    p = part_no_for_combo(cno)
    conn = open_part(p)
    try:
        conn.execute(
            f"""
            UPDATE {TABLE}
            SET is_winner=1, win_draw_no=?, win_date=?
            WHERE combo_no=?
            """,
            (int(draw["draw_no"]), draw.get("draw_date"), cno),
        )
        conn.commit()
        return {"ok": True, "combo_no": cno, "draw_no": int(draw["draw_no"]), "part": p}
    finally:
        conn.close()


def _fetch_from_parts(
    combo_start: int,
    limit: int,
    *,
    winners_only: bool = False,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    need = limit
    cursor = max(1, int(combo_start))

    if winners_only:
        return _fetch_winners_page(max(0, int(combo_start) - 1), limit)

    while need > 0 and cursor <= TOTAL_COMBOS:
        p = part_no_for_combo(cursor)
        _, end = part_combo_range(p)
        take = min(need, end - cursor + 1)
        conn = open_part(p)
        try:
            rows = conn.execute(
                f"""
                SELECT * FROM {TABLE}
                WHERE combo_no >= ?
                ORDER BY combo_no
                LIMIT ?
                """,
                (cursor, take),
            ).fetchall()
            got = len(rows)
            items.extend(row_to_item(r) for r in rows)
        finally:
            conn.close()
        if got == 0:
            break
        need -= got
        cursor += got
    return items


def _fetch_all_winners_sorted() -> list[dict[str, Any]]:
    """당첨 조합 전체 — 회차 최신순(내림차순)."""
    all_winners: list[dict[str, Any]] = []
    for p in range(1, PART_COUNT + 1):
        if not part_db_path(p).is_file():
            continue
        conn = open_part(p)
        try:
            rows = conn.execute(
                f"""
                SELECT * FROM {TABLE}
                WHERE is_winner=1
                ORDER BY win_draw_no DESC, combo_no ASC
                """
            ).fetchall()
            all_winners.extend(row_to_item(r) for r in rows)
        finally:
            conn.close()
    all_winners.sort(
        key=lambda x: (-(int(x.get("win_draw_no") or 0)), int(x["combo_no"]))
    )
    return all_winners


def winner_page_for_combo(combo_no: int, per_page: int) -> int | None:
    per = max(1, int(per_page))
    for idx, w in enumerate(_fetch_all_winners_sorted()):
        if int(w["combo_no"]) == int(combo_no):
            return idx // per + 1
    return None


def _fetch_winners_page(offset: int, limit: int) -> list[dict[str, Any]]:
    """당첨만 — 회차 최신순 페이지."""
    all_winners = _fetch_all_winners_sorted()
    off = max(0, int(offset))
    return all_winners[off : off + limit]


def combo_no_to_page(combo_no: int, per_page: int) -> int:
    return max(1, (int(combo_no) - 1) // max(1, int(per_page)) + 1)


def fetch_combo_page(
    page: int,
    per_page: int,
    *,
    winners_only: bool = False,
) -> dict[str, Any]:
    page = max(1, int(page))
    per_page = max(1, min(int(per_page), 500))
    if winners_only:
        offset = (page - 1) * per_page
        items = _fetch_winners_page(offset, per_page)
        total = get_meta()["winners"]
        total_pages = max(1, (total + per_page - 1) // per_page) if total else 0
        return {
            "items": items,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "total": total,
            "winners_only": True,
            "winners_order": "draw_desc",
            "combo_total": TOTAL_COMBOS,
            "start_combo_no": items[0]["combo_no"] if items else None,
        }

    start_combo = (page - 1) * per_page + 1
    items = _fetch_from_parts(start_combo, per_page)
    total_pages = max(1, (TOTAL_COMBOS + per_page - 1) // per_page)
    return {
        "items": items,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "total": TOTAL_COMBOS,
        "winners_only": False,
        "combo_total": TOTAL_COMBOS,
        "start_combo_no": start_combo,
    }


def fetch_combo_range(
    start: int,
    count: int,
    *,
    winners_only: bool = False,
) -> dict[str, Any]:
    """하위 호환: start/count → page 변환."""
    count = max(1, min(int(count), 500))
    if winners_only:
        items = _fetch_winners_page(max(0, int(start) - 1), count)
        total = get_meta()["winners"]
        return {
            "items": items,
            "start": start,
            "count": len(items),
            "total": total,
            "winners_only": True,
            "combo_total": TOTAL_COMBOS,
        }
    items = _fetch_from_parts(int(start), count)
    return {
        "items": items,
        "start": start,
        "count": len(items),
        "total": TOTAL_COMBOS,
        "winners_only": False,
        "combo_total": TOTAL_COMBOS,
    }


def fetch_combo_jump(combo_no: int, *, per_page: int = 120) -> dict[str, Any]:
    cno = int(combo_no)
    if cno < 1 or cno > TOTAL_COMBOS:
        return {"error": "not_found", "combo_no": cno}
    p = part_no_for_combo(cno)
    conn = open_part(p)
    try:
        row = conn.execute(
            f"SELECT * FROM {TABLE} WHERE combo_no = ?",
            (cno,),
        ).fetchone()
        if not row:
            return {"error": "not_found", "combo_no": cno}
        item = row_to_item(row)
        per = max(1, min(int(per_page), 500))
        result: dict[str, Any] = {
            "item": item,
            "combo_total": TOTAL_COMBOS,
            "part": p,
            "page": combo_no_to_page(cno, per),
        }
        if item.get("is_winner"):
            result["winner_page"] = winner_page_for_combo(cno, per)
        return result
    finally:
        conn.close()


def search_combo_by_combo_no(combo_no: int, *, per_page: int = 120) -> dict[str, Any]:
    cno = int(combo_no)
    if cno < 1 or cno > TOTAL_COMBOS:
        return {"error": "not_found", "combo_no": cno}
    result = fetch_combo_jump(cno, per_page=per_page)
    if "error" in result:
        return result
    per = max(1, min(int(per_page), 500))
    return {
        "combo_no": cno,
        "combo_total": TOTAL_COMBOS,
        "item": result["item"],
        "part": result.get("part"),
        "page": result.get("page"),
        "winner_page": result.get("winner_page"),
    }


def search_combo_by_numbers(
    nums: list[int] | tuple[int, ...],
    *,
    per_page: int = 120,
) -> dict[str, Any]:
    cno = combo_to_no(nums)
    result = fetch_combo_jump(cno, per_page=per_page)
    if "error" in result:
        return result
    per = max(1, min(int(per_page), 500))
    return {
        "combo_no": cno,
        "combo_total": TOTAL_COMBOS,
        "item": result["item"],
        "part": result.get("part"),
        "page": combo_no_to_page(cno, per),
        "winner_page": result.get("winner_page"),
    }


# 하위 호환 별칭
build_all_combos = build_all_combos_parts
