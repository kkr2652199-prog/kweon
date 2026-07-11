"""v13_popularity_pair — 역사적 인기번호쌍 기반 조합 생성기 (전략 X 2뇌).

pair_popularity + number_popularity 체인 가중 추출로 6번호 × 5세트 생성.
R2: 당첨 확률 향상 주장 금지 — 기술통계 기반 조합 생성만.
"""

from __future__ import annotations

import random
import statistics
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

from app.lotto4.brains._utils import _weighted_draw_without_replacement, jaccard
from app.lotto4.brains.popularity_freq_brain import load_popularity_weights
from app.lotto4.models import get_lotto4_db

NUM_SETS = 5
TOP30_WINNER_MIN = 11
ERA = "C"
DISCLAIMER = (
    "역사적으로 당첨자가 많았던 회차에 자주 함께 등장한 번호쌍 기반입니다. "
    "당첨 확률은 모든 조합이 동일합니다."
)
BRAIN_TAG = "v13_popularity_pair"
RNG_SEED_MUL = 20260618


def _pair_key(a: int, b: int) -> tuple[int, int]:
    x, y = int(a), int(b)
    return (x, y) if x < y else (y, x)


def build_pair_popularity_table() -> dict[str, Any]:
    """era_C 상위30%(winner_cnt>=11) 회차에서 쌍 빈도 측정 → pair_popularity 적재."""
    conn = get_lotto4_db()
    try:
        rows = conn.execute(
            """
            SELECT n1, n2, n3, n4, n5, n6, winner_cnt
            FROM lotto4_winners_full
            WHERE era = ? AND winner_cnt >= ?
            ORDER BY drw_no
            """,
            (ERA, TOP30_WINNER_MIN),
        ).fetchall()

        pair_freq: dict[tuple[int, int], int] = defaultdict(int)
        for r in rows:
            nums = sorted([int(r[i]) for i in range(6)])
            for a, b in combinations(nums, 2):
                pair_freq[(a, b)] += 1

        top_draws_n = len(rows)
        conn.executescript(
            """
            DROP TABLE IF EXISTS pair_popularity;
            CREATE TABLE pair_popularity (
                num_a INTEGER NOT NULL,
                num_b INTEGER NOT NULL,
                freq INTEGER NOT NULL,
                freq_pct REAL NOT NULL,
                era TEXT NOT NULL DEFAULT 'C',
                updated_at TEXT DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (num_a, num_b, era)
            );
            """
        )
        insert_rows = []
        all_freqs: list[int] = []
        for a in range(1, 46):
            for b in range(a + 1, 46):
                f = pair_freq.get((a, b), 0)
                pct = round(f / top_draws_n, 4) if top_draws_n else 0.0
                insert_rows.append((a, b, f, pct, ERA))
                all_freqs.append(f)

        conn.executemany(
            """
            INSERT INTO pair_popularity (num_a, num_b, freq, freq_pct, era)
            VALUES (?, ?, ?, ?, ?)
            """,
            insert_rows,
        )
        conn.commit()

        ranked = sorted(
            [
                {"pair": f"{a}-{b}", "num_a": a, "num_b": b, "freq": f, "freq_pct": round(f / top_draws_n, 4)}
                for a, b, f, pct, _ in insert_rows
            ],
            key=lambda x: x["freq"],
            reverse=True,
        )
        nonzero = [x["freq"] for x in ranked if x["freq"] > 0]
        mean_f = statistics.mean(all_freqs)
        std_f = statistics.pstdev(all_freqs) if len(all_freqs) > 1 else 0.0
        max_f = max(all_freqs)
        min_f = min(all_freqs)
        cv = round(std_f / mean_f, 4) if mean_f > 0 else 0.0
        ratio = round(max_f / min_f, 4) if min_f > 0 else float("inf")
        spread = max_f - min_f

        if spread <= 3 or cv < 0.35 or ratio < 1.5:
            verdict = "약함"
        else:
            verdict = "유효"

        return {
            "era": ERA,
            "top_draws_n": top_draws_n,
            "winner_cnt_min": TOP30_WINNER_MIN,
            "total_pairs": 990,
            "pairs_with_freq_gt0": len(nonzero),
            "freq_mean": round(mean_f, 4),
            "freq_std": round(std_f, 4),
            "freq_min": min_f,
            "freq_max": max_f,
            "freq_cv": cv,
            "max_min_ratio": ratio,
            "top10_pairs": ranked[:10],
            "bottom10_pairs": ranked[-10:],
            "verdict": verdict,
        }
    finally:
        conn.close()


def load_pair_weights() -> dict[tuple[int, int], float]:
    """pair_popularity freq_pct 로드. 테이블 없으면 빌드."""
    conn = get_lotto4_db()
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pair_popularity'"
        ).fetchone()
        if not exists:
            conn.close()
            build_pair_popularity_table()
            conn = get_lotto4_db()

        rows = conn.execute(
            """
            SELECT num_a, num_b, freq_pct
            FROM pair_popularity
            WHERE era = ?
            """,
            (ERA,),
        ).fetchall()
        if not rows:
            build_pair_popularity_table()
            rows = conn.execute(
                """
                SELECT num_a, num_b, freq_pct
                FROM pair_popularity
                WHERE era = ?
                """,
                (ERA,),
            ).fetchall()

        return {
            _pair_key(int(r[0]), int(r[1])): max(float(r[2]), 0.001)
            for r in rows
        }
    finally:
        conn.close()


def avg_pair_score(nums: list[int], pair_weights: dict[tuple[int, int], float]) -> float:
    """세트 15쌍의 평균 freq_pct."""
    pairs = list(combinations(sorted(int(n) for n in nums), 2))
    if not pairs:
        return 0.0
    vals = [pair_weights.get((a, b), 0.0) for a, b in pairs]
    return round(sum(vals) / len(vals), 4)


def _chain_pick(
    rng: random.Random,
    picked: list[int],
    number_weights: dict[int, float],
    pair_weights: dict[tuple[int, int], float],
) -> int | None:
    available = [n for n in range(1, 46) if n not in picked]
    if not available:
        return None

    weights: dict[int, float] = {}
    for c in available:
        if not picked:
            w = number_weights.get(c, 0.01)
        else:
            w = sum(pair_weights.get(_pair_key(c, p), 0.001) for p in picked)
            if w <= 0:
                w = number_weights.get(c, 0.01)
        weights[c] = max(float(w), 0.001)

    one = _weighted_draw_without_replacement(rng, weights, 1)
    return one[0] if one else None


def _draw_one_pair_set(
    rng: random.Random,
    number_weights: dict[int, float],
    pair_weights: dict[tuple[int, int], float],
    existing: list[list[int]],
    jaccard_limit: float = 0.5,
) -> list[int] | None:
    for _ in range(200):
        picked: list[int] = []
        ok = True
        for _step in range(6):
            n = _chain_pick(rng, picked, number_weights, pair_weights)
            if n is None:
                ok = False
                break
            picked.append(n)
        if not ok or len(picked) != 6:
            continue
        nums = sorted(picked)
        st = set(nums)
        if any(jaccard(st, set(prev)) >= jaccard_limit for prev in existing):
            continue
        return nums
    return None


def generate_pair_sets(
    target_draw_no: int,
    n_sets: int = NUM_SETS,
) -> dict[str, Any]:
    """체인 가중으로 인기쌍 기반 조합 n_sets개 생성."""
    number_weights = load_popularity_weights()
    pair_weights = load_pair_weights()
    sets: list[dict[str, Any]] = []
    existing: list[list[int]] = []

    for set_no in range(1, n_sets + 1):
        seed = int(target_draw_no) * RNG_SEED_MUL + set_no * 131
        rng = random.Random(seed)
        nums = _draw_one_pair_set(rng, number_weights, pair_weights, existing)
        if nums is None:
            continue
        existing.append(nums)
        sets.append(
            {
                "set_no": set_no,
                "numbers": nums,
                "avg_pair_score": avg_pair_score(nums, pair_weights),
            }
        )

    return {
        "target_draw_no": int(target_draw_no),
        "brain": BRAIN_TAG,
        "disclaimer": DISCLAIMER,
        "source_tables": ["number_popularity", "pair_popularity"],
        "sets": sets,
    }


def generate(target_draw_no: int) -> dict[str, Any]:
    """API·테스트용 진입점."""
    return generate_pair_sets(target_draw_no)
