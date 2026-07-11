"""STEP2: 순수 1군 → app/hyodo 복제·격리 (1회성 설정 스크립트)."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(r"D:\MONEY lol\My_Library\app\lotto")
DST = ROOT / "app" / "hyodo"

REPLACEMENTS = [
    ("app.lotto", "app.hyodo"),
    ('DATA_DIR / "lotto.db"', 'DATA_DIR / "lotto_hyodo.db"'),
    ('DATA_DIR / "lotto_patterns.db"', 'DATA_DIR / "lotto_patterns_hyodo.db"'),
    ("lotto_patterns.db", "lotto_patterns_hyodo.db"),
    ("lstm_lotto.pt", "lstm_hyodo.pt"),
    ("lotto_brain_weights", "hyodo_brain_weights"),
    ('prefix="/api/lotto"', 'prefix="/api/hyodo"'),
    ('tags=["lotto"]', 'tags=["hyodo"]'),
    ("app.lotto 독립 패키지", "app.hyodo 독립 패키지 (효도로또)"),
]


def transform(content: str, filename: str) -> str:
    for old, new in REPLACEMENTS:
        content = content.replace(old, new)
    # models.py: use local DATA_DIR, not app.config
    if filename == "models.py":
        content = """\"\"\"효도로또 전용 DB 모델 — app.hyodo 독립 패키지.\"\"\"
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
    \"\"\"효도로또 DB 테이블 생성.\"\"\"
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_lotto_db()
    conn.executescript(
        \"\"\"
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
    \"\"\"
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
"""
    return content


def patch_data_service(content: str) -> str:
    """2·3군 의존 제거 — 효도로또 1군 단독."""
    # refresh_all_army: 1군 hyodo만
    old_refresh = re.search(
        r"def refresh_all_army_prediction_scores\(target_draw_no: int\) -> None:.*?(?=\ndef |\Z)",
        content,
        re.DOTALL,
    )
    if old_refresh:
        new_refresh = '''def refresh_all_army_prediction_scores(target_draw_no: int) -> None:
    """효도로또 1군 단독: 당첨 확정 시 채점·가중치·N+1 예측."""
    from app.hyodo.engine import refresh_prediction_scores_for_target_draw
    from app.hyodo.feedback import maybe_update_brain_weights_after_scoring

    refresh_prediction_scores_for_target_draw(target_draw_no)
    maybe_update_brain_weights_after_scoring(target_draw_no)
    maybe_generate_army1_next_predictions(scored_draw_no=target_draw_no)
    from app.hyodo.postmortem_engine import maybe_build_postmortem_after_scoring

    maybe_build_postmortem_after_scoring(target_draw_no)


'''
        content = content[: old_refresh.start()] + new_refresh + content[old_refresh.end() :]

    # backfill: hyodo-only stub
    old_backfill = re.search(
        r"def backfill_unscored_army2_army3_predictions\(\) -> dict:.*?(?=\ndef |\Z)",
        content,
        re.DOTALL,
    )
    if old_backfill:
        new_backfill = '''def backfill_unscored_army2_army3_predictions() -> dict:
    """효도로또: 2·3군 미사용 — no-op."""
    return {"army2": 0, "army3": 0, "skipped": True}


'''
        content = content[: old_backfill.start()] + new_backfill + content[old_backfill.end() :]

    # army2/army3 auto-gen: no-op stubs
    for fn in ("maybe_generate_army2_next_predictions", "maybe_generate_army3_next_predictions"):
        pat = rf"def {fn}\(scored_draw_no: int\) -> dict:.*?(?=\ndef |\Z)"
        m = re.search(pat, content, re.DOTALL)
        if m:
            stub = f'''def {fn}(scored_draw_no: int) -> dict:
    """효도로또: 2·3군 미사용 — no-op."""
    return {{"generated": False, "reason": "hyodo_army1_only", "scored_draw_no": scored_draw_no}}


'''
            content = content[: m.start()] + stub + content[m.end() :]

    # remove any remaining lotto2/lotto3 imports
    content = re.sub(r"^\s*from app\.lotto[23]\..*\n", "", content, flags=re.MULTILINE)
    content = content.replace("app.lotto2.", "app.hyodo._removed_lotto2.")
    content = content.replace("app.lotto3.", "app.hyodo._removed_lotto3.")
    return content


def main() -> None:
    if DST.exists():
        shutil.rmtree(DST)
    DST.mkdir(parents=True)

    py_files = sorted(
        p for p in SRC.glob("*.py") if ".before_" not in p.name
    )
    for src in py_files:
        text = src.read_text(encoding="utf-8")
        text = transform(text, src.name)
        if src.name == "data_service.py":
            text = patch_data_service(text)
        (DST / src.name).write_text(text, encoding="utf-8")
        print(f"copied: {src.name}")

    init_file = DST / "__init__.py"
    init_file.write_text('"""효도로또(1.5군) — 순수 1군 복제·격리 패키지."""\n', encoding="utf-8")
    print("done:", DST)


if __name__ == "__main__":
    main()
