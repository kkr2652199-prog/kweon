"""lotto_draws에서 보너스 번호 빈도·최근 출현 당첨 6수 패턴 → lotto_bonus_stats."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.lotto4.models import LOTTO_DB_PATH  # noqa: E402


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS lotto_bonus_stats (
            bonus_no INTEGER PRIMARY KEY,
            total_count INTEGER NOT NULL DEFAULT 0,
            last_draw_no INTEGER,
            coappear_with TEXT,
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
            SELECT draw_no, draw_date, num1, num2, num3, num4, num5, num6, bonus
            FROM lotto_draws
            ORDER BY draw_no ASC
            """
        ).fetchall()

        counts: dict[int, int] = {b: 0 for b in range(1, 46)}
        last: dict[int, tuple[int, str | None, list[int]]] = {}

        for draw_no, draw_date, n1, n2, n3, n4, n5, n6, bonus in rows:
            try:
                b = int(bonus)
            except (TypeError, ValueError):
                continue
            if b < 1 or b > 45:
                continue
            try:
                main6 = sorted(int(x) for x in (n1, n2, n3, n4, n5, n6))
            except (TypeError, ValueError):
                continue
            if len(main6) != 6:
                continue
            counts[b] += 1
            ds = str(draw_date) if draw_date is not None else None
            last[b] = (int(draw_no), ds, main6)

        conn.execute("DELETE FROM lotto_bonus_stats")
        for b in range(1, 46):
            cnt = counts.get(b, 0)
            if b in last:
                dr_no, dr_dt, main6 = last[b]
                co = json.dumps(
                    {"last_draw_no": dr_no, "last_draw_date": dr_dt, "main": main6},
                    ensure_ascii=False,
                )
            else:
                dr_no, co = None, None
            conn.execute(
                """
                INSERT INTO lotto_bonus_stats
                    (bonus_no, total_count, last_draw_no, coappear_with, updated_at)
                VALUES (?, ?, ?, ?, datetime('now','localtime'))
                """,
                (b, cnt, dr_no, co),
            )
        conn.commit()
        print(
            "lotto_bonus_stats rows:",
            conn.execute("SELECT COUNT(*) FROM lotto_bonus_stats").fetchone()[0],
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
