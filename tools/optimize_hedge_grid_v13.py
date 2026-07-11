"""
Hedge(FINAL_SCORE) 가중치 그리드 서치 — 검증 구간 기본 1023~1222회차.

`ensemble.precompute_combo_scores` 를 회짓수만큼 1회 캐시한 뒤,
가중치 조합마다 `pick_with_final_weights` 만 반복합니다.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

DB_DEFAULT = str(ROOT / "data" / "lotto4.db")


def load_actuals(db_path: str, lo: int, hi: int) -> dict[int, tuple[set[int], int]]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT draw_no, num1, num2, num3, num4, num5, num6, bonus
            FROM lotto_draws
            WHERE draw_no >= ? AND draw_no <= ?
            """,
            (lo, hi),
        ).fetchall()
    finally:
        conn.close()
    return {
        int(r[0]): ({int(r[i]) for i in range(1, 7)}, int(r[7]))
        for r in rows
    }


def valid_weight_grid():
    cons = [0.25, 0.30, 0.35, 0.40, 0.45]
    struct = [0.15, 0.20, 0.25, 0.30]
    gap = [0.05, 0.10, 0.15, 0.20]
    div = [0.05, 0.10, 0.15, 0.20]
    ev = [0.05, 0.10, 0.15]
    out: list[tuple[float, float, float, float, float]] = []
    for t in product(cons, struct, gap, div, ev):
        if abs(sum(t) - 1.0) < 1e-9:
            out.append(tuple(float(x) for x in t))
    return out


def pick_sets_from_pack(pack, wtuple):
    from app.lotto4.brains import ensemble  # noqa: PLC0415

    picked, _ = ensemble.pick_with_final_weights_lexsort(pack, wtuple)
    return [p[0] for p in picked[:5]]


def objective_on_draws(
    packs: dict,
    draw_list: list[int],
    actuals: dict[int, tuple[set[int], int]],
    wtuple: tuple[float, float, float, float, float],
) -> tuple[float, int, int, float]:
    """반환: score, n5p, n4, avg_matched"""
    n5p = n4 = 0
    mcs: list[int] = []
    for d in draw_list:
        win, _ = actuals[d]
        for nums in pick_sets_from_pack(packs[d], wtuple):
            mc = len(win & set(nums))
            mcs.append(mc)
            if mc >= 5:
                n5p += 1
            elif mc == 4:
                n4 += 1
    avg = sum(mcs) / len(mcs) if mcs else 0.0
    score = n5p * 100 + n4 * 10 + avg
    return score, n5p, n4, avg


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB_DEFAULT)
    ap.add_argument("--val-from", type=int, default=1023)
    ap.add_argument("--val-to", type=int, default=1222)
    args = ap.parse_args()

    from app.lotto4.brains import ensemble  # noqa: PLC0415

    db_path = os.path.abspath(args.db)
    v0, v1 = int(args.val_from), int(args.val_to)
    actuals = load_actuals(db_path, v0, v1)
    draw_list = sorted(actuals.keys())
    if not draw_list:
        print("검증 회차가 없습니다.")
        return

    print(f"캐시 precompute: {len(draw_list)}회차 …", flush=True)
    packs: dict[int, object] = {}
    for i, d in enumerate(draw_list):
        packs[d] = ensemble.precompute_combo_scores(d, db_path)
        if (i + 1) % 20 == 0:
            print(f"  … {i + 1}/{len(draw_list)}", flush=True)

    grid = valid_weight_grid()
    default_w = (
        float(ensemble.W_CONSENSUS),
        float(ensemble.W_STRUCT),
        float(ensemble.W_GAP),
        float(ensemble.W_DIV),
        float(ensemble.W_EV),
    )

    def report(name: str, wt: tuple[float, ...]) -> None:
        sc, a, b, av = objective_on_draws(packs, draw_list, actuals, wt)
        print(
            f"{name}: score={sc:.4f} (5+세트={a}, 4세트={b}, avg={av:.4f}) "
            f"w={tuple(round(x, 2) for x in wt)}"
        )

    print()
    report("기본(현재 ensemble 상수)", default_w)
    best = max(
        grid,
        key=lambda wt: objective_on_draws(packs, draw_list, actuals, wt)[0],
    )
    bsc, bn5, bn4, bavg = objective_on_draws(packs, draw_list, actuals, best)
    print(
        f"최적: score={bsc:.4f} (5+세트={bn5}, 4세트={bn4}, avg={bavg:.4f}) "
        f"w={tuple(round(x, 2) for x in best)}"
    )
    print()
    print("ensemble.py 에 적용할 상수:")
    print(f"W_CONSENSUS = {best[0]}")
    print(f"W_STRUCT = {best[1]}")
    print(f"W_GAP = {best[2]}")
    print(f"W_DIV = {best[3]}")
    print(f"W_EV = {best[4]}")


if __name__ == "__main__":
    main()
