"""회차별 1~5등 당첨 정보 — DB 그릇·lt645 수집."""

from __future__ import annotations

import logging
import time
import json
from typing import Any

from app.lotto.data_service import _fetch_from_dhlottery_lt645
from app.testlotto.models import get_lotto_db, init_testlotto_db

logger = logging.getLogger(__name__)

TIER_LABELS: dict[int, str] = {
    1: "1등",
    2: "2등",
    3: "3등",
    4: "4등",
    5: "5등",
}

TIER_MATCH_HINT: dict[int, str] = {
    1: "6개 일치",
    2: "5개 + 보너스",
    3: "5개 일치",
    4: "4개 일치",
    5: "3개 일치",
}


def upsert_prize_tiers(draw_no: int, tiers: list[dict[str, Any]], *, source: str = "lt645") -> int:
    """등수별 행 저장. 반환: 저장된 행 수."""
    conn = get_lotto_db()
    n = 0
    try:
        for t in tiers:
            rank = int(t.get("tier_rank") or 0)
            if rank < 1 or rank > 5:
                continue
            conn.execute(
                """
                INSERT INTO testlotto_draw_prize_tiers (
                    draw_no, tier_rank, winner_count, prize_per_game, total_prize,
                    source, detail_json, updated_at
                ) VALUES (?,?,?,?,?,?,?, datetime('now','localtime'))
                ON CONFLICT(draw_no, tier_rank) DO UPDATE SET
                    winner_count=excluded.winner_count,
                    prize_per_game=excluded.prize_per_game,
                    total_prize=excluded.total_prize,
                    source=excluded.source,
                    detail_json=excluded.detail_json,
                    updated_at=excluded.updated_at
                """,
                (
                    draw_no,
                    rank,
                    int(t.get("winner_count") or 0),
                    int(t.get("prize_per_game") or 0),
                    int(t.get("total_prize") or 0),
                    source,
                    json.dumps(
                        {
                            "tier_label": t.get("tier_label") or TIER_LABELS.get(rank, f"{rank}등"),
                            "match_hint": t.get("match_hint") or TIER_MATCH_HINT.get(rank, ""),
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def fetch_and_save_tiers(draw_no: int) -> dict[str, Any]:
    """lt645 API → DB 저장."""
    init_testlotto_db()
    raw = _fetch_from_dhlottery_lt645(draw_no)
    if not raw:
        return {"draw_no": draw_no, "ok": False, "reason": "lt645 조회 실패"}
    tiers = raw.get("tiers") or []
    saved = upsert_prize_tiers(draw_no, tiers, source=raw.get("source", "lt645"))

    conn = get_lotto_db()
    try:
        conn.execute(
            """
            UPDATE lotto_draws SET
                draw_date = COALESCE(?, draw_date),
                total_sales = CASE WHEN ? > 0 THEN ? ELSE total_sales END,
                first_prize = CASE WHEN ? > 0 THEN ? ELSE first_prize END,
                first_winners = CASE WHEN ? > 0 THEN ? ELSE first_winners END
            WHERE draw_no = ?
            """,
            (
                raw.get("draw_date"),
                int(raw.get("total_sales") or 0),
                int(raw.get("total_sales") or 0),
                int(raw.get("first_prize") or 0),
                int(raw.get("first_prize") or 0),
                int(raw.get("first_winners") or 0),
                int(raw.get("first_winners") or 0),
                draw_no,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return {"draw_no": draw_no, "ok": True, "saved_tiers": saved, "tiers": tiers}


def _tiers_from_draw_row(draw: dict) -> list[dict[str, Any]]:
    """DB에 tier 없을 때 1등만 lotto_draws에서 복원."""
    fp = int(draw.get("first_prize") or 0)
    fw = int(draw.get("first_winners") or 0)
    if fp <= 0 and fw <= 0:
        return []
    return [
        {
            "tier_rank": 1,
            "tier_label": "1등",
            "match_hint": TIER_MATCH_HINT[1],
            "winner_count": fw,
            "prize_per_game": fp,
            "total_prize": fp * fw if fp and fw else 0,
            "source": "lotto_draws_fallback",
        }
    ]


def get_prize_tiers(draw_no: int, *, auto_fetch: bool = True) -> list[dict[str, Any]]:
    """회차 등수표 — 없으면 lt645 1회 시도 후 1등 fallback."""
    init_testlotto_db()
    conn = get_lotto_db()
    try:
        rows = conn.execute(
            """
            SELECT tier_rank, winner_count, prize_per_game, total_prize, source
            FROM testlotto_draw_prize_tiers
            WHERE draw_no = ?
            ORDER BY tier_rank
            """,
            (draw_no,),
        ).fetchall()
        if not rows and auto_fetch:
            conn.close()
            fetch_and_save_tiers(draw_no)
            conn = get_lotto_db()
            rows = conn.execute(
                """
                SELECT tier_rank, winner_count, prize_per_game, total_prize, source
                FROM testlotto_draw_prize_tiers
                WHERE draw_no = ?
                ORDER BY tier_rank
                """,
                (draw_no,),
            ).fetchall()

        if rows:
            out = []
            for r in rows:
                d = dict(r)
                rank = int(d["tier_rank"])
                out.append(
                    {
                        "tier_rank": rank,
                        "tier_label": TIER_LABELS.get(rank, f"{rank}등"),
                        "match_hint": TIER_MATCH_HINT.get(rank, ""),
                        "winner_count": int(d.get("winner_count") or 0),
                        "prize_per_game": int(d.get("prize_per_game") or 0),
                        "total_prize": int(d.get("total_prize") or 0),
                        "source": d.get("source") or "",
                    }
                )
            return out

        draw = conn.execute("SELECT * FROM lotto_draws WHERE draw_no = ?", (draw_no,)).fetchone()
        if draw:
            return _tiers_from_draw_row(dict(draw))
        return []
    finally:
        conn.close()


def sync_prize_tiers_range(
    start: int,
    end: int,
    *,
    sleep_sec: float = 0.35,
) -> dict[str, Any]:
    """구간 백필 (lt645)."""
    init_testlotto_db()
    ok, fail = 0, 0
    for draw_no in range(start, end + 1):
        conn = get_lotto_db()
        exists = conn.execute(
            "SELECT COUNT(*) FROM lotto_draws WHERE draw_no = ?", (draw_no,)
        ).fetchone()[0]
        conn.close()
        if not exists:
            fail += 1
            continue
        res = fetch_and_save_tiers(draw_no)
        if res.get("ok"):
            ok += 1
        else:
            fail += 1
        if sleep_sec:
            time.sleep(sleep_sec)
    return {"start": start, "end": end, "synced": ok, "failed": fail}
