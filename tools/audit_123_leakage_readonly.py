"""READ-ONLY 1~3군 백테스트 누수 정찰 — lotto_audit.db only."""
from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

DB = Path(r"D:\MONEY lol\My_Library\data_audit_readonly\lotto_audit.db")
FUSION_WINS = (198, 725, 774, 800, 1037, 1040, 1122)
BOTH6 = (800, 1122)
BRAINS = ("stat", "markov", "llm", "lstm", "fusion", "hyena")


def main() -> None:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    out: dict = {"db": str(DB), "db_bytes": DB.stat().st_size}

    # STEP0
    for tbl in ("lotto_predictions", "lotto_predictions_army2", "lotto_predictions_army3"):
        total = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        by_tag = conn.execute(
            f"SELECT brain_tag, COUNT(*) cnt FROM {tbl} GROUP BY brain_tag ORDER BY brain_tag"
        ).fetchall()
        out[f"step0_{tbl}"] = {
            "total": total,
            "by_brain_tag": {r["brain_tag"]: r["cnt"] for r in by_tag},
        }

    # STEP1 fusion rank6 rows + created_at
    ph = ",".join("?" * len(FUSION_WINS))
    rows = conn.execute(
        f"""
        SELECT target_draw_no, brain_tag, method, matched_count, bonus_matched,
               num1,num2,num3,num4,num5,num6, created_at, id
        FROM lotto_predictions
        WHERE target_draw_no IN ({ph}) AND brain_tag='fusion' AND matched_count=6
        ORDER BY target_draw_no, created_at
        """,
        FUSION_WINS,
    ).fetchall()
    out["step1_fusion_rank6"] = [dict(r) for r in rows]

    # all fusion rows at those draws (any match)
    all_fusion = conn.execute(
        f"""
        SELECT target_draw_no, matched_count, created_at, method
        FROM lotto_predictions
        WHERE target_draw_no IN ({ph}) AND brain_tag='fusion'
        ORDER BY target_draw_no, matched_count DESC, created_at
        """,
        FUSION_WINS,
    ).fetchall()
    out["step1_fusion_all_at_wins"] = [dict(r) for r in all_fusion]

    # other brains rank6 at same draws
    for tag in BRAINS:
        r6 = conn.execute(
            f"""
            SELECT target_draw_no, created_at, matched_count
            FROM lotto_predictions
            WHERE target_draw_no IN ({ph}) AND brain_tag=? AND matched_count=6
            ORDER BY target_draw_no
            """,
            (*FUSION_WINS, tag),
        ).fetchall()
        out[f"step1_{tag}_rank6"] = [dict(r) for r in r6]

    # created_at distribution global fusion
    ts = conn.execute(
        """
        SELECT target_draw_no, MIN(created_at) min_ca, MAX(created_at) max_ca,
               COUNT(*) cnt
        FROM lotto_predictions WHERE brain_tag='fusion'
        GROUP BY target_draw_no ORDER BY target_draw_no
        """
    ).fetchall()
    # summarize: how many draws have min==max created_at (single batch per draw)
    same_ts = sum(1 for r in ts if r["min_ca"] == r["max_ca"])
    out["step1_fusion_per_draw_ts"] = {
        "draws_with_predictions": len(ts),
        "draws_all_sets_same_ts": same_ts,
        "sample_first10": [dict(r) for r in ts[:10]],
        "sample_win_draws": [
            dict(r) for r in ts if r["target_draw_no"] in FUSION_WINS
        ],
    }

    # global created_at clustering: count unique timestamps for fusion
    uniq = conn.execute(
        "SELECT COUNT(DISTINCT created_at) FROM lotto_predictions WHERE brain_tag='fusion'"
    ).fetchone()[0]
    total_f = conn.execute(
        "SELECT COUNT(*) FROM lotto_predictions WHERE brain_tag='fusion'"
    ).fetchone()[0]
    out["step1_fusion_ts_global"] = {
        "total_rows": total_f,
        "distinct_created_at": uniq,
        "ratio": round(uniq / max(total_f, 1), 4),
    }

    # backtest night log timing hint
    night = conn.execute(
        """
        SELECT MIN(created_at), MAX(created_at)
        FROM lotto_predictions WHERE brain_tag='fusion'
        """
    ).fetchone()
    out["step1_fusion_ts_range"] = {"min": night[0], "max": night[1]}

    # STEP3 cross-app 800, 1122
    for d in BOTH6:
        block = {}
        for tbl, tag_col in (
            ("lotto_predictions", "fusion"),
            ("lotto_predictions_army2", "v11_fusion"),
            ("lotto_predictions_army3", "v12_fusion"),
        ):
            # army2/3 tag names
            if tbl == "lotto_predictions_army2":
                btag = "v11_fusion"
            elif tbl == "lotto_predictions_army3":
                btag = "v12_fusion"
            else:
                btag = "fusion"
            rs = conn.execute(
                f"""
                SELECT brain_tag, matched_count, created_at, method,
                       num1,num2,num3,num4,num5,num6
                FROM {tbl}
                WHERE target_draw_no=? AND matched_count=6
                ORDER BY created_at
                """,
                (d,),
            ).fetchall()
            block[tbl] = [dict(r) for r in rs]
        # actual draw
        dr = conn.execute(
            "SELECT draw_no, num1,num2,num3,num4,num5,num6, bonus, first_winners FROM lotto_draws WHERE draw_no=?",
            (d,),
        ).fetchone()
        block["lotto_draws"] = dict(dr) if dr else None
        out[f"step3_draw_{d}"] = block

    # popularity: number frequency in all draws vs 800/1122
    all_freq = Counter()
    for r in conn.execute(
        "SELECT num1,num2,num3,num4,num5,num6 FROM lotto_draws WHERE draw_no BETWEEN 1 AND 1221"
    ):
        for i in range(6):
            all_freq[int(r[i])] += 1
    for d in BOTH6 + FUSION_WINS:
        dr = conn.execute(
            "SELECT num1,num2,num3,num4,num5,num6, first_winners FROM lotto_draws WHERE draw_no=?",
            (d,),
        ).fetchone()
        if not dr:
            continue
        nums = [int(dr[i]) for i in range(6)]
        pop_score = sum(all_freq[n] for n in nums) / 6.0
        out.setdefault("step3_popularity", {})[str(d)] = {
            "nums": nums,
            "first_winners": dr[6],
            "avg_historical_freq": round(pop_score, 2),
        }

    # Check if predictions at draw 800 created in same second across armies
    for d in BOTH6:
        times = {}
        for tbl, btag in (
            ("lotto_predictions", "fusion"),
            ("lotto_predictions_army2", "v11_fusion"),
            ("lotto_predictions_army3", "v12_fusion"),
        ):
            rs = conn.execute(
                f"SELECT MIN(created_at), MAX(created_at), COUNT(*) FROM {tbl} WHERE target_draw_no=?",
                (d,),
            ).fetchone()
            times[tbl] = {"min": rs[0], "max": rs[1], "cnt": rs[2]}
        out[f"step3_all_brains_ts_draw_{d}"] = times

    conn.close()
    out_path = Path(r"d:\3kweon\tools\_audit_123_output.json")
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("written", out_path)


if __name__ == "__main__":
    main()
