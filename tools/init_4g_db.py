from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.lotto.models import init_lotto_db  # noqa: E402
from app.lotto2.models import init_lotto2_db  # noqa: E402
from app.lotto4.models import init_lotto4_db  # noqa: E402
from app.lotto4.v13_weights_v2 import init_v13_v2_seeds  # noqa: E402


def main() -> None:
    init_lotto_db()
    init_lotto2_db()
    init_lotto4_db()
    init_v13_v2_seeds()
    db = ROOT / "data" / "lotto4.db"
    conn = sqlite3.connect(str(db))
    try:
        n = conn.execute("SELECT COUNT(*) FROM lotto_draws").fetchone()[0]
        print("lotto_draws", n)
        rows = conn.execute(
            "SELECT COUNT(*) FROM lotto_brain_weights_army4 WHERE brain_tag LIKE 'v13_%'"
        ).fetchone()[0]
        print("v13 weight rows", rows)
        log = conn.execute(
            "SELECT COUNT(*) FROM lotto_weight_log_army4 WHERE draw_no = 0 AND brain_tag LIKE 'v13_%'"
        ).fetchone()[0]
        print("v13 log draw0", log)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
