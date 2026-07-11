"""v13_diversity — Jaccard·제출 이력·십단위 커버리지 다양성 (5단계-A)."""

from __future__ import annotations

import random
import sqlite3
from collections import defaultdict

from app.lotto4.brains._utils import (
    jaccard,
    smart_filter_relaxed,
    sum_filter,
    odd_even_filter,
)

JACCARD_PAIR = 0.5
JACCARD_HISTORY = 0.6
NUM_SETS = 5
RECENT_ROUNDS = 10


def _decades_map() -> dict[int, list[int]]:
    d: dict[int, list[int]] = {
        0: list(range(1, 10)),
        1: list(range(10, 20)),
        2: list(range(20, 30)),
        3: list(range(30, 40)),
        4: list(range(40, 46)),
    }
    return d


def load_recent_submission_sets(
    db_path: str, draw_no: int, n_rounds: int = RECENT_ROUNDS
) -> list[list[int]]:
    """최근 n_rounds개 target 회차의 v13_ensemble 제출 세트."""
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            """
            SELECT target_draw_no, num1, num2, num3, num4, num5, num6
            FROM lotto_predictions_army4
            WHERE target_draw_no < ? AND brain_tag = 'v13_ensemble'
            ORDER BY target_draw_no DESC, id ASC
            """,
            (int(draw_no),),
        ).fetchall()
    except (OSError, sqlite3.Error):
        return []
    finally:
        if conn is not None:
            conn.close()

    by_draw: dict[int, list[list[int]]] = defaultdict(list)
    for r in rows:
        d = int(r[0])
        nums = [int(r[i]) for i in range(1, 7)]
        by_draw[d].append(nums)

    draws_sorted = sorted(by_draw.keys(), reverse=True)[:n_rounds]
    out: list[list[int]] = []
    for d in draws_sorted:
        out.extend(by_draw[d])
    return out


def diversity_score_for_set(
    s: list[int],
    candidate_sets: list[list[int]],
    recent_sets: list[list[int]],
) -> float:
    st = sorted({int(x) for x in s if 1 <= int(x) <= 45})
    if len(st) != 6:
        return 0.0
    ss = set(st)
    others = [o for o in candidate_sets if sorted(o) != st]
    if others:
        avg_j = sum(jaccard(ss, set(o)) for o in others) / len(others)
    else:
        avg_j = 0.0
    div_score = (1.0 - avg_j) * 5.0

    if recent_sets:
        min_hist = min(jaccard(ss, set(h)) for h in recent_sets)
    else:
        min_hist = 0.0
    div_score += (1.0 - min_hist) * 3.0

    decades_covered = len({n // 10 for n in st})
    div_score += decades_covered * 0.5
    return div_score


def _minmax_normalize(raw: list[float]) -> list[float]:
    if not raw:
        return []
    lo, hi = min(raw), max(raw)
    if hi - lo < 1e-9:
        return [0.5] * len(raw)
    return [(r - lo) / (hi - lo) for r in raw]


def score_combo(combo: set, target_draw: int, db) -> float:
    """Jaccard 다양성 점수 (0~1 정규화)."""
    st = sorted({int(x) for x in combo if 1 <= int(x) <= 45})
    if len(st) != 6:
        return 0.0
    recent = load_recent_submission_sets(db, target_draw)
    raw = diversity_score_for_set(st, [st], recent)
    return min(1.0, max(0.0, raw / 10.0))


def score_batch(combos: list, target_draw: int, db) -> list[float]:
    """배치 다양성 점수 (min-max 0~1)."""
    recent = load_recent_submission_sets(db, target_draw)
    cleaned: list[list[int]] = []
    valid_idx: list[int] = []
    for idx, combo in enumerate(combos):
        st = sorted({int(x) for x in combo if 1 <= int(x) <= 45})
        if len(st) == 6:
            cleaned.append(st)
            valid_idx.append(idx)
    raw = [diversity_score_for_set(st, cleaned, recent) for st in cleaned]
    normed = _minmax_normalize(raw)
    out = [0.0] * len(combos)
    for j, idx in enumerate(valid_idx):
        out[idx] = normed[j]
    return out


def rescore(
    candidate_sets: list[list[int]],
    draw_no: int,
    db_path: str,
) -> list[tuple[list[int], float]]:
    recent = load_recent_submission_sets(db_path, draw_no)
    cleaned: list[list[int]] = []
    for raw in candidate_sets:
        st = sorted({int(x) for x in raw if 1 <= int(x) <= 45})
        if len(st) == 6:
            cleaned.append(list(st))
    out: list[tuple[list[int], float]] = []
    for st in cleaned:
        sc = diversity_score_for_set(st, cleaned, recent)
        out.append((st, sc))
    out.sort(key=lambda x: -x[1])
    return out


def filter_duplicates(
    candidate_sets: list[list[int]],
    draw_no: int,
    db_path: str,
) -> list[list[int]]:
    recent = load_recent_submission_sets(db_path, draw_no)
    selected: list[list[int]] = []
    for raw in candidate_sets:
        st = sorted({int(x) for x in raw if 1 <= int(x) <= 45})
        if len(st) != 6:
            continue
        ss = set(st)
        if any(jaccard(ss, set(x)) >= JACCARD_PAIR for x in selected):
            continue
        if any(jaccard(ss, set(h)) >= JACCARD_HISTORY for h in recent):
            continue
        selected.append(list(st))
    return selected


def _try_decade_covering_combo(rng: random.Random) -> list[int] | None:
    dm = _decades_map()
    picked: list[int] = []
    used: set[int] = set()
    for d in range(5):
        pool = [n for n in dm[d] if n not in used]
        if not pool:
            return None
        n = rng.choice(pool)
        picked.append(n)
        used.add(n)
    d_extra = rng.randint(0, 4)
    pool = [n for n in dm[d_extra] if n not in used]
    if not pool:
        for d in range(5):
            pool = [n for n in dm[d] if n not in used]
            if pool:
                picked.append(rng.choice(pool))
                break
        if len(picked) != 6:
            return None
    else:
        picked.append(rng.choice(pool))
    return sorted(picked)


def predict(draw_no: int, db_path: str) -> list[list[int]]:
    rng = random.Random(draw_no * 271_829 + 10_007)
    recent = load_recent_submission_sets(db_path, draw_no)
    sets: list[list[int]] = []
    sum_range = (100, 175)

    for _ in range(4000):
        if len(sets) >= NUM_SETS:
            break
        cand = _try_decade_covering_combo(rng)
        if cand is None:
            cand = sorted(rng.sample(range(1, 46), 6))
        if not sum_filter(cand, sum_range[0], sum_range[1]):
            continue
        if not odd_even_filter(cand):
            continue
        if not smart_filter_relaxed(cand):
            continue
        if len({n // 10 for n in cand}) < 3:
            continue
        st = set(cand)
        if any(jaccard(st, set(p)) >= JACCARD_PAIR for p in sets):
            continue
        if any(jaccard(st, set(h)) >= JACCARD_HISTORY for h in recent):
            continue
        sets.append(cand)

    while len(sets) < NUM_SETS:
        cand = sorted(rng.sample(range(1, 46), 6))
        if (
            smart_filter_relaxed(cand)
            and len({n // 10 for n in cand}) >= 3
            and not any(jaccard(set(cand), set(p)) >= JACCARD_PAIR for p in sets)
        ):
            sets.append(cand)
        if rng.random() > 0.995 and len(sets) >= 3:
            break
    while len(sets) < NUM_SETS:
        sets.append(sorted(rng.sample(range(1, 46), 6)))
    return sets[:NUM_SETS]
