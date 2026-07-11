"""효도로또 전용 DB 모델 — app.hyodo 독립 패키지."""
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
LOTTO_DB_PATH = _DATA_DIR / "lotto_hyodo.db"


def get_lotto_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(LOTTO_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_hyodo_db():
    """효도로또 DB 테이블 생성."""
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

        CREATE TABLE IF NOT EXISTS hyodo_brain_weights (
            brain_tag          TEXT PRIMARY KEY,
            current_weight     REAL NOT NULL,
            recent_avg_match   REAL DEFAULT 0,
            total_predictions  INTEGER DEFAULT 0,
            total_matches      INTEGER DEFAULT 0,
            last_updated_draw  INTEGER DEFAULT 0,
            updated_at         TEXT DEFAULT (datetime('now','localtime'))
        );
    """
    )
    existing_cols = [r[1] for r in conn.execute("PRAGMA table_info(lotto_predictions)").fetchall()]
    if "brain_tag" not in existing_cols:
        conn.execute("ALTER TABLE lotto_predictions ADD COLUMN brain_tag TEXT DEFAULT 'legacy'")
    seeds = [("stat", 1.5), ("markov", 1.0), ("llm", 2.5), ("lstm", 2.0), ("hyena", 1.0)]
    for brain_tag, weight in seeds:
        conn.execute(
            "INSERT OR IGNORE INTO hyodo_brain_weights (brain_tag, current_weight) VALUES (?, ?)",
            (brain_tag, weight),
        )
    conn.commit()
    conn.close()


# 하위 호환 alias
init_lotto_db = init_hyodo_db
