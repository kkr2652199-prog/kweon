"""CDM 뇌 이식 단위 테스트 8개 (지시서 STEP 4)."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from app.lotto4.brains import hyena_commander
from app.lotto4.brains import ensemble
from app.lotto4.brains import stat_generator
from app.lotto4.brains.cdm_brain import CDMBrain, _pass_struct_filter

DB = str(ROOT / "data" / "lotto4.db")
DRAW = 1200


def main() -> None:
    errs: list[str] = []
    cdm = CDMBrain()

    pmf = cdm.get_pmf(DRAW, DB)
    if set(pmf.keys()) != set(range(1, 46)):
        errs.append("PMF 키 45개 아님")
    if abs(sum(pmf.values()) - 1.0) > 0.01:
        errs.append(f"PMF 합계 {sum(pmf.values()):.4f}")
    if any(v < 0 for v in pmf.values()):
        errs.append("PMF 음수 존재")
    print("T1 PMF: OK", flush=True)

    pmf2 = cdm.get_pmf(DRAW, DB)
    if pmf != pmf2:
        errs.append("PMF 비결정론적")
    print("T2 PMF deterministic: OK", flush=True)

    sets5 = cdm.predict(DRAW, DB, 5)
    if len(sets5) != 5:
        errs.append(f"세트 수 {len(sets5)} != 5")
    for s in sets5:
        if len(s) != 6 or s != sorted(s):
            errs.append(f"세트 형식 오류: {s}")
        if not all(1 <= n <= 45 for n in s):
            errs.append(f"범위 오류: {s}")
    print("T3 predict 5 sets: OK", flush=True)

    for s in sets5:
        if not _pass_struct_filter(s):
            errs.append(f"구조필터 실패: {s}")
    print("T4 struct filter: OK", flush=True)

    pmf100 = cdm.get_pmf(100, DB)
    if len(pmf100) != 45:
        errs.append("draw 100 PMF 실패")
    print("T5 early draw: OK", flush=True)

    h1 = hyena_commander.predict(DRAW, DB)
    h2 = hyena_commander.predict(DRAW, DB)
    if h1 != h2:
        errs.append("hyena 비결정론적")
    if len(h1) != 5:
        errs.append(f"hyena 세트 {len(h1)}")
    print("T6 hyena deterministic: OK", flush=True)

    e1 = ensemble.predict(DRAW, DB)
    if e1 != h1:
        errs.append("ensemble != hyena")
    print("T7 ensemble == hyena: OK", flush=True)

    t0 = time.perf_counter()
    hyena_commander.predict(DRAW, DB)
    elapsed = time.perf_counter() - t0
    if elapsed >= 5.0:
        errs.append(f"시간 {elapsed:.2f}s >= 5s")
    print(f"T8 timing: {elapsed:.3f}s OK", flush=True)

    if errs:
        print("FAIL:", errs)
        sys.exit(1)
    print("ALL 8 TESTS PASSED")


if __name__ == "__main__":
    main()
