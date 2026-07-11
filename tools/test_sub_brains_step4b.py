"""5단계-B — ev_brain / evolution_brain 단위 테스트."""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from app.lotto4.brains import ev_brain, evolution_brain

DB_PATH = str(ROOT / "data" / "lotto4.db")


def _pop_geo_full(s: list[int], draw_no: int, db: str) -> float:
    p = ev_brain.popularity_score(s, draw_no, db)
    return float(p ** (1.0 / 6.0))


def main() -> None:
    fails: list[str] = []
    draw_no = 1224

    ev_sets = ev_brain.predict(draw_no, DB_PATH)
    if len(ev_sets) != 5:
        fails.append(f"ev predict: 기대 5세트, 실제 {len(ev_sets)}")
    for i, s in enumerate(ev_sets):
        if len(s) != 6 or len(set(s)) != 6 or not all(1 <= x <= 45 for x in s):
            fails.append(f"ev 세트{i+1} 형식")

    pops_geo = [_pop_geo_full(s, draw_no, DB_PATH) for s in ev_sets]
    mean_pop = sum(pops_geo) / len(pops_geo) if pops_geo else 9.99
    if mean_pop >= 1.0:
        fails.append(f"ev 평균 popularity^1/6 기대 <1.0, 실제 {mean_pop:.4f}")

    mu31 = 6 * 31 / 45
    bc = [sum(1 for n in s if n <= 31) for s in ev_sets]
    if sum(bc) / len(bc) >= mu31 - 0.15:
        fails.append(f"생일(1~31) 개수 평균 {sum(bc)/len(bc):.2f} >= 기대 {mu31:.2f}-0.15")

    pop_set = [3, 7, 14, 21, 28, 35]
    unpop_set = [33, 34, 38, 40, 41, 43]
    rs = ev_brain.rescore([pop_set, unpop_set, list(range(1, 7))], draw_no, DB_PATH)
    if len(rs) != 3:
        fails.append("ev rescore 개수")
    elif rs[0][0] != sorted(unpop_set):
        top = rs[0][0]
        if ev_brain.ev_score_for_set(top, draw_no, DB_PATH) < ev_brain.ev_score_for_set(
            sorted(pop_set), draw_no, DB_PATH
        ):
            fails.append("비인기 세트가 ev_score 상위가 아님")

    evo_sets = evolution_brain.predict(draw_no, DB_PATH)
    if len(evo_sets) != 5:
        fails.append(f"evolution predict 개수 {len(evo_sets)}")

    dw = evolution_brain.get_dynamic_weights(draw_no, DB_PATH)
    ssum = sum(dw.values())
    if abs(ssum - 1.0) > 0.02:
        fails.append(f"dynamic_weights 합={ssum}")
    for t, w in dw.items():
        if not (0.1 - 1e-6 <= w <= 0.5 + 1e-6):
            fails.append(f"{t} 가중 {w} not in [0.1,0.5]")

    ers = evolution_brain.rescore([[5, 12, 22, 28, 33, 40], [7, 8, 9, 10, 11, 12], [25, 26, 31, 35, 41, 44]], draw_no, DB_PATH)
    if len(ers) != 3:
        fails.append("evolution rescore")

    evolution_brain.update_trust(1222, DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM lotto_evolution_trust_army4 WHERE draw_no = 1222"
        ).fetchone()[0]
        if int(n) < 4:
            fails.append(f"update_trust 후 draw 1222 행 수 {n}, 기대 4")
    finally:
        conn.close()

    print("기대값 5세트:", ev_sets)
    print("popularity^(1/6) 평균:", mean_pop)
    print("dynamic_weights:", dw)
    print("진화 5세트:", evo_sets)

    if fails:
        print("\n실패:")
        for f in fails:
            print(" ", f)
        print("\n[FAIL] 서브뇌 5단계-B 단위 테스트 일부 실패")
    else:
        print("\n[OK] 서브뇌 5단계-B 단위 테스트 전부 통과")


if __name__ == "__main__":
    main()
