"""V9 2군 stat: 1군 _statistical_predict 재사용 + 미당첨 데이터."""
from app.lotto.predict_statistical import _statistical_predict, get_statistical_prob_vector


def army2_stat_predict(miss_draws: list[dict], n_sets: int = 5) -> list[dict]:
    """1군 stat 함수를 미당첨 데이터로 호출."""
    if not miss_draws:
        return []
    results = _statistical_predict(miss_draws, n_sets)
    for r in results:
        r["brain_tag"] = "army2_stat"
        r["method"] = "역전통계두뇌"
    return results


def army2_stat_prob_vector(miss_draws: list[dict]) -> dict[int, float]:
    if not miss_draws:
        return {n: 1.0 / 45 for n in range(1, 46)}
    return get_statistical_prob_vector(miss_draws)
