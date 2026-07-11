"""READ-ONLY 4군 lotto4.db 데이터 활용도 정찰."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

DB = Path(r"d:\3kweon\data\lotto4.db")
ROOT = Path(r"d:\3kweon\app\lotto4")
OUT = Path(r"d:\3kweon\tools\_audit4_data_util.json")

FOCUS = [
    "lotto4_winners_full",
    "number_popularity",
    "pair_popularity",
    "shape_profile",
    "lotto_cooccur_2",
    "lotto_cooccur_3",
    "lotto_cooccur_4",
    "lotto_bonus_stats",
    "lotto_draw_tiers",
    "lotto_analysis_army4",
    "lotto_predictions_army4",
    "lotto_fullbacktest_army4",
    "lotto_draws",
    "lotto_number_freq",
    "lotto_brain_weights_army4",
    "lotto_weight_log_army4",
    "lotto_evolution_trust_army4",
]


def db_inventory() -> dict:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    inv = {}
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
    ]
    for t in tables:
        cnt = conn.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
        cols = conn.execute(f"PRAGMA table_info([{t}])").fetchall()
        inv[t] = {
            "rows": cnt,
            "columns": [f"{c[1]}:{c[2]}" for c in cols],
        }
    # STEP3 coverage
    step3 = {}
    if "number_popularity" in tables:
        rows = conn.execute(
            "SELECT number, top30_pct FROM number_popularity ORDER BY number"
        ).fetchall()
        step3["number_popularity"] = {
            "rows": len(rows),
            "min_pct": min(r[1] for r in rows) if rows else None,
            "max_pct": max(r[1] for r in rows) if rows else None,
            "zero_pct": sum(1 for r in rows if float(r[1]) <= 0),
        }
    if "pair_popularity" in tables:
        pr = conn.execute(
            "SELECT COUNT(*), SUM(CASE WHEN freq>0 THEN 1 ELSE 0 END), SUM(freq) FROM pair_popularity"
        ).fetchone()
        step3["pair_popularity"] = {
            "total_pairs": pr[0],
            "pairs_freq_gt0": pr[1],
            "sum_freq": pr[2],
        }
    if "lotto4_winners_full" in tables:
        wf = conn.execute(
            "SELECT COUNT(*), SUM(CASE WHEN winner_cnt>0 THEN 1 ELSE 0 END), SUM(CASE WHEN prize_per>0 THEN 1 ELSE 0 END) FROM lotto4_winners_full"
        ).fetchone()
        step3["lotto4_winners_full"] = {
            "rows": wf[0],
            "winner_cnt_pos": wf[1],
            "prize_per_pos": wf[2],
        }
    if "lotto_draw_tiers" in tables:
        tr = conn.execute(
            "SELECT tier_rank, COUNT(*), SUM(winner_count) FROM lotto_draw_tiers GROUP BY tier_rank ORDER BY tier_rank"
        ).fetchall()
        step3["lotto_draw_tiers"] = [dict(zip(["tier", "rows", "sum_winners"], r)) for r in tr]
    conn.close()
    return {"tables": inv, "step3": step3}


def grep_table_refs() -> dict[str, list[str]]:
    refs: dict[str, list[str]] = {t: [] for t in FOCUS}
    pat = re.compile(
        r"\b(" + "|".join(re.escape(t) for t in FOCUS + ["lotto_cooccur_2"]) + r")\b",
        re.I,
    )
    for py in ROOT.rglob("*.py"):
        rel = str(py.relative_to(ROOT.parent.parent))
        text = py.read_text(encoding="utf-8", errors="replace")
        for m in pat.finditer(text):
            tbl = m.group(1).lower()
            key = tbl
            for f in FOCUS:
                if f.lower() == tbl:
                    key = f
                    break
            if rel not in refs.get(key, []):
                refs.setdefault(key, []).append(rel)
    return refs


def main() -> None:
    inv = db_inventory()
    refs = grep_table_refs()
    OUT.write_text(
        json.dumps({"inventory": inv, "code_refs": refs}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("written", OUT)
    print("tables", len(inv["tables"]))
    for t in FOCUS:
        r = inv["tables"].get(t, {}).get("rows", "MISSING")
        nref = len(refs.get(t, []))
        print(f"{t}: rows={r} refs={nref}")


if __name__ == "__main__":
    main()
