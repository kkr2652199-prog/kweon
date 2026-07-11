"""cooccur 2·3·4 walk-forward 슬라이스 — draw_no < cutoff 만 집계 (R13).

기존 lotto_cooccur_2/3/4 정적 테이블은 변경하지 않음.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

from app.lotto4.models import LOTTO_DB_PATH

CooccurEntry = dict[str, Any]


def _aggregate_from_draws(
    rows: list[tuple],
) -> tuple[
    dict[tuple[int, int], int],
    dict[tuple[int, int, int], int],
    dict[tuple[int, int, int, int], int],
    dict[tuple[int, int], tuple[int, str | None]],
    dict[tuple[int, int, int], tuple[int, str | None]],
    dict[tuple[int, int, int, int], tuple[int, str | None]],
]:
    c2: dict[tuple[int, int], int] = defaultdict(int)
    c3: dict[tuple[int, int, int], int] = defaultdict(int)
    c4: dict[tuple[int, int, int, int], int] = defaultdict(int)
    last2: dict[tuple[int, int], tuple[int, str | None]] = {}
    last3: dict[tuple[int, int, int], tuple[int, str | None]] = {}
    last4: dict[tuple[int, int, int, int], tuple[int, str | None]] = {}

    for draw_no, draw_date, *nums in rows:
        try:
            six = sorted(int(x) for x in nums)
        except (TypeError, ValueError):
            continue
        if len(six) != 6 or any(n < 1 or n > 45 for n in six):
            continue
        ds = str(draw_date) if draw_date is not None else None
        dn = int(draw_no)

        for a, b in combinations(six, 2):
            pair = (a, b)
            c2[pair] += 1
            last2[pair] = (dn, ds)
        for a, b, c in combinations(six, 3):
            tri = (a, b, c)
            c3[tri] += 1
            last3[tri] = (dn, ds)
        for quad in combinations(six, 4):
            c4[quad] += 1
            last4[quad] = (dn, ds)

    return c2, c3, c4, last2, last3, last4


def _to_sorted_entries(
    counts: dict,
    last_map: dict,
    top_n: int | None,
) -> list[CooccurEntry]:
    entries: list[CooccurEntry] = []
    for key, cnt in counts.items():
        last_no, last_date = last_map.get(key, (None, None))
        entries.append(
            {
                "nums": list(key),
                "count": int(cnt),
                "last_draw_no": last_no,
                "last_draw_date": last_date,
            }
        )
    entries.sort(
        key=lambda e: (
            -(e["last_draw_no"] or 0),
            -int(e["count"]),
            tuple(e["nums"]),
        )
    )
    if top_n is not None:
        return entries[:top_n]
    return entries


def aggregate_cooccur_before(
    cutoff_draw_no: int,
    db_path: str | Path | None = None,
    top_n: int | None = None,
) -> dict[str, Any]:
    """cutoff_draw_no 미만 회차만으로 cooccur 2·3·4 동적 집계 (R13).

    Args:
        cutoff_draw_no: target 회차 N — draw_no < N 인 데이터만 사용.
        db_path: SQLite 경로 (기본 lotto4.db).
        top_n: 상위 N개만 반환 (None이면 전체).

    Returns:
        dict with cooccur_2/3/4 lists, cutoff_draw_no, draw_count.
    """
    path = Path(db_path) if db_path is not None else LOTTO_DB_PATH
    cutoff = int(cutoff_draw_no)
    conn = sqlite3.connect(str(path))
    try:
        rows = conn.execute(
            """
            SELECT draw_no, draw_date, num1, num2, num3, num4, num5, num6
            FROM lotto_draws
            WHERE draw_no < ?
            ORDER BY draw_no ASC
            """,
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()

    c2, c3, c4, last2, last3, last4 = _aggregate_from_draws(rows)

    return {
        "cutoff_draw_no": cutoff,
        "draw_count": len(rows),
        "max_draw_no": max((int(r[0]) for r in rows), default=None),
        "cooccur_2": _to_sorted_entries(c2, last2, top_n),
        "cooccur_3": _to_sorted_entries(c3, last3, top_n),
        "cooccur_4": _to_sorted_entries(c4, last4, top_n),
        "cooccur_2_total": len(c2),
        "cooccur_3_total": len(c3),
        "cooccur_4_total": len(c4),
    }
