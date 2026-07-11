"""Phase 3 — 하이에나 잔반처리기: 다른 뇌가 놓친 번호 패턴 학습 → 보충 풀 제공.

번호를 생성하지 않음. miss history + XGBoost로 scavenge pool 산출.
R13: target_draw 미만 데이터만 사용.
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from typing import Any

import numpy as np

from app.lotto4.brains._utils import load_draws_before

try:
    from xgboost import XGBClassifier
except ImportError:  # pragma: no cover
    XGBClassifier = None  # type: ignore

BRAIN_TAGS = (
    "v13_seq",
    "v13_struct",
    "v13_gap",
    "v13_diversity",
    "v13_ev",
    "v13_evolution",
)
DEFAULT_LOOKBACK = 50
TRAIN_WINDOW = 200
LOOKBACK_FEAT = 10
MIN_TRAIN_SAMPLES = 40


def _parse_nums(row: tuple) -> set[int]:
    return {int(row[i]) for i in range(len(row))}


def _draw_actual_map(db_path: str, start: int, end: int) -> dict[int, set[int]]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT draw_no, num1, num2, num3, num4, num5, num6
            FROM lotto_draws
            WHERE draw_no >= ? AND draw_no < ?
            ORDER BY draw_no
            """,
            (int(start), int(end)),
        ).fetchall()
    finally:
        conn.close()
    return {int(r[0]): _parse_nums(r[1:]) for r in rows}


def _brain_predictions_map(
    db_path: str, start: int, end: int
) -> dict[tuple[int, str], set[int]]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT target_draw_no, brain_tag, num1, num2, num3, num4, num5, num6
            FROM lotto_predictions_army4
            WHERE target_draw_no >= ? AND target_draw_no < ?
              AND brain_tag != 'v13_ensemble'
            ORDER BY target_draw_no, brain_tag
            """,
            (int(start), int(end)),
        ).fetchall()
    finally:
        conn.close()
    out: dict[tuple[int, str], set[int]] = defaultdict(set)
    for r in rows:
        key = (int(r[0]), str(r[1]))
        out[key].update(int(r[i]) for i in range(2, 8))
    return dict(out)


class HyenaScavenger:
    """다른 뇌의 miss 패턴 → scavenge pool."""

    def __init__(self) -> None:
        self.miss_history: dict[str, list[dict[str, Any]]] = {}
        self.scavenge_model: Any = None
        self._trained_draw: int | None = None
        self._brain_tags: tuple[str, ...] = BRAIN_TAGS

    def _collect_miss_history(
        self, target_draw: int, db_path: str, lookback: int = DEFAULT_LOOKBACK
    ) -> dict[str, list[dict[str, Any]]]:
        start = max(1, int(target_draw) - int(lookback))
        end = int(target_draw)
        actual_map = _draw_actual_map(db_path, start, end)
        pred_map = _brain_predictions_map(db_path, start, end)

        history: dict[str, list[dict[str, Any]]] = {t: [] for t in self._brain_tags}
        for draw_no in sorted(actual_map.keys()):
            actual = actual_map[draw_no]
            for tag in self._brain_tags:
                predicted = pred_map.get((draw_no, tag), set())
                if not predicted:
                    continue
                missed = sorted(actual - predicted)
                history[tag].append(
                    {
                        "draw": draw_no,
                        "predicted_nums": sorted(predicted),
                        "actual_nums": sorted(actual),
                        "missed_nums": missed,
                    }
                )
        self.miss_history = history
        return history

    def _analyze_miss_patterns(
        self, miss_history: dict[str, list[dict[str, Any]]]
    ) -> dict[str, Any]:
        per_brain_miss_rate: dict[str, dict[int, float]] = {}
        brain_miss_counts: dict[int, int] = Counter()
        brain_appear_counts: dict[int, int] = Counter()
        cross_miss: dict[int, int] = Counter()
        cross_total: dict[int, int] = Counter()
        recent_streak: dict[int, int] = {n: 0 for n in range(1, 46)}

        for tag, entries in miss_history.items():
            miss_cnt: Counter[int] = Counter()
            appear_cnt: Counter[int] = Counter()
            for e in entries:
                actual = set(e["actual_nums"])
                missed = set(e["missed_nums"])
                for n in actual:
                    appear_cnt[n] += 1
                    if n in missed:
                        miss_cnt[n] += 1
            rates: dict[int, float] = {}
            for n in range(1, 46):
                if appear_cnt[n] > 0:
                    rates[n] = miss_cnt[n] / appear_cnt[n]
            per_brain_miss_rate[tag] = rates
            brain_miss_counts.update(miss_cnt)
            brain_appear_counts.update(appear_cnt)

        all_entries_by_draw: dict[int, dict[str, set[int]]] = defaultdict(dict)
        for tag, entries in miss_history.items():
            for e in entries:
                all_entries_by_draw[e["draw"]][tag] = set(e["missed_nums"])

        for draw_no in sorted(all_entries_by_draw.keys()):
            tag_misses = all_entries_by_draw[draw_no]
            if len(tag_misses) < 2:
                continue
            common = set.intersection(*tag_misses.values()) if tag_misses else set()
            for n in range(1, 46):
                cross_total[n] += 1
                if n in common:
                    cross_miss[n] += 1

        blind_spot_nums = [
            n
            for n, c in sorted(cross_miss.items(), key=lambda x: (-x[1], x[0]))
            if c >= 2
        ][:15]

        last_draws = sorted(
            {e["draw"] for entries in miss_history.values() for e in entries}
        )[-5:]
        for n in range(1, 46):
            streak = 0
            for d in reversed(last_draws):
                missed_any = False
                for tag, entries in miss_history.items():
                    for e in entries:
                        if e["draw"] == d and n in e["missed_nums"]:
                            missed_any = True
                            break
                    if missed_any:
                        break
                if missed_any:
                    streak += 1
                else:
                    break
            recent_streak[n] = streak

        hot_misses = [
            n
            for n, s in sorted(recent_streak.items(), key=lambda x: (-x[1], x[0]))
            if s >= 3
        ][:10]

        return {
            "per_brain_miss_rate": per_brain_miss_rate,
            "blind_spot_nums": blind_spot_nums,
            "hot_misses": hot_misses,
            "cross_miss_rate": {
                n: (cross_miss[n] / cross_total[n] if cross_total[n] else 0.0)
                for n in range(1, 46)
            },
        }

    def train_scavenge_model(self, target_draw: int, db_path: str) -> None:
        if XGBClassifier is None:
            self.scavenge_model = None
            self._trained_draw = int(target_draw)
            return

        start = max(1, int(target_draw) - TRAIN_WINDOW)
        end = int(target_draw)
        actual_map = _draw_actual_map(db_path, start, end)
        pred_map = _brain_predictions_map(db_path, start, end)
        draws = sorted(actual_map.keys())
        if len(draws) < MIN_TRAIN_SAMPLES:
            self.scavenge_model = None
            self._trained_draw = int(target_draw)
            return

        xs: list[np.ndarray] = []
        ys: list[int] = []

        for i, draw_no in enumerate(draws):
            if i < LOOKBACK_FEAT:
                continue
            hist_draws = draws[i - LOOKBACK_FEAT : i]
            actual = actual_map[draw_no]
            for n in range(1, 46):
                xs.append(
                    self._feature_vector(n, draw_no, hist_draws, actual_map, pred_map)
                )
                ys.append(1 if n in actual else 0)

        if len(xs) < MIN_TRAIN_SAMPLES:
            self.scavenge_model = None
            self._trained_draw = int(target_draw)
            return

        x_mat = np.stack(xs, axis=0)
        pos = sum(ys)
        neg = len(ys) - pos
        spw = float(neg / pos) if pos > 0 else 1.0

        clf = XGBClassifier(
            max_depth=3,
            n_estimators=50,
            learning_rate=0.1,
            scale_pos_weight=min(spw, 10.0),
            random_state=42,
            n_jobs=1,
            verbosity=0,
        )
        try:
            clf.fit(x_mat, np.array(ys, dtype=np.int32))
            self.scavenge_model = clf
        except (ValueError, RuntimeError):
            self.scavenge_model = None
        self._trained_draw = int(target_draw)

    def _feature_vector(
        self,
        num: int,
        target_draw: int,
        hist_draws: list[int],
        actual_map: dict[int, set[int]],
        pred_map: dict[tuple[int, str], set[int]],
    ) -> np.ndarray:
        appear = [1.0 if num in actual_map.get(d, set()) else 0.0 for d in hist_draws]
        pred_feats: list[float] = []
        miss_feats: list[float] = []
        for tag in self._brain_tags:
            for d in hist_draws:
                predicted = pred_map.get((d, tag), set())
                if not predicted:
                    pred_feats.append(0.0)
                    miss_feats.append(0.0)
                else:
                    pred_feats.append(1.0 if num in predicted else 0.0)
                    actual = actual_map.get(d, set())
                    missed = actual - predicted
                    miss_feats.append(1.0 if num in missed else 0.0)

        tail = float(num % 10)
        decade = float(min(4, (num - 1) // 10))
        odd = float(num % 2)

        streak = 0.0
        for d in reversed(hist_draws):
            all_missed = True
            found = False
            for tag in self._brain_tags:
                predicted = pred_map.get((d, tag), set())
                if not predicted:
                    continue
                found = True
                actual = actual_map.get(d, set())
                if num not in (actual - predicted):
                    all_missed = False
                    break
            if found and all_missed:
                streak += 1.0
            else:
                break

        return np.array(appear + pred_feats + miss_feats + [tail, decade, odd, streak], dtype=np.float64)

    def predict_scavenge_probs(self, target_draw: int, db_path: str) -> dict[int, float]:
        if self._trained_draw != int(target_draw):
            self.train_scavenge_model(target_draw, db_path)

        start = max(1, int(target_draw) - TRAIN_WINDOW)
        end = int(target_draw)
        actual_map = _draw_actual_map(db_path, start, end)
        pred_map = _brain_predictions_map(db_path, start, end)
        draws = sorted(actual_map.keys())
        hist_draws = draws[-LOOKBACK_FEAT:] if len(draws) >= LOOKBACK_FEAT else draws

        probs: dict[int, float] = {}
        if self.scavenge_model is None or XGBClassifier is None:
            patterns = self._analyze_miss_patterns(
                self._collect_miss_history(target_draw, db_path)
            )
            for n in range(1, 46):
                probs[n] = float(patterns["cross_miss_rate"].get(n, 0.0))
            return probs

        for n in range(1, 46):
            x = self._feature_vector(n, target_draw, hist_draws, actual_map, pred_map).reshape(1, -1)
            try:
                p = float(self.scavenge_model.predict_proba(x)[0][1])
            except (ValueError, IndexError, RuntimeError):
                p = 0.0
            probs[n] = p
        return probs

    def get_scavenge_pool(
        self, target_draw: int, db_path: str, pool_size: int = 8
    ) -> list[tuple[int, float]]:
        miss_history = self._collect_miss_history(target_draw, db_path)
        if not any(miss_history.values()):
            return []

        patterns = self._analyze_miss_patterns(miss_history)
        self.train_scavenge_model(target_draw, db_path)
        xgb_probs = self.predict_scavenge_probs(target_draw, db_path)

        scores: dict[int, float] = {}
        for n in patterns["blind_spot_nums"]:
            scores[n] = scores.get(n, 0.0) + 3.0
        for n in patterns["hot_misses"]:
            scores[n] = scores.get(n, 0.0) + 2.0

        agg_miss: Counter[int] = Counter()
        for tag, rates in patterns["per_brain_miss_rate"].items():
            for n, r in rates.items():
                if r > 0.3:
                    agg_miss[n] += r
        for n, v in agg_miss.items():
            scores[n] = scores.get(n, 0.0) + v

        for n, p in xgb_probs.items():
            scores[n] = scores.get(n, 0.0) + p * 5.0

        ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
        out = [(n, round(s, 4)) for n, s in ranked if s > 0][:pool_size]
        return out
