"""V11 모델: 틈새공략 + 진화 강화.

V9 컨셉 유지:
- 학습 데이터 = 1군 미당첨 회차 + 최근 50회 (틈새 + 보강)
- 6뇌 분리, 가중치 진화 (고정 η=V11_HEDGE_ETA + Clipping)
- lotto_brain_weights_army4 + 패치 J lotto_weight_log_army4(신규) — 기존 가중치 테이블 컬럼 불변

1군 코드 의존성: 함수 호출만 (수정 0).
"""

from __future__ import annotations

import math
import random
import sqlite3
from pathlib import Path

LOTTO_DB_PATH = Path(r"d:\3kweon\data\lotto4.db")

# V11 6뇌 (V9와 동일 구조, brain_tag만 v13_*)
V11_BRAINS = (
    "v13_stat",
    "v13_run",
    "v13_offset",
    "v13_contrarian",
    "v13_lstm",
    "v13_fusion",
    "v13_hyena",
)

# V11 시드 가중치 (V9 시드 그대로, 진화는 η=2.0으로 강화)
V11_SEED_WEIGHTS: dict[str, float] = {
    "v13_stat": 1.5,
    "v13_run": 1.0,
    "v13_offset": 1.0,
    "v13_contrarian": 2.5,
    "v13_lstm": 2.0,
    "v13_fusion": 2.0,
    "v13_hyena": 2.0,
}

V11_HEDGE_ETA = 2.0  # Hedge 고정 학습률 η (V9 1.5, V11·V12 기준 2.0)
V11_RECENT_BOOST = 50  # 최근 50회차 추가 학습 (틈새 + 최신 트렌드)
W_MAX = 100.0  # 가중치 상한 (Clipping)

# 패치 K 롤백 — 정규화 제거, 패치 J(가중치 로그) 상태 복원.

# 패치 J — 가중치 시계열 로그 (후반부 분석용). 기존 lotto_brain_weights_army4 스키마 불변.


def _ensure_weight_log_table(conn: sqlite3.Connection) -> None:
    """패치 J: lotto_weight_log_army4 신규 테이블만 생성."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lotto_weight_log_army4 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            draw_no INTEGER NOT NULL,
            brain_tag TEXT NOT NULL,
            weight_before REAL NOT NULL,
            weight_after REAL NOT NULL,
            matched_count INTEGER,
            eta REAL,
            logged_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(draw_no, brain_tag)
        )
        """
    )


# 패치 I — 직전 N회 당첨번호 Jaccard 회피 (컨닝 방지: draw_no < target 엄수)
V13_WIN_AVOID_N = 3
V13_WIN_AVOID_THRESHOLD = 0.4
V13_WIN_AVOID_MAX_RETRIES = 1000  # 실패 누적 시 회피 해제 후 삽입 (무한루프 방지)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(LOTTO_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def get_v13_training_draws(target_draw_no: int) -> list[dict]:
    """V11 학습 데이터: 1군 미당첨 회차 + 최근 50회차 (중복 제거).

    컷닝 0%: target_draw_no 미만만.
    """
    conn = _connect()
    try:
        # 1) 1군 미당첨 회차 (max <= 4)
        miss_rows = conn.execute(
            """
            SELECT d.* FROM lotto_draws d
            WHERE d.draw_no < ?
              AND d.draw_no IN (
                SELECT target_draw_no FROM lotto_predictions
                WHERE brain_tag IN ('stat','markov','llm','lstm','fusion','hyena')
                  AND matched_count >= 0
                  AND target_draw_no < ?
                GROUP BY target_draw_no
                HAVING MAX(matched_count) <= 4
              )
            ORDER BY d.draw_no
            """,
            (target_draw_no, target_draw_no),
        ).fetchall()

        # 2) 최근 50회차
        recent_rows = conn.execute(
            """
            SELECT * FROM lotto_draws
            WHERE draw_no < ?
            ORDER BY draw_no DESC
            LIMIT ?
            """,
            (target_draw_no, V11_RECENT_BOOST),
        ).fetchall()

        # 3) 중복 제거 (draw_no 기준)
        seen: set[int] = set()
        result: list[dict] = []
        for r in miss_rows:
            d = dict(r)
            draw_no = int(d["draw_no"])
            if draw_no not in seen:
                seen.add(draw_no)
                result.append(d)
        for r in recent_rows:
            d = dict(r)
            draw_no = int(d["draw_no"])
            if draw_no not in seen:
                seen.add(draw_no)
                result.append(d)

        result.sort(key=lambda x: x["draw_no"])
        return result
    finally:
        conn.close()


def get_recent_winning_sets(target_draw_no: int, n: int = V13_WIN_AVOID_N) -> list[set[int]]:
    """target_draw_no 미만 최근 n회 당첨 6개를 집합 리스트로 반환 (최신이 앞)."""
    if n <= 0:
        return []
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT num1, num2, num3, num4, num5, num6
            FROM lotto_draws
            WHERE draw_no < ?
            ORDER BY draw_no DESC
            LIMIT ?
            """,
            (target_draw_no, n),
        ).fetchall()
    finally:
        conn.close()
    out: list[set[int]] = []
    for r in rows:
        try:
            s = {int(r[f"num{i}"]) for i in range(1, 7)}
        except (KeyError, TypeError, ValueError):
            continue
        if len(s) == 6:
            out.append(s)
    return out


def is_diff_from_recent_wins(
    combo: list[int],
    winning_sets: list[set[int]],
    threshold: float = V13_WIN_AVOID_THRESHOLD,
) -> bool:
    """당첨 집합 중 하나라도 Jaccard >= threshold면 False(탈락)."""
    if not winning_sets:
        return True
    s = set(combo)
    for wset in winning_sets:
        inter = len(s & wset)
        uni = len(s | wset)
        jac = inter / uni if uni else 0.0
        if jac >= threshold:
            return False
    return True


def v13_pass_win_avoid(
    combo: list[int],
    winning_sets: list[set[int]],
    st: dict[str, int | bool],
) -> bool:
    """패치 I: True면 조합 채택(통과 또는 재시도 한도 초과로 무시). False면 재시도."""
    if st.get("bypass"):
        return True
    if not winning_sets:
        return True
    if is_diff_from_recent_wins(combo, winning_sets, V13_WIN_AVOID_THRESHOLD):
        return True
    fc = int(st.get("fail_count", 0)) + 1
    st["fail_count"] = fc
    if fc >= V13_WIN_AVOID_MAX_RETRIES:
        st["bypass"] = True
        return True
    return False


def v13_perturb_combo_one_swap(combo: list[int], rng: random.Random) -> list[int]:
    """한 칸만 교체하여 인접 후보 생성 (재시도용)."""
    nums = sorted(int(x) for x in combo)
    if len(nums) != 6:
        return nums
    i = rng.randint(0, 5)
    pool = [x for x in range(1, 46) if x not in nums]
    if not pool:
        return nums
    nums[i] = rng.choice(pool)
    return sorted(nums)


def _calc_lottery_score(matched_count: int, bonus_matched: int) -> int:
    """1군 feedback._calculate_lottery_score 동형 (로컬 복제, lotto 의존 0).

    1등(6)=100, 2등(5+보너스)=50, 3등(5)=30, 4등(4)=10, 5등(3)=3, 그 외=0.
    """
    if matched_count < 0:
        return 0
    if matched_count == 6:
        return 100
    if matched_count == 5:
        return 50 if bonus_matched else 30
    if matched_count == 4:
        return 10
    if matched_count == 3:
        return 3
    return 0


def get_v13_brain_weights() -> dict[str, float]:
    """V11 가중치 조회 (lotto_brain_weights_army4 테이블의 v13_* 사용).

    없으면 시드값 반환.
    """
    conn = _connect()
    try:
        placeholders = ",".join("?" * len(V11_BRAINS))
        rows = conn.execute(
            f"""
            SELECT brain_tag, current_weight FROM lotto_brain_weights_army4
            WHERE brain_tag IN ({placeholders})
            """,
            V11_BRAINS,
        ).fetchall()
        result = {str(r["brain_tag"]): float(r["current_weight"]) for r in rows if r["current_weight"] is not None}
        for tag, seed in V11_SEED_WEIGHTS.items():
            if tag not in result:
                result[tag] = seed
        return result
    finally:
        conn.close()


def init_v13_seeds() -> None:
    """V11 6뇌 시드 가중치 INSERT (없으면).

    레거시 `v13_combo` 가중치 행은 V11_BRAINS 외부 → 마이그레이션으로 제거.
    """
    conn = _connect()
    try:
        _ensure_weight_log_table(conn)
        conn.execute(
            "DELETE FROM lotto_brain_weights_army4 WHERE brain_tag = ?",
            ("v13_combo",),
        )
        for tag, weight in V11_SEED_WEIGHTS.items():
            conn.execute(
                "INSERT OR IGNORE INTO lotto_brain_weights_army4 (brain_tag, current_weight) VALUES (?, ?)",
                (tag, weight),
            )
        for tag, weight in V11_SEED_WEIGHTS.items():
            conn.execute(
                """
                INSERT OR REPLACE INTO lotto_weight_log_army4
                    (draw_no, brain_tag, weight_before, weight_after, matched_count, eta)
                VALUES (0, ?, 0.0, ?, NULL, NULL)
                """,
                (tag, float(weight)),
            )
        conn.commit()
    finally:
        conn.close()


def update_v13_weights(target_draw_no: int, last_n: int = 50) -> None:
    """V11 가중치 진화 (고정 η + Clipping).

    시그널: avg_match + avg_lottery_score/30 — 1군 update_brain_weights Layer 5-B 동형.
    η = V11_HEDGE_ETA (draw_count와 무관).
    new_weight = min(base × exp(η × score_signal), W_MAX)
    """
    from collections import defaultdict

    conn = _connect()
    try:
        _ensure_weight_log_table(conn)
        placeholders = ",".join("?" * len(V11_BRAINS))
        flat = conn.execute(
            f"""
            SELECT brain_tag, matched_count, bonus_matched
            FROM lotto_predictions_army4
            WHERE target_draw_no <= ? AND target_draw_no > ?
              AND matched_count >= 0
              AND brain_tag IN ({placeholders})
            """,
            (target_draw_no, target_draw_no - last_n, *V11_BRAINS),
        ).fetchall()

        n_by: dict[str, int] = defaultdict(int)
        sum_m_by: dict[str, float] = defaultdict(float)
        sum_ls_by: dict[str, float] = defaultdict(float)
        for r in flat:
            tag = str(r["brain_tag"])
            mc = int(r["matched_count"] or 0)
            bm = int(r["bonus_matched"] or 0)
            ls = _calc_lottery_score(mc, bm)
            n_by[tag] += 1
            sum_m_by[tag] += float(mc)
            sum_ls_by[tag] += float(ls)

        new_by_tag: dict[str, float] = {}
        meta_by_tag: dict[str, tuple[float, int, int]] = {}
        for tag, n in n_by.items():
            base = float(V11_SEED_WEIGHTS.get(tag, 1.0))
            avg_m = sum_m_by[tag] / float(n)
            avg_lottery_score = sum_ls_by[tag] / float(n)
            score_signal = avg_m + avg_lottery_score / 30.0
            eta = V11_HEDGE_ETA
            new_w = base * math.exp(eta * score_signal)
            new_w = min(float(new_w), W_MAX)
            new_by_tag[tag] = new_w
            meta_by_tag[tag] = (avg_m, int(n), int(sum_m_by[tag]))

        weight_before: dict[str, float] = {}
        for tag in V11_BRAINS:
            row = conn.execute(
                "SELECT current_weight FROM lotto_brain_weights_army4 WHERE brain_tag = ?",
                (tag,),
            ).fetchone()
            if row is not None and row["current_weight"] is not None:
                weight_before[tag] = float(row["current_weight"])
            else:
                weight_before[tag] = float(V11_SEED_WEIGHTS.get(tag, 1.0))

        for tag in V11_BRAINS:
            wb = weight_before[tag]
            wa = new_by_tag.get(tag, wb)
            if tag in new_by_tag:
                avg_m, tn, tm = meta_by_tag[tag]
                conn.execute(
                    """
                    UPDATE lotto_brain_weights_army4
                    SET current_weight = ?, recent_avg_match = ?,
                        total_predictions = ?, total_matches = ?,
                        last_updated_draw = ?, updated_at = datetime('now','localtime')
                    WHERE brain_tag = ?
                    """,
                    (
                        wa,
                        avg_m,
                        tn,
                        tm,
                        int(target_draw_no),
                        tag,
                    ),
                )
            mc_row = conn.execute(
                """
                SELECT MAX(matched_count) AS mx FROM lotto_predictions_army4
                WHERE target_draw_no = ? AND brain_tag = ?
                """,
                (target_draw_no, tag),
            ).fetchone()
            max_mc = mc_row["mx"]
            max_mc_int = int(max_mc) if max_mc is not None else None
            conn.execute(
                """
                INSERT OR REPLACE INTO lotto_weight_log_army4
                    (draw_no, brain_tag, weight_before, weight_after, matched_count, eta)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    int(target_draw_no),
                    tag,
                    wb,
                    wa,
                    max_mc_int,
                    float(V11_HEDGE_ETA),
                ),
            )
        conn.commit()
    finally:
        conn.close()

