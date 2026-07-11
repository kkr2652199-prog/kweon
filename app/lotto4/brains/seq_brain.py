"""v13_seq — LSTM 2층 + Dot-Attention, 다음 회차 멀티라벨(45) 예측 (PyTorch).

기존 transformer(PatchTST) 경로는 seq_brain으로 교체. 롤백용 transformer.py 유지.
"""

from __future__ import annotations

import random
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from app.lotto4.brains._utils import (
    jaccard,
    load_draws_before,
    smart_filter_relaxed,
)

try:
    import torch
    import torch.nn as nn
except ImportError:  # pragma: no cover
    torch = None  # type: ignore
    nn = None  # type: ignore

WINDOW = 50
HIDDEN1 = 128
HIDDEN2 = 64
LR = 0.001
EPOCHS_INITIAL = 50
EPOCHS_FINETUNE = 5
FINETUNE_TAIL = 100
MIN_DRAW_NO = 51
NUM_SETS = 5
JACCARD_LIMIT = 0.5
TEMPS = (0.5, 0.7, 1.0, 1.2, 1.5)
BATCH_SIZE = 32

_ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = _ROOT / "models"
MODEL_PATH = MODEL_DIR / "seq_brain_latest.pt"


def _draw_to_vec(draw: dict[str, Any]) -> np.ndarray:
    v = np.zeros(45, dtype=np.float32)
    for n in draw.get("nums", []):
        ni = int(n)
        if 1 <= ni <= 45:
            v[ni - 1] = 1.0
    return v


def _build_windows(
    draws: list[dict[str, Any]], window: int = WINDOW
) -> tuple[np.ndarray, np.ndarray]:
    if len(draws) <= window:
        return np.array([]), np.array([])
    n = len(draws) - window
    X = np.zeros((n, window, 45), dtype=np.float32)
    y = np.zeros((n, 45), dtype=np.float32)
    for i in range(window, len(draws)):
        k = i - window
        for t in range(window):
            X[k, t] = _draw_to_vec(draws[i - window + t])
        y[k] = _draw_to_vec(draws[i])
    return X, y


if torch is not None:

    class SeqBrainNet(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.lstm1 = nn.LSTM(45, HIDDEN1, batch_first=True)
            self.lstm2 = nn.LSTM(HIDDEN1, HIDDEN2, batch_first=True)
            self.attn_w = nn.Linear(HIDDEN2, HIDDEN2)
            self.attn_u = nn.Linear(HIDDEN2, 1, bias=False)
            self.fc = nn.Linear(HIDDEN2, 45)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            h, _ = self.lstm1(x)
            h, _ = self.lstm2(h)
            e = self.attn_u(torch.tanh(self.attn_w(h))).squeeze(-1)
            a = torch.softmax(e, dim=1)
            ctx = (a.unsqueeze(-1) * h).sum(dim=1)
            return torch.sigmoid(self.fc(ctx))


def _ensure_torch() -> None:
    if torch is None or nn is None:
        raise RuntimeError("PyTorch 필요: pip install torch")


def _train_epochs(
    model: "SeqBrainNet",
    X: np.ndarray,
    y: np.ndarray,
    epochs: int,
    device: torch.device,
    verbose: bool = False,
) -> float:
    _ensure_torch()
    if len(X) == 0:
        return 0.0
    model.train()
    opt = torch.optim.Adam(model.parameters(), lr=LR)
    loss_fn = nn.BCELoss()
    xt = torch.from_numpy(X).to(device)
    yt = torch.from_numpy(y).to(device)
    n = len(X)
    final_loss = 0.0
    for ep in range(epochs):
        perm = torch.randperm(n, device=device)
        loss_sum = 0.0
        steps = 0
        for start in range(0, n, BATCH_SIZE):
            idx = perm[start : start + BATCH_SIZE]
            if len(idx) == 0:
                continue
            opt.zero_grad()
            pred = model(xt[idx])
            loss = loss_fn(pred, yt[idx])
            loss.backward()
            opt.step()
            loss_sum += float(loss.item())
            steps += 1
        final_loss = loss_sum / max(steps, 1)
        if verbose and (ep + 1) % 10 == 0:
            print(f"  epoch {ep + 1}/{epochs} loss={final_loss:.4f}")
    return final_loss


def _save_model(model: "SeqBrainNet", meta: dict[str, Any]) -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_torch()
    payload = {"state_dict": model.state_dict(), "meta": meta}
    torch.save(payload, MODEL_PATH)


def _load_model(
    device: torch.device,
    target_draw: int | None = None,
) -> tuple["SeqBrainNet", dict[str, Any]]:
    """모델 로드 + walk-forward 검증. 위반 시 파일 삭제 후 빈 모델 반환."""
    _ensure_torch()
    model = SeqBrainNet().to(device)
    meta: dict[str, Any] = {}
    if not MODEL_PATH.is_file():
        return model, meta
    try:
        try:
            payload = torch.load(MODEL_PATH, map_location=device, weights_only=False)
        except TypeError:
            payload = torch.load(MODEL_PATH, map_location=device)
    except OSError:
        return model, meta

    if target_draw is not None and isinstance(payload, dict):
        ck_meta = payload.get("meta", {})
        trained_through = int(
            ck_meta.get("last_update_draw") or ck_meta.get("target_draw") or 0
        )
        if trained_through >= target_draw:
            print(
                f"[SEQ_BRAIN] WALK-FORWARD 위반 감지: "
                f"모델 학습범위={trained_through}, target={target_draw}. "
                f"모델 폐기, 재학습 필요."
            )
            MODEL_PATH.unlink(missing_ok=True)
            return SeqBrainNet().to(device), {}

    if isinstance(payload, dict) and "state_dict" in payload:
        model.load_state_dict(payload["state_dict"])
        meta = payload.get("meta", {})
    else:
        model.load_state_dict(payload)
    return model, meta


def initial_train(
    db_path: str,
    target_draw: int,
    *,
    verbose: bool = True,
) -> float:
    """draw_no in [MIN_DRAW_NO, target_draw) 구간으로 초기 학습 후 저장."""
    _ensure_torch()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    draws_all = load_draws_before(db_path, target_draw)
    draws = [d for d in draws_all if int(d["draw_no"]) >= MIN_DRAW_NO]
    if len(draws) <= WINDOW:
        raise ValueError(f"학습 데이터 부족: len={len(draws)} need > {WINDOW}")
    X, y = _build_windows(draws, WINDOW)
    model = SeqBrainNet().to(device)
    if verbose:
        print(f"[seq_brain] initial_train target_draw<{target_draw} samples={len(X)} device={device}")
    loss = _train_epochs(model, X, y, EPOCHS_INITIAL, device, verbose=verbose)
    max_draw = max(int(d["draw_no"]) for d in draws) if draws else target_draw - 1
    _save_model(
        model,
        {
            "target_draw": target_draw,
            "last_update_draw": max_draw,
            "final_loss": loss,
            "trained_at": datetime.now().isoformat(),
        },
    )
    if verbose:
        print(f"[seq_brain] saved {MODEL_PATH} final_loss={loss:.4f}")
    return loss


def update_model(draw_no: int, db_path: str, *, epochs: int = EPOCHS_FINETUNE) -> float:
    """당첨 확정 회차 이후 등에서 호출 가능한 온라인 미세조정 (draw_no 이전 데이터만)."""
    _ensure_torch()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    draws = load_draws_before(db_path, draw_no + 1)
    draws = [d for d in draws if int(d["draw_no"]) >= MIN_DRAW_NO]
    if len(draws) <= WINDOW:
        return 0.0
    X, y = _build_windows(draws, WINDOW)
    if len(X) == 0:
        return 0.0
    tail = min(FINETUNE_TAIL, len(X))
    X, y = X[-tail:], y[-tail:]
    model, _ = _load_model(device)
    model.train()
    loss = _train_epochs(model, X, y, epochs, device, verbose=False)
    _save_model(
        model,
        {
            "last_update_draw": draw_no,
            "finetune_loss": loss,
            "trained_at": datetime.now().isoformat(),
        },
    )
    return loss


def _finetune_before_predict(model: "SeqBrainNet", draws: list[dict[str, Any]], device: torch.device) -> None:
    """예측 직전: 최근 FINETUNE_TAIL 회차 구간만 추가 학습."""
    draws_f = [d for d in draws if int(d["draw_no"]) >= MIN_DRAW_NO]
    if len(draws_f) <= WINDOW:
        return
    X, y = _build_windows(draws_f, WINDOW)
    if len(X) == 0:
        return
    tail = min(FINETUNE_TAIL, len(X))
    _train_epochs(model, X[-tail:], y[-tail:], EPOCHS_FINETUNE, device, verbose=False)


def _normalized_temp(p: np.ndarray, temp: float) -> np.ndarray:
    p = np.clip(p, 1e-9, 1.0)
    z = np.power(p, 1.0 / max(temp, 0.05))
    s = z.sum()
    if s <= 0:
        return np.ones(45, dtype=np.float64) / 45.0
    return z / s


def _sample_combo_legacy(prob45: np.ndarray, rng: random.Random) -> list[int]:
    """비복원 가중 추출 6개 (legacy)."""
    p = prob45.astype(np.float64).copy()
    picked: list[int] = []
    for _ in range(6):
        s = p.sum()
        if s <= 0:
            return []
        p = p / s
        r = rng.random()
        acc = 0.0
        for i in range(45):
            acc += p[i]
            if r <= acc:
                picked.append(i + 1)
                p[i] = 0.0
                break
        else:
            picked.append(int(np.argmax(p)) + 1)
            p[picked[-1] - 1] = 0.0
    return sorted(picked)


def _top_k_numbers(prob45: np.ndarray, top_k: int) -> list[int]:
    """확률 상위 top_k 번호 (동점 시 번호 오름차순)."""
    p = prob45.astype(np.float64)
    ranked = sorted(range(1, 46), key=lambda n: (-p[n - 1], n))
    return ranked[: min(top_k, 45)]


def _sample_combo_focused(
    prob45: np.ndarray,
    top_k: int,
    rng: random.Random,
    *,
    temperature: float | None = None,
) -> list[int]:
    """top-k 풀에서 비복원 가중 추출. temperature=None이면 raw 확률."""
    pool = _top_k_numbers(prob45, top_k)
    if len(pool) < 6:
        return []
    p = prob45.astype(np.float64)
    weights = np.array([max(p[n - 1], 1e-9) for n in pool], dtype=np.float64)
    if temperature is not None:
        weights = np.power(weights, 1.0 / max(temperature, 0.05))
    weights = weights / max(weights.sum(), 1e-9)

    nums = list(pool)
    probs = weights.copy()
    picked: list[int] = []
    for _ in range(6):
        if not nums:
            break
        probs = probs / max(probs.sum(), 1e-9)
        r = rng.random()
        acc = 0.0
        chosen = len(nums) - 1
        for j in range(len(nums)):
            acc += probs[j]
            if r <= acc:
                chosen = j
                break
        picked.append(nums[chosen])
        nums.pop(chosen)
        probs = np.delete(probs, chosen)
    return sorted(picked) if len(picked) == 6 else []


def _pick_deterministic_from_pool(prob45: np.ndarray, top_k: int, skip: set[int]) -> list[int]:
    """확정형: top-k 풀에서 skip 제외 후 확률 상위 6개."""
    pool = [n for n in _top_k_numbers(prob45, top_k) if n not in skip]
    if len(pool) < 6:
        return []
    p = prob45.astype(np.float64)
    chosen = sorted(pool, key=lambda n: (-p[n - 1], n))[:6]
    return sorted(chosen)


def _predict_cpu_random_filtered(draw_no: int) -> list[list[int]]:
    """창 길이 부족·Torch 없음 시: 필터·유사도만 적용한 난수 세트 (당첨 미래 미참조)."""
    rng = random.Random(draw_no * 131_071 + 7)
    out: list[list[int]] = []
    seen: list[tuple[int, ...]] = []
    for _ in range(NUM_SETS):
        for _try in range(400):
            cand = sorted(rng.sample(range(1, 46), 6))
            if not smart_filter_relaxed(cand):
                continue
            t = tuple(cand)
            if any(jaccard(set(t), set(s)) >= JACCARD_LIMIT for s in seen):
                continue
            seen.append(t)
            out.append(cand)
            break
    while len(out) < NUM_SETS:
        out.append(sorted(rng.sample(range(1, 46), 6)))
    return out[:NUM_SETS]


def _legacy_predict(draw_no: int, db_path: str) -> list[list[int]]:
    """에이스 직접생성 (B안 이전)."""
    if torch is None:
        return _predict_cpu_random_filtered(draw_no)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    draws = load_draws_before(db_path, draw_no)
    if len(draws) < WINDOW + 1:
        return _predict_cpu_random_filtered(draw_no)

    if not MODEL_PATH.is_file():
        try:
            initial_train(db_path, draw_no, verbose=False)
        except (ValueError, RuntimeError):
            return _predict_cpu_random_filtered(draw_no)

    model, meta = _load_model(device, target_draw=draw_no)
    if not meta and not MODEL_PATH.is_file():
        try:
            initial_train(db_path, draw_no, verbose=False)
            model, _ = _load_model(device, target_draw=draw_no)
        except (ValueError, RuntimeError):
            return _predict_cpu_random_filtered(draw_no)
    model.train()
    if torch is not None:
        torch.manual_seed(int(draw_no) * 17_131)
    _finetune_before_predict(model, draws, device)
    model.eval()

    seq = np.stack([_draw_to_vec(draws[i]) for i in range(len(draws) - WINDOW, len(draws))], axis=0)
    x = torch.from_numpy(seq[np.newaxis, ...]).float().to(device)
    with torch.no_grad():
        p = model(x).cpu().numpy()[0]

    existing: list[tuple[int, ...]] = []
    results: list[list[int]] = []

    def _try_add(cand: list[int]) -> bool:
        if len(cand) != 6 or len(set(cand)) != 6:
            return False
        if not smart_filter_relaxed(cand):
            return False
        t = tuple(cand)
        if t in existing:
            return False
        if any(jaccard(set(t), set(ex)) >= JACCARD_LIMIT for ex in existing):
            return False
        existing.append(t)
        results.append(cand)
        return True

    # 전략 A: 확정형 2세트 — top-12 풀, 확률 상위 6 + 잔여 6 (temperature 없음)
    for skip in (set(), set(existing[0]) if results else set()):
        if len(results) >= 2:
            break
        cand = _pick_deterministic_from_pool(p, 12, skip)
        if cand:
            _try_add(cand)

    # 전략 B: 탐색형 3세트 — top-20 풀, temperature 0.5
    explore_rng = random.Random(draw_no * 404_321 + 8181)
    for ei in range(3):
        if len(results) >= NUM_SETS:
            break
        sub_rng = random.Random(draw_no * 909_001 + ei * 17 + 8181)
        for _ in range(500):
            cand = _sample_combo_focused(p, 20, sub_rng, temperature=0.5)
            if _try_add(cand):
                break

    # fallback: legacy / 완전 난수
    p_norm = p / max(p.sum(), 1e-9)
    while len(results) < NUM_SETS:
        cand = _sample_combo_focused(p_norm, 45, explore_rng, temperature=None)
        if not cand:
            cand = _sample_combo_legacy(p_norm, explore_rng)
        if _try_add(cand):
            continue
        cand = sorted(explore_rng.sample(range(1, 46), 6))
        if tuple(cand) not in existing:
            existing.append(tuple(cand))
            results.append(cand)

    return results[:NUM_SETS]


def predict(draw_no: int, db_path: str) -> list[list[int]]:
    """QUARANTINE (2026-05-23): walk-forward 위반 의심 — 빈 리스트 반환."""
    _ = draw_no, db_path
    return []
    # TODO: 재활성화 시 아래 주석 해제
    # return _safe_predict(draw_no, db_path)


def _safe_predict(draw_no: int, db_path: str) -> list[list[int]]:
    """walk-forward 보장 predict (재활성화용)."""
    return _legacy_predict(draw_no, db_path)


def _legacy_predict_active(draw_no: int, db_path: str) -> list[list[int]]:
    """격리 전 원본 predict (보존)."""
    return _legacy_predict(draw_no, db_path)


def _p_vector_for_scoring(draw_no: int, db_path: str) -> np.ndarray:
    """score_combo/batch용 LSTM p-벡터 (sigmoid, 미세조정 1회)."""
    if torch is None:
        return np.ones(45, dtype=np.float64) / 45.0
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    draws = load_draws_before(db_path, draw_no)
    if len(draws) < WINDOW + 1:
        return np.ones(45, dtype=np.float64) / 45.0
    if not MODEL_PATH.is_file():
        try:
            initial_train(db_path, draw_no, verbose=False)
        except (ValueError, RuntimeError):
            return np.ones(45, dtype=np.float64) / 45.0
    model, _ = _load_model(device)
    model.train()
    if torch is not None:
        torch.manual_seed(int(draw_no) * 17_131)
    _finetune_before_predict(model, draws, device)
    model.eval()
    seq = np.stack(
        [_draw_to_vec(draws[i]) for i in range(len(draws) - WINDOW, len(draws))],
        axis=0,
    )
    x = torch.from_numpy(seq[np.newaxis, ...]).float().to(device)
    with torch.no_grad():
        p = model(x).cpu().numpy()[0]
    return p.astype(np.float64)


def score_combo(combo: set, target_draw: int, db) -> float:
    """combo 6번호의 LSTM p값 평균 (0~1)."""
    p = _p_vector_for_scoring(target_draw, db)
    nums = sorted({int(x) for x in combo if 1 <= int(x) <= 45})
    if len(nums) != 6:
        return 0.0
    return float(np.mean([p[n - 1] for n in nums]))


def score_batch(combos: list, target_draw: int, db) -> list[float]:
    """p-벡터 1회 계산 후 배치 점수."""
    p = _p_vector_for_scoring(target_draw, db)
    out: list[float] = []
    for combo in combos:
        nums = sorted({int(x) for x in combo if 1 <= int(x) <= 45})
        if len(nums) != 6:
            out.append(0.0)
        else:
            out.append(float(np.mean([p[n - 1] for n in nums])))
    return out


def get_prob_vector(draw_no: int, db_path: str) -> np.ndarray:
    """진단용: `predict`와 동일하게 직전 미세조정 후 정규화 확률(합=1)."""
    if torch is None or not MODEL_PATH.is_file():
        return np.ones(45, dtype=np.float64) / 45.0
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    draws = load_draws_before(db_path, draw_no)
    if len(draws) < WINDOW + 1:
        return np.ones(45, dtype=np.float64) / 45.0
    model, _ = _load_model(device)
    model.train()
    _finetune_before_predict(model, draws, device)
    model.eval()
    seq = np.stack([_draw_to_vec(draws[i]) for i in range(len(draws) - WINDOW, len(draws))], axis=0)
    x = torch.from_numpy(seq[np.newaxis, ...]).float().to(device)
    with torch.no_grad():
        pr = model(x).cpu().numpy()[0]
    s = pr.sum()
    return (pr / s).astype(np.float64) if s > 0 else np.ones(45) / 45.0
