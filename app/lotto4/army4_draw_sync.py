"""lotto_draws 확정 후 lotto_predictions_army4 적중·보너스 갱신 (4군 전용)."""

from __future__ import annotations


def refresh_army4_predictions_for_draw(draw_no: int) -> dict:
    from app.lotto4.models import get_lotto4_db

    conn = get_lotto4_db()
    try:
        dr = conn.execute("SELECT * FROM lotto_draws WHERE draw_no = ?", (draw_no,)).fetchone()
        if not dr:
            return {"ok": False, "error": "no_draw", "updated": 0}
        d = dict(dr)
        actual = {d["num1"], d["num2"], d["num3"], d["num4"], d["num5"], d["num6"]}
        bonus = int(d["bonus"])
        rows = conn.execute(
            """
            SELECT id, num1, num2, num3, num4, num5, num6
            FROM lotto_predictions_army4
            WHERE target_draw_no = ?
            """,
            (draw_no,),
        ).fetchall()
        n = 0
        for p in rows:
            pr = {p["num1"], p["num2"], p["num3"], p["num4"], p["num5"], p["num6"]}
            matched = len(pr & actual)
            bonus_matched = 1 if bonus in pr else 0
            conn.execute(
                """
                UPDATE lotto_predictions_army4
                SET matched_count = ?, bonus_matched = ?
                WHERE id = ?
                """,
                (matched, bonus_matched, p["id"]),
            )
            n += 1
        conn.commit()
        return {"ok": True, "updated": n, "draw_no": draw_no}
    finally:
        conn.close()
