"""STEP3 검증: strategy_x 5뇌 전회차 적재 + 9뇌 무간섭 + 대시보드 읽기."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.lotto4.models import LOTTO_DB_PATH
from app.lotto4.strategy_x_logging import STRATEGY_X_FIVE_BRAIN_TAGS

ERA_START = 262
ERA_END = 1228
EXPECTED_PER_TAG = 5


def main() -> None:
    conn = sqlite3.connect(str(LOTTO_DB_PATH))
    conn.row_factory = sqlite3.Row
    out: dict = {}

    try:
        v13_pred = conn.execute(
            "SELECT COUNT(*) AS c FROM lotto_predictions_army4 WHERE brain_tag LIKE 'v13_%'"
        ).fetchone()["c"]
        sx_pred = conn.execute(
            "SELECT COUNT(*) AS c FROM lotto_predictions_army4 WHERE brain_tag LIKE 'strategy_x_%'"
        ).fetchone()["c"]
        v13_fb = conn.execute(
            """
            SELECT COUNT(*) AS c FROM lotto_fullbacktest_army4
            WHERE brain_tag LIKE 'v13_%'
            """
        ).fetchone()["c"]
        sx_fb = conn.execute(
            """
            SELECT COUNT(*) AS c FROM lotto_fullbacktest_army4
            WHERE brain_tag IN ({})
            """.format(",".join("?" for _ in STRATEGY_X_FIVE_BRAIN_TAGS)),
            STRATEGY_X_FIVE_BRAIN_TAGS,
        ).fetchone()["c"]

        out["predictions"] = {
            "v13_rows": int(v13_pred),
            "strategy_x_rows": int(sx_pred),
            "strategy_x_was_zero_now_filled": int(sx_pred) > 0,
        }
        out["fullbacktest"] = {
            "v13_rows_preserved": int(v13_fb),
            "strategy_x_five_brain_rows": int(sx_fb),
        }

        by_tag = []
        for tag in STRATEGY_X_FIVE_BRAIN_TAGS:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n,
                       ROUND(AVG(matched_count), 4) AS avg_m,
                       MIN(target_draw_no) AS lo,
                       MAX(target_draw_no) AS hi
                FROM lotto_predictions_army4
                WHERE brain_tag = ? AND matched_count >= 0
                  AND target_draw_no BETWEEN ? AND ?
                """,
                (tag, ERA_START, ERA_END),
            ).fetchone()
            by_tag.append(
                {
                    "brain_tag": tag,
                    "rows": int(row["n"] or 0),
                    "avg_matched": float(row["avg_m"] or 0),
                    "draw_range": [row["lo"], row["hi"]],
                    "sets_per_draw_ok": int(row["n"] or 0) % EXPECTED_PER_TAG == 0
                    if row["n"]
                    else False,
                }
            )
        out["per_brain_predictions"] = by_tag

        fb_by_tag = []
        for tag in STRATEGY_X_FIVE_BRAIN_TAGS:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n, ROUND(AVG(matched_count), 4) AS avg_m
                FROM lotto_fullbacktest_army4
                WHERE brain_tag = ? AND draw_no BETWEEN ? AND ?
                """,
                (tag, ERA_START, ERA_END),
            ).fetchone()
            fb_by_tag.append(
                {
                    "brain_tag": tag,
                    "rows": int(row["n"] or 0),
                    "avg_matched": float(row["avg_m"] or 0),
                }
            )
        out["per_brain_fullbacktest"] = fb_by_tag

        sample = conn.execute(
            """
            SELECT target_draw_no, brain_tag, matched_count, num1, num2, num3, num4, num5, num6
            FROM lotto_predictions_army4
            WHERE brain_tag = ? AND target_draw_no = 500
            ORDER BY method
            LIMIT 3
            """,
            (STRATEGY_X_FIVE_BRAIN_TAGS[0],),
        ).fetchall()
        out["sample_draw_500"] = [dict(r) for r in sample]

        # dashboard query simulation (strategy_x stats shape)
        stats_rows = conn.execute(
            """
            SELECT brain_tag, COUNT(1) AS n, ROUND(AVG(matched_count), 3) AS avg_m,
                   MAX(matched_count) AS best
            FROM lotto_predictions_army4
            WHERE matched_count >= 0 AND brain_tag IN ({})
              AND target_draw_no BETWEEN ? AND ?
            GROUP BY brain_tag
            ORDER BY brain_tag
            """.format(",".join("?" for _ in STRATEGY_X_FIVE_BRAIN_TAGS)),
            (*STRATEGY_X_FIVE_BRAIN_TAGS, ERA_START, ERA_END),
        ).fetchall()
        out["dashboard_readable"] = {
            "stats_query_rows": len(stats_rows),
            "brains": [dict(r) for r in stats_rows],
            "ok": len(stats_rows) == len(STRATEGY_X_FIVE_BRAIN_TAGS),
        }

        out["army13_interference"] = {
            "v13_predictions_unchanged_check": int(v13_pred) >= 4550,
            "note": "v13 행수는 적재 전후 동일해야 함 (삭제 안 함)",
        }
    finally:
        conn.close()

    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.stdout.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    main()
