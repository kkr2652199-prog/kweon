"""동반출현 2·3·4 — 최신 회차순 정리 → JSON + lotto_analysis_army4."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DB = _ROOT / "data" / "lotto4.db"
OUT = _ROOT / "tools" / "_cooccur_latest.json"
TOP_N = 200


def _fetch_sorted(conn: sqlite3.Connection, table: str, cols: int) -> list[dict]:
    num_cols = ", ".join(f"num{i}" for i in range(1, cols + 1))
    rows = conn.execute(
        f"""
        SELECT {num_cols}, count, last_draw_no, last_draw_date
        FROM {table}
        ORDER BY last_draw_no DESC, count DESC
        LIMIT ?
        """,
        (TOP_N,),
    ).fetchall()
    out = []
    for r in rows:
        nums = [int(r[i]) for i in range(cols)]
        out.append(
            {
                "nums": nums,
                "count": int(r[cols]),
                "last_draw_no": int(r[cols + 1]) if r[cols + 1] is not None else None,
                "last_draw_date": r[cols + 2],
            }
        )
    return out


def export() -> dict:
    conn = sqlite3.connect(DB)
    try:
        result = {
            "sorted_by": "last_draw_no DESC, count DESC",
            "top_n": TOP_N,
            "cooccur_2": _fetch_sorted(conn, "lotto_cooccur_2", 2),
            "cooccur_3": _fetch_sorted(conn, "lotto_cooccur_3", 3),
            "cooccur_4": _fetch_sorted(conn, "lotto_cooccur_4", 4),
        }
        for size in (2, 3, 4):
            key = f"cooccur_{size}"
            result[f"{key}_total_rows"] = conn.execute(
                f"SELECT COUNT(*) FROM lotto_cooccur_{size}"
            ).fetchone()[0]

        payload = json.dumps(result, ensure_ascii=False)
        OUT.write_text(payload, encoding="utf-8")

        conn.execute(
            "DELETE FROM lotto_analysis_army4 WHERE analysis_type = 'cooccur_latest'"
        )
        conn.execute(
            """
            INSERT INTO lotto_analysis_army4 (draw_no, analysis_type, data_json)
            VALUES (?, 'cooccur_latest', ?)
            """,
            (result["cooccur_2"][0]["last_draw_no"] if result["cooccur_2"] else 0, payload),
        )
        conn.commit()
        return result
    finally:
        conn.close()


if __name__ == "__main__":
    data = export()
    print(json.dumps({
        "ok": True,
        "out": str(OUT),
        "cooccur_2_top": data["cooccur_2"][:3],
        "cooccur_3_top": data["cooccur_3"][:3],
        "cooccur_4_top": data["cooccur_4"][:3],
        "totals": {
            k: data.get(f"{k}_total_rows")
            for k in ("cooccur_2", "cooccur_3", "cooccur_4")
        },
    }, ensure_ascii=False, indent=2))
