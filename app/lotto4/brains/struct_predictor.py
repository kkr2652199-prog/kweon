"""Phase 2A-fix+C — 구조 변수 예측 ML (번호 비생성, XGBoost multiclass).

7개 구조 변수를 독립 분류기로 예측 → hyena Commander 필터 보너스.
R13: target_draw 미만 데이터만 사용.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Callable

import numpy as np

from app.lotto4.brains._utils import (
    calc_ac_value,
    count_consecutive,
    load_draws_before,
)

try:
    from xgboost import XGBClassifier
except ImportError:  # pragma: no cover
    XGBClassifier = None  # type: ignore

_LAST_CUT = 1223
TRAIN_WINDOW = 500
LOOKBACK = 10
MIN_TRAIN_SAMPLES = 30

SUM_ZONES = ("A", "B", "C", "D")
CONSEC_CLASSES = (0, 1, 2, 3)
AC_CLASSES = (0, 1, 2)
TAIL_DUP_CLASSES = (1, 2, 3)
DECADE_CLASSES = (1, 2, 3, 4, 5)

VAR_NAMES = (
    "sum_zone",
    "odd_count",
    "high_count",
    "consec_pairs",
    "ac_zone",
    "tail_max_dup",
    "decade_spread",
)


def _history_cut(draw_no: int) -> int:
    return min(int(draw_no), _LAST_CUT)


def _nums(draw: dict[str, Any]) -> list[int]:
    return sorted(int(x) for x in draw.get("nums", []))


def _sum_zone(total: int) -> str:
    if total <= 120:
        return "A"
    if total <= 150:
        return "B"
    if total <= 180:
        return "C"
    return "D"


def _tail_max_dup(nums: list[int]) -> int:
    tails = [n % 10 for n in nums]
    m = max(Counter(tails).values()) if tails else 1
    return min(3, m)


def _decade_spread(nums: list[int]) -> int:
    decades = {min(4, (n - 1) // 10) for n in nums}
    return max(1, min(5, len(decades)))


def _ac_zone(ac: int) -> int:
    if ac <= 6:
        return 0
    if ac <= 8:
        return 1
    return 2


def _consec_class(c: int) -> int:
    return min(3, int(c))


def extract_struct_labels(nums: list[int]) -> dict[str, Any]:
    """조합/당첨번호에서 7개 구조 라벨 추출."""
    s = sorted(nums)
    total = sum(s)
    odd = sum(1 for n in s if n % 2 == 1)
    high = sum(1 for n in s if n >= 23)
    consec = _consec_class(count_consecutive(s))
    ac = _ac_zone(calc_ac_value(s))
    tail = _tail_max_dup(s)
    decade = _decade_spread(s)
    return {
        "sum_zone": _sum_zone(total),
        "odd_count": odd,
        "high_count": high,
        "consec_pairs": consec,
        "ac_zone": ac,
        "tail_max_dup": tail,
        "decade_spread": decade,
    }


def _label_to_vector(labels: dict[str, Any]) -> np.ndarray:
    zone_map = {"A": 0.0, "B": 1.0, "C": 2.0, "D": 3.0}
    return np.array(
        [
            zone_map.get(str(labels["sum_zone"]), 1.0),
            float(labels["odd_count"]),
            float(labels["high_count"]),
            float(labels["consec_pairs"]),
            float(labels["ac_zone"]),
            float(labels["tail_max_dup"]),
            float(labels["decade_spread"]),
        ],
        dtype=np.float64,
    )


def _encode_features(struct_seq: list[dict[str, Any]]) -> np.ndarray:
    """최근 LOOKBACK 회차 구조 → 91차원 특성."""
    vecs = [_label_to_vector(s) for s in struct_seq[-LOOKBACK:]]
    while len(vecs) < LOOKBACK:
        vecs.insert(0, np.zeros(7, dtype=np.float64))
    flat = np.concatenate(vecs, axis=0)  # 70
    arr = np.stack(vecs, axis=0)
    ma5 = arr[-5:].mean(axis=0) if len(arr) >= 1 else np.zeros(7)
    ma10 = arr.mean(axis=0)
    delta = arr[-1] - arr[-2] if len(arr) >= 2 else np.zeros(7)
    return np.concatenate([flat, ma5, ma10, delta], axis=0).astype(np.float64)


class StructPredictor:
    """7변수 독립 XGBoost 구조 예측기."""

    def __init__(self) -> None:
        self.models: dict[str, Any] = {}
        self._trained_draw: int | None = None

    def _build_dataset(
        self, draws: list[dict[str, Any]]
    ) -> tuple[list[np.ndarray], dict[str, list[Any]]]:
        labels_hist: list[dict[str, Any]] = []
        for d in draws:
            nums = _nums(d)
            if len(nums) == 6:
                labels_hist.append(extract_struct_labels(nums))

        xs: list[np.ndarray] = []
        ys: dict[str, list[Any]] = {v: [] for v in VAR_NAMES}

        for i in range(LOOKBACK, len(labels_hist)):
            window = labels_hist[i - LOOKBACK : i]
            xs.append(_encode_features(window))
            for v in VAR_NAMES:
                ys[v].append(labels_hist[i][v])

        return xs, ys

    def train(self, target_draw: int, db_path: str) -> None:
        """walk-forward: target_draw 미만 최근 TRAIN_WINDOW 회차."""
        if XGBClassifier is None:
            self.models = {}
            self._trained_draw = int(target_draw)
            return

        draws = load_draws_before(db_path, _history_cut(target_draw))
        if len(draws) > TRAIN_WINDOW:
            draws = draws[-TRAIN_WINDOW:]

        xs, ys = self._build_dataset(draws)
        if len(xs) < MIN_TRAIN_SAMPLES:
            self.models = {}
            self._trained_draw = int(target_draw)
            return

        x_mat = np.stack(xs, axis=0)
        self.models = {}

        spec: dict[str, tuple[str, ...]] = {
            "sum_zone": SUM_ZONES,
            "odd_count": tuple(range(7)),
            "high_count": tuple(range(7)),
            "consec_pairs": CONSEC_CLASSES,
            "ac_zone": AC_CLASSES,
            "tail_max_dup": TAIL_DUP_CLASSES,
            "decade_spread": DECADE_CLASSES,
        }

        for var in VAR_NAMES:
            y_raw = ys[var]
            classes = spec[var]
            if var == "sum_zone":
                y_vals = [classes.index(str(y)) for y in y_raw]
            else:
                y_vals = [
                    classes.index(int(y)) if int(y) in classes else 0 for y in y_raw
                ]

            present = sorted(set(y_vals))
            if len(present) < 2:
                continue
            idx_map = {v: i for i, v in enumerate(present)}
            y_enc = [idx_map[v] for v in y_vals]
            n_cls = len(present)

            clf = XGBClassifier(
                max_depth=3,
                n_estimators=50,
                learning_rate=0.1,
                objective="multi:softprob",
                num_class=n_cls,
                random_state=42,
                n_jobs=1,
                verbosity=0,
            )
            try:
                clf.fit(x_mat, np.array(y_enc, dtype=np.int32))
                self.models[var] = {
                    "model": clf,
                    "classes": classes,
                    "present": present,
                }
            except (ValueError, RuntimeError):
                continue

        self._trained_draw = int(target_draw)

    def predict_struct(self, target_draw: int, db_path: str) -> dict[str, Any]:
        if self._trained_draw != int(target_draw):
            self.train(target_draw, db_path)

        draws = load_draws_before(db_path, _history_cut(target_draw))
        labels_hist = [
            extract_struct_labels(_nums(d))
            for d in draws
            if len(_nums(d)) == 6
        ]
        window = labels_hist[-LOOKBACK:]
        x = _encode_features(window).reshape(1, -1)

        out: dict[str, Any] = {}
        defaults = extract_struct_labels([3, 7, 13, 25, 33, 41])

        for var in VAR_NAMES:
            entry = self.models.get(var)
            if entry is None or XGBClassifier is None:
                out[var] = defaults[var]
                out[f"{var}_probs"] = {str(defaults[var]): 1.0}
                continue

            clf = entry["model"]
            classes = entry["classes"]
            present = entry.get("present", list(range(len(classes))))
            try:
                proba = clf.predict_proba(x)[0]
                prob_map = {
                    str(classes[present[i]]): float(proba[i]) for i in range(len(present))
                }
                best_i = int(np.argmax(proba))
                pred_val = classes[present[best_i]]
                out[var] = pred_val
                out[f"{var}_probs"] = prob_map
            except (ValueError, IndexError, RuntimeError):
                out[var] = defaults[var]
                out[f"{var}_probs"] = {str(defaults[var]): 1.0}

        return out

    def get_struct_filter(self, target_draw: int, db_path: str) -> Callable[[list[int]], float]:
        pred = self.predict_struct(target_draw, db_path)

        def struct_filter(combo: list[int]) -> float:
            if len(combo) != 6:
                return 0.0
            actual = extract_struct_labels(sorted(combo))
            scores: list[float] = []
            for var in VAR_NAMES:
                probs = pred.get(f"{var}_probs", {})
                key = str(actual[var])
                scores.append(float(probs.get(key, 0.0)))
            return float(sum(scores) / len(scores)) if scores else 0.0

        return struct_filter

    def class_distribution(self, target_draw: int, db_path: str) -> dict[str, dict[str, float]]:
        """학습 데이터 클래스 비율 (보고서용)."""
        draws = load_draws_before(db_path, _history_cut(target_draw))
        if len(draws) > TRAIN_WINDOW:
            draws = draws[-TRAIN_WINDOW:]
        counts: dict[str, Counter] = {v: Counter() for v in VAR_NAMES}
        for d in draws:
            nums = _nums(d)
            if len(nums) != 6:
                continue
            lab = extract_struct_labels(nums)
            for v in VAR_NAMES:
                counts[v][str(lab[v])] += 1
        out: dict[str, dict[str, float]] = {}
        for v in VAR_NAMES:
            tot = sum(counts[v].values()) or 1
            out[v] = {k: c / tot for k, c in counts[v].items()}
        return out
