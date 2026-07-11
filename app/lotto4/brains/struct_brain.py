"""v13_struct — 7개 구조 변수 XGBoost 예측 후 번호 표집 (4단계).

롤백용 trend.py 유지.
"""

from __future__ import annotations

import os
import random
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np

from app.lotto4.brains._utils import (
    calc_ac_value,
    count_consecutive,
    count_same_decade,
    jaccard,
    load_draws_before,
)

try:
    from sklearn.model_selection import KFold
    from xgboost import XGBRegressor
except ImportError:  # pragma: no cover
    KFold = None  # type: ignore
    XGBRegressor = None  # type: ignore

MIN_DRAW_TRAIN = 101
# 공개 당첨 상한(이후 회차는 cap+1 미만만 로드). predict(1223) → draw_no<1223
_LAST_PUBLIC_DRAW_NO = 1223
MIN_HIST = 20  # MA20·구조 시계열
NUM_SETS = 5
JACCARD_LIMIT = 0.5
RANDOM_TRIES = 10_000
TOP_K_POOL_NUMBERS = 15
TOP_K_CANDIDATES = 400
UPDATE_TAIL_DRAWS = 500
DRAW_NORM = 2500.0

VAR_NAMES: tuple[str, ...] = (
    "total_sum",
    "odd_count",
    "high_count",
    "ac_value",
    "consec_count",
    "decade_max",
    "tail_variety",
)

TOLS = np.array([15.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0], dtype=np.float64)

XGB_KW: dict[str, Any] = {
    "n_estimators": 200,
    "max_depth": 4,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "objective": "reg:squarederror",
    "random_state": 42,
    "n_jobs": -1,
}

_ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = _ROOT / "models"


def _nums(draw: dict[str, Any]) -> list[int]:
    return [int(x) for x in draw["nums"]]


def struct_vector(nums: list[int]) -> np.ndarray:
    s = sorted(nums)
    if len(s) != 6:
        return np.zeros(7, dtype=np.float64)
    total = float(sum(s))
    odd_c = float(sum(1 for n in s if n % 2 == 1))
    high_c = float(sum(1 for n in s if n >= 23))
    ac = float(calc_ac_value(s))
    consec = float(count_consecutive(s))
    decade = float(count_same_decade(s))
    tail_v = float(len({n % 10 for n in s}))
    return np.array(
        [total, odd_c, high_c, ac, consec, decade, tail_v], dtype=np.float64
    )


def _history_cut(draw_no: int) -> int:
    """예측 대상 draw_no에 대해 DB 조회 상한 (< cap 만 로드)."""
    d = int(draw_no)
    cap = _LAST_PUBLIC_DRAW_NO + 1
    return d if d <= cap else cap


def _build_features(
    struct_hist: list[np.ndarray], target_draw_no: int
) -> np.ndarray:
    """struct_hist: 과거 회차 구조 벡터 시계열 (이미 끝이 직전 회차)."""
    s = struct_hist
    last = s[-1]
    if len(s) >= 5:
        ma5 = np.mean(np.stack(s[-5:], axis=0), axis=0)
        std5 = np.std(np.stack(s[-5:], axis=0), axis=0)
    else:
        ma5 = last.copy()
        std5 = np.zeros(7, dtype=np.float64)
    if len(s) >= 20:
        ma20 = np.mean(np.stack(s[-20:], axis=0), axis=0)
    else:
        ma20 = np.mean(np.stack(s, axis=0), axis=0)
    if len(s) >= 2:
        delta = s[-1] - s[-2]
    else:
        delta = np.zeros(7, dtype=np.float64)
    draw_norm = np.array([target_draw_no / DRAW_NORM], dtype=np.float64)
    return np.concatenate([last, ma5, ma20, std5, delta, draw_norm], axis=0)


def _training_matrix(
    draws: list[dict[str, Any]],
) -> tuple[np.ndarray, np.ndarray] | tuple[None, None]:
    if len(draws) < MIN_HIST + 1:
        return None, None
    X_list: list[np.ndarray] = []
    y_list: list[np.ndarray] = []
    structs: list[np.ndarray] = []
    for d in draws:
        structs.append(struct_vector(_nums(d)))

    for k in range(MIN_HIST, len(draws)):
        if int(draws[k]["draw_no"]) < MIN_DRAW_TRAIN:
            continue
        hist = structs[:k]
        x = _build_features(hist, int(draws[k]["draw_no"]))
        y = structs[k]
        X_list.append(x)
        y_list.append(y)

    if not X_list:
        return None, None
    return np.stack(X_list, axis=0), np.stack(y_list, axis=0)


def _models_dir() -> Path:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    return MODEL_DIR


def _model_path(name: str) -> Path:
    # XGBoost 3.x sklearn save_model 기본값은 UBJSON. .json 경로에도 UBJSON을 쓰면 load 시 JSON 파서 오류.
    return _models_dir() / f"struct_brain_{name}.ubj"


def _atomic_save_xgb(model: Any, path: Path) -> None:
    """동시 로드(XGBoost) 시 빈 파일을 읽는 일을 줄이기 위해 tmp 저장 후 replace."""
    _ensure_xgb()
    tmp = path.with_name(path.name + ".tmp")
    try:
        model.save_model(str(tmp))
        os.replace(str(tmp), str(path))
    finally:
        if tmp.is_file():
            try:
                tmp.unlink()
            except OSError:
                pass


def _all_model_paths_exist() -> bool:
    try:
        return all(
            _model_path(n).is_file() and _model_path(n).stat().st_size > 64
            for n in VAR_NAMES
        )
    except OSError:
        return False


def _ensure_xgb() -> None:
    if XGBRegressor is None or KFold is None:
        raise RuntimeError("xgboost·sklearn 필요: pip install xgboost scikit-learn")


def cv_rmse(X: np.ndarray, y_col: np.ndarray, n_splits: int = 5) -> float:
    _ensure_xgb()
    n = len(X)
    if n < n_splits:
        return float("nan")
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=42)
    errs: list[float] = []
    for tr, va in kf.split(X):
        m = XGBRegressor(**XGB_KW)
        m.fit(X[tr], y_col[tr])
        pred = m.predict(X[va])
        errs.append(float(np.sqrt(np.mean((pred - y_col[va]) ** 2))))
    return float(np.mean(errs))


def initial_train(db_path: str, target_draw: int, *, verbose: bool = True) -> dict[str, float]:
    """draw_no < target_draw, draw_no >= 101 구간으로 7모델 학습·저장."""
    _ensure_xgb()
    if int(target_draw) < MIN_DRAW_TRAIN:
        if verbose:
            print(
                f"[struct_brain] initial_train skip: target_draw={target_draw} "
                f"< MIN_DRAW_TRAIN={MIN_DRAW_TRAIN}"
            )
        return {}
    draws = load_draws_before(db_path, target_draw)
    Xm, Ym = _training_matrix(draws)
    if Xm is None or len(Xm) < 50:
        raise ValueError(f"학습 표본 부족: {0 if Xm is None else len(Xm)}")

    rmses: dict[str, float] = {}
    for i, name in enumerate(VAR_NAMES):
        rmse = cv_rmse(Xm, Ym[:, i])
        rmses[name] = rmse
        if verbose:
            print(f"  CV RMSE {name}: {rmse:.4f}")
        m = XGBRegressor(**XGB_KW)
        m.fit(Xm, Ym[:, i])
        _atomic_save_xgb(m, _model_path(name))

    if verbose:
        print(f"[struct_brain] saved 7 models under {_models_dir()}")
    return rmses


def _load_models() -> list[Any]:
    _ensure_xgb()
    out: list[Any] = []
    for name in VAR_NAMES:
        p = _model_path(name)
        if not p.is_file():
            raise FileNotFoundError(str(p))
        m = XGBRegressor(**XGB_KW)
        m.load_model(str(p))
        out.append(m)
    return out


def update_models(draw_no: int, db_path: str, *, verbose: bool = False) -> None:
    """최근 UPDATE_TAIL_DRAWS 회차만으로 7모델 재학습 (예측 직전 호출)."""
    _ensure_xgb()
    cut = _history_cut(draw_no)
    draws = load_draws_before(db_path, cut)
    if cut <= MIN_DRAW_TRAIN:
        return
    if len(draws) > UPDATE_TAIL_DRAWS:
        draws = draws[-UPDATE_TAIL_DRAWS:]
    Xm, Ym = _training_matrix(draws)
    if Xm is None or len(Xm) < 30:
        return
    for i, name in enumerate(VAR_NAMES):
        m = XGBRegressor(**XGB_KW)
        m.fit(Xm, Ym[:, i])
        _atomic_save_xgb(m, _model_path(name))
    if verbose:
        print(f"[struct_brain] update_models cut={cut} rows={len(Xm)}")


def _postprocess_y_hat(raw: np.ndarray) -> np.ndarray:
    y_hat = raw.astype(np.float64).copy()
    y_hat[1] = float(np.clip(np.round(y_hat[1]), 0, 6))
    y_hat[2] = float(np.clip(np.round(y_hat[2]), 0, 6))
    y_hat[4] = float(np.clip(np.round(y_hat[4]), 0, 5))
    y_hat[5] = float(np.clip(np.round(y_hat[5]), 1, 5))
    y_hat[6] = float(np.clip(np.round(y_hat[6]), 1, 6))
    y_hat[3] = float(np.clip(np.round(y_hat[3]), 0, 10))
    y_hat[0] = float(np.clip(y_hat[0], 21.0, 255.0))
    return y_hat


def _infer_y_hat(draw_no: int, db_path: str) -> np.ndarray:
    cut = _history_cut(draw_no)
    draws = load_draws_before(db_path, cut)
    if len(draws) < MIN_HIST:
        return _postprocess_y_hat(
            np.array([100.0, 3.0, 3.0, 7.0, 1.0, 3.0, 5.0])
        )
    structs = [struct_vector(_nums(d)) for d in draws]
    X = _build_features(structs, int(draw_no)).reshape(1, -1)
    models = _load_models()
    raw = np.array([float(models[i].predict(X)[0]) for i in range(7)])
    return _postprocess_y_hat(raw)


def predict_struct_vector(
    draw_no: int, db_path: str, *, skip_update: bool = False
) -> np.ndarray:
    """진단용: 학습 후 7차원 구조 추정.

    앙상블에서 직전 `predict()`가 이미 `update_models`를 호출했으면
    `skip_update=True`로 중복 저장·경합을 피한다.

    `predict()`가 초기 회차에서 RNG 폴백만 하고 디스크에 모델이 없을 수 있음 —
    그때는 `_infer_y_hat`과 동일한 기본 벡터로 진행한다.
    """
    if not skip_update:
        update_models(draw_no, db_path)
    if not _all_model_paths_exist():
        return _postprocess_y_hat(
            np.array([100.0, 3.0, 3.0, 7.0, 1.0, 3.0, 5.0])
        )
    return _infer_y_hat(draw_no, db_path)


def _count_soft_match(actual: np.ndarray, y_hat: np.ndarray) -> int:
    ok = 0
    if abs(actual[0] - y_hat[0]) <= TOLS[0]:
        ok += 1
    for i in range(1, 7):
        if abs(actual[i] - y_hat[i]) <= TOLS[i]:
            ok += 1
    return ok


def _struct_distance(actual: np.ndarray, y_hat: np.ndarray) -> float:
    return float(np.sum(np.abs(actual - y_hat) / TOLS))


def _generate_candidates_legacy(
    y_hat: np.ndarray, rng: random.Random
) -> list[tuple[float, list[int]]]:
    cands: list[tuple[float, list[int]]] = []
    seen: set[tuple[int, ...]] = set()
    for _ in range(RANDOM_TRIES):
        cand = sorted(rng.sample(range(1, 46), 6))
        t = tuple(cand)
        if t in seen:
            continue
        seen.add(t)
        act = struct_vector(cand)
        if _count_soft_match(act, y_hat) < 5:
            continue
        d = _struct_distance(act, y_hat)
        cands.append((d, cand))
    cands.sort(key=lambda x: x[0])
    return cands[:TOP_K_CANDIDATES]


def _score_numbers(y_hat: np.ndarray) -> dict[int, float]:
    """1~45 각 번호의 구조 적합도 (odd/high/decade/tail 가중합)."""
    tgt_odd = float(y_hat[1])
    tgt_high = float(y_hat[2])
    tgt_decade_max = float(y_hat[5])
    tgt_tail = float(y_hat[6])

    scores: dict[int, float] = {}
    for n in range(1, 46):
        odd_s = (tgt_odd / 6.0) if n % 2 == 1 else ((6.0 - tgt_odd) / 6.0)
        high_s = (tgt_high / 6.0) if n >= 23 else ((6.0 - tgt_high) / 6.0)
        decade_idx = min((n - 1) // 10, 4)
        decade_cap = [10, 10, 10, 10, 5][decade_idx]
        decade_s = min(tgt_decade_max, float(decade_cap)) / 6.0
        tail_s = tgt_tail / 6.0
        scores[n] = odd_s + high_s + decade_s + tail_s
    return scores


def _generate_candidates_deterministic(
    y_hat: np.ndarray,
) -> list[tuple[float, list[int]]]:
    """top-15 번호 풀 → 15C6 전수 평가 (결정론적)."""
    scored = _score_numbers(y_hat)
    pool = sorted(
        range(1, 46),
        key=lambda n: (-scored[n], n),
    )[:TOP_K_POOL_NUMBERS]
    if len(pool) < 6:
        return []

    cands: list[tuple[float, list[int]]] = []
    for combo in combinations(pool, 6):
        cand = sorted(combo)
        act = struct_vector(cand)
        if _count_soft_match(act, y_hat) < 5:
            continue
        d = _struct_distance(act, y_hat)
        cands.append((d, cand))
    cands.sort(key=lambda x: (x[0], x[1]))
    return cands


def _center_y_hat_uniform() -> np.ndarray:
    """모델 없음·초기 회차: 중심 구조 벡터(균등·무정보에 가까운 타깃)."""
    return _postprocess_y_hat(
        np.array([100.0, 3.0, 3.0, 7.0, 1.0, 3.0, 5.0])
    )


def _pick_sets_from_y_hat(draw_no: int, y_hat: np.ndarray) -> list[list[int]]:
    """구조 타깃 y_hat 기반 후보 → 5세트 (결정론적 우선, legacy fallback)."""
    pool = _generate_candidates_deterministic(y_hat)

    if not pool:
        rng = random.Random(draw_no * 131_101 + 77)
        pool = _generate_candidates_legacy(y_hat, rng)

    if not pool:
        rng2 = random.Random(draw_no + 1)
        for _ in range(5000):
            cand = sorted(rng2.sample(range(1, 46), 6))
            act = struct_vector(cand)
            if _count_soft_match(act, y_hat) >= 4:
                pool.append((_struct_distance(act, y_hat), cand))
        pool.sort(key=lambda x: (x[0], x[1]))

    existing: list[tuple[int, ...]] = []
    results: list[list[int]] = []
    for d, cand in pool:
        t = tuple(cand)
        if any(jaccard(set(t), set(e)) >= JACCARD_LIMIT for e in existing):
            continue
        existing.append(t)
        results.append(cand)
        if len(results) >= NUM_SETS:
            break

    while len(results) < NUM_SETS and pool:
        for d, cand in pool:
            t = tuple(cand)
            if t in existing:
                continue
            existing.append(t)
            results.append(cand)
            if len(results) >= NUM_SETS:
                break
        break

    r2 = random.Random(draw_no * 707 + 13)
    while len(results) < NUM_SETS:
        results.append(sorted(r2.sample(range(1, 46), 6)))

    return [list(x) for x in results[:NUM_SETS]]


def _legacy_predict(draw_no: int, db_path: str) -> list[list[int]]:
    """에이스 직접생성 (B안 이전)."""
    if XGBRegressor is None:
        rng = random.Random(draw_no * 97_117 + 3)
        return [sorted(rng.sample(range(1, 46), 6)) for _ in range(NUM_SETS)]

    if not _all_model_paths_exist():
        try:
            initial_train(db_path, _history_cut(draw_no), verbose=False)
        except (ValueError, FileNotFoundError, RuntimeError):
            pass
        if not _all_model_paths_exist():
            return _pick_sets_from_y_hat(draw_no, _center_y_hat_uniform())

    update_models(draw_no, db_path)
    y_hat = _infer_y_hat(draw_no, db_path)
    return _pick_sets_from_y_hat(draw_no, y_hat)


def predict(draw_no: int, db_path: str) -> list[list[int]]:
    """풀백·레거시 호환: 에이스 직접생성."""
    return _legacy_predict(draw_no, db_path)


def _y_hat_for_scoring(target_draw: int, db_path: str) -> np.ndarray:
    """score_batch용 구조 타깃 1회 추론."""
    if XGBRegressor is None:
        return _center_y_hat_uniform()
    if not _all_model_paths_exist():
        try:
            initial_train(db_path, _history_cut(target_draw), verbose=False)
        except (ValueError, FileNotFoundError, RuntimeError):
            pass
        if not _all_model_paths_exist():
            return _center_y_hat_uniform()
    update_models(target_draw, db_path)
    return _infer_y_hat(target_draw, db_path)


def _struct_score_from_vectors(actual: np.ndarray, y_hat: np.ndarray) -> float:
    dist = _struct_distance(actual, y_hat)
    max_dist = float(len(TOLS))
    normalized = min(1.0, dist / max_dist)
    return max(0.0, 1.0 - normalized)


def score_combo(combo: set, target_draw: int, db) -> float:
    """구조 벡터와 XGB 예측 간 거리 기반 점수 (0~1)."""
    nums = sorted({int(x) for x in combo if 1 <= int(x) <= 45})
    if len(nums) != 6:
        return 0.0
    actual = struct_vector(nums)
    y_hat = _y_hat_for_scoring(target_draw, db)
    return _struct_score_from_vectors(actual, y_hat)


def score_batch(combos: list, target_draw: int, db) -> list[float]:
    """XGB 예측 1회, 모든 combo 구조 거리 점수."""
    y_hat = _y_hat_for_scoring(target_draw, db)
    out: list[float] = []
    for combo in combos:
        nums = sorted({int(x) for x in combo if 1 <= int(x) <= 45})
        if len(nums) != 6:
            out.append(0.0)
        else:
            actual = struct_vector(nums)
            out.append(_struct_score_from_vectors(actual, y_hat))
    return out
