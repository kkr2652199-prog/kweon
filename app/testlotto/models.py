"""테스트로또 전용 DB 모델 — app.testlotto 독립 패키지."""
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
LOTTO_DB_PATH = _DATA_DIR / "lotto_testlotto.db"


def get_lotto_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(LOTTO_DB_PATH), timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_testlotto_db():
    """테스트로또 DB 테이블 생성."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_lotto_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS lotto_draws (
            draw_no        INTEGER PRIMARY KEY,
            draw_date      TEXT NOT NULL,
            num1           INTEGER NOT NULL,
            num2           INTEGER NOT NULL,
            num3           INTEGER NOT NULL,
            num4           INTEGER NOT NULL,
            num5           INTEGER NOT NULL,
            num6           INTEGER NOT NULL,
            bonus          INTEGER NOT NULL,
            total_sales    INTEGER DEFAULT 0,
            first_prize    INTEGER DEFAULT 0,
            first_winners  INTEGER DEFAULT 0,
            created_at     TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS lotto_predictions (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            target_draw_no INTEGER NOT NULL,
            method         TEXT NOT NULL,
            num1           INTEGER NOT NULL,
            num2           INTEGER NOT NULL,
            num3           INTEGER NOT NULL,
            num4           INTEGER NOT NULL,
            num5           INTEGER NOT NULL,
            num6           INTEGER NOT NULL,
            confidence     REAL DEFAULT 0,
            reasoning      TEXT,
            matched_count  INTEGER DEFAULT -1,
            bonus_matched  INTEGER DEFAULT 0,
            brain_tag      TEXT DEFAULT 'legacy',
            created_at     TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS lotto_analysis (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            draw_no        INTEGER NOT NULL,
            analysis_type  TEXT NOT NULL,
            data_json      TEXT NOT NULL,
            created_at     TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS testlotto_brain_weights (
            brain_tag          TEXT PRIMARY KEY,
            current_weight     REAL NOT NULL,
            recent_avg_match   REAL DEFAULT 0,
            total_predictions  INTEGER DEFAULT 0,
            total_matches      INTEGER DEFAULT 0,
            last_updated_draw  INTEGER DEFAULT 0,
            updated_at         TEXT DEFAULT (datetime('now','localtime'))
        );

        -- 회차별 분석 그릇 (P1: 컬럼 선점, 값은 점진 채움)
        CREATE TABLE IF NOT EXISTS testlotto_draw_features (
            draw_no            INTEGER PRIMARY KEY,
            carry_over_count   INTEGER DEFAULT 0,
            carry_over_nums    TEXT,
            consecutive_count  INTEGER DEFAULT 0,
            ending_digits      TEXT,
            ac_value           INTEGER DEFAULT 0,
            gap_overdue_nums   TEXT,
            sum_total          INTEGER DEFAULT 0,
            odd_count          INTEGER DEFAULT 0,
            even_count         INTEGER DEFAULT 0,
            zone_low_mid_high  TEXT,
            pair_hot_json      TEXT,
            combo_rank_814     INTEGER,
            bonus_num          INTEGER DEFAULT 0,
            updated_at         TEXT DEFAULT (datetime('now','localtime'))
        );

        -- 회차·뇌별 복습 기록 (예측→채점→오답분석→피드백)
        CREATE TABLE IF NOT EXISTS testlotto_brain_review (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            draw_no            INTEGER NOT NULL,
            brain_tag          TEXT NOT NULL,
            predicted_nums     TEXT NOT NULL,
            matched_count      INTEGER DEFAULT -1,
            missed_patterns    TEXT,
            feedback_json      TEXT,
            weight_snapshot    TEXT,
            created_at         TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(draw_no, brain_tag)
        );

        -- 예측뇌 누적 학습 상태 (오답 패턴·조정값)
        CREATE TABLE IF NOT EXISTS testlotto_brain_learn_state (
            brain_tag          TEXT PRIMARY KEY,
            state_json         TEXT NOT NULL,
            review_count       INTEGER DEFAULT 0,
            last_draw_no       INTEGER DEFAULT 0,
            updated_at         TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_brain_review_draw ON testlotto_brain_review(draw_no);
        CREATE INDEX IF NOT EXISTS idx_brain_review_tag ON testlotto_brain_review(brain_tag);

        -- 뇌별 상세페이지 스냅샷 (회차×뇌×phase, 용량 커져도 조회 빠르게)
        CREATE TABLE IF NOT EXISTS testlotto_brain_page (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            draw_no            INTEGER NOT NULL,
            brain_tag          TEXT NOT NULL,
            phase              TEXT NOT NULL DEFAULT 'review',
            predicted_nums     TEXT,
            actual_nums        TEXT,
            matched_count      INTEGER DEFAULT -1,
            missed_patterns    TEXT,
            hit_nums           TEXT,
            miss_nums          TEXT,
            feature_snapshot   TEXT,
            feedback_json      TEXT,
            learn_snapshot_json TEXT,
            aux_analysis_json  TEXT,
            narrative          TEXT,
            detail_json        TEXT,
            created_at         TEXT DEFAULT (datetime('now','localtime')),
            updated_at         TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(draw_no, brain_tag, phase)
        );

        CREATE INDEX IF NOT EXISTS idx_brain_page_draw ON testlotto_brain_page(draw_no);
        CREATE INDEX IF NOT EXISTS idx_brain_page_tag ON testlotto_brain_page(brain_tag);
        CREATE INDEX IF NOT EXISTS idx_brain_page_range ON testlotto_brain_page(draw_no, brain_tag);

        -- 회차별 1~5등 당첨 (엑셀 데이터시트 뼈대)
        CREATE TABLE IF NOT EXISTS testlotto_draw_prize_tiers (
            draw_no            INTEGER NOT NULL,
            tier_rank          INTEGER NOT NULL,
            winner_count       INTEGER DEFAULT 0,
            prize_per_game     INTEGER DEFAULT 0,
            total_prize        INTEGER DEFAULT 0,
            source             TEXT DEFAULT '',
            detail_json        TEXT,
            updated_at         TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (draw_no, tier_rank)
        );

        CREATE INDEX IF NOT EXISTS idx_prize_tiers_draw ON testlotto_draw_prize_tiers(draw_no);

        -- 회차별 정밀 당첨 이력 (lt645 원본·판매·당첨유형 통합)
        CREATE TABLE IF NOT EXISTS testlotto_draw_detail (
            draw_no              INTEGER PRIMARY KEY,
            draw_date            TEXT,
            game_seq_no          INTEGER DEFAULT 0,
            total_sales          INTEGER DEFAULT 0,
            cumulative_sales     INTEGER DEFAULT 0,
            total_winners        INTEGER DEFAULT 0,
            win_type_0           INTEGER DEFAULT 0,
            win_type_1           INTEGER DEFAULT 0,
            win_type_2           INTEGER DEFAULT 0,
            win_type_3           INTEGER DEFAULT 0,
            raw_lt645_json       TEXT,
            store_fetch_status   TEXT DEFAULT '',
            store_fetch_note     TEXT,
            source               TEXT DEFAULT 'lt645',
            synced_at            TEXT DEFAULT (datetime('now','localtime'))
        );

        -- 회차별 1·2등 당첨 판매점 (동행복권 store.do — 가능 시 채움)
        CREATE TABLE IF NOT EXISTS testlotto_draw_win_stores (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            draw_no              INTEGER NOT NULL,
            tier_rank            INTEGER NOT NULL DEFAULT 1,
            store_name           TEXT NOT NULL DEFAULT '',
            pick_method          TEXT DEFAULT '',
            address              TEXT DEFAULT '',
            region               TEXT DEFAULT '',
            raw_json             TEXT,
            source               TEXT DEFAULT 'store.do',
            updated_at           TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_win_stores_draw ON testlotto_draw_win_stores(draw_no);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_win_stores_unique
            ON testlotto_draw_win_stores(draw_no, tier_rank, store_name, address);
    """
    )
    existing_cols = [r[1] for r in conn.execute("PRAGMA table_info(lotto_predictions)").fetchall()]
    if "brain_tag" not in existing_cols:
        conn.execute("ALTER TABLE lotto_predictions ADD COLUMN brain_tag TEXT DEFAULT 'legacy'")
    for table, col, typedef in (
        ("testlotto_brain_review", "predicted_sets_json", "TEXT"),
        ("testlotto_brain_review", "best_set_no", "INTEGER DEFAULT 1"),
        ("testlotto_brain_review", "bonus_matched", "INTEGER DEFAULT 0"),
        ("testlotto_brain_page", "predicted_sets_json", "TEXT"),
        ("testlotto_brain_page", "best_set_no", "INTEGER DEFAULT 1"),
        ("testlotto_brain_page", "bonus_matched", "INTEGER DEFAULT 0"),
    ):
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if col not in cols:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
            except Exception:
                pass
    seeds = [("stat", 1.5), ("markov", 1.0), ("review", 1.2)]
    for brain_tag, weight in seeds:
        conn.execute(
            "INSERT OR IGNORE INTO testlotto_brain_weights (brain_tag, current_weight) VALUES (?, ?)",
            (brain_tag, weight),
        )
    conn.commit()
    conn.close()


# 하위 호환 alias
init_lotto_db = init_testlotto_db
