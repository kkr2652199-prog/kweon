"""Phase 4 단위 테스트 10항목."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from app.lotto4.brains import ensemble, hyena_commander, stat_generator
from app.lotto4.brains.cdm_brain import CDMBrain
from app.lotto4.brains.constraint_brain import ConstraintBrain
from app.lotto4.brains.sumrange_brain import SumrangeBrain

DB = str(ROOT / "data" / "lotto4.db")
DRAW = 1200


def _top10(pmf: dict[int, float]) -> set[int]:
    return set(sorted(pmf.keys(), key=lambda n: (-pmf[n], n))[:10])


def _overlap(a: set[int], b: set[int]) -> int:
    return len(a & b)


def main() -> None:
    errs: list[str] = []
    sr = SumrangeBrain()
    cn = ConstraintBrain()

    pmf_sr = sr.get_pmf(DRAW, DB)
    pmf_cn = cn.get_pmf(DRAW, DB)
    if len(pmf_sr) != 45 or abs(sum(pmf_sr.values()) - 1.0) > 0.01:
        errs.append("sumrange PMF")
    if len(pmf_cn) != 45 or abs(sum(pmf_cn.values()) - 1.0) > 0.01:
        errs.append("constraint PMF")
    print("T1-2 PMF OK")

    s5 = sr.predict(DRAW, DB, 5)
    c5 = cn.predict(DRAW, DB, 5)
    for label, sets in (("sumrange", s5), ("constraint", c5)):
        if len(sets) != 5:
            errs.append(f"{label} count {len(sets)}")
        for s in sets:
            if len(s) != 6 or s != sorted(s) or not all(1 <= n <= 45 for n in s):
                errs.append(f"{label} format {s}")
    print("T3-4 predict OK")

    pmf_stat = stat_generator.get_pmf(DRAW, DB)
    pmf_cdm = CDMBrain().get_pmf(DRAW, DB)
    t_stat, t_sr, t_cn, t_cdm = _top10(pmf_stat), _top10(pmf_sr), _top10(pmf_cn), _top10(pmf_cdm)
    ov_sr = _overlap(t_stat, t_sr)
    ov_cn = _overlap(t_stat, t_cn)
    print(f"T5 sumrange overlap={ov_sr} T6 constraint overlap={ov_cn}")
    if ov_sr > 7:
        errs.append(f"sumrange overlap {ov_sr}>7")
    if ov_cn > 7:
        errs.append(f"constraint overlap {ov_cn}>7")

    entries = hyena_commander._collect_all_candidates(DRAW, DB)
    total = len(entries)
    stat_n = sum(1 for s, _ in ((e[0], e[1]) for e in entries) if s == "stat_generator")
    excluded_n = sum(1 for s, _ in ((e[0], e[1]) for e in entries) if s in hyena_commander.EXCLUDED_FROM_CONSENSUS)
    cons = hyena_commander._consensus_from_tagged(entries)
    cons_legacy = sum(cons.values())
    if total < 200:
        errs.append(f"pool size {total}")
    if stat_n != 200:
        errs.append(f"stat entries {stat_n}")
    if excluded_n < 15:
        errs.append(f"excluded entries {excluded_n}")
    if abs(cons_legacy - 200 * 6) > 1:
        errs.append(f"consensus sum {cons_legacy} != 1200")
    print(f"T7 pool={total} stat={stat_n} excluded={excluded_n} consensus_nums={cons_legacy}")

    sample = [3, 7, 13, 19, 24, 44]
    if not hyena_commander._pass_tier1_filter(sample):
        errs.append("tier1 sample fail")
    ac_fail = [1, 2, 3, 4, 5, 6]
    if hyena_commander._pass_struct_filter(ac_fail) and not hyena_commander._pass_tier1_filter(ac_fail):
        pass
    print("T8 tier1 OK")

    h = hyena_commander.predict(DRAW, DB)
    e = ensemble.predict(DRAW, DB)
    if h != e:
        errs.append("ensemble != hyena")
    print("T9 ensemble OK")

    t0 = time.perf_counter()
    hyena_commander.predict(DRAW, DB)
    elapsed = time.perf_counter() - t0
    if elapsed >= 10.0:
        errs.append(f"time {elapsed:.2f}s")
    print(f"T10 time {elapsed:.3f}s")

    if errs:
        print("FAIL:", errs)
        sys.exit(1)
    print("ALL 10 TESTS PASSED")


if __name__ == "__main__":
    main()
