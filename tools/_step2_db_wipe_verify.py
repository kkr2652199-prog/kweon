import sqlite3

db = r"d:\3kweon\data\lotto4.db"
conn = sqlite3.connect(db)
conn.execute("PRAGMA busy_timeout = 120000")

for t in [
    "lotto_predictions_army4",
    "lotto_fullbacktest_army4",
    "lotto_evolution_trust_army4",
]:
    conn.execute(f"DELETE FROM {t}")
    print(f"[삭제] {t}: {conn.execute('SELECT changes()').fetchone()[0]}행")

conn.execute(
    """UPDATE lotto_brain_weights_army4
SET total_predictions=0, total_matches=0, recent_avg_match=0, last_updated_draw=0"""
)

conn.commit()

print()
print("=== 초기화 실측 검증 ===")
# predictions 는 target_draw_no, 나머지는 draw_no
_table_draw_col = {
    "lotto_predictions_army4": "target_draw_no",
    "lotto_fullbacktest_army4": "draw_no",
    "lotto_evolution_trust_army4": "draw_no",
}
for t in [
    "lotto_predictions_army4",
    "lotto_fullbacktest_army4",
    "lotto_evolution_trust_army4",
]:
    col = _table_draw_col[t]
    row = conn.execute(
        f"SELECT COUNT(*), MIN({col}), MAX({col}) FROM {t}"
    ).fetchone()
    print(f"{t}: count={row[0]}, min={row[1]}, max={row[2]}")
    assert row[0] == 0, f"❌ {t}가 비어있지 않음!"

draws = conn.execute(
    "SELECT COUNT(*) FROM lotto_draws WHERE draw_no BETWEEN 5 AND 1223"
).fetchone()[0]
print(f"lotto_draws: {draws}행 (보존)")

conn.close()
print("✅ 초기화 완료")
