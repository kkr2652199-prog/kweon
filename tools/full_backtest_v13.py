"""
4군 풀 백테스트 (기본 5~1223회): 활성 7뇌 + Commander.

- predict(target=N) 시 각 뇌는 DB에서 draw_no < N 만 로드 (`load_draws_before` 등).
- 채점 후 update_trust(N)·온라인 학습: N회차까지 반영 후 N+1 예측에 사용.
- lotto_predictions_army4 + lotto_fullbacktest_army4 동시 기록, 뇌 단위 commit.
"""

from __future__ import annotations

import argparse
import glob
import importlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from app.lotto4._llm_isolation import assert_army1_predict_llm_not_loaded

DB_DEFAULT = str(ROOT / "data" / "lotto4.db")
START_DRAW_DEFAULT = 5
END_DRAW_DEFAULT = 1223
MAX_DRAW_CAP = 1223
SETS_PER_BRAIN = 5
EXPECTED_ROWS_PER_DRAW = 7 * SETS_PER_BRAIN
# 보고서용: 진화 스냅샷 (회차 완료 직후 가중치)
EVOLUTION_SNAPSHOT_DRAWS: frozenset[int] = frozenset(
    {100, 300, 500, 700, 900, 1100, 1223}
)
BRAIN_TAGS: tuple[str, ...] = (
    "v13_seq",
    "v13_struct",
    "v13_gap",
    "v13_diversity",
    "v13_ev",
    "v13_evolution",
    "v13_ensemble",
)
# predict 실패 시 NOT NULL 유지용 플레이스홀더 (1~45)
_PLACEHOLDER_COMBO: tuple[int, ...] = (7, 14, 21, 28, 35, 42)

# 활성 7뇌 + Commander (지시서 순서)
BRAIN_ORDER: list[tuple[str, str]] = [
    ("v13_seq", "app.lotto4.brains.seq_brain"),
    ("v13_struct", "app.lotto4.brains.struct_brain"),
    ("v13_gap", "app.lotto4.brains.gap_brain"),
    ("v13_diversity", "app.lotto4.brains.diversity_brain"),
    ("v13_ev", "app.lotto4.brains.ev_brain"),
    ("v13_evolution", "app.lotto4.brains.evolution_brain"),
    ("v13_ensemble", "app.lotto4.brains.ensemble"),
]

def _check_stale_models() -> None:
    """백테스트 전 잔여 모델 파일 경고 (_quarantine 제외)."""
    model_dirs = (
        str(ROOT / "models"),
        str(ROOT / "app" / "lotto4" / "models"),
    )
    extensions = ("*.pt", "*.pth", "*.ubj")
    stale: list[str] = []
    for d in model_dirs:
        if not os.path.isdir(d):
            continue
        for ext in extensions:
            stale.extend(glob.glob(os.path.join(d, ext)))
    stale = [f for f in stale if "_quarantine" not in f.replace("\\", "/")]
    if not stale:
        return
    print(f"[WARNING] 잔여 모델 파일 {len(stale)}개 발견 — walk-forward 위반 위험!")
    for f in stale:
        print(f"  ⚠️ {f}")
    print("[WARNING] 먼저 reset_fullback_army4_db.py를 실행하세요.")
    if "--force" not in sys.argv:
        print("[ERROR] --force 없이 실행 불가. 종료.")
        sys.exit(1)


CREATE_FB_SQL = """
CREATE TABLE IF NOT EXISTS lotto_fullbacktest_army4 (
    draw_no INTEGER NOT NULL,
    brain_tag TEXT NOT NULL,
    set_no INTEGER NOT NULL,
    numbers TEXT NOT NULL,
    matched_count INTEGER NOT NULL,
    matched_numbers TEXT,
    bonus_matched INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (draw_no, brain_tag, set_no)
);
CREATE INDEX IF NOT EXISTS idx_fullback_army4_draw
    ON lotto_fullbacktest_army4(draw_no);
"""


def load_actuals(db_path: str, lo: int, hi: int) -> dict[int, tuple[set[int], int]]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT draw_no, num1, num2, num3, num4, num5, num6, bonus
            FROM lotto_draws
            WHERE draw_no >= ? AND draw_no <= ?
            ORDER BY draw_no
            """,
            (lo, hi),
        ).fetchall()
    finally:
        conn.close()
    out: dict[int, tuple[set[int], int]] = {}
    for r in rows:
        dno = int(r[0])
        win = {int(r[i]) for i in range(1, 7)}
        bonus = int(r[7])
        out[dno] = (win, bonus)
    return out


def score_line(
    nums: list[int], win: set[int], bonus: int
) -> tuple[int, str, int]:
    st = set(nums)
    hit = sorted(win & st)
    mc = len(hit)
    matched_txt = ",".join(str(x) for x in hit) if hit else ""
    b = 1 if (mc == 5 and bonus in st) else 0
    return mc, matched_txt, b


def row_done_count(conn: sqlite3.Connection, draw_no: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM lotto_fullbacktest_army4 WHERE draw_no = ?",
        (draw_no,),
    ).fetchone()
    return int(row[0]) if row else 0


def predictions_row_count(conn: sqlite3.Connection, draw_no: int) -> int:
    q = (
        "SELECT COUNT(*) FROM lotto_predictions_army4 WHERE target_draw_no = ? "
        "AND brain_tag IN ("
        + ",".join("?" for _ in BRAIN_TAGS)
        + ")"
    )
    row = conn.execute(q, (draw_no, *BRAIN_TAGS)).fetchone()
    return int(row[0]) if row else 0


def ensure_fb_table(conn: sqlite3.Connection) -> None:
    conn.executescript(CREATE_FB_SQL)


def format_evolution_log(after_draw_completed: int, db_path: str) -> str:
    """회차 after_draw_completed 처리 후, 다음 회차 예측에 쓰일 get_dynamic_weights."""
    from app.lotto4.brains import evolution_brain  # noqa: PLC0415

    nxt = int(after_draw_completed) + 1
    dw = evolution_brain.get_dynamic_weights(nxt, db_path)
    wseq = float(dw.get("v13_seq", 0.25))
    wst = float(dw.get("v13_struct", 0.25))
    s = wseq + wst
    ps = wseq / s if s > 0 else 0.5
    pst = wst / s if s > 0 else 0.5
    return (
        f"[진화] draw {after_draw_completed} → 다음예측 nxt={nxt}: "
        f"player seq={ps:.3f}, struct={pst:.3f} | "
        f"chief seq={wseq:.3f}, struct={wst:.3f}"
    )


def evolution_snapshot_row(after_draw: int, db_path: str) -> dict[str, object]:
    from app.lotto4.brains import evolution_brain  # noqa: PLC0415

    nxt = after_draw + 1
    dw = evolution_brain.get_dynamic_weights(nxt, db_path)
    wseq = float(dw.get("v13_seq", 0.25))
    wst = float(dw.get("v13_struct", 0.25))
    s = wseq + wst
    return {
        "after_draw": after_draw,
        "weights_for_predict_draw": nxt,
        "player_seq": round(wseq / s, 6) if s > 0 else 0.5,
        "player_struct": round(wst / s, 6) if s > 0 else 0.5,
        "chief_v13_seq": round(wseq, 6),
        "chief_v13_struct": round(wst, 6),
    }


class _TeeTextIO:
    """stdout/stderr를 콘솔과 로그 파일에 동시 기록 (Windows CMD `1>>` 잠금 회피)."""

    __slots__ = ("_streams",)

    def __init__(self, *streams: object) -> None:
        self._streams = streams

    def write(self, s: str) -> int:
        n = 0
        for st in self._streams:
            n = st.write(s)
            st.flush()
        return n

    def flush(self) -> None:
        for st in self._streams:
            st.flush()

    def isatty(self) -> bool:
        return False


def main() -> None:
    ap = argparse.ArgumentParser(description="4군 풀 백테스트 → army4 predictions + fullbacktest")
    ap.add_argument("--db", default=DB_DEFAULT, help="SQLite DB path")
    ap.add_argument("--start", type=int, default=START_DRAW_DEFAULT)
    ap.add_argument("--end", type=int, default=END_DRAW_DEFAULT)
    ap.add_argument(
        "--force",
        action="store_true",
        help="이미 35행 완료된 회차도 전부 재계산 (skip 비활성화)",
    )
    ap.add_argument(
        "--log-file",
        default=None,
        help="UTF-8 로그 파일(append). CMD 리다이렉트 대신 사용 권장.",
    )
    args = ap.parse_args()

    log_fp = None
    old_out, old_err = sys.__stdout__, sys.__stderr__
    if args.log_file:
        lp = Path(os.path.abspath(args.log_file))
        lp.parent.mkdir(parents=True, exist_ok=True)
        log_fp = open(lp, "a", encoding="utf-8", buffering=1)
        sys.stdout = _TeeTextIO(old_out, log_fp)
        sys.stderr = _TeeTextIO(old_err, log_fp)

    try:
        _run_backtest(args)
    finally:
        if log_fp is not None:
            sys.stdout, sys.stderr = old_out, old_err
            log_fp.close()


def _run_backtest(args: argparse.Namespace) -> None:
    _check_stale_models()
    db_path = os.path.abspath(args.db)
    start_d = max(5, int(args.start))
    end_d = min(int(args.end), MAX_DRAW_CAP)

    from app.lotto4.brains import evolution_brain  # noqa: PLC0415
    from app.lotto4.brains import seq_brain, struct_brain  # noqa: PLC0415
    from app.lotto4.v13_weights_v2 import V13_BRAIN_METHOD  # noqa: PLC0415

    assert_army1_predict_llm_not_loaded("full_backtest_v13: 뇌 모듈 로드 직후")

    snap_path = ROOT / "reports" / "fullback_evolution_snapshots_5_1223.jsonl"

    actuals = load_actuals(db_path, start_d, end_d)
    targets = [d for d in range(start_d, end_d + 1) if d in actuals]

    print("=== 4군 풀 백테스트 (Army4 full backtest) ===")
    print(f"DB: {db_path}")
    print(f"구간: {start_d}~{end_d} (실행 대상 {len(targets)}회차)")
    print(f"뇌: {[t for t, _ in BRAIN_ORDER]}")
    print()

    wall0 = time.perf_counter()

    # API 서버 등 동시 접근 시 대기 (밀리초)
    conn = sqlite3.connect(db_path, timeout=300.0)
    try:
        conn.execute("PRAGMA busy_timeout = 300000")
        ensure_fb_table(conn)
        n_targets = len(targets)
        for idx, target in enumerate(targets):
            fb_done = row_done_count(conn, target)
            pr_done = predictions_row_count(conn, target)
            if (
                not args.force
                and fb_done >= EXPECTED_ROWS_PER_DRAW
                and pr_done >= EXPECTED_ROWS_PER_DRAW
            ):
                if (idx + 1) % 100 == 0 or target % 100 == 0:
                    pct_try = 100.0 * (idx + 1) / max(n_targets, 1)
                    print(
                        f"  [skip] draw {target} (fullback+predictions 완료) "
                        f"[진행] {idx + 1}/{n_targets} ({pct_try:.1f}%)",
                        flush=True,
                    )
                continue

            win, bonus = actuals[target]
            if fb_done > 0 or pr_done > 0:
                conn.execute(
                    "DELETE FROM lotto_fullbacktest_army4 WHERE draw_no = ?",
                    (target,),
                )
                conn.execute(
                    "DELETE FROM lotto_predictions_army4 WHERE target_draw_no = ? "
                    "AND brain_tag IN ("
                    + ",".join("?" for _ in BRAIN_TAGS)
                    + ")",
                    (target, *BRAIN_TAGS),
                )
                conn.commit()

            t0 = time.perf_counter()

            for tag, mod_path in BRAIN_ORDER:
                mod = importlib.import_module(mod_path)
                pred_fn = getattr(mod, "predict", None)
                if not callable(pred_fn):
                    raise RuntimeError(f"{tag}: no predict")
                conn.execute(
                    "DELETE FROM lotto_predictions_army4 WHERE target_draw_no = ? AND brain_tag = ?",
                    (target, tag),
                )
                try:
                    sets = pred_fn(target, db_path)
                except Exception as e:  # noqa: BLE001
                    print(f"[ERROR] {tag} draw={target}: {e}", flush=True)
                    sets = []

                if not isinstance(sets, list):
                    sets = []
                method = V13_BRAIN_METHOD.get(tag, tag)
                for si in range(SETS_PER_BRAIN):
                    cand: list[int] = []
                    if si < len(sets) and isinstance(sets[si], list):
                        try:
                            raw = sorted(int(x) for x in sets[si])
                        except (TypeError, ValueError):
                            raw = []
                        if (
                            len(raw) == 6
                            and len(set(raw)) == 6
                            and all(1 <= x <= 45 for x in raw)
                        ):
                            cand = raw
                    if len(cand) == 6:
                        nums = cand
                        mc, mt, bm = score_line(nums, win, bonus)
                        reasoning = f"{method} 세트{si + 1} (풀백테)"
                    else:
                        nums = list(_PLACEHOLDER_COMBO)
                        mc, mt, bm = -1, "", 0
                        reasoning = f"{method} 세트{si + 1} (풀백테·무효)"
                    num_txt = ",".join(str(x) for x in nums)
                    conf = round(0.5 + 0.01 * si, 4)
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO lotto_fullbacktest_army4
                        (draw_no, brain_tag, set_no, numbers, matched_count,
                         matched_numbers, bonus_matched)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (target, tag, si + 1, num_txt, mc, mt, bm),
                    )
                    conn.execute(
                        """
                        INSERT INTO lotto_predictions_army4
                        (target_draw_no, method, num1, num2, num3, num4, num5, num6,
                         confidence, reasoning, matched_count, bonus_matched, brain_tag)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            target,
                            method,
                            nums[0],
                            nums[1],
                            nums[2],
                            nums[3],
                            nums[4],
                            nums[5],
                            conf,
                            reasoning,
                            mc,
                            bm,
                            tag,
                        ),
                    )
                conn.commit()

            evolution_brain.update_trust(target, db_path)

            # v13_seq 격리: update_model 스킵
            _ = seq_brain
            try:
                # load_draws_before(..., target+1) → N회차 당첨까지 반영 (N+1 예측용). 커닝 아님.
                struct_brain.update_models(target + 1, db_path)
            except Exception as e:  # noqa: BLE001
                print(f"[WARN] struct update_models {target + 1}: {e}", flush=True)

            conn.commit()
            dt = time.perf_counter() - t0
            assert_army1_predict_llm_not_loaded(f"full_backtest_v13: draw {target} 처리 후")

            if target in EVOLUTION_SNAPSHOT_DRAWS:
                snap_path.parent.mkdir(parents=True, exist_ok=True)
                row = evolution_snapshot_row(target, db_path)
                with open(snap_path, "a", encoding="utf-8") as sf:
                    sf.write(json.dumps(row, ensure_ascii=False) + "\n")

            pct = 100.0 * (idx + 1) / max(n_targets, 1)
            # 보고서용: 초반 50회·200~210회는 매 회차 로그 (skip 없음 확인)
            detail_band = (target <= 50) or (200 <= target <= 210)
            if (
                idx == 0
                or (idx + 1) % 100 == 0
                or target % 100 == 0
                or target == end_d
                or detail_band
            ):
                print(
                    f"  [진행] {idx + 1}/{n_targets} 완료 ({pct:.1f}%) | draw {target} "
                    f"OK ({dt:.1f}s, 누적 {time.perf_counter() - wall0:.0f}s)",
                    flush=True,
                )
            if (idx + 1) % 100 == 0 or target == end_d:
                print(format_evolution_log(target, db_path), flush=True)
    finally:
        conn.close()

    print()
    print(f"완료. 총 벽시계: {time.perf_counter() - wall0:.1f}s ({(time.perf_counter() - wall0)/60:.1f}분)")


if __name__ == "__main__":
    main()
