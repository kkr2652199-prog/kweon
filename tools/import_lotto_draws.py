"""One-off: copy lotto_draws schema + rows from source DB to dest DB. No hardcoded paths."""

from __future__ import annotations

import sqlite3
import sys


def main() -> None:
    if len(sys.argv) != 3:
        print("usage: python import_lotto_draws.py SRC_DB DEST_DB", file=sys.stderr)
        sys.exit(2)
    src_p, dest_p = sys.argv[1], sys.argv[2]
    src = sqlite3.connect(f"file:{src_p}?mode=ro", uri=True)
    dest = sqlite3.connect(dest_p)
    try:
        row = src.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='lotto_draws'"
        ).fetchone()
        if not row or not row[0]:
            raise SystemExit("source has no lotto_draws table")
        dest.executescript(row[0])
        dest.commit()
        dest.execute("DELETE FROM lotto_draws")
        cols = [r[1] for r in src.execute("PRAGMA table_info(lotto_draws)").fetchall()]
        col_list = ",".join(cols)
        ph = ",".join(["?"] * len(cols))
        q_in = f"SELECT {col_list} FROM lotto_draws"
        q_out = f"INSERT INTO lotto_draws ({col_list}) VALUES ({ph})"
        batch = src.execute(q_in).fetchall()
        dest.executemany(q_out, batch)
        dest.commit()
        n = dest.execute("SELECT COUNT(*) FROM lotto_draws").fetchone()[0]
        print("lotto_draws rows:", n)
    finally:
        src.close()
        dest.close()


if __name__ == "__main__":
    main()
