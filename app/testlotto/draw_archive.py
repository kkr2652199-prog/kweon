"""동행복권 회차별 정밀 당첨 이력 수집·DB 저장 (lt645 + 판매점)."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import requests

from app.lotto.data_service import _fetch_from_dhlottery_lt645, _parse_lt645_item
from app.testlotto.models import get_lotto_db, init_testlotto_db
from app.testlotto.prize_tiers import TIER_MATCH_HINT, upsert_prize_tiers

logger = logging.getLogger(__name__)

WIN_TYPE_LABELS = {
    0: "기타",
    1: "수동선택",
    2: "자동선택",
    3: "반자동",
}

STORE_POST_URL = "https://www.dhlottery.co.kr/store.do?method=topStore&pageGubun=L645"
GAME_NO = 5133


def _parse_store_html(html: str, draw_no: int, tier_rank: int = 1) -> list[dict[str, Any]]:
    """store.do HTML에서 1등 판매점 파싱 (구형 테이블 구조)."""
    stores: list[dict[str, Any]] = []
    if "tbl_data_col" not in html and "tbl_data" not in html:
        return stores

    blocks = re.split(r"<table[^>]*class=\"[^\"]*tbl_data[^\"]*\"[^>]*>", html, flags=re.I)
    tier_blocks = blocks[1:2] if tier_rank == 1 else blocks[2:3]
    for block in tier_blocks:
        tbody_m = re.search(r"<tbody[^>]*>(.*?)</tbody>", block, re.S | re.I)
        if not tbody_m:
            continue
        for row_m in re.finditer(r"<tr[^>]*>(.*?)</tr>", tbody_m.group(1), re.S | re.I):
            row = row_m.group(1)
            if "nodata" in row.lower():
                continue
            tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)
            clean = [re.sub(r"<[^>]+>", "", t).strip() for t in tds]
            clean = [c for c in clean if c]
            if len(clean) < 2:
                continue
            # [번호, 상호, 구분, 소재지] 또는 [상호, 구분, 소재지]
            if len(clean) >= 4:
                name, method, addr = clean[1], clean[2], clean[3]
            elif len(clean) == 3:
                name, method, addr = clean[0], clean[1], clean[2]
            else:
                name, method, addr = clean[0], "", clean[1] if len(clean) > 1 else ""
            region = addr.split()[0] if addr else ""
            stores.append(
                {
                    "draw_no": draw_no,
                    "tier_rank": tier_rank,
                    "store_name": name,
                    "pick_method": method,
                    "address": addr,
                    "region": region,
                    "source": "store.do",
                }
            )
    return stores


def fetch_win_stores(draw_no: int, *, session: requests.Session | None = None) -> dict[str, Any]:
    """1등 당첨 판매점 조회 (HTML POST, SPA 전환 시 빈 목록 가능)."""
    sess = session or requests.Session()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": STORE_POST_URL,
    }
    try:
        sess.get(STORE_POST_URL, headers=headers, timeout=15)
        post_data = {
            "method": "topStore",
            "nowPage": "1",
            "rankNo": "1",
            "gameNo": str(GAME_NO),
            "drwNo": str(draw_no),
            "schKey": "all",
            "schVal": "",
        }
        resp = sess.post(STORE_POST_URL, data=post_data, headers=headers, timeout=20)
        resp.raise_for_status()
        html = resp.text
        stores = _parse_store_html(html, draw_no, tier_rank=1)
        if stores:
            return {"draw_no": draw_no, "ok": True, "status": "ok", "stores": stores, "note": ""}
        return {
            "draw_no": draw_no,
            "ok": True,
            "status": "pending",
            "stores": [],
            "note": "판매점 HTML 미제공(SPA 전환·구간 미기록 가능)",
        }
    except Exception as e:
        logger.warning("판매점 조회 %d회: %s", draw_no, e)
        return {
            "draw_no": draw_no,
            "ok": False,
            "status": "pending",
            "stores": [],
            "note": str(e),
        }


def upsert_draw_row(parsed: dict[str, Any]) -> None:
    """lotto_draws 갱신."""
    conn = get_lotto_db()
    try:
        conn.execute(
            """
            INSERT INTO lotto_draws (
                draw_no, draw_date, num1, num2, num3, num4, num5, num6, bonus,
                total_sales, first_prize, first_winners
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(draw_no) DO UPDATE SET
                draw_date=excluded.draw_date,
                num1=excluded.num1, num2=excluded.num2, num3=excluded.num3,
                num4=excluded.num4, num5=excluded.num5, num6=excluded.num6,
                bonus=excluded.bonus,
                total_sales=CASE WHEN excluded.total_sales > 0 THEN excluded.total_sales ELSE total_sales END,
                first_prize=CASE WHEN excluded.first_prize > 0 THEN excluded.first_prize ELSE first_prize END,
                first_winners=CASE WHEN excluded.first_winners >= 0 THEN excluded.first_winners ELSE first_winners END
            """,
            (
                parsed["draw_no"],
                parsed["draw_date"],
                parsed["num1"],
                parsed["num2"],
                parsed["num3"],
                parsed["num4"],
                parsed["num5"],
                parsed["num6"],
                parsed["bonus"],
                int(parsed.get("total_sales") or 0),
                int(parsed.get("first_prize") or 0),
                int(parsed.get("first_winners") or 0),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def upsert_draw_detail(draw_no: int, raw: dict[str, Any], parsed: dict[str, Any], store_result: dict[str, Any]) -> None:
    conn = get_lotto_db()
    try:
        conn.execute(
            """
            INSERT INTO testlotto_draw_detail (
                draw_no, draw_date, game_seq_no, total_sales, cumulative_sales, total_winners,
                win_type_0, win_type_1, win_type_2, win_type_3,
                raw_lt645_json, store_fetch_status, store_fetch_note, source, synced_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?, datetime('now','localtime'))
            ON CONFLICT(draw_no) DO UPDATE SET
                draw_date=excluded.draw_date,
                game_seq_no=excluded.game_seq_no,
                total_sales=excluded.total_sales,
                cumulative_sales=excluded.cumulative_sales,
                total_winners=excluded.total_winners,
                win_type_0=excluded.win_type_0,
                win_type_1=excluded.win_type_1,
                win_type_2=excluded.win_type_2,
                win_type_3=excluded.win_type_3,
                raw_lt645_json=excluded.raw_lt645_json,
                store_fetch_status=excluded.store_fetch_status,
                store_fetch_note=excluded.store_fetch_note,
                source=excluded.source,
                synced_at=excluded.synced_at
            """,
            (
                draw_no,
                parsed.get("draw_date"),
                int(raw.get("gmSqNo") or 0),
                int(parsed.get("total_sales") or 0),
                int(raw.get("wholEpsdSumNtslAmt") or 0),
                int(raw.get("sumWnNope") or 0),
                int(raw.get("winType0") or 0),
                int(raw.get("winType1") or 0),
                int(raw.get("winType2") or 0),
                int(raw.get("winType3") or 0),
                json.dumps(raw, ensure_ascii=False),
                store_result.get("status") or "",
                store_result.get("note") or "",
                parsed.get("source") or "lt645",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def upsert_win_stores(draw_no: int, stores: list[dict[str, Any]]) -> int:
    if not stores:
        return 0
    conn = get_lotto_db()
    n = 0
    try:
        conn.execute("DELETE FROM testlotto_draw_win_stores WHERE draw_no = ?", (draw_no,))
        for s in stores:
            conn.execute(
                """
                INSERT OR REPLACE INTO testlotto_draw_win_stores (
                    draw_no, tier_rank, store_name, pick_method, address, region,
                    raw_json, source, updated_at
                ) VALUES (?,?,?,?,?,?,?,?, datetime('now','localtime'))
                """,
                (
                    draw_no,
                    int(s.get("tier_rank") or 1),
                    s.get("store_name") or "",
                    s.get("pick_method") or "",
                    s.get("address") or "",
                    s.get("region") or "",
                    json.dumps(s, ensure_ascii=False),
                    s.get("source") or "store.do",
                ),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def _fetch_lt645_raw(draw_no: int) -> dict[str, Any] | None:
    """lt645 원본 dict (parse 전)."""
    import requests as req_lib

    from app.lotto.data_service import DHLOTTERY_LT645_API, _dhlottery_request_headers

    url = DHLOTTERY_LT645_API.format(draw_no=int(draw_no), ts=int(time.time() * 1000))
    try:
        resp = req_lib.get(url, headers=_dhlottery_request_headers(), timeout=20)
        resp.raise_for_status()
        data = resp.json()
        items = (data.get("data") or {}).get("list") or []
        if not items:
            return None
        item = items[0]
        if int(item.get("ltEpsd") or 0) != int(draw_no):
            return None
        return item
    except Exception as e:
        logger.warning("lt645 raw %d회: %s", draw_no, e)
        return None


def fetch_and_save_draw_archive(
    draw_no: int,
    *,
    fetch_stores: bool = True,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """회차 1건 — lt645 정밀 이력 + 등수 + 판매점(가능 시) 저장."""
    try:
        init_testlotto_db()
        raw = _fetch_lt645_raw(draw_no)
        if not raw:
            parsed = _fetch_from_dhlottery_lt645(draw_no)
            if not parsed:
                return {"draw_no": draw_no, "ok": False, "reason": "lt645 조회 실패"}
            raw = {k: parsed.get(k) for k in parsed}
        else:
            parsed = _parse_lt645_item(raw)

        upsert_draw_row(parsed)

        tiers = parsed.get("tiers") or []
        tier_details = []
        for t in tiers:
            rank = int(t["tier_rank"])
            tier_details.append(
                {
                    **t,
                    "tier_label": f"{rank}등",
                    "match_hint": TIER_MATCH_HINT.get(rank, ""),
                }
            )
        saved_tiers = upsert_prize_tiers(draw_no, tier_details, source="lt645")

        store_result: dict[str, Any] = {"status": "skipped", "stores": [], "note": ""}
        if fetch_stores:
            try:
                store_result = fetch_win_stores(draw_no, session=session)
            except Exception as e:
                logger.warning("판매점 처리 %d회: %s", draw_no, e)
                store_result = {
                    "status": "pending",
                    "stores": [],
                    "note": str(e),
                }
        saved_stores = 0
        try:
            saved_stores = upsert_win_stores(draw_no, store_result.get("stores") or [])
        except Exception as e:
            logger.warning("판매점 저장 %d회: %s", draw_no, e)
            store_result["status"] = "pending"
            store_result["note"] = (store_result.get("note") or "") + f" | save:{e}"

        upsert_draw_detail(draw_no, raw, parsed, store_result)

        return {
            "draw_no": draw_no,
            "ok": True,
            "draw_date": parsed.get("draw_date"),
            "total_sales": parsed.get("total_sales"),
            "first_winners": parsed.get("first_winners"),
            "saved_tiers": saved_tiers,
            "saved_stores": saved_stores,
            "store_status": store_result.get("status"),
            "store_note": store_result.get("note"),
            "win_types": {
                WIN_TYPE_LABELS[i]: int(raw.get(f"winType{i}") or 0) for i in range(4)
            },
        }
    except Exception as e:
        logger.exception("archive %d회 저장 실패", draw_no)
        return {"draw_no": draw_no, "ok": False, "reason": str(e)}


def sync_draw_archive_range(
    start: int,
    end: int,
    *,
    fetch_stores: bool = True,
    sleep_sec: float = 0.4,
) -> dict[str, Any]:
    """구간 백필."""
    init_testlotto_db()
    sess = requests.Session()
    ok, fail, store_ok, store_pending = 0, 0, 0, 0
    results: list[dict[str, Any]] = []
    for draw_no in range(start, end + 1):
        try:
            res = fetch_and_save_draw_archive(draw_no, fetch_stores=fetch_stores, session=sess)
        except Exception as e:
            logger.exception("archive 구간 %d회 예외", draw_no)
            res = {"draw_no": draw_no, "ok": False, "reason": str(e)}
        results.append(res)
        if res.get("ok"):
            ok += 1
            st = res.get("store_status")
            if st == "ok" and (res.get("saved_stores") or 0) > 0:
                store_ok += 1
            elif st in ("pending", "empty", "error"):
                store_pending += 1
        else:
            fail += 1
        if sleep_sec:
            time.sleep(sleep_sec)
    return {
        "start": start,
        "end": end,
        "synced": ok,
        "failed": fail,
        "store_ok": store_ok,
        "store_pending": store_pending,
        "items": results,
    }


def get_draw_archive(draw_no: int) -> dict[str, Any]:
    """회차 정밀 이력 조회."""
    init_testlotto_db()
    conn = get_lotto_db()
    try:
        detail = conn.execute(
            "SELECT * FROM testlotto_draw_detail WHERE draw_no = ?", (draw_no,)
        ).fetchone()
        tiers = conn.execute(
            """
            SELECT tier_rank, winner_count, prize_per_game, total_prize, source, detail_json
            FROM testlotto_draw_prize_tiers WHERE draw_no = ? ORDER BY tier_rank
            """,
            (draw_no,),
        ).fetchall()
        stores = conn.execute(
            """
            SELECT tier_rank, store_name, pick_method, address, region, source
            FROM testlotto_draw_win_stores WHERE draw_no = ? ORDER BY tier_rank, store_name
            """,
            (draw_no,),
        ).fetchall()
        draw = conn.execute("SELECT * FROM lotto_draws WHERE draw_no = ?", (draw_no,)).fetchone()
        if not detail and not draw:
            return {"error": f"{draw_no}회 데이터 없음"}

        d = dict(detail) if detail else {}
        win_types = {
            WIN_TYPE_LABELS[i]: int(d.get(f"win_type_{i}") or 0) for i in range(4)
        }
        return {
            "draw_no": draw_no,
            "draw_date": d.get("draw_date") or (dict(draw).get("draw_date") if draw else ""),
            "actual_nums": (
                sorted(
                    [
                        int(dict(draw)[f"num{i}"])
                        for i in range(1, 7)
                    ]
                )
                if draw
                else []
            ),
            "bonus": int(dict(draw)["bonus"]) if draw else 0,
            "total_sales": int(d.get("total_sales") or 0),
            "cumulative_sales": int(d.get("cumulative_sales") or 0),
            "total_winners": int(d.get("total_winners") or 0),
            "win_types": win_types,
            "prize_tiers": [
                {
                    "tier_rank": int(r["tier_rank"]),
                    "tier_label": f"{r['tier_rank']}등",
                    "match_hint": TIER_MATCH_HINT.get(int(r["tier_rank"]), ""),
                    "winner_count": int(r["winner_count"] or 0),
                    "prize_per_game": int(r["prize_per_game"] or 0),
                    "total_prize": int(r["total_prize"] or 0),
                }
                for r in tiers
            ],
            "win_stores": [dict(s) for s in stores],
            "store_fetch_status": d.get("store_fetch_status") or "",
            "store_fetch_note": d.get("store_fetch_note") or "",
            "synced_at": d.get("synced_at"),
            "has_raw": bool(d.get("raw_lt645_json")),
        }
    finally:
        conn.close()
