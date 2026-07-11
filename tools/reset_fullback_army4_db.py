"""4군 풀백·예측·진화 이력 완전 삭제 (lotto_draws 유지)."""

from __future__ import annotations

import glob
import os
import sqlite3

DB = r"d:\3kweon\data\lotto4.db"

MODEL_DIRS = (
    r"d:\3kweon\models",
    r"d:\3kweon\app\lotto4\models",
    r"d:\3kweon\app\lotto4\brains\models",
)
MODEL_EXTENSIONS = ("*.pt", "*.pth", "*.ubj", "*.pkl", "*.joblib")


def reset_models() -> list[str]:
    """백테스트 전 모델 파일 완전 초기화 (_quarantine 제외)."""
    deleted: list[str] = []
    for d in MODEL_DIRS:
        if not os.path.isdir(d):
            continue
        for ext in MODEL_EXTENSIONS:
            for f in glob.glob(os.path.join(d, ext)):
                if "_quarantine" in f.replace("\\", "/"):
                    continue
                os.remove(f)
                deleted.append(f)
    print(f"[RESET] 모델 파일 {len(deleted)}개 삭제")
    for f in deleted:
        print(f"  삭제: {f}")
    return deleted


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA busy_timeout = 120000")

    conn.execute("DELETE FROM lotto_predictions_army4")
    print("predictions 삭제:", conn.execute("SELECT changes()").fetchone()[0])

    conn.execute("DELETE FROM lotto_fullbacktest_army4")
    print("fullbacktest 삭제:", conn.execute("SELECT changes()").fetchone()[0])

    conn.execute("DELETE FROM lotto_evolution_trust_army4")
    print("evolution 삭제:", conn.execute("SELECT changes()").fetchone()[0])

    conn.execute(
        """UPDATE lotto_brain_weights_army4
SET total_predictions=0, total_matches=0,
    recent_avg_match=0, last_updated_draw=0"""
    )
    print("brain_weights 통계 리셋:", conn.execute("SELECT changes()").fetchone()[0])

    conn.commit()

    for t in (
        "lotto_predictions_army4",
        "lotto_fullbacktest_army4",
        "lotto_evolution_trust_army4",
    ):
        cnt = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"{t}: {cnt}행")
        assert cnt == 0, f"❌ {t}가 비어있지 않음!"

    draws = conn.execute(
        "SELECT COUNT(*) FROM lotto_draws WHERE draw_no BETWEEN 5 AND 1223"
    ).fetchone()[0]
    print(f"lotto_draws: {draws}행 (보존)")
    assert draws >= 1217, "❌ 당첨번호 테이블 이상!"

    reset_models()
    conn.close()
    print("✅ DB 완전 초기화 완료")


if __name__ == "__main__":
    main()
