"""V9 Layer: 2군(역전 로또) 전용 DB 모델.

1군 테이블과 완전 분리. lotto_draws만 1군과 공유(읽기 전용).
"""
import sqlite3
from pathlib import Path

LOTTO_DB_PATH = Path(r"d:\3kweon\data\lotto4.db")


def get_lotto4_db() -> sqlite3.Connection:
    """2군 DB 연결(1군과 같은 lotto.db 파일, 테이블만 분리)."""
    conn = sqlite3.connect(str(LOTTO_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_lotto4_db() -> None:
    """2군 전용 테이블 3개 신규 생성(기존 1군 테이블 수정 없음)."""
    conn = get_lotto4_db()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS lotto_predictions_army4 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_draw_no INTEGER NOT NULL,
                method TEXT NOT NULL,
                num1 INTEGER NOT NULL,
                num2 INTEGER NOT NULL,
                num3 INTEGER NOT NULL,
                num4 INTEGER NOT NULL,
                num5 INTEGER NOT NULL,
                num6 INTEGER NOT NULL,
                confidence REAL DEFAULT 0,
                reasoning TEXT,
                matched_count INTEGER DEFAULT -1,
                bonus_matched INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now','localtime')),
                brain_tag TEXT DEFAULT 'legacy'
            );

            CREATE INDEX IF NOT EXISTS idx_lp4_draw
                ON lotto_predictions_army4(target_draw_no);
            CREATE INDEX IF NOT EXISTS idx_lp4_brain
                ON lotto_predictions_army4(brain_tag);

            CREATE TABLE IF NOT EXISTS lotto_cooccur_3 (
                num1 INTEGER NOT NULL,
                num2 INTEGER NOT NULL,
                num3 INTEGER NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                last_draw_no INTEGER,
                last_draw_date TEXT,
                updated_at TEXT DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (num1, num2, num3)
            );

            CREATE TABLE IF NOT EXISTS lotto_cooccur_4 (
                num1 INTEGER NOT NULL,
                num2 INTEGER NOT NULL,
                num3 INTEGER NOT NULL,
                num4 INTEGER NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                last_draw_no INTEGER,
                last_draw_date TEXT,
                updated_at TEXT DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (num1, num2, num3, num4)
            );

            CREATE TABLE IF NOT EXISTS lotto_bonus_stats (
                bonus_no INTEGER PRIMARY KEY,
                total_count INTEGER NOT NULL DEFAULT 0,
                last_draw_no INTEGER,
                coappear_with TEXT,
                updated_at TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS lotto_number_freq (
                number INTEGER PRIMARY KEY,
                total_count INTEGER NOT NULL DEFAULT 0,
                rank_most INTEGER,
                rank_least INTEGER,
                updated_at TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS lotto_brain_weights_army4 (
                brain_tag TEXT PRIMARY KEY,
                current_weight REAL NOT NULL,
                recent_avg_match REAL DEFAULT 0,
                total_predictions INTEGER DEFAULT 0,
                total_matches INTEGER DEFAULT 0,
                last_updated_draw INTEGER DEFAULT 0,
                updated_at TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS lotto_analysis_army4 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                draw_no INTEGER NOT NULL,
                analysis_type TEXT NOT NULL,
                data_json TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS lotto_evolution_trust_army4 (
                brain_tag TEXT NOT NULL,
                draw_no INTEGER NOT NULL,
                matched_count INTEGER DEFAULT 0,
                trust_score REAL DEFAULT 0.25,
                context_sum REAL,
                context_odd REAL,
                context_high REAL,
                context_ac REAL,
                created_at TEXT DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (brain_tag, draw_no)
            );

            CREATE TABLE IF NOT EXISTS lotto_fullbacktest_army4 (
                draw_no INTEGER NOT NULL,
                brain_tag TEXT NOT NULL,
                set_no INTEGER NOT NULL,
                numbers TEXT NOT NULL,
                matched_count INTEGER NOT NULL,
                matched_numbers TEXT,
                bonus_matched INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (draw_no, brain_tag, set_no)
            );
            CREATE INDEX IF NOT EXISTS idx_fullback_army4_draw
                ON lotto_fullbacktest_army4(draw_no);
            """
        )

        conn.commit()
    finally:
        conn.close()


def get_miss_draws_for_army4(target_draw_no: int) -> list[dict]:
    """2군 학습용: 1군 미당첨 회차(max<=4) 당첨번호(target 미만).

    컷닝 방지: target_draw_no 미만만 사용.
    """
    conn = get_lotto4_db()
    try:
        rows = conn.execute(
            """
            SELECT d.* FROM lotto_draws d
            WHERE d.draw_no < ?
              AND d.draw_no IN (
                SELECT target_draw_no FROM lotto_predictions
                WHERE brain_tag IN ('stat','markov','llm','lstm','fusion','hyena')
                  AND matched_count >= 0
                  AND target_draw_no < ?
                GROUP BY target_draw_no
                HAVING MAX(matched_count) <= 4
              )
            ORDER BY d.draw_no
            """,
            (target_draw_no, target_draw_no),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_full_draws_for_army4(target_draw_no: int) -> list[dict]:
    """V10 학습용: 1군 미당첨 필터 없이 target 미만 전체 회차.

    V9의 get_miss_draws_for_army4와 다르게, 1군 약점에 의존하지 않고
    전체 데이터를 학습 표본으로 사용.
    컷닝 방지: target_draw_no 미만만 사용.
    """
    conn = get_lotto4_db()
    try:
        rows = conn.execute(
            "SELECT * FROM lotto_draws WHERE draw_no < ? ORDER BY draw_no",
            (target_draw_no,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
