"""V10 Stacking Meta-Learner (Logistic Regression with NumPy).

핵심:
- 입력: 6뇌 PMF (270 차원 = 6 brains × 45 numbers)
- 출력: 최종 PMF (45 차원)
- 학습: 과거 회차에서 실제 당첨번호를 정답으로 multi-label 로지스틱 회귀
- 외부 ML 라이브러리 불필요 (numpy만 사용)

1군 코드 의존성 0. lotto_draws 읽기 전용.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np

LOTTO_DB_PATH = Path(__file__).parent.parent.parent / "data" / "lotto4.db"
META_MODEL_PATH = Path(__file__).parent / "stacking_meta_weights.json"

ARMY2_BRAINS = (
    "army2_stat",
    "army2_markov",
    "army2_combo",
    "army2_lstm",
    "army2_fusion",
    "army2_hyena",
)
N_BRAINS = len(ARMY2_BRAINS)
N_NUMBERS = 45
INPUT_DIM = N_BRAINS * N_NUMBERS  # 270


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(LOTTO_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _brain_pmf_for_draw(brain_tag: str, draw_no: int) -> np.ndarray:
    """특정 회차에서 특정 뇌의 예측 5세트로부터 PMF 산출 (1~45)."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT num1, num2, num3, num4, num5, num6
            FROM lotto_predictions_army2
            WHERE brain_tag = ? AND target_draw_no = ?
            """,
            (brain_tag, draw_no),
        ).fetchall()
    finally:
        conn.close()

    pmf = np.zeros(N_NUMBERS, dtype=np.float64)
    if not rows:
        pmf[:] = 1.0 / N_NUMBERS
        return pmf
    for r in rows:
        for i in range(6):
            x = r[i]
            if 1 <= x <= 45:
                pmf[x - 1] += 1.0
    s = pmf.sum()
    if s == 0:
        pmf[:] = 1.0 / N_NUMBERS
    else:
        pmf /= s
    return pmf


def build_feature_vector(draw_no: int) -> np.ndarray:
    """회차별 6뇌 PMF를 하나의 270차원 벡터로 결합."""
    feats = []
    for tag in ARMY2_BRAINS:
        feats.append(_brain_pmf_for_draw(tag, draw_no))
    return np.concatenate(feats)


def build_target_vector(draw_no: int) -> np.ndarray:
    """실제 당첨번호 6개를 multi-hot 45차원 벡터로 변환."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT num1, num2, num3, num4, num5, num6 FROM lotto_draws WHERE draw_no = ?",
            (draw_no,),
        ).fetchone()
    finally:
        conn.close()
    y = np.zeros(N_NUMBERS, dtype=np.float64)
    if row:
        for i in range(6):
            x = row[i]
            if 1 <= x <= 45:
                y[x - 1] = 1.0
    return y


def build_dataset(start_draw: int, end_draw: int) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """학습용 (X, Y, draw_list) 빌드.

    Returns:
        X: shape (n_samples, 270)
        Y: shape (n_samples, 45)
        draw_list: 사용된 회차 번호
    """
    X_rows = []
    Y_rows = []
    draws = []
    for d in range(start_draw, end_draw + 1):
        x = build_feature_vector(d)
        if x.sum() == 0:
            continue
        y = build_target_vector(d)
        if y.sum() < 6:
            continue
        X_rows.append(x)
        Y_rows.append(y)
        draws.append(d)
    if not X_rows:
        return np.zeros((0, INPUT_DIM)), np.zeros((0, N_NUMBERS)), []
    return np.vstack(X_rows), np.vstack(Y_rows), draws


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def train_meta_model(
    X: np.ndarray,
    Y: np.ndarray,
    lr: float = 0.05,
    epochs: int = 200,
    l2: float = 1e-3,
    seed: int = 42,
) -> dict:
    """Multi-label Logistic Regression (45 binary heads, 270 input dim).

    Returns: {"W": (270, 45), "b": (45,), "loss_history": [...]}
    """
    rng = np.random.default_rng(seed)
    W = rng.normal(0, 0.01, size=(INPUT_DIM, N_NUMBERS))
    b = np.zeros(N_NUMBERS, dtype=np.float64)

    n = X.shape[0]
    if n == 0:
        return {"W": W, "b": b, "loss_history": []}

    losses = []
    for _epoch in range(epochs):
        Z = X @ W + b
        P = _sigmoid(Z)
        eps = 1e-9
        loss = -np.mean(Y * np.log(P + eps) + (1 - Y) * np.log(1 - P + eps))
        loss += 0.5 * l2 * np.sum(W * W) / n
        losses.append(float(loss))

        grad_Z = (P - Y) / n
        grad_W = X.T @ grad_Z + l2 * W / n
        grad_b = grad_Z.sum(axis=0)

        W -= lr * grad_W
        b -= lr * grad_b

    return {"W": W, "b": b, "loss_history": losses}


def predict_meta_pmf(X: np.ndarray, model: dict) -> np.ndarray:
    """학습된 메타모델로 PMF 산출."""
    W, b = model["W"], model["b"]
    Z = X @ W + b
    P = _sigmoid(Z)
    s = P.sum(axis=1, keepdims=True)
    s[s == 0] = 1.0
    return P / s


def save_model(model: dict, path: Path = META_MODEL_PATH) -> None:
    """JSON으로 W, b 저장 (loss_history 제외)."""
    payload = {
        "W": model["W"].tolist(),
        "b": model["b"].tolist(),
        "input_dim": INPUT_DIM,
        "n_numbers": N_NUMBERS,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def load_model(path: Path = META_MODEL_PATH) -> dict:
    """JSON에서 W, b 복원."""
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return {
        "W": np.array(payload["W"], dtype=np.float64),
        "b": np.array(payload["b"], dtype=np.float64),
    }

