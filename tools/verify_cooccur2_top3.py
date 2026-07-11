"""2개 동반출현 TOP3: 비가중 집계 vs predict_cooccur 가중 행렬.

동행복권 공식 2개 동반 통계(전 기간 누적)와 맞출 때는 비가중 TOP3를 사용한다.
predict_cooccur._build_cooccur_matrix는 최근 50회에 가중 2.0을 적용하므로 순위가 달라질 수 있다.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.lotto4.models import get_lotto4_db  # noqa: E402
from app.lotto4.legacy.predict_cooccur import _build_cooccur_matrix  # noqa: E402


def _six_from_row(d: dict) -> list[int] | None:
    try:
        return sorted(int(d[f"num{i}"]) for i in range(1, 7))
    except (KeyError, TypeError, ValueError):
        return None


def _top3_pairs_matrix(w: list[list[float]]) -> list[tuple[int, int, float]]:
    pairs: list[tuple[float, int, int]] = []
    for i in range(45):
        for j in range(i + 1, 45):
            pairs.append((w[i][j], i + 1, j + 1))
    pairs.sort(key=lambda t: (-t[0], t[1], t[2]))
    return [(int(t[1]), int(t[2]), t[0]) for t in pairs[:3]]


def main() -> None:
    conn = get_lotto4_db()
    try:
        draws = [dict(r) for r in conn.execute("SELECT * FROM lotto_draws ORDER BY draw_no ASC")]
    finally:
        conn.close()

    w0: list[list[float]] = [[0.0] * 45 for _ in range(45)]
    for d in draws:
        nums = _six_from_row(d)
        if not nums or len(nums) != 6:
            continue
        for a in range(6):
            for b in range(a + 1, 6):
                i, j = nums[a] - 1, nums[b] - 1
                w0[i][j] += 1.0
                w0[j][i] += 1.0

    u3 = _top3_pairs_matrix(w0)
    print("=== 2개 동반 TOP3 (비가중, lotto_draws 전체) - 공식 통계 비교용 ===")
    for n1, n2, cnt in u3:
        print(f"  {n1:02d}-{n2:02d}: {int(cnt)}회 (동행복권 2개 동반 누적과 대조)")

    w1 = _build_cooccur_matrix(draws)
    r3 = _top3_pairs_matrix(w1)
    print("\n=== 2개 동반 TOP3 (predict_cooccur 가중 행렬) ===")
    for n1, n2, wt in r3:
        print(f"  {n1:02d}-{n2:02d}: weight={wt:.3f}")


if __name__ == "__main__":
    main()
