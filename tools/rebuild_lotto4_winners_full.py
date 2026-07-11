"""lotto_draws(+1등 정보) → lotto4_winners_full 재구축."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DB = _ROOT / "data" / "lotto4.db"

ERA_A = (1, 87)
ERA_B = (88, 261)


def era_label(drw_no: int) -> str:
    if drw_no <= ERA_A[1]:
        return "A"
    if drw_no <= ERA_B[1]:
        return "B"
    return "C"


def rebuild() -> dict:
    conn = sqlite3.connect(DB)
    try:
        conn.executescript(
            """
            DROP TABLE IF EXISTS lotto4_winners_full;
            CREATE TABLE lotto4_winners_full (
                drw_no INTEGER PRIMARY KEY,
                n1 INTEGER NOT NULL, n2 INTEGER NOT NULL, n3 INTEGER NOT NULL,
                n4 INTEGER NOT NULL, n5 INTEGER NOT NULL, n6 INTEGER NOT NULL,
                bonus INTEGER NOT NULL,
                winner_cnt INTEGER NOT NULL,
                prize_per INTEGER NOT NULL,
                era TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            );
            """
        )
        rows = conn.execute(
            """
            SELECT draw_no, num1, num2, num3, num4, num5, num6, bonus,
                   first_winners, first_prize
            FROM lotto_draws
            ORDER BY draw_no
            """
        ).fetchall()
        conn.executemany(
            """
            INSERT INTO lotto4_winners_full (
                drw_no, n1, n2, n3, n4, n5, n6, bonus, winner_cnt, prize_per, era
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7],
                    int(r[8] or 0), int(r[9] or 0), era_label(int(r[0])),
                )
                for r in rows
            ],
        )
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM lotto4_winners_full").fetchone()[0]
        era_c = conn.execute(
            "SELECT COUNT(*) FROM lotto4_winners_full WHERE era='C'"
        ).fetchone()[0]
        return {"total": total, "era_c": era_c, "max_drw": rows[-1][0] if rows else 0}
    finally:
        conn.close()


if __name__ == "__main__":
    import json
    print(json.dumps(rebuild(), ensure_ascii=False))
