"""v13_shape — 역사적 당첨 형태 기반 조합 생성기 (전략 X 3뇌).

shape_profile(era_C 상위30%) 형태대에 부합하는 세트 선별 → 6번호 × 5세트.
R2: 당첨 확률 향상 주장 금지 — 기술통계 기반 조합 생성만.
"""

from __future__ import annotations

import json
import random
import statistics
from collections import Counter
from typing import Any

from app.lotto4.brains._utils import jaccard
from app.lotto4.models import get_lotto4_db

NUM_SETS = 5
TOP30_WINNER_MIN = 11
ERA = "C"
DISCLAIMER = (
    "역사적으로 당첨자가 많았던 회차의 번호 구성 형태 기반입니다. "
    "당첨 확률은 모든 조합이 동일합니다."
)
BRAIN_TAG = "v13_shape"
RNG_SEED_MUL = 20260619
CANDIDATE_POOL = 800
ODD_CNT_RANGE = (2, 4)
DECADE_MIN = 3


def _decade(n: int) -> int:
    return n // 10


def extract_shape_metrics(nums: list[int]) -> dict[str, int]:
    s = sorted(int(n) for n in nums)
    return {
        "sum6": sum(s),
        "odd_cnt": sum(1 for n in s if n % 2 == 1),
        "low_cnt": sum(1 for n in s if n <= 22),
        "decade_cnt": len({_decade(n) for n in s}),
    }


def _percentile(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    xs = sorted(vals)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    if f == c:
        return xs[f]
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def _collect_draw_shapes(rows: list) -> list[dict[str, int]]:
    out: list[dict[str, int]] = []
    for r in rows:
        nums = [int(r[i]) for i in range(6)]
        out.append(extract_shape_metrics(nums))
    return out


def _dist_counter(field: str, shapes: list[dict[str, int]]) -> dict[str, int]:
    c: Counter[int] = Counter()
    for s in shapes:
        c[int(s[field])] += 1
    return {str(k): int(v) for k, v in sorted(c.items())}


def _segment_summary(shapes: list[dict[str, int]]) -> dict[str, Any]:
    sums = [float(s["sum6"]) for s in shapes]
    lows = [float(s["low_cnt"]) for s in shapes]
    decades = [float(s["decade_cnt"]) for s in shapes]
    return {
        "n": len(shapes),
        "sum6": {
            "mean": round(statistics.mean(sums), 2) if sums else 0.0,
            "std": round(statistics.pstdev(sums), 2) if len(sums) > 1 else 0.0,
            "p5": round(_percentile(sums, 5), 2),
            "p95": round(_percentile(sums, 95), 2),
        },
        "odd_cnt_dist": _dist_counter("odd_cnt", shapes),
        "low_cnt_dist": _dist_counter("low_cnt", shapes),
        "decade_coverage_dist": _dist_counter("decade_cnt", shapes),
        "low_cnt_mean": round(statistics.mean(lows), 4) if lows else 0.0,
        "decade_cnt_mean": round(statistics.mean(decades), 4) if decades else 0.0,
    }


def _save_profile_row(
    conn: Any, era: str, segment: str, metric: str, data: dict[str, Any]
) -> None:
    conn.execute(
        """
        INSERT INTO shape_profile (era, segment, metric, data_json)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(era, segment, metric) DO UPDATE SET
            data_json = excluded.data_json,
            updated_at = datetime('now','localtime')
        """,
        (era, segment, metric, json.dumps(data, ensure_ascii=False)),
    )


def build_shape_profile_table() -> dict[str, Any]:
    """era_C 상위30% vs 전체 형태 분포 측정 → shape_profile 적재."""
    conn = get_lotto4_db()
    try:
        all_rows = conn.execute(
            """
            SELECT n1, n2, n3, n4, n5, n6, winner_cnt
            FROM lotto4_winners_full
            WHERE era = ? AND winner_cnt > 0
            ORDER BY drw_no
            """,
            (ERA,),
        ).fetchall()
        top_rows = [r for r in all_rows if int(r[6]) >= TOP30_WINNER_MIN]

        all_shapes = _collect_draw_shapes(all_rows)
        top_shapes = _collect_draw_shapes(top_rows)
        top_summary = _segment_summary(top_shapes)
        all_summary = _segment_summary(all_shapes)

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS shape_profile (
                era TEXT NOT NULL,
                segment TEXT NOT NULL,
                metric TEXT NOT NULL,
                data_json TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (era, segment, metric)
            );
            """
        )
        _save_profile_row(conn, ERA, "top30", "summary", top_summary)
        _save_profile_row(conn, ERA, "all", "summary", all_summary)
        conn.commit()

        t_sum = top_summary["sum6"]
        a_sum = all_summary["sum6"]
        sum_delta = round(t_sum["mean"] - a_sum["mean"], 2)
        odd_top = {int(k): v for k, v in top_summary["odd_cnt_dist"].items()}
        odd_all = {int(k): v for k, v in all_summary["odd_cnt_dist"].items()}
        top_odd_24_pct = round(
            100.0 * (odd_top.get(2, 0) + odd_top.get(3, 0) + odd_top.get(4, 0))
            / max(top_summary["n"], 1),
            2,
        )
        all_odd_24_pct = round(
            100.0 * (odd_all.get(2, 0) + odd_all.get(3, 0) + odd_all.get(4, 0))
            / max(all_summary["n"], 1),
            2,
        )
        decade_delta = round(
            top_summary["decade_cnt_mean"] - all_summary["decade_cnt_mean"], 4
        )
        low_delta = round(top_summary["low_cnt_mean"] - all_summary["low_cnt_mean"], 4)

        notable = 0
        if abs(sum_delta) >= 3:
            notable += 1
        if abs(top_odd_24_pct - all_odd_24_pct) >= 5:
            notable += 1
        if abs(decade_delta) >= 0.15:
            notable += 1
        if abs(low_delta) >= 0.2:
            notable += 1
        verdict = "유효" if notable >= 2 else "약함, 필터로만 사용"

        return {
            "era": ERA,
            "top30_draws_n": top_summary["n"],
            "all_draws_n": all_summary["n"],
            "winner_cnt_min_top30": TOP30_WINNER_MIN,
            "top30_summary": top_summary,
            "all_summary": all_summary,
            "compare": {
                "sum6_mean_delta_top30_minus_all": sum_delta,
                "odd_cnt_2to4_pct_top30": top_odd_24_pct,
                "odd_cnt_2to4_pct_all": all_odd_24_pct,
                "low_cnt_mean_delta": low_delta,
                "decade_cnt_mean_delta": decade_delta,
            },
            "verdict": verdict,
        }
    finally:
        conn.close()


def load_shape_profile() -> dict[str, Any]:
    """shape_profile top30 summary 로드. 없으면 빌드."""
    conn = get_lotto4_db()
    try:
        row = conn.execute(
            """
            SELECT data_json FROM shape_profile
            WHERE era = ? AND segment = 'top30' AND metric = 'summary'
            """,
            (ERA,),
        ).fetchone()
        if not row:
            conn.close()
            build_shape_profile_table()
            conn = get_lotto4_db()
            row = conn.execute(
                """
                SELECT data_json FROM shape_profile
                WHERE era = ? AND segment = 'top30' AND metric = 'summary'
                """,
                (ERA,),
            ).fetchone()
        return json.loads(row[0]) if row else {}
    finally:
        conn.close()


def _matches_shape(metrics: dict[str, int], profile: dict[str, Any]) -> bool:
    sum6 = profile.get("sum6", {})
    p5 = float(sum6.get("p5", 100))
    p95 = float(sum6.get("p95", 175))
    odd = metrics["odd_cnt"]
    return (
        p5 <= metrics["sum6"] <= p95
        and ODD_CNT_RANGE[0] <= odd <= ODD_CNT_RANGE[1]
        and metrics["decade_cnt"] >= DECADE_MIN
    )


def _random_combo(rng: random.Random) -> list[int]:
    return sorted(rng.sample(range(1, 46), 6))


def _draw_shape_sets(
    rng: random.Random,
    profile: dict[str, Any],
    existing: list[list[int]],
    jaccard_limit: float = 0.5,
) -> list[int] | None:
    candidates: list[list[int]] = []
    for _ in range(CANDIDATE_POOL):
        nums = _random_combo(rng)
        metrics = extract_shape_metrics(nums)
        if not _matches_shape(metrics, profile):
            continue
        st = set(nums)
        if any(jaccard(st, set(prev)) >= jaccard_limit for prev in existing):
            continue
        if any(jaccard(st, set(prev)) >= jaccard_limit for prev in candidates):
            continue
        candidates.append(nums)
        if len(candidates) >= 1:
            return nums
    return None


def generate_shape_sets(target_draw_no: int, n_sets: int = NUM_SETS) -> dict[str, Any]:
    """형태대 부합 세트 n_sets개 생성."""
    profile = load_shape_profile()
    sets: list[dict[str, Any]] = []
    existing: list[list[int]] = []

    for set_no in range(1, n_sets + 1):
        seed = int(target_draw_no) * RNG_SEED_MUL + set_no * 173
        rng = random.Random(seed)
        nums = _draw_shape_sets(rng, profile, existing)
        if nums is None:
            continue
        existing.append(nums)
        metrics = extract_shape_metrics(nums)
        sets.append(
            {
                "set_no": set_no,
                "numbers": nums,
                "shape_metrics": metrics,
            }
        )

    return {
        "target_draw_no": int(target_draw_no),
        "brain": BRAIN_TAG,
        "disclaimer": DISCLAIMER,
        "source_table": "shape_profile",
        "shape_criteria": {
            "sum6_range": [
                profile.get("sum6", {}).get("p5"),
                profile.get("sum6", {}).get("p95"),
            ],
            "odd_cnt_range": list(ODD_CNT_RANGE),
            "decade_cnt_min": DECADE_MIN,
        },
        "sets": sets,
    }


def generate(target_draw_no: int) -> dict[str, Any]:
    """API·테스트용 진입점."""
    return generate_shape_sets(target_draw_no)
