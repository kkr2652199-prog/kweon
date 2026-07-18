# -*- coding: utf-8
"""조합결과 저장소(lotto_patterns_testlotto.db) READ-ONLY 열람 인터페이스.

7뇌(lead1)·향후 8뇌가 5뇌 적중 패턴·조합 재료를 조회하는 전용 접근층.
lotto_patterns_testlotto.db만 query_only로 읽으며 원본 lotto_testlotto.db·6뇌는 절대 미접근.
쓰기 금지 — 재료 조회 전용.
"""
from __future__ import annotations

import json
import sqlite3

from app.config import DATA_DIR

PATTERN_DB_PATH = DATA_DIR / "lotto_patterns_testlotto.db"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(PATTERN_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def is_available() -> bool:
    """저장소 구축 여부(테이블 존재) 확인."""
    if not PATTERN_DB_PATH.exists():
        return False
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='draw_combo_summary'"
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_union_numbers(draw_no: int) -> list[dict]:
    """회차 5뇌 합집합 번호 — [{number,k,is_winning}]. READ-ONLY."""
    conn = _conn()
    try:
        rows = conn.execute(
            """
            SELECT number, k_brains AS k, MAX(is_winning) AS is_winning
            FROM brain_number_pick WHERE draw_no=? GROUP BY number ORDER BY number
            """,
            (draw_no,),
        ).fetchall()
        return [
            {"number": int(r["number"]), "k": int(r["k"]),
             "is_winning": int(r["is_winning"])}
            for r in rows
        ]
    finally:
        conn.close()


def get_consensus_numbers(draw_no: int, min_k: int = 3) -> list[int]:
    """합의 번호(k>=min_k) 리스트 — 8뇌 합성 재료. READ-ONLY."""
    conn = _conn()
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT number FROM brain_number_pick
            WHERE draw_no=? AND k_brains>=? ORDER BY number
            """,
            (draw_no, min_k),
        ).fetchall()
        return [int(r["number"]) for r in rows]
    finally:
        conn.close()


def get_ktier_winners(draw_no: int) -> dict[int, int]:
    """회차 k별 당첨(main6) 번호 수 — {k: count}. READ-ONLY."""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT k_brains AS k, winning_count AS c FROM v_ktier_win WHERE draw_no=?",
            (draw_no,),
        ).fetchall()
        return {int(r["k"]): int(r["c"]) for r in rows}
    finally:
        conn.close()


def get_draw_combo(draw_no: int) -> dict | None:
    """회차 조합결과 요약 (union/oracle/best/consensus/분포). READ-ONLY."""
    conn = _conn()
    try:
        s = conn.execute(
            "SELECT * FROM draw_combo_summary WHERE draw_no=?", (draw_no,)
        ).fetchone()
        if not s:
            return None
        out = dict(s)
        for key in ("sample_hist", "raw_hist", "ktier_win_json"):
            out[key] = json.loads(out[key])
        combos = conn.execute(
            "SELECT strategy, numbers, hit_count, note FROM combo_result "
            "WHERE draw_no=? ORDER BY strategy",
            (draw_no,),
        ).fetchall()
        out["combos"] = [
            {"strategy": c["strategy"], "numbers": json.loads(c["numbers"]),
             "hit_count": int(c["hit_count"]), "note": c["note"]}
            for c in combos
        ]
        return out
    finally:
        conn.close()
