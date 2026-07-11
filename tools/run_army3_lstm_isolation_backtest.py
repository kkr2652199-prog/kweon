"""3군 LSTM 누수 격리 + 순방향 재백테 (코드 수정 없음)."""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(r"D:\MONEY lol\My_Library")
sys.path.insert(0, str(ROOT))

DB = ROOT / "data" / "lotto.db"
PT = ROOT / "models" / "lstm_lotto.pt"
PT_BAK = ROOT / "models" / "lstm_lotto.pt.bak_20260529"
OUT = Path(r"d:\3kweon\tools\_army3_backtest_run.json")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def q(sql: str, params=()):
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def print_table(title: str, rows: list[dict]):
    print(f"\n=== {title} ===")
    if not rows:
        print("(empty)")
        return
    cols = list(rows[0].keys())
    print("\t".join(cols))
    for r in rows:
        print("\t".join(str(r.get(c, "")) for c in cols))


STEP0_BASELINE = [
    {"brain_tag": "v12_hyena", "cnt": 6105, "avg_mc": 2.0532, "max_mc": 6, "hit6": 2},
    {"brain_tag": "v12_fusion", "cnt": 6105, "avg_mc": 1.9133, "max_mc": 6, "hit6": 5},
    {"brain_tag": "v12_snake", "cnt": 6105, "avg_mc": 1.8046, "max_mc": 5, "hit6": 0},
    {"brain_tag": "v12_lstm", "cnt": 6080, "avg_mc": 1.7913, "max_mc": 5, "hit6": 0},
    {"brain_tag": "v12_contrarian", "cnt": 6105, "avg_mc": 0.8084, "max_mc": 4, "hit6": 0},
    {"brain_tag": "v12_run", "cnt": 6105, "avg_mc": 0.8077, "max_mc": 4, "hit6": 0},
    {"brain_tag": "v12_offset", "cnt": 6105, "avg_mc": 0.8062, "max_mc": 4, "hit6": 0},
    {"brain_tag": "v12_stat", "cnt": 6105, "avg_mc": 0.7921, "max_mc": 4, "hit6": 0},
]


def step0():
    print("\n######## STEP 0 ########")
    if PT_BAK.is_file():
        print(f"SHA256 backup: {sha256(PT_BAK)}")
    rows = list(STEP0_BASELINE)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if not OUT.is_file():
        OUT.write_text(json.dumps({"step0": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print_table("STEP0 army3 scores (baseline before isolation)", rows)
    return rows


def step1():
    print("\n######## STEP 1 ########")
    if PT.is_file():
        PT.unlink()
        print(f"deleted: {PT}")
    else:
        print(f"already absent: {PT}")

    conn = sqlite3.connect(str(DB))
    try:
        for tbl in (
            "lotto_predictions_army3",
            "lotto_brain_weights_army3",
            "lotto_weight_log_army3",
        ):
            conn.execute(f"DELETE FROM {tbl}")
        conn.commit()
        for tbl in (
            "lotto_predictions_army3",
            "lotto_brain_weights_army3",
            "lotto_weight_log_army3",
        ):
            n = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            print(f"COUNT {tbl}: {n}")
    finally:
        conn.close()

    from app.lotto3.v12_models import init_v12_seeds

    init_v12_seeds()
    w = q("SELECT brain_tag, current_weight FROM lotto_brain_weights_army3 ORDER BY brain_tag")
    print_table("weights after init_v12_seeds", w)
    print(f"weights rows: {len(w)}")
    wl = q(
        "SELECT draw_no, brain_tag FROM lotto_weight_log_army3 ORDER BY brain_tag"
    )
    print_table("weight_log after init", wl)
    print(f"weight_log rows: {len(wl)}")


def step2(start: int = 1, end: int = 1221, checkpoint_every: int = 100):
    print("\n######## STEP 2 ########")
    print(f"range: {start}~{end} checkpoint_every={checkpoint_every}")
    print(f"start: {datetime.now().isoformat(timespec='seconds')}")
    from app.lotto3.v12_engine import run_v12_chunk_backtest

    result = run_v12_chunk_backtest(start, end, checkpoint_every=checkpoint_every)
    print(f"end: {datetime.now().isoformat(timespec='seconds')}")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    at100 = q(
        "SELECT COUNT(*) AS c FROM lotto_predictions_army3 WHERE target_draw_no <= 100"
    )
    print(f"predictions rows target<=100: {at100[0]['c']}")
    cached_check = q(
        """
        SELECT target_draw_no, COUNT(*) AS c
        FROM lotto_predictions_army3
        WHERE target_draw_no = 100
        GROUP BY target_draw_no
        """
    )
    print_table("draw 100 row count (expect ~40 if fresh)", cached_check)
    return result


def step2_resume():
    """중단 후 이어하기: 마지막 완료 회차 다음부터 1221까지."""
    mx = q("SELECT MAX(target_draw_no) AS m FROM lotto_predictions_army3")[0]["m"]
    start = int(mx or 0) + 1
    if start > 1221:
        print(f"already complete through 1221 (max={mx})")
        return {"status": "already_done", "max": mx}
    return step2(start, 1221, 100)


def step3(step0_rows: list[dict]):
    print("\n######## STEP 3 ########")
    rows = q(
        """
        SELECT brain_tag, COUNT(*) AS cnt,
               ROUND(AVG(matched_count), 4) AS avg_mc,
               MAX(matched_count) AS max_mc,
               SUM(CASE WHEN matched_count >= 4 THEN 1 ELSE 0 END) AS hit4,
               SUM(CASE WHEN matched_count >= 6 THEN 1 ELSE 0 END) AS hit6
        FROM lotto_predictions_army3
        WHERE target_draw_no BETWEEN 6 AND 1221
        GROUP BY brain_tag
        ORDER BY avg_mc DESC
        """
    )
    print_table("STEP3 scores 6-1221", rows)

    before = {r["brain_tag"]: r for r in step0_rows}
    print("\n=== STEP0 vs STEP3 compare ===")
    print("brain_tag\tbefore_avg\tafter_avg\tdelta")
    for r in rows:
        tag = r["brain_tag"]
        b = before.get(tag, {}).get("avg_mc")
        a = r["avg_mc"]
        if b is not None and a is not None:
            print(f"{tag}\t{b}\t{a}\t{float(a) - float(b):+.4f}")
        else:
            print(f"{tag}\t{b}\t{a}\tN/A")

    if PT.is_file():
        import torch

        ck = torch.load(str(PT), map_location="cpu", weights_only=False)
        print(f"\nlstm_lotto.pt exists: True")
        print(f"mtime: {datetime.fromtimestamp(PT.stat().st_mtime)}")
        print(f"last_trained_on: {ck.get('last_trained_on')}")
    else:
        print("\nlstm_lotto.pt exists: False")

    missing_lstm = q(
        """
        SELECT f.target_draw_no
        FROM (
          SELECT DISTINCT target_draw_no FROM lotto_predictions_army3
          WHERE brain_tag='v12_fusion'
        ) f
        LEFT JOIN (
          SELECT DISTINCT target_draw_no FROM lotto_predictions_army3
          WHERE brain_tag='v12_lstm'
        ) l ON f.target_draw_no = l.target_draw_no
        WHERE l.target_draw_no IS NULL
        ORDER BY f.target_draw_no
        """
    )
    print_table("draws fusion but no lstm", missing_lstm)

    payload = {"step0": step0_rows, "step3": rows}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\njson saved: {OUT}")
    return rows


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "all"
    s0 = step0()
    if phase in ("all", "1"):
        step1()
    if phase in ("all", "2"):
        step2(1, 1221, 100)
    if phase == "2resume":
        step2_resume()
    if phase in ("all", "3"):
        s3 = step3(s0)
        return s0, s3
    return s0, None


if __name__ == "__main__":
    main()
