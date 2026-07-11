"""V9 2군 markov: 1군 _markov_predict 재사용 + 미당첨 데이터."""
from app.lotto.predict_markov import _markov_predict, get_markov_prob_vector


def army4_markov_predict(miss_draws: list[dict], n_sets: int = 5) -> list[dict]:
    if not miss_draws or len(miss_draws) < 2:
        return []
    results = _markov_predict(miss_draws, n_sets)
    for r in results:
        r["brain_tag"] = "army4_markov"
        r["method"] = "역전마르코프두뇌"
    return results


def army4_markov_prob_vector(miss_draws: list[dict]) -> dict[int, float]:
    if not miss_draws or len(miss_draws) < 2:
        return {n: 1.0 / 45 for n in range(1, 46)}
    return get_markov_prob_vector(miss_draws)
