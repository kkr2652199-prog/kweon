"""로또 하이브리드 퓨전 (앙상블 가중 투표) — app.lotto 독립 패키지.
2026-04-20: LSTM 두뇌 편입 (4두뇌 → 5두뇌). 가중치 lstm=2.0, total_weight 5.0 → 7.0.
2026-04-20: LLM 세트 source 필드 인식 — fallback 세트 llm_vec 오염 차단
2026-04-25 Layer 3: VECTOR_WEIGHTS를 lotto_brain_weights DB에서 동적 로드.
2026-04-25 Layer 3.5: Top-K Greedy 1세트 강제 (LSTM top10 overlap 1.80 → 2.80/세트).
"""
import logging
import random

from app.lotto.feedback import _load_brain_weights_from_db
from app.lotto.filters import tier1_filter
from app.lotto.predict_cluster import get_cluster_weights
from app.lotto.predict_entropy import get_entropy_weights
from app.lotto.predict_llm import _llm_predict
from app.lotto.predict_markov import _markov_predict, get_markov_prob_vector
from app.lotto.predict_statistical import _statistical_predict, get_statistical_prob_vector
from app.lotto.predict_lstm import get_lstm_prob_vector

logger = logging.getLogger(__name__)


def _hybrid_predict(draws: list[dict], target_draw_no: int, n_sets: int = 5) -> list[dict]:
    """하이브리드 두뇌: 통계 + LLM 결과를 교차 검증하여 최적 조합 선별."""
    _ = target_draw_no  # API 대칭·추후 확장용
    stat_sets = _statistical_predict(draws, n_sets * 2)
    llm_sets = _llm_predict(draws, target_draw_no, n_sets * 2)
    markov_sets = _markov_predict(draws, n_sets * 2)

    # 앙상블 가중 투표: 백테스트 성적 기반 가중치
    # LLM(2.27) > 통계(1.91) > 마르코프(신규, 기본 1.0)
    BRAIN_WEIGHTS = {
        "llm": 2.5,  # 4개 적중 2회, 최고 성적
        "stat": 1.5,  # 안정적 2개 적중
        "markov": 1.0,  # 신규, 기본값
    }

    num_score: dict[int, float] = {}
    for s in stat_sets:
        for n in s["nums"]:
            num_score[n] = num_score.get(n, 0) + s["confidence"] * BRAIN_WEIGHTS["stat"]
    for s in llm_sets:
        for n in s["nums"]:
            num_score[n] = num_score.get(n, 0) + s["confidence"] * BRAIN_WEIGHTS["llm"]
    for s in markov_sets:
        for n in s["nums"]:
            num_score[n] = num_score.get(n, 0) + s["confidence"] * BRAIN_WEIGHTS["markov"]

    # 상위 20개 번호에서 조합 생성 (기존 15 → 20으로 다양성 확대)
    top_nums = [n for n, _ in sorted(num_score.items(), key=lambda x: x[1], reverse=True)[:20]]

    # 동반출현 쌍 데이터 (최근 200회)
    pair_freq_h: dict[tuple[int, int], int] = {}
    recent_for_pairs_h = draws[-200:] if len(draws) >= 200 else draws
    for d in recent_for_pairs_h:
        ns = sorted([d["num1"], d["num2"], d["num3"], d["num4"], d["num5"], d["num6"]])
        for i in range(len(ns)):
            for j in range(i + 1, len(ns)):
                pair_freq_h[(ns[i], ns[j])] = pair_freq_h.get((ns[i], ns[j]), 0) + 1

    results: list[dict] = []
    used: set[tuple[int, ...]] = set()
    attempts = 0

    while len(results) < n_sets and attempts < 3000:
        attempts += 1

        # 가중 선택: num_score를 가중치로 사용
        if len(top_nums) >= 6:
            pool_h = top_nums[:]
            w_h = [num_score.get(n, 1) for n in pool_h]
            nums: list[int] = []
            for pick_i in range(6):
                chosen = random.choices(pool_h, weights=w_h, k=1)[0]
                nums.append(chosen)
                ci = pool_h.index(chosen)
                pool_h.pop(ci)
                w_h.pop(ci)
                # 동반출현 실시간 부스트
                if pick_i < 5:
                    for pi, pn in enumerate(pool_h):
                        pk = (min(chosen, pn), max(chosen, pn))
                        pc = pair_freq_h.get(pk, 0)
                        if pc >= 5:
                            w_h[pi] *= 1 + min(pc * 0.02, 0.4)
        else:
            nums = sorted(random.sample(range(1, 46), 6))

        nums.sort()

        # ── 1티어 필터 (통계두뇌와 동일) ──
        s = sum(nums)
        odd_count = sum(1 for n in nums if n % 2 == 1)
        ranges_hit = len({(n - 1) // 10 for n in nums})
        consec = 1
        max_consec = 1
        for ci in range(1, len(nums)):
            if nums[ci] == nums[ci - 1] + 1:
                consec += 1
                max_consec = max(max_consec, consec)
            else:
                consec = 1
        if not tier1_filter(nums):
            continue

        key = tuple(nums)
        if key in used:
            continue
        used.add(key)

        # 신뢰도: 세 두뇌 합산 점수 + 필터 보너스
        overlap_score = sum(num_score.get(n, 0) for n in nums)
        max_possible = sum(sorted(num_score.values(), reverse=True)[:6])
        confidence = overlap_score / max(max_possible, 1) * 80  # 기본 80점 만점

        # 필터 통과 보너스
        if 100 <= s <= 175:
            confidence += 8
        if 2 <= odd_count <= 4:
            confidence += 5
        if ranges_hit >= 4:
            confidence += 7
        elif ranges_hit >= 3:
            confidence += 3

        confidence = min(round(confidence, 1), 99.0)

        results.append(
            {
                "nums": nums,
                "confidence": confidence,
                "reasoning": f"하이브리드v4(앙상블 LLM×2.5+통계×1.5+마르코프×1.0), 합계={s}, 홀{odd_count}짝{6 - odd_count}, 구간{ranges_hit}, 합산={round(overlap_score, 1)}",
            }
        )

    results.sort(key=lambda x: x["confidence"], reverse=True)
    return results[:n_sets]


def _vector_fusion_predict(
    draws: list[dict],
    target_draw_no: int,
    n_sets: int = 5,
    use_topk_greedy: bool = True,
) -> list[dict]:
    """확률 벡터 기반 퓨전 예측 (하이브리드 v5).

    각 두뇌가 1~45 확률 벡터를 출력하고,
    가중 합산 → 엔트로피 보정 → 클러스터 보정 → 번호 선택.

    이전 _hybrid_predict(v4)와 달리:
    - 번호 세트가 아닌 확률 벡터 단위로 합산 (정보 손실 없음)
    - 1~45 전체 번호가 점수를 가짐 (누락 없음)
    - Shannon 엔트로피로 불확실한 번호 필터링
    - K-Means 클러스터링으로 그룹 패턴 반영
    """
    import random
    from app.lotto.filters import tier1_filter

    # ── 1. 각 두뇌의 확률 벡터 수집 ──
    stat_vec = get_statistical_prob_vector(draws)
    markov_vec = get_markov_prob_vector(draws)

    try:
        lstm_vec = get_lstm_prob_vector(draws)
        # uniform 반환은 실패 신호. 1/45 ≈ 0.02222 에서 편차 1e-6 이내면 uniform 간주
        _lstm_is_uniform = all(
            abs(lstm_vec.get(n, 0) - (1 / 45)) < 1e-6 for n in range(1, 46)
        )
        lstm_failed = _lstm_is_uniform
    except Exception as e:  # noqa: BLE001
        logger.warning("LSTM vector failed, fallback to zero weight: %s", e)
        lstm_vec = {i: 0.0 for i in range(1, 46)}
        lstm_failed = True

    # LLM 벡터: LLM은 확률 벡터를 직접 못 만드므로 예측 세트에서 출현 빈도로 역산
    # 방향 B 연장: source='llm'인 세트만 사용 (통계 fallback 세트는 벡터 오염 원천 차단)
    llm_failed = False
    try:
        from app.lotto.predict_llm import _llm_predict

        llm_sets = _llm_predict(draws, target_draw_no, n_sets * 3)

        # source='llm'인 세트만 추림
        pure_llm_sets = [s for s in llm_sets if s.get("source", "llm") == "llm"]
        fallback_count = len(llm_sets) - len(pure_llm_sets)

        if fallback_count > 0:
            logger.info(
                "LLM 세트 %d/%d개가 statistical_fallback — 해당 세트는 llm_vec에서 제외",
                fallback_count,
                len(llm_sets),
            )

        if not pure_llm_sets:
            # 전부 fallback → LLM 벡터 무효, 가중치에서 제외
            logger.warning("LLM 세트 전부 fallback — llm_vec 무효, VECTOR_WEIGHTS에서 llm 제외")
            llm_vec = {n: 0.0 for n in range(1, 46)}
            llm_failed = True
        else:
            # 순수 LLM 세트로만 벡터 생성
            llm_vec: dict[int, float] = {n: 0.0 for n in range(1, 46)}
            for s in pure_llm_sets:
                weight = s.get("confidence", 50) / 100.0
                for num in s["nums"]:
                    llm_vec[num] += weight
            # 정규화
            llm_total = sum(llm_vec.values())
            if llm_total > 0:
                llm_vec = {n: llm_vec[n] / llm_total for n in range(1, 46)}
            else:
                llm_vec = {n: 1.0 / 45 for n in range(1, 46)}
    except Exception as e:
        logger.warning("LLM 벡터 생성 실패: %s — llm_vec 무효 처리", e)
        llm_vec = {n: 0.0 for n in range(1, 46)}
        llm_failed = True

    # ── 2. 가중 합산 (Layer 3 동적 가중치 — DB 조회) ──
    # 주: lotto_brain_weights는 stat/markov/llm/lstm 4두뇌만 시드.
    # fusion은 4두뇌 합성 결과이므로 자체 가중치 없음 (의도된 설계).
    VECTOR_WEIGHTS: dict[str, float] = _load_brain_weights_from_db()
    # 실패 두뇌는 가중치에서 제외 → 나머지로 자동 재분배
    if lstm_failed:
        VECTOR_WEIGHTS = {k: v for k, v in VECTOR_WEIGHTS.items() if k != "lstm"}
    if llm_failed:
        VECTOR_WEIGHTS = {k: v for k, v in VECTOR_WEIGHTS.items() if k != "llm"}
    total_weight = sum(VECTOR_WEIGHTS.values())
    logger.info(
        "Vector fusion weights: %s (lstm_failed=%s, llm_failed=%s)",
        VECTOR_WEIGHTS,
        lstm_failed,
        llm_failed,
    )

    fused_vec: dict[int, float] = {}
    for n in range(1, 46):
        weighted_sum = (
            stat_vec.get(n, 0) * VECTOR_WEIGHTS.get("stat", 0)
            + markov_vec.get(n, 0) * VECTOR_WEIGHTS.get("markov", 0)
            + llm_vec.get(n, 0) * VECTOR_WEIGHTS.get("llm", 0)
            + lstm_vec.get(n, 0) * VECTOR_WEIGHTS.get("lstm", 0)
        )
        fused_vec[n] = weighted_sum / total_weight

    # ── 3. Shannon 엔트로피 보정 ──
    fused_vec = get_entropy_weights(fused_vec)

    # ── 4. K-Means 클러스터 보정 ──
    fused_vec = get_cluster_weights(draws, fused_vec)

    # ── 5. 번호 선택 (가중 샘플링 + 1티어 필터) ──
    results: list[dict] = []
    used: set[tuple[int, ...]] = set()
    attempts = 0

    pool_nums = list(range(1, 46))

    # Layer 3.5: Top-K Greedy 1세트 강제 (LSTM 신호 보존)
    if use_topk_greedy and n_sets >= 1:
        top6 = sorted(
            [n for n, _ in sorted(fused_vec.items(), key=lambda x: x[1], reverse=True)[:6]]
        )
        if tier1_filter(top6):
            confidence_topk = sum(fused_vec.get(n, 0) for n in top6) * 100 * 6
            confidence_topk = min(99.9, confidence_topk)
            reasoning_topk = "벡터퓨전 Top-K Greedy (fused_vec 상위 6개, 강자 보존)"
            results.append(
                {
                    "nums": top6,
                    "confidence": round(float(confidence_topk), 1),
                    "reasoning": reasoning_topk,
                }
            )
            used.add(tuple(top6))

    while len(results) < n_sets and attempts < 5000:
        attempts += 1

        # 가중 비복원 추출
        pool = pool_nums[:]
        w = [fused_vec.get(n, 1.0 / 45) for n in pool]
        nums: list[int] = []

        for _ in range(6):
            chosen = random.choices(pool, weights=w, k=1)[0]
            nums.append(chosen)
            idx = pool.index(chosen)
            pool.pop(idx)
            w.pop(idx)

        nums.sort()

        # 1티어 필터
        if not tier1_filter(nums):
            continue

        key = tuple(nums)
        if key in used:
            continue
        used.add(key)

        # 신뢰도 계산
        s = sum(nums)
        odd_count = sum(1 for n in nums if n % 2 == 1)
        ranges_hit = len({(n - 1) // 10 for n in nums})

        # 퓨전 점수 기반 신뢰도
        fusion_score = sum(fused_vec.get(n, 0) for n in nums)
        max_possible = sum(sorted(fused_vec.values(), reverse=True)[:6])
        confidence = (fusion_score / max(max_possible, 0.001)) * 70

        # 보너스
        if 100 <= s <= 175:
            confidence += 10
        if 2 <= odd_count <= 4:
            confidence += 7
        if ranges_hit >= 4:
            confidence += 8
        elif ranges_hit >= 3:
            confidence += 5

        confidence = min(round(confidence, 1), 99.0)

        results.append(
            {
                "nums": nums,
                "confidence": confidence,
                "reasoning": (
                    f"벡터퓨전v5(통계×{VECTOR_WEIGHTS.get('stat', 0)}"
                    f"+LLM×{VECTOR_WEIGHTS.get('llm', 0)}"
                    f"+마르코프×{VECTOR_WEIGHTS.get('markov', 0)}"
                    f"+LSTM×{VECTOR_WEIGHTS.get('lstm', 0)}"
                    f"+엔트로피+클러스터), "
                    f"합계={s}, 홀{odd_count}짝{6 - odd_count}, 구간{ranges_hit}"
                ),
            }
        )

    results.sort(key=lambda x: x["confidence"], reverse=True)
    return results[:n_sets]
