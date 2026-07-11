"""Dead Zone(D꼴 분포) 후처리: 저분산·중권(z3) 집중·소수 과다 패턴에 신뢰도 보정.

정찰 요약(n≈1202): D그룹 평균 분산 ~142, A ~190; D는 중권·소수 쪽 경향.
교집합 채점은 confidence를 쓰지 않으므로, 본 모듈은 표시·가중 메타만 바꾼다.
"""

from __future__ import annotations

import logging
import statistics
from typing import Any

logger = logging.getLogger(__name__)

# D 평균 분산(~142)보다 확실히 낮은 조합을 저분산 데드존으로 본다 (원 지시 130 유지).
# 142 − 1σ(≈59) ≈ 83 은 더 공격적; 필요 시 상수만 조정.
DZ_VAR_THRESHOLD = 130.0

DZ_CONF_PENALTY_LOW_VAR = -0.10
DZ_CONF_PENALTY_Z3 = -0.05
DZ_CONF_PENALTY_HIGH_PRIME = -0.04
DZ_CONF_BONUS_LOW_PRIME = 0.03
DZ_CONF_CLAMP_LO = 0.01
DZ_CONF_CLAMP_HI = 0.99


def _population_variance(nums: list[int]) -> float:
    if len(nums) < 2:
        return 0.0
    return float(statistics.pvariance(nums))


def _is_prime(n: int) -> bool:
    if n < 2:
        return False
    i = 2
    while i * i <= n:
        if n % i == 0:
            return False
        i += 1
    return True


def _prime_count(nums: list[int]) -> int:
    return sum(1 for x in nums if _is_prime(int(x)))


def _z3_count(nums: list[int]) -> int:
    """1~45를 저·중·고 권으로 볼 때 중권(16~30) 개수."""
    return sum(1 for n in nums if 16 <= int(n) <= 30)


def annotate_set_with_dz(nums: list[int]) -> dict[str, Any]:
    """6개 번호로 D꼴 지표와 confidence 델타(합)를 계산한다."""
    clean = [int(x) for x in nums]
    if len(clean) != 6:
        return {
            "dz_var": 0.0,
            "dz_prime_cnt": 0,
            "dz_z3_cnt": 0,
            "dz_delta_conf": 0.0,
            "dz_filter_passed": True,
        }

    var = _population_variance(clean)
    pc = _prime_count(clean)
    z3 = _z3_count(clean)
    delta = 0.0
    if var < DZ_VAR_THRESHOLD:
        delta += DZ_CONF_PENALTY_LOW_VAR
    if z3 >= 3:
        delta += DZ_CONF_PENALTY_Z3
    if pc >= 3:
        delta += DZ_CONF_PENALTY_HIGH_PRIME
    if pc <= 1:
        delta += DZ_CONF_BONUS_LOW_PRIME

    passed = (var >= DZ_VAR_THRESHOLD) and (z3 < 3) and (pc < 4)

    return {
        "dz_var": round(var, 4),
        "dz_prime_cnt": pc,
        "dz_z3_cnt": z3,
        "dz_delta_conf": round(delta, 6),
        "dz_filter_passed": passed,
    }


def apply_dead_zone_to_row(row: dict[str, Any]) -> None:
    """예측 행 dict in-place: nums 기준으로 dz_* 채우고 confidence 클램프 보정."""
    nums = list(row.get("nums") or [])
    if len(nums) != 6:
        return

    meta = annotate_set_with_dz(nums)
    row["dz_var"] = meta["dz_var"]
    row["dz_prime_cnt"] = meta["dz_prime_cnt"]
    row["dz_z3_cnt"] = meta["dz_z3_cnt"]
    row["dz_delta_conf"] = meta["dz_delta_conf"]
    row["dz_filter_passed"] = meta["dz_filter_passed"]

    try:
        base = float(row.get("confidence", 0.5))
    except (TypeError, ValueError):
        base = 0.5
        logger.debug("dead_zone: invalid confidence, using 0.5")

    adj = base + float(meta["dz_delta_conf"])
    row["confidence"] = max(DZ_CONF_CLAMP_LO, min(DZ_CONF_CLAMP_HI, adj))
