"""
4군 미니 백테스트 — v13 (Commander v2 반영)
범위: draw 1200 ~ 1222
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import time

import sqlite3

from app.lotto4.brains.diversity_brain import predict as diversity_predict
from app.lotto4.brains.ensemble import predict as ensemble_predict
from app.lotto4.brains.ev_brain import predict as ev_predict
from app.lotto4.brains.evolution_brain import predict as evolution_predict
from app.lotto4.brains.gap_brain import predict as gap_predict
from app.lotto4.brains.struct_brain import predict as struct_predict
from app.lotto4.brains.seq_brain import predict as seq_predict
from app.lotto4.v13_weights_v2 import V13_V2_HIDDEN_BRAINS

DB_PATH = str(ROOT / "data" / "lotto4.db")
START, END = 1200, 1222


def get_actual(db_path: str, draw_no: int) -> set[int] | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT num1,num2,num3,num4,num5,num6 FROM lotto_draws WHERE draw_no=?",
            (draw_no,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {int(x) for x in row}


def summarize_matches(matches: list[int]) -> dict[str, float | int | dict[int, int]]:
    n = len(matches)
    if not n:
        return {
            "avg": 0.0,
            "high_match_rate": 0.0,
            "top_match_count": 0,
            "max_matched": 0,
            "match_distribution": {i: 0 for i in range(7)},
        }
    dist: dict[int, int] = {i: 0 for i in range(7)}
    for m in matches:
        k = max(0, min(6, int(m)))
        dist[k] = dist.get(k, 0) + 1
    high4 = sum(1 for m in matches if m >= 4)
    top5 = sum(1 for m in matches if m >= 5)
    return {
        "avg": sum(matches) / n,
        "high_match_rate": 100.0 * high4 / n,
        "top_match_count": top5,
        "max_matched": max(matches),
        "match_distribution": dist,
    }


def run() -> None:
    results: dict[str, list[int]] = {
        "v13_ensemble": [],
        "v13_seq": [],
        "v13_struct": [],
        "v13_diversity": [],
        "v13_gap": [],
        "v13_ev": [],
        "v13_evolution": [],
        "v13_cdm": [],
        "v13_cond_prob": [],
    }
    brains: dict[str, object] = {
        "v13_struct": struct_predict,
        "v13_ensemble": ensemble_predict,
        "v13_gap": gap_predict,
        "v13_ev": ev_predict,
        "v13_seq": seq_predict,
        "v13_diversity": diversity_predict,
        "v13_evolution": evolution_predict,
    }

    t0 = time.perf_counter()
    seq_draw_seconds: list[float] = []
    diversity_draw_seconds: list[float] = []
    evolution_draw_seconds: list[float] = []

    for draw_no in range(START, END + 1):
        actual = get_actual(DB_PATH, draw_no)
        if not actual:
            continue
        for name, fn in brains.items():
            try:
                t_call = time.perf_counter()
                sets = fn(draw_no, DB_PATH)
                elapsed = time.perf_counter() - t_call
                if name == "v13_seq":
                    seq_draw_seconds.append(elapsed)
                if name == "v13_diversity":
                    diversity_draw_seconds.append(elapsed)
                if name == "v13_evolution":
                    evolution_draw_seconds.append(elapsed)
                for s in sets:
                    matched = len(set(s) & actual)
                    results[name].append(matched)
            except Exception as e:
                print(f"[ERROR] {name} draw={draw_no}: {e}")

    total_sec = time.perf_counter() - t0
    n_sq = len(seq_draw_seconds)
    avg_sq = (sum(seq_draw_seconds) / n_sq) if n_sq else 0.0
    n_ge = len(diversity_draw_seconds)
    avg_ge = (sum(diversity_draw_seconds) / n_ge) if n_ge else 0.0
    n_evo = len(evolution_draw_seconds)
    avg_evo = (sum(evolution_draw_seconds) / n_evo) if n_evo else 0.0
    print("\n--- timing ---")
    print(f"  전체 백테스트: {total_sec:.3f}s")
    print(f"  seq(LSTM) 회차당 평균: {avg_sq:.3f}s (n={n_sq})")
    print(f"  diversity 회차당 평균: {avg_ge:.3f}s (n={n_ge})")
    print(f"  evolution 회차당 평균: {avg_evo:.3f}s (n={n_evo})")

    display_order = [
        ("v13_ensemble", "Commander v2"),
        ("v13_seq", "에이스"),
        ("v13_struct", "에이스"),
        ("v13_diversity", "리스코어"),
        ("v13_gap", "리스코어"),
        ("v13_ev", "리스코어"),
        ("v13_evolution", "메타"),
        ("v13_cdm", "HIDDEN"),
        ("v13_cond_prob", "HIDDEN"),
    ]

    print("\n=== 성적표 (avg | high_4+ % | top_5+ | max | 분포 0..6) ===")
    print(
        f"{'뇌':<16} {'avg':>6} {'hi4%':>8} {'5+':>5} {'max':>4} "
        f"{'d0':>4}{'d1':>4}{'d2':>4}{'d3':>4}{'d4':>4}{'d5':>4}{'d6':>4}  상태"
    )
    for name, role in display_order:
        if name in V13_V2_HIDDEN_BRAINS:
            print(f"{name:<16} {'—':>6} {'—':>8} {'—':>5} {'—':>4} {'—':>32}  {role}")
            continue
        mlist = results.get(name, [])
        if not mlist:
            print(f"{name:<16} {'N/A':>6} {'N/A':>8} {'N/A':>5} {'N/A':>4} {'—':>32}  {role}")
            continue
        s = summarize_matches(mlist)
        dist = s["match_distribution"]
        assert isinstance(dist, dict)
        dcols = "".join(f"{dist.get(i, 0):>4}" for i in range(7))
        print(
            f"{name:<16} {float(s['avg']):>6.3f} {float(s['high_match_rate']):>8.2f} "
            f"{int(s['top_match_count']):>5} {int(s['max_matched']):>4} {dcols}  {role}"
        )


if __name__ == "__main__":
    run()
