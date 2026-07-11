"""V11 모델: 틈새공략 + 진화 강화.

V9 컨셉 유지:
- 학습 데이터 = 1군 미당첨 회차 + 최근 50회 (틈새 + 보강)
- 6뇌 분리, 가중치 진화 (η=2.0)
- DB 스키마 변경 없음, 기존 테이블 + brain_tag 'v11_*' 사용

1군 코드 의존성: 함수 호출만 (수정 0).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

LOTTO_DB_PATH = Path(__file__).parent.parent.parent / "data" / "lotto4.db"

# V11 6뇌 (V9와 동일 구조, brain_tag만 v11_*)
V11_BRAINS = (
    "v11_stat",
    "v11_markov",
    "v11_combo",
    "v11_lstm",
    "v11_fusion",
    "v11_hyena",
)

# V11 시드 가중치 (V9 시드 그대로, 진화는 η=2.0으로 강화)
V11_SEED_WEIGHTS: dict[str, float] = {
    "v11_stat": 1.5,
    "v11_markov": 1.0,
    "v11_combo": 2.5,
    "v11_lstm": 2.0,
    "v11_fusion": 2.0,
    "v11_hyena": 2.0,
}

V11_HEDGE_ETA = 2.0  # V9는 1.5, V11은 2.0 (진화 강화)
V11_RECENT_BOOST = 50  # 최근 50회차 추가 학습 (틈새 + 최신 트렌드)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(LOTTO_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def get_v11_training_draws(target_draw_no: int) -> list[dict]:
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


def get_v11_brain_weights() -> dict[str, float]:
    """V11 가중치 조회 (lotto_brain_weights_army2 테이블의 v11_* 사용).

    없으면 시드값 반환.
    """
    conn = _connect()
    try:
        placeholders = ",".join("?" * len(V11_BRAINS))
        rows = conn.execute(
            f"""
            SELECT brain_tag, current_weight FROM lotto_brain_weights_army2
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


def init_v11_seeds() -> None:
    """V11 6뇌 시드 가중치 INSERT (없으면)."""
    conn = _connect()
    try:
        for tag, weight in V11_SEED_WEIGHTS.items():
            conn.execute(
                "INSERT OR IGNORE INTO lotto_brain_weights_army2 (brain_tag, current_weight) VALUES (?, ?)",
                (tag, weight),
            )
        conn.commit()
    finally:
        conn.close()


def update_v11_weights(target_draw_no: int, last_n: int = 50) -> None:
    """V11 가중치 진화 (Hedge η=2.0, V9의 η=1.5보다 강함).

    new_weight = base_weight × exp(η × avg_match / 6)
    """
    import math

    conn = _connect()
    try:
        placeholders = ",".join("?" * len(V11_BRAINS))
        rows = conn.execute(
            f"""
            SELECT brain_tag, AVG(matched_count) AS avg_m,
                   COUNT(1) AS n, SUM(matched_count) AS sum_m
            FROM lotto_predictions_army2
            WHERE target_draw_no <= ? AND target_draw_no > ?
              AND matched_count >= 0
              AND brain_tag IN ({placeholders})
            GROUP BY brain_tag
            """,
            (target_draw_no, target_draw_no - last_n, *V11_BRAINS),
        ).fetchall()

        for r in rows:
            tag = str(r["brain_tag"])
            base = float(V11_SEED_WEIGHTS.get(tag, 1.0))
            avg_m = float(r["avg_m"] or 0.0)
            new_w = base * math.exp(V11_HEDGE_ETA * avg_m / 6.0)
            conn.execute(
                """
                UPDATE lotto_brain_weights_army2
                SET current_weight = ?, recent_avg_match = ?,
                    total_predictions = ?, total_matches = ?,
                    last_updated_draw = ?, updated_at = datetime('now','localtime')
                WHERE brain_tag = ?
                """,
                (
                    new_w,
                    avg_m,
                    int(r["n"] or 0),
                    int(r["sum_m"] or 0),
                    int(target_draw_no),
                    tag,
                ),
            )
        conn.commit()
    finally:
        conn.close()

