"""lotto_draws에서 2·3·4개 동반출현 집계 → lotto_cooccur_2/3/4."""

from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.lotto4.models import LOTTO_DB_PATH  # noqa: E402


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS lotto_cooccur_2 (
            num1 INTEGER NOT NULL,
            num2 INTEGER NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            last_draw_no INTEGER,
            last_draw_date TEXT,
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (num1, num2)
        );
        CREATE TABLE IF NOT EXISTS lotto_cooccur_3 (
            num1 INTEGER NOT NULL,
            num2 INTEGER NOT NULL,
            num3 INTEGER NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            last_draw_no INTEGER,
            last_draw_date TEXT,
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (num1, num2, num3)
        );
        CREATE TABLE IF NOT EXISTS lotto_cooccur_4 (
            num1 INTEGER NOT NULL,
            num2 INTEGER NOT NULL,
            num3 INTEGER NOT NULL,
            num4 INTEGER NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            last_draw_no INTEGER,
            last_draw_date TEXT,
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (num1, num2, num3, num4)
        );
        """
    )


def main() -> None:
    conn = sqlite3.connect(str(LOTTO_DB_PATH))
    try:
        _ensure_tables(conn)
        rows = conn.execute(
            """
            SELECT draw_no, draw_date, num1, num2, num3, num4, num5, num6
            FROM lotto_draws
            ORDER BY draw_no ASC
            """
        ).fetchall()

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

            for a, b in combinations(six, 2):
                pair = (a, b)
                c2[pair] += 1
                last2[pair] = (int(draw_no), ds)
            for a, b, c in combinations(six, 3):
                tri = (a, b, c)
                c3[tri] += 1
                last3[tri] = (int(draw_no), ds)
            for quad in combinations(six, 4):
                c4[quad] += 1
                last4[quad] = (int(draw_no), ds)

        conn.execute("DELETE FROM lotto_cooccur_2")
        conn.execute("DELETE FROM lotto_cooccur_3")
        conn.execute("DELETE FROM lotto_cooccur_4")
        conn.executemany(
            """
            INSERT INTO lotto_cooccur_2
                (num1, num2, count, last_draw_no, last_draw_date, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now','localtime'))
            """,
            [
                (*pair, c2[pair], last2[pair][0], last2[pair][1])
                for pair in sorted(c2.keys())
            ],
        )
        conn.executemany(
            """
            INSERT INTO lotto_cooccur_3
                (num1, num2, num3, count, last_draw_no, last_draw_date, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now','localtime'))
            """,
            [
                (*tri, c3[tri], last3[tri][0], last3[tri][1])
                for tri in sorted(c3.keys())
            ],
        )
        conn.executemany(
            """
            INSERT INTO lotto_cooccur_4
                (num1, num2, num3, num4, count, last_draw_no, last_draw_date, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
            """,
            [
                (*quad, c4[quad], last4[quad][0], last4[quad][1])
                for quad in sorted(c4.keys())
            ],
        )
        conn.commit()

        n2 = conn.execute("SELECT COUNT(*) FROM lotto_cooccur_2").fetchone()[0]
        n3 = conn.execute("SELECT COUNT(*) FROM lotto_cooccur_3").fetchone()[0]
        n4 = conn.execute("SELECT COUNT(*) FROM lotto_cooccur_4").fetchone()[0]
        print(f"lotto_cooccur_2 rows: {n2} (max theoret. C(45,2)={990})")
        print(f"lotto_cooccur_3 rows: {n3} (max theoret. C(45,3)={14190})")
        print(f"lotto_cooccur_4 rows: {n4} (max theoret. C(45,4)={148995}, 출현 조합만)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
