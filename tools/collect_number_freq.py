"""lotto_draws 메인 6개 번호 출현 빈도·순위 → lotto_number_freq."""

from __future__ import annotations

import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.lotto4.models import LOTTO_DB_PATH  # noqa: E402


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS lotto_number_freq (
            number INTEGER PRIMARY KEY,
            total_count INTEGER NOT NULL DEFAULT 0,
            rank_most INTEGER,
            rank_least INTEGER,
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        """
    )


def main() -> None:
    conn = sqlite3.connect(str(LOTTO_DB_PATH))
    try:
        _ensure_table(conn)
        rows = conn.execute(
            """
            SELECT num1, num2, num3, num4, num5, num6
            FROM lotto_draws
            """
        ).fetchall()

        ctr: Counter[int] = Counter()
        for tup in rows:
            for x in tup:
                try:
                    n = int(x)
                except (TypeError, ValueError):
                    continue
                if 1 <= n <= 45:
                    ctr[n] += 1

        for n in range(1, 46):
            if n not in ctr:
                ctr[n] = 0

        by_desc = sorted(ctr.items(), key=lambda kv: (-kv[1], kv[0]))
        by_asc = sorted(ctr.items(), key=lambda kv: (kv[1], kv[0]))
        rank_most = {}
        for r, (n, _) in enumerate(by_desc, start=1):
            rank_most[n] = r
        rank_least = {}
        for r, (n, _) in enumerate(by_asc, start=1):
            rank_least[n] = r

        conn.execute("DELETE FROM lotto_number_freq")
        conn.executemany(
            """
            INSERT INTO lotto_number_freq
                (number, total_count, rank_most, rank_least, updated_at)
            VALUES (?, ?, ?, ?, datetime('now','localtime'))
            """,
            [
                (n, ctr[n], rank_most[n], rank_least[n])
                for n in range(1, 46)
            ],
        )
        conn.commit()
        print("lotto_number_freq rows:", 45)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
