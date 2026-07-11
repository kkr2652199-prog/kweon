# -*- coding: utf-8
"""7뇌 1등가자 — 5뇌 25세트 READ-ONLY → F1_V2_STRICT (popavoid→wheel, 카피0).

활성 공식 F1_V2_STRICT: F1 가중 + 인기회피 25후보 → 커버리지 wheel 5세트.
  - 단일 뇌 세트와 COPY_OVERLAP(5) 이상 겹치면 폐기·재생성 (카피율 0).
  - k = 지목 뇌 수(합의) × N-1까지 뇌 번호 정밀도(walk-forward)
  - draw별 고정 시드로 결정론적.
generate_f1_sets(F1_BASE)는 대조·복구용으로 유지.
CAP2(SEL4+v3)는 _select_cap2_sets로 보존.
6뇌 lotto_predictions READ-ONLY. brain_tag=lead1.
"""
from __future__ import annotations

import logging
import random
import statistics
from collections import Counter, defaultdict

from app.hyodo.models import get_lotto_db, init_lotto_db

logger = logging.getLogger(__name__)

# 6뇌 DB 식별 (READ-ONLY 조회용 — hyena는 7뇌 선택 풀에서 제외)
SIX_BRAINS: tuple[str, ...] = ("stat", "markov", "llm", "lstm", "fusion", "hyena")
POOL_BRAINS: tuple[str, ...] = ("stat", "markov", "llm", "lstm", "fusion")
MIN_POOL_SETS = 25  # 5뇌 × 5세트
MAX_PER_BRAIN = 2  # CAP2: 한 뇌 최대 2세트
SETS_TO_PICK = 5
RECENCY_DECAY = 0.995
SEL4_COUNT = 3  # 참고(레거시); CAP2는 통합 풀 5세트
V3_COUNT = 2
BRAIN7_TAG = "lead1"
BRAIN7_METHOD = "1등가자"

# F1 과학적 조합 파라미터
COPY_OVERLAP = 5        # 단일 뇌 세트와 이 이상 겹치면 카피 → 배제
F1_MAX_ATTEMPTS = 40    # 카피 회피 재생성 상한
F1_SEED_MULT = 2654435761  # draw별 고정 시드 (결정론)
# F1_V2_STRICT (popavoid → wheel, 카피 0)
F1_FORMULA = "F1_V2_STRICT"
WHEEL_POOL = 25
POP_PENALTY = 1.5
SUM_CENTER = 138
STRICT_REFILL_ATTEMPTS = 60


def _load_flat_sets(conn, target_draw_no: int) -> list[tuple[str, tuple[int, ...]]]:
    """5뇌 25세트 (brain_tag, nums) — hyena 제외, READ-ONLY."""
    placeholders = ",".join("?" * len(POOL_BRAINS))
    rows = conn.execute(
        f"""
        SELECT brain_tag, num1, num2, num3, num4, num5, num6
        FROM lotto_predictions
        WHERE target_draw_no = ? AND brain_tag IN ({placeholders})
        ORDER BY brain_tag, id
        """,
        (target_draw_no, *POOL_BRAINS),
    ).fetchall()
    out: list[tuple[str, tuple[int, ...]]] = []
    for r in rows:
        tag = str(r[0])
        nums = tuple(sorted(int(r[i]) for i in range(1, 7)))
        out.append((tag, nums))
    return out


def _pool_brains_ready(conn, target_draw_no: int) -> bool:
    """5뇌 각 5세트 이상 — hyena 불필요."""
    placeholders = ",".join("?" * len(POOL_BRAINS))
    rows = conn.execute(
        f"""
        SELECT brain_tag, COUNT(*) AS c
        FROM lotto_predictions
        WHERE target_draw_no = ? AND brain_tag IN ({placeholders})
        GROUP BY brain_tag
        HAVING c >= 5
        """,
        (target_draw_no, *POOL_BRAINS),
    ).fetchall()
    return len(rows) >= len(POOL_BRAINS)


def _six_brain_ready(conn, target_draw_no: int) -> bool:
    """하위 호환 별칭 — 5뇌 풀 준비 여부."""
    return _pool_brains_ready(conn, target_draw_no)


def _win_plus_bonus(conn, draw_no: int) -> list[int]:
    r = conn.execute(
        "SELECT num1,num2,num3,num4,num5,num6,bonus FROM lotto_draws WHERE draw_no=?",
        (draw_no,),
    ).fetchone()
    if not r:
        return []
    return [int(r[i]) for i in range(7)]


def _draw_contribution(
    flat: list[tuple[str, tuple[int, ...]]],
    win_nums: list[int],
) -> dict[str, float]:
    """정답(6+보너스) 각 v: k뇌 포착 → 1/k — 5뇌만."""
    by_brain: dict[str, set[int]] = defaultdict(set)
    for tag, nums in flat:
        by_brain[tag] |= set(nums)
    pres: dict[int, set[str]] = defaultdict(set)
    for tag, nums in by_brain.items():
        for n in nums:
            pres[n].add(tag)

    contrib = {b: 0.0 for b in POOL_BRAINS}
    for v in win_nums:
        catchers = pres.get(v, set())
        k = len(catchers)
        if k <= 0:
            continue
        share = 1.0 / k
        for b in catchers:
            if b in contrib:
                contrib[b] += share
    return contrib


def _build_contribution_history(conn, target_draw_no: int) -> list[tuple[int, dict[str, float]]]:
    """target_draw_no 미만 확정 회차만 — walk-forward, 5뇌 기여만."""
    draw_rows = conn.execute(
        """
        SELECT DISTINCT p.target_draw_no AS dn
        FROM lotto_predictions p
        INNER JOIN lotto_draws d ON d.draw_no = p.target_draw_no
        WHERE p.target_draw_no < ?
        ORDER BY p.target_draw_no
        """,
        (target_draw_no,),
    ).fetchall()

    history: list[tuple[int, dict[str, float]]] = []
    for (dn,) in draw_rows:
        flat = _load_flat_sets(conn, dn)
        if len(flat) < MIN_POOL_SETS:
            continue
        win7 = _win_plus_bonus(conn, dn)
        if len(win7) < 7:
            continue
        history.append((dn, _draw_contribution(flat, win7)))
    return history


def _recency_weights(
    history: list[tuple[int, dict[str, float]]],
    target_dn: int,
) -> dict[str, float]:
    weights = {b: 0.0 for b in POOL_BRAINS}
    for dn, contrib in history:
        if dn >= target_dn:
            continue
        factor = RECENCY_DECAY ** (target_dn - dn)
        for b in POOL_BRAINS:
            weights[b] += contrib.get(b, 0.0) * factor
    if all(w <= 0 for w in weights.values()):
        return {b: 1.0 for b in POOL_BRAINS}
    return weights


def _global_vote(flat: list[tuple[str, tuple[int, ...]]]) -> Counter[int]:
    votes: Counter[int] = Counter()
    for _, nums in flat:
        votes.update(nums)
    return votes


def _weighted_number_scores(
    flat: list[tuple[str, tuple[int, ...]]],
    brain_weights: dict[str, float],
) -> Counter[int]:
    by_brain: dict[str, set[int]] = defaultdict(set)
    for tag, nums in flat:
        by_brain[tag] |= set(nums)
    num_w: Counter[int] = Counter()
    for tag, nums_set in by_brain.items():
        w = brain_weights.get(tag, 0.0)
        for n in nums_set:
            num_w[n] += w
    return num_w


def _score_set_equal(nums: tuple[int, ...], votes: Counter[int]) -> float:
    return float(sum(votes.get(n, 0) for n in nums))


def _score_set_weighted(nums: tuple[int, ...], num_w: Counter[int]) -> float:
    return float(sum(num_w.get(n, 0.0) for n in nums))


def _rank_tagged_sets(
    flat: list[tuple[str, tuple[int, ...]]],
    scorer,
) -> list[tuple[str, tuple[int, ...], float]]:
    """점수 내림차순 unique (tag, nums, score)."""
    ranked = sorted(flat, key=lambda x: (-scorer(x[1]), x[0], x[1]))
    seen: set[tuple[int, ...]] = set()
    out: list[tuple[str, tuple[int, ...], float]] = []
    for tag, nums in ranked:
        if nums in seen:
            continue
        seen.add(nums)
        out.append((tag, nums, scorer(nums)))
    return out


def _select_cap2_sets(
    flat: list[tuple[str, tuple[int, ...]]],
    history: list[tuple[int, dict[str, float]]],
    target_dn: int,
) -> list[tuple[str, tuple[int, ...], str, float]]:
    """B1_CAP2: SEL4+v3 통합 풀 greedy, brain_tag당 최대 MAX_PER_BRAIN."""
    votes = _global_vote(flat)
    bw = _recency_weights(history, target_dn)
    weighted = _weighted_number_scores(flat, bw)

    sel4_rank = _rank_tagged_sets(flat, lambda n: _score_set_equal(n, votes))
    v3_rank = _rank_tagged_sets(flat, lambda n: _score_set_weighted(n, weighted))

    pool: list[tuple[str, tuple[int, ...], str, float]] = [
        (tag, nums, "SEL4", sc) for tag, nums, sc in sel4_rank
    ] + [
        (tag, nums, "V3", sc) for tag, nums, sc in v3_rank
    ]

    brain_cnt: Counter[str] = Counter()
    picks: list[tuple[str, tuple[int, ...], str, float]] = []
    seen_nums: set[tuple[int, ...]] = set()

    for tag, nums, src, score in pool:
        if nums in seen_nums:
            continue
        if brain_cnt[tag] >= MAX_PER_BRAIN:
            continue
        picks.append((tag, nums, src, score))
        seen_nums.add(nums)
        brain_cnt[tag] += 1
        if len(picks) >= SETS_TO_PICK:
            break
    return picks


def _rank_unique_sets(
    flat: list[tuple[str, tuple[int, ...]]],
    scorer,
    top_n: int,
    exclude: set[tuple[int, ...]] | None = None,
) -> list[tuple[tuple[int, ...], float]]:
    """점수 내림차순 unique 세트 top_n."""
    ex = exclude or set()
    ranked = sorted(
        flat,
        key=lambda x: (-scorer(x[1]), x[0], x[1]),
    )
    out: list[tuple[tuple[int, ...], float]] = []
    seen: set[tuple[int, ...]] = set()
    for _, nums in ranked:
        if nums in seen or nums in ex:
            continue
        seen.add(nums)
        out.append((nums, scorer(nums)))
        if len(out) >= top_n:
            break
    return out


# ─────────────────────────────────────────────────────────────
# F1 과학적 조합 (합의 k × 뇌 신뢰도) — 활성 공식
# ─────────────────────────────────────────────────────────────
def _union_presence(
    flat: list[tuple[str, tuple[int, ...]]],
) -> dict[int, set[str]]:
    """번호 -> 포착 뇌 집합(dedup)."""
    by_brain: dict[str, set[int]] = defaultdict(set)
    for tag, nums in flat:
        by_brain[tag] |= set(nums)
    pres: dict[int, set[str]] = defaultdict(set)
    for tag, s in by_brain.items():
        for n in s:
            pres[n].add(tag)
    return pres


def _brain_number_reliability(conn, target_draw_no: int) -> dict[str, float]:
    """N-1까지 뇌별 번호 정밀도 (walk-forward, 라플라스). 컨닝 금지."""
    pick = {b: 0 for b in POOL_BRAINS}
    win = {b: 0 for b in POOL_BRAINS}
    placeholders = ",".join("?" * len(POOL_BRAINS))
    rows = conn.execute(
        f"""
        SELECT p.target_draw_no dn, p.brain_tag,
               p.num1,p.num2,p.num3,p.num4,p.num5,p.num6,
               d.num1 w1,d.num2 w2,d.num3 w3,d.num4 w4,d.num5 w5,d.num6 w6
        FROM lotto_predictions p
        INNER JOIN lotto_draws d ON d.draw_no = p.target_draw_no
        WHERE p.target_draw_no < ? AND p.brain_tag IN ({placeholders})
        """,
        (target_draw_no, *POOL_BRAINS),
    ).fetchall()
    seen: dict[tuple[int, str], set[int]] = defaultdict(set)
    wins_by_draw: dict[int, set[int]] = {}
    for r in rows:
        dn = int(r[0])
        tag = str(r[1])
        nums = {int(r[i]) for i in range(2, 8)}
        if dn not in wins_by_draw:
            wins_by_draw[dn] = {int(r[i]) for i in range(8, 14)}
        seen[(dn, tag)] |= nums
    for (dn, tag), s in seen.items():
        wset = wins_by_draw.get(dn, set())
        for n in s:
            pick[tag] += 1
            if n in wset:
                win[tag] += 1
    return {b: (win[b] + 1) / (pick[b] + 2) for b in POOL_BRAINS}


def _f1_weights(
    pres: dict[int, set[str]], rel: dict[str, float]
) -> dict[int, float]:
    """번호 가중 = k × 포착뇌 평균 신뢰도."""
    out: dict[int, float] = {}
    for n, brains in pres.items():
        if not brains:
            continue
        k = len(brains)
        mean_rel = sum(rel.get(b, 0.0) for b in brains) / k
        out[n] = k * mean_rel
    return out


def _weighted_sample6(weights: dict[int, float], rng: random.Random) -> tuple[int, ...]:
    """비복원 가중 6개 추출."""
    pool = list(weights.items())
    picked: list[int] = []
    for _ in range(6):
        if not pool:
            break
        total = sum(w for _, w in pool)
        if total <= 0:
            rest = [n for n, _ in pool]
            rng.shuffle(rest)
            picked.extend(rest[: 6 - len(picked)])
            break
        r = rng.random() * total
        acc = 0.0
        for i, (n, w) in enumerate(pool):
            acc += w
            if r <= acc:
                picked.append(n)
                pool.pop(i)
                break
    return tuple(sorted(picked[:6]))


def _max_single_overlap(cand: tuple[int, ...], flat) -> int:
    return max((len(set(cand) & set(s)) for _, s in flat), default=0)


def generate_sets_with_weights(
    flat: list[tuple[str, tuple[int, ...]]],
    weights: dict[int, float],
    seed: int,
    n: int = SETS_TO_PICK,
    copy_filter: bool = True,
) -> list[tuple[tuple[int, ...], float, int]]:
    """가중 비복원 추출로 n세트 생성 — (nums, weight_score, max_overlap). 결정론적.

    copy_filter=True면 단일 뇌 세트와 COPY_OVERLAP 이상 겹치는 세트 배제(재생성).
    F1·FLAT_UNION 등이 이 코어를 공유(가중치만 다름).
    """
    if len(weights) < 6:
        return []
    rng = random.Random(seed)
    out: list[tuple[tuple[int, ...], float, int]] = []
    seen: set[tuple[int, ...]] = set()
    for _ in range(n):
        best = None
        best_ov = 99
        for _ in range(F1_MAX_ATTEMPTS):
            cand = _weighted_sample6(weights, rng)
            if len(set(cand)) < 6 or cand in seen:
                continue
            ov = _max_single_overlap(cand, flat)
            if not copy_filter or ov < COPY_OVERLAP:
                best, best_ov = cand, ov
                break
            if ov < best_ov:
                best, best_ov = cand, ov
        if best is None:
            continue
        score = sum(weights.get(x, 0.0) for x in best)
        out.append((best, score, best_ov))
        seen.add(best)
    return out


def generate_f1_sets(
    flat: list[tuple[str, tuple[int, ...]]],
    rel: dict[str, float],
    seed: int,
    n: int = SETS_TO_PICK,
) -> list[tuple[tuple[int, ...], float, int]]:
    """F1_BASE 5세트 — 합의k×신뢰도 가중 (대조·복구용)."""
    pres = _union_presence(flat)
    if len(pres) < 6:
        return []
    weights = _f1_weights(pres, rel)
    return generate_sets_with_weights(flat, weights, seed, n)


def _popularity_score(nums: tuple[int, ...]) -> float:
    """인기 패턴 점수 — 낮을수록 독식에 유리."""
    s = sorted(nums)
    consec = sum(1 for i in range(1, 6) if s[i] == s[i - 1] + 1)
    low31 = sum(1 for n in nums if n <= 31)
    total = sum(nums)
    sum_pop = max(0.0, 1.0 - abs(total - SUM_CENTER) / 40.0)
    return consec * 2.0 + (low31 / 6.0) * 1.5 + sum_pop


def _wheel_pick(
    cands: list[tuple[tuple[int, ...], float, int]], n: int,
) -> list[tuple[tuple[int, ...], float, int]]:
    """커버리지 최대·세트간 중복 최소 greedy n세트."""
    if not cands:
        return []
    remaining = list(cands)
    selected: list[tuple[tuple[int, ...], float, int]] = []
    covered: set[int] = set()

    while len(selected) < n and remaining:
        best_i = -1
        best_metric = -1e18
        for i, (nums, score, ov) in enumerate(remaining):
            ns = set(nums)
            new_cov = len(ns - covered)
            if selected:
                avg_ov = statistics.mean(len(ns & set(s)) for s, _, _ in selected)
            else:
                avg_ov = 0.0
            metric = new_cov * 12.0 + score - avg_ov * 4.0
            if metric > best_metric:
                best_metric = metric
                best_i = i
        pick = remaining.pop(best_i)
        selected.append(pick)
        covered |= set(pick[0])
    return selected


def _generate_popavoid_sets(
    flat: list[tuple[str, tuple[int, ...]]],
    weights: dict[int, float],
    seed: int,
    n: int,
) -> list[tuple[tuple[int, ...], float, int]]:
    """F1 가중 + 인기 패널티 후보 풀."""
    if len(weights) < 6:
        return []
    rng = random.Random(seed)
    out: list[tuple[tuple[int, ...], float, int]] = []
    seen: set[tuple[int, ...]] = set()

    for _ in range(n):
        best_cand = None
        best_score = -1e18
        best_ov = 99
        for _ in range(F1_MAX_ATTEMPTS):
            cand = _weighted_sample6(dict(weights), rng)
            if len(set(cand)) < 6 or cand in seen:
                continue
            ov = _max_single_overlap(cand, flat)
            if ov >= COPY_OVERLAP and ov >= best_ov:
                continue
            f1_sc = sum(weights.get(x, 0.0) for x in cand)
            adj = f1_sc - POP_PENALTY * _popularity_score(cand)
            if adj > best_score or (best_cand is None and ov < best_ov):
                best_score = adj
                best_cand = cand
                best_ov = ov
        if best_cand is None:
            continue
        f1_sc = sum(weights.get(x, 0.0) for x in best_cand)
        out.append((best_cand, f1_sc, best_ov))
        seen.add(best_cand)
    return out


def generate_f1_v2_strict_sets(
    flat: list[tuple[str, tuple[int, ...]]],
    rel: dict[str, float],
    seed: int,
    n: int = SETS_TO_PICK,
) -> list[tuple[tuple[int, ...], float, int]]:
    """F1_V2_STRICT — popavoid→wheel + ov<COPY_OVERLAP 강제."""
    pres = _union_presence(flat)
    if len(pres) < 6:
        return []
    weights = _f1_weights(pres, rel)

    pop_raw = _generate_popavoid_sets(flat, weights, seed, WHEEL_POOL)
    f1_pool = generate_sets_with_weights(
        flat, weights, seed, WHEEL_POOL, copy_filter=True,
    )

    by_nums: dict[tuple[int, ...], tuple[tuple[int, ...], float, int]] = {}
    for s in pop_raw + f1_pool:
        if s[2] < COPY_OVERLAP:
            by_nums[s[0]] = s
    cands = list(by_nums.values())

    selected = _wheel_pick(cands, n) if cands else []
    selected = [s for s in selected if s[2] < COPY_OVERLAP]
    seen = {s[0] for s in selected}

    remaining = [s for s in cands if s[0] not in seen]
    while len(selected) < n and remaining:
        add = _wheel_pick(remaining, 1)
        if not add:
            break
        pick = add[0]
        if pick[2] >= COPY_OVERLAP or pick[0] in seen:
            remaining = [s for s in remaining if s[0] != pick[0]]
            continue
        selected.append(pick)
        seen.add(pick[0])
        remaining = [s for s in remaining if s[0] not in seen]

    rs = seed
    for attempt in range(STRICT_REFILL_ATTEMPTS):
        if len(selected) >= n:
            break
        rs = (rs + 7919 + attempt) & 0xFFFFFFFF
        extra = generate_sets_with_weights(flat, weights, rs, 1, copy_filter=True)
        for s in extra:
            if s[2] < COPY_OVERLAP and s[0] not in seen:
                selected.append(s)
                seen.add(s[0])
                break

    return [s for s in selected if s[2] < COPY_OVERLAP][:n]


def compute_brain7_sets(conn, target_draw_no: int) -> list[dict]:
    """5세트 산출 — F1_V2_STRICT, 5뇌 READ-ONLY. 실패 시 []."""
    if not _pool_brains_ready(conn, target_draw_no):
        logger.info("[7뇌] %d회차 5뇌 25세트 미완 — skip", target_draw_no)
        return []

    flat = _load_flat_sets(conn, target_draw_no)
    if len(flat) < MIN_POOL_SETS:
        return []

    rel = _brain_number_reliability(conn, target_draw_no)
    seed = (target_draw_no * F1_SEED_MULT) & 0xFFFFFFFF
    f1_sets = generate_f1_v2_strict_sets(flat, rel, seed)
    if len(f1_sets) < SETS_TO_PICK:
        return []

    results: list[dict] = []
    for rank, (nums, score, ov) in enumerate(f1_sets, 1):
        results.append({
            "nums": list(nums),
            "confidence": round(min(score * 10, 99.9), 1),
            "reasoning": (
                f"출처:{F1_FORMULA} | popavoid→wheel | 가중={score:.2f} | max겹침={ov}"
            ),
            "method": BRAIN7_METHOD,
            "brain_tag": BRAIN7_TAG,
            "selection_source": F1_FORMULA,
            "rank": rank,
        })
    return results[:SETS_TO_PICK]


def _score_rows_if_actual(conn, target_draw_no: int) -> None:
    """refresh_prediction_scores_for_target_draw와 동일 로직 — lead1만."""
    ar = conn.execute(
        "SELECT num1,num2,num3,num4,num5,num6,bonus FROM lotto_draws WHERE draw_no=?",
        (target_draw_no,),
    ).fetchone()
    if not ar:
        return
    actual_set = {ar[i] for i in range(6)}
    bonus = ar[6]
    rows = conn.execute(
        """
        SELECT id, num1,num2,num3,num4,num5,num6
        FROM lotto_predictions
        WHERE target_draw_no=? AND brain_tag=?
        """,
        (target_draw_no, BRAIN7_TAG),
    ).fetchall()
    for p in rows:
        pr = {p[i] for i in range(1, 7)}
        matched = len(pr & actual_set)
        bonus_matched = 1 if bonus in pr else 0
        conn.execute(
            "UPDATE lotto_predictions SET matched_count=?, bonus_matched=? WHERE id=?",
            (matched, bonus_matched, p[0]),
        )


def save_brain7_predictions(conn, target_draw_no: int) -> int:
    """lead1 DELETE+INSERT. 반환=저장 세트 수."""
    preds = compute_brain7_sets(conn, target_draw_no)
    if not preds:
        return 0

    conn.execute(
        "DELETE FROM lotto_predictions WHERE target_draw_no=? AND brain_tag=?",
        (target_draw_no, BRAIN7_TAG),
    )

    for pred in preds:
        conn.execute(
            """
            INSERT INTO lotto_predictions
            (target_draw_no, method, brain_tag, num1, num2, num3, num4, num5, num6,
             confidence, reasoning, matched_count, bonus_matched)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                target_draw_no,
                pred["method"],
                pred["brain_tag"],
                pred["nums"][0],
                pred["nums"][1],
                pred["nums"][2],
                pred["nums"][3],
                pred["nums"][4],
                pred["nums"][5],
                pred["confidence"],
                pred["reasoning"],
                -1,
                0,
            ),
        )

    _score_rows_if_actual(conn, target_draw_no)
    return len(preds)


def run_brain7_for_draw(target_draw_no: int) -> bool:
    """독립 트랜잭션 — 6뇌 commit 이후 호출. 실패해도 6뇌 무영향."""
    init_lotto_db()
    conn = get_lotto_db()
    try:
        n = save_brain7_predictions(conn, target_draw_no)
        if n <= 0:
            return False
        conn.commit()
        logger.info("[7뇌 1등가자] %d회차 %d세트 저장", target_draw_no, n)
        return True
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        logger.warning("[7뇌 1등가자] %d회차 실패: %s", target_draw_no, e)
        return False
    finally:
        conn.close()


def ensure_brain7_for_draw(target_draw_no: int) -> bool:
    """lead1 없으면 생성. 캐시 hit 경로용."""
    init_lotto_db()
    conn = get_lotto_db()
    try:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM lotto_predictions WHERE target_draw_no=? AND brain_tag=?",
            (target_draw_no, BRAIN7_TAG),
        ).fetchone()[0]
        if cnt >= 5:
            _score_rows_if_actual(conn, target_draw_no)
            conn.commit()
            return True
    finally:
        conn.close()
    return run_brain7_for_draw(target_draw_no)
