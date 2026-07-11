"""
P2 — 헤지 가중치 궤적 시뮬 + v13_ensemble 평가 (실 DB `lotto_brain_weights_army4` 변경 없음).

회차 구간을 따라가며:
  1) 현재 시뮬 가중치로 하위 7뇌 예측 → ensemble(가중치 오버라이드) 5세트
  2) 8뇌 각각 평균 적중으로 헤지 1스텝 (`apply_hedge_step_to_weights`)

비교: `--compare-baseline` 이면 가중치를 항상 1.0으로 둔 ensemble과 나란히 요약.

사용 (프로젝트 루트):
  python tools/simulate_hedge_ensemble_v13.py --start 1200 --end 1222
  python tools/simulate_hedge_ensemble_v13.py --start 200 --end 1222 --init-weight 3.0 --snapshot-every 100 --write-db
"""

from __future__ import annotations

import argparse
import importlib
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from app.lotto4.brains import ensemble as ensemble_mod
from app.lotto4.v13_weights_v2 import (
    V13_V2_BRAIN_ORDER,
    V13_V2_SEED_WEIGHTS,
    apply_hedge_step_to_weights,
)

DB_DEFAULT = str(ROOT / "data" / "lotto4.db")

BRAINS: dict[str, str] = {
    "v13_struct": "app.lotto4.brains.struct_brain",
    "v13_cdm": "app.lotto4.brains.cdm_brain",
    "v13_seq": "app.lotto4.brains.seq_brain",
    "v13_cond_prob": "app.lotto4.brains.cond_prob_brain",
    "v13_diversity": "app.lotto4.brains.diversity_brain",
    "v13_evolution": "app.lotto4.brains.evolution_brain",
    "v13_gap": "app.lotto4.brains.gap_brain",
    "v13_ev": "app.lotto4.brains.ev_brain",
    "v13_ensemble": "app.lotto4.brains.ensemble",
}


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


def _avg_match(sets: list[list[int]], actual: set[int]) -> float:
    hits: list[int] = []
    for s in sets or []:
        if not isinstance(s, list) or len(s) != 6:
            continue
        hits.append(len(set(s) & actual))
    return sum(hits) / len(hits) if hits else 0.0


def _call_brain(tag: str, draw_no: int, db_path: str) -> list[list[int]]:
    mod_path = BRAINS[tag]
    mod = importlib.import_module(mod_path)
    fn = getattr(mod, "predict", None)
    if not callable(fn):
        return []
    raw = fn(draw_no, db_path)
    return raw if isinstance(raw, list) else []


def _initial_weights(init_override: float | None = None) -> dict[str, float]:
    if init_override is not None:
        return {t: float(init_override) for t in V13_V2_BRAIN_ORDER}
    return {t: float(V13_V2_SEED_WEIGHTS.get(t, 1.0)) for t in V13_V2_BRAIN_ORDER}

def _frozen_weights() -> dict[str, float]:
    return {t: 1.0 for t in V13_V2_BRAIN_ORDER}


def run(
    db_path: str,
    draws: list[int],
    *,
    compare_baseline: bool,
    init_weight: float | None = None,
    snapshot_every: int = 0,
) -> tuple[dict[str, float], list[tuple[int, float, dict[str, float]]], list[int], list[int]]:
    actual = load_actual(db_path)
    w_hedge = _initial_weights(init_weight)
    w_frozen = _frozen_weights()
    best_h: list[int] = []
    best_f: list[int] = []
    snapshots: list[tuple[int, float, dict[str, float]]] = []

    t0 = time.perf_counter()
    for idx, d in enumerate(draws):
        real = actual.get(d)
        if not real:
            continue

        av_h: dict[str, float] = {}
        for tag in V13_V2_BRAIN_ORDER:
            if tag == "v13_ensemble":
                break
            sets = _call_brain(tag, d, db_path)
            av_h[tag] = _avg_match(sets, real)

        ens_h = ensemble_mod.predict(d, db_path, weights_override=w_hedge)
        av_h["v13_ensemble"] = _avg_match(ens_h, real)

        if compare_baseline:
            ens_f = ensemble_mod.predict(d, db_path, weights_override=w_frozen)
        else:
            ens_f = ens_h

        bh = max((len(set(s) & real) for s in ens_h if isinstance(s, list) and len(s) == 6), default=0)
        best_h.append(bh)
        if compare_baseline:
            bf = max(
                (len(set(s) & real) for s in ens_f if isinstance(s, list) and len(s) == 6),
                default=0,
            )
            best_f.append(bf)

        w_hedge = apply_hedge_step_to_weights(w_hedge, av_h)

        if snapshot_every > 0 and (idx + 1) % snapshot_every == 0:
            vals = list(w_hedge.values())
            spread = max(vals) - min(vals) if vals else 0.0
            snap = {k: round(float(v), 4) for k, v in w_hedge.items()}
            snapshots.append((d, spread, snap))

    n = len(best_h)
    mean_bh = sum(best_h) / n if n else 0.0
    print()
    print("=== 헤지 시뮬 + ensemble ===")
    print(f"DB: {db_path}")
    print(f"회차: {draws[0]}~{draws[-1]} (유효 {n}회)")
    print(f"  ensemble 회차별 최고 적중 평균 (best_avg): {mean_bh:.4f}")

    if compare_baseline and best_f:
        mean_bf = sum(best_f) / len(best_f)
        print(f"  [비교] 가중치 1.0 고정 ensemble best_avg: {mean_bf:.4f}")
        print(f"  차이 (헤지 - 고정): {mean_bh - mean_bf:+.4f}")

    final_vals = list(w_hedge.values())
    final_spread = max(final_vals) - min(final_vals) if final_vals else 0.0
    print(f"\n최종 가중치 spread (max-min): {final_spread:.4f}")

    print("\n헤지 종료 시 시뮬 가중치 (순위):")
    for tag, w in sorted(w_hedge.items(), key=lambda x: -x[1]):
        print(f"  {tag}: {w:.4f}")

    if snapshots:
        print("\n=== 수렴 스냅샷 (100회차 단위: spread, 최고/최저 뇌) ===")
        for draw_no, spread, snap in snapshots:
            items = sorted(snap.items(), key=lambda x: -x[1])
            top_n, top_v = items[0]
            bot_n, bot_v = items[-1]
            print(
                f"  draw {draw_no}: spread={spread:.4f} "
                f"top={top_n}({top_v:.4f}) bot={bot_n}({bot_v:.4f})"
            )

    elapsed = time.perf_counter() - t0
    print(f"\n총 {elapsed:.1f}s")

    return w_hedge, snapshots, best_h, best_f

def _write_weights_to_db(db_path: str, weights: dict[str, float]) -> None:
    conn = sqlite3.connect(db_path)
    try:
        for tag, w in weights.items():
            conn.execute(
                """
                UPDATE lotto_brain_weights_army4
                SET current_weight = ?, updated_at = datetime('now','localtime')
                WHERE brain_tag = ?
                """,
                (round(float(w), 4), tag),
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
    print("\n=== DB 반영 확인 (lotto_brain_weights_army4) ===")
    for tag, w in rows:
        print(f"  {tag}: {w}")


def main() -> None:
    ap = argparse.ArgumentParser(description="헤지 궤적 시뮬 후 ensemble 지표 (P2)")
    ap.add_argument("--db", default=DB_DEFAULT, help="lotto4.sqlite 경로")
    ap.add_argument("--start", type=int, default=1200)
    ap.add_argument("--end", type=int, default=1222)
    ap.add_argument(
        "--init-weight",
        type=float,
        default=None,
        help="초기 가중치(8뇌 동일). 미지정 시 시드 1.0",
    )
    ap.add_argument(
        "--snapshot-every",
        type=int,
        default=0,
        metavar="N",
        help="N회차마다 spread 로그",
    )
    ap.add_argument(
        "--write-db",
        action="store_true",
        help="시뮬 최종 가중치를 lotto_brain_weights_army4에 반영",
    )
    ap.add_argument(
        "--compare-baseline",
        action="store_true",
        help="하위 7뇌 투표 가중치 1.0 고정 ensemble과 비교",
    )
    args = ap.parse_args()

    actual = load_actual(args.db)
    draws = sorted(d for d in actual if args.start <= d <= args.end)
    if not draws:
        print("구간에 당첨 데이터가 없습니다.")
        sys.exit(1)

    init_msg = args.init_weight if args.init_weight is not None else "seed1.0"
    print(
        f"시뮬 회차 수: {len(draws)} compare_baseline={args.compare_baseline} "
        f"init={init_msg} snapshot_every={args.snapshot_every} write_db={args.write_db}"
    )
    w_final, _snaps, _bh, _bf = run(
        args.db,
        draws,
        compare_baseline=args.compare_baseline,
        init_weight=args.init_weight,
        snapshot_every=args.snapshot_every,
    )
    if args.write_db:
        _write_weights_to_db(args.db, w_final)

if __name__ == "__main__":
    main()
