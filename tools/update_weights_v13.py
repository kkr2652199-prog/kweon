"""
백테스트 성격의 평가: 회차당 best 적중 평균으로 current_weight 갱신.
정규화: 최고 뇌 = 100.0 (3군 hyena 100.0 스케일 맞춤)
"""

from __future__ import annotations

import importlib
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from app.lotto4.v13_weights_v2 import init_v13_v2_seeds

DB_PATH = str(ROOT / "data" / "lotto4.db")
EVAL_START = 800
EVAL_END = 1222

BRAINS: dict[str, str] = {
    "v13_struct": "app.lotto4.brains.struct_brain",
    "v13_cdm": "app.lotto4.brains.cdm_brain",
    "v13_ensemble": "app.lotto4.brains.ensemble",
    "v13_gap": "app.lotto4.brains.gap_brain",
    "v13_seq": "app.lotto4.brains.seq_brain",
    "v13_cond_prob": "app.lotto4.brains.cond_prob_brain",
    "v13_diversity": "app.lotto4.brains.diversity_brain",
    "v13_evolution": "app.lotto4.brains.evolution_brain",
    "v13_ev": "app.lotto4.brains.ev_brain",


def load_actual(db_path: str) -> dict[int, set[int]]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT draw_no, num1, num2, num3, num4, num5, num6
            FROM lotto_draws
            ORDER BY draw_no
            """
        ).fetchall()
    finally:
        conn.close()
    return {int(r[0]): {int(r[i]) for i in range(1, 7)} for r in rows}


def main() -> None:
    init_v13_v2_seeds()
    actual = load_actual(DB_PATH)
    test_draws = sorted(d for d in actual if EVAL_START <= d <= EVAL_END)
    if not test_draws:
        print("평가 구간에 당첨 데이터가 없습니다.")
        return

    t0 = time.perf_counter()
    print(f"가중치 평가 구간: {test_draws[0]}~{test_draws[-1]} ({len(test_draws)}회차)")

    scores: dict[str, float] = {}
    for tag, mod_path in BRAINS.items():
        mod = importlib.import_module(mod_path)
        pred = getattr(mod, "predict", None)
        if not callable(pred):
            scores[tag] = 0.0
            continue
        best_list: list[int] = []
        for n, draw_no in enumerate(test_draws, 1):
            real = actual[draw_no]
            try:
                sets = pred(draw_no, DB_PATH)
                best = max((len(set(s) & real) for s in (sets or []) if len(s) == 6), default=0)
            except Exception as e:  # noqa: BLE001
                print(f"  [WARN] {tag} draw={draw_no}: {e}")
                best = 0
            best_list.append(best)
            if n % 100 == 0:
                print(f"  {tag}: ... {n}/{len(test_draws)}", flush=True)
        avg = sum(best_list) / len(best_list) if best_list else 0.0
        scores[tag] = avg
        print(f"  {tag}: best_avg = {avg:.4f}")

    max_score = max(scores.values()) if scores else 1.0
    if max_score <= 0:
        max_score = 1.0

    weights = {tag: round(float(scores[tag]) / max_score * 100.0, 1) for tag in scores}

    print()
    print("새 가중치:")
    for tag, w in sorted(weights.items(), key=lambda x: x[1], reverse=True):
        print(f"  {tag}: {w}")

    conn = sqlite3.connect(DB_PATH)
    try:
        for tag, w in weights.items():
            conn.execute(
                """
                UPDATE lotto_brain_weights_army4
                SET current_weight = ?, updated_at = datetime('now','localtime')
                WHERE brain_tag = ?
                """,
                (w, tag),
            )
        conn.commit()

        rows = conn.execute(
            """
            SELECT brain_tag, current_weight FROM lotto_brain_weights_army4
            WHERE brain_tag LIKE 'v13_%'
            ORDER BY current_weight DESC
            """
        ).fetchall()
    finally:
        conn.close()

    print()
    print("DB 반영 확인:")
    for tag, w in rows:
        print(f"  {tag}: {w}")

    print()
    print(f"총 소요: {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()
