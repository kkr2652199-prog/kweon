"""V11 fusion: 1군 _vector_fusion_predict 패턴 복제.

V9 fusion: _load_army2_weights → 단순 평균 (약함)
V11 fusion: 1군 vector fusion 패턴 (entropy clip + Top-K + tier1)
"""

from __future__ import annotations

import math
import random

from app.lotto.filters import tier1_filter
from app.lotto2.predict_stat import army2_stat_prob_vector
from app.lotto2.predict_markov import army2_markov_prob_vector
from app.lotto2.predict_combo import army2_combo_prob_vector
from app.lotto2.predict_lstm import army2_lstm_prob_vector
from app.lotto2.v11_models import get_v11_brain_weights


def _entropy_clip(pmf: dict[int, float], target_entropy: float = 3.5) -> dict[int, float]:
    """엔트로피가 target보다 낮으면 살짝 평탄화 (1군 패턴)."""
    H = -sum(p * math.log(p + 1e-12) for p in pmf.values() if p > 0)
    if H >= target_entropy:
        return pmf
    alpha = max(0.0, min(0.3, (target_entropy - H) / 4.0))
    n = len(pmf) or 45
    uniform = 1.0 / n
    return {k: (1 - alpha) * v + alpha * uniform for k, v in pmf.items()}


def v11_fusion_predict(training_draws: list[dict], n_sets: int = 5) -> list[dict]:
    """V11 fusion: 4뇌 PMF → 가중 합성 → entropy clip → Top-K Greedy 샘플링."""
    if not training_draws:
        return []

    weights = get_v11_brain_weights()
    pmfs = {
        "v11_stat": army2_stat_prob_vector(training_draws),
        "v11_markov": army2_markov_prob_vector(training_draws),
        "v11_combo": army2_combo_prob_vector(training_draws),
        "v11_lstm": army2_lstm_prob_vector(training_draws),
    }

    fused = {n: 0.0 for n in range(1, 46)}
    total_w = sum(weights.get(t, 1.0) for t in pmfs.keys()) or 1.0
    for tag, pmf in pmfs.items():
        w = weights.get(tag, 1.0) / total_w
        for n in range(1, 46):
            fused[n] += pmf.get(n, 0.0) * w

    s = sum(fused.values()) or 1.0
    fused = {n: v / s for n, v in fused.items()}

    fused = _entropy_clip(fused, target_entropy=3.5)

    nums_list = list(fused.keys())
    w_list = list(fused.values())

    sets: list[dict] = []
    attempts = 0
    while len(sets) < n_sets and attempts < 200:
        attempts += 1
        cand = sorted(random.choices(nums_list, weights=w_list, k=6))
        if len(set(cand)) != 6:
            continue
        try:
            if not tier1_filter(cand):
                continue
        except Exception:  # noqa: BLE001
            pass
        sets.append(
            {
                "nums": cand,
                "confidence": 0.6,
                "reasoning": (
                    f"V11 fusion 4뇌 가중합성+entropy_clip "
                    f"(lstm w={weights.get('v11_lstm', 2.0):.2f})"
                ),
                "brain_tag": "v11_fusion",
                "method": "V11퓨전두뇌",
            }
        )
    return sets


def v11_fusion_prob_vector(training_draws: list[dict]) -> dict[int, float]:
    """V11 fusion PMF (hyena 입력용)."""
    if not training_draws:
        return {n: 1.0 / 45 for n in range(1, 46)}

    weights = get_v11_brain_weights()
    pmfs = {
        "v11_stat": army2_stat_prob_vector(training_draws),
        "v11_markov": army2_markov_prob_vector(training_draws),
        "v11_combo": army2_combo_prob_vector(training_draws),
        "v11_lstm": army2_lstm_prob_vector(training_draws),
    }
    fused = {n: 0.0 for n in range(1, 46)}
    total_w = sum(weights.get(t, 1.0) for t in pmfs.keys()) or 1.0
    for tag, pmf in pmfs.items():
        w = weights.get(tag, 1.0) / total_w
        for n in range(1, 46):
            fused[n] += pmf.get(n, 0.0) * w
    s = sum(fused.values()) or 1.0
    return {n: v / s for n, v in fused.items()}

