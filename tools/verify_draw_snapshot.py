#!/usr/bin/env python3
"""draw_snapshot / analysis_board API 검증 (READ ONLY)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.testlotto.detail_service import get_draw_detail
from app.testlotto.draw_snapshot import build_analysis_board, build_snapshot_context
from app.testlotto.data_service import _get_draws_before


REQUIRED_KEYS = {
    "freq_grid",
    "freq_recent",
    "hot_top5",
    "cold_top5",
    "spike_nums",
    "cold_comeback",
    "zone6",
    "zone5_color",
    "consecutive_runs",
    "pairs_in_draw",
    "pair_hot_hits",
    "bonus_profile",
    "sum_total",
    "odd_count",
    "even_count",
    "ac_value",
    "ending_digits",
}


def check_draw(draw_no: int) -> dict:
    detail = get_draw_detail(draw_no)
    if detail.get("error"):
        return {"draw_no": draw_no, "ok": False, "error": detail["error"]}

    board = detail.get("analysis_board")
    if not board:
        return {"draw_no": draw_no, "ok": False, "error": "analysis_board missing"}

    missing = REQUIRED_KEYS - set(board.keys())
    if missing:
        return {"draw_no": draw_no, "ok": False, "error": f"missing keys: {sorted(missing)}"}

    if len(board.get("freq_grid") or []) != 45:
        return {"draw_no": draw_no, "ok": False, "error": "freq_grid len != 45"}

    if len(board.get("zone6") or []) != 6:
        return {"draw_no": draw_no, "ok": False, "error": "zone6 len != 6"}

    if len(board.get("zone5_color") or []) != 5:
        return {"draw_no": draw_no, "ok": False, "error": "zone5_color len != 5"}

    # 직접 계산과 API 일치
    draws_before = _get_draws_before(draw_no)
    draw_row = {
        "draw_no": draw_no,
        **{f"num{i}": n for i, n in enumerate(detail["actual_nums"], 1)},
        "bonus": detail.get("bonus"),
    }
    direct = build_analysis_board(
        draw_no,
        detail["actual_nums"],
        int(detail.get("bonus") or 0),
        draws_before + [draw_row],
    )
    if direct["sum_total"] != board["sum_total"]:
        return {
            "draw_no": draw_no,
            "ok": False,
            "error": f"sum mismatch direct={direct['sum_total']} api={board['sum_total']}",
        }

    ctx = build_snapshot_context(draws_before)
    wrong = (detail.get("brains") or [{}])[0].get("wrong_note") or {}
    explains = wrong.get("num_explains") or []
    has_snapshot_tag = any(
        any(t in ("급등", "HOT", "1구간", "2구간", "3구간", "4구간", "5구간", "6구간", "핫쌍", "장기미출") for t in (e.get("tags") or []))
        for e in explains
    )

    return {
        "draw_no": draw_no,
        "ok": True,
        "sum": board["sum_total"],
        "hot_top5": [x["num"] for x in board["hot_top5"]],
        "spike_nums": board["spike_nums"],
        "zone6_counts": [z["count"] for z in board["zone6"]],
        "snapshot_ctx_keys": sorted(ctx.keys()) if ctx else [],
        "wrong_note_snapshot_tags": has_snapshot_tag,
    }


def main() -> int:
    targets = [1228, 1231]
    if len(sys.argv) > 1:
        targets = [int(x) for x in sys.argv[1:]]
    all_ok = True
    for draw_no in targets:
        r = check_draw(draw_no)
        print(json.dumps(r, ensure_ascii=False))
        if not r.get("ok"):
            all_ok = False
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
