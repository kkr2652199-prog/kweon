"""로또 LLM 두뇌 예측 — app.lotto 독립 패키지.
2026-04-20: 반환 dict에 source 필드 도입 ('llm' | 'statistical_fallback')
2026-04-20: Python 3.13 호환 — asyncio.get_running_loop() 기반 루프 감지로 수정
2026-04-20: Layer 2-b — LLM 프롬프트에 과거 피드백 섹션 주입 (함정/적중 번호). 컨닝 방지: 과거 피드백만 참조.
"""
import asyncio
import concurrent.futures
import logging
from collections import Counter

from app.lotto.predict_statistical import _statistical_predict

logger = logging.getLogger(__name__)


def _llm_predict(draws: list[dict], target_draw_no: int, n_sets: int = 5) -> list[dict]:
    """LLM 두뇌: 로또 전용 LLM(LM Studio Gemma) 분석 예측.
    knowledge_engine 비의존 — lotto_llm_client 직접 호출.
    컨닝 방지: draws에는 target_draw_no 이전 데이터만 포함."""
    try:
        from app.lotto.predict_llm_client import lotto_llm_call as _llm_call
    except ImportError:
        logger.warning("로또 LLM 클라이언트 없음 — 통계 두뇌로 대체")
        fallback = _statistical_predict(draws, n_sets)
        for x in fallback:
            x["source"] = "statistical_fallback"
        return fallback

    # 최근 50회차 데이터만 프롬프트에 포함 (토큰 절약)
    recent_50 = draws[-50:] if len(draws) > 50 else draws
    draw_text = ""
    for d in recent_50:
        draw_text += (
            f"{d['draw_no']}회: {d['num1']},{d['num2']},{d['num3']},"
            f"{d['num4']},{d['num5']},{d['num6']} (보너스:{d['bonus']})\n"
        )

    # 전체 빈도 상위 10개, 하위 10개
    freq = Counter()
    for d in draws:
        for k in ["num1", "num2", "num3", "num4", "num5", "num6"]:
            freq[d[k]] += 1
    hot = [str(n) for n, _ in freq.most_common(10)]
    cold = [str(n) for n, _ in freq.most_common()[:-11:-1]]

    # ── 1티어: LLM에게 풍부한 분석 데이터 제공 ──
    # Overdue 번호 (30회 이상 미출현)
    last_seen_llm: dict[int, int] = {}
    for d in draws:
        for k in ["num1", "num2", "num3", "num4", "num5", "num6"]:
            last_seen_llm[d[k]] = d["draw_no"]
    latest_no = draws[-1]["draw_no"] if draws else 0
    overdue = sorted(
        [n for n in range(1, 46) if latest_no - last_seen_llm.get(n, 0) >= 30],
        key=lambda n: latest_no - last_seen_llm.get(n, 0),
        reverse=True,
    )
    overdue_str = ", ".join(str(n) for n in overdue[:10]) if overdue else "없음"

    # 최근 5회 핫 번호 (2회 이상 출현)
    recent_5_llm = draws[-5:] if len(draws) >= 5 else draws
    hot_recent: dict[int, int] = {}
    for d in recent_5_llm:
        for k in ["num1", "num2", "num3", "num4", "num5", "num6"]:
            hot_recent[d[k]] = hot_recent.get(d[k], 0) + 1
    hot_streak = [str(n) for n, c in sorted(hot_recent.items(), key=lambda x: x[1], reverse=True) if c >= 2]
    hot_streak_str = ", ".join(hot_streak[:10]) if hot_streak else "없음"

    # 최근 10회 홀짝 평균
    recent_10_llm = draws[-10:] if len(draws) >= 10 else draws
    avg_odd = sum(
        sum(1 for k in ["num1", "num2", "num3", "num4", "num5", "num6"] if d[k] % 2 == 1)
        for d in recent_10_llm
    ) / len(recent_10_llm)
    odd_even_str = f"최근 10회 평균 홀 {avg_odd:.1f}개, 짝 {6 - avg_odd:.1f}개"

    # 동반출현 상위 5쌍
    pair_c: dict[tuple[int, int], int] = {}
    recent_for_p = draws[-200:] if len(draws) >= 200 else draws
    for d in recent_for_p:
        ns = sorted([d["num1"], d["num2"], d["num3"], d["num4"], d["num5"], d["num6"]])
        for i in range(len(ns)):
            for j in range(i + 1, len(ns)):
                pair_c[(ns[i], ns[j])] = pair_c.get((ns[i], ns[j]), 0) + 1
    top5_pairs = sorted(pair_c.items(), key=lambda x: x[1], reverse=True)[:5]
    pairs_str = (
        ", ".join(f"({a}-{b}:{c}회)" for (a, b), c in top5_pairs) if top5_pairs else "없음"
    )

    last_draw_no = recent_50[-1]["draw_no"] if recent_50 else target_draw_no - 1

    # ── 피드백 섹션 구성 (Layer 2-b) ──
    # 컨닝 방지: get_feedback_summary는 DB의 과거 회차 피드백만 반환
    feedback_section = ""
    try:
        from app.lotto.feedback import get_feedback_summary

        fb = get_feedback_summary(last_n=20)
        if fb.get("has_feedback"):
            trap_list = fb.get("frequent_traps", [])
            hit_list = fb.get("frequent_hits", [])
            traps_str = ", ".join(str(n) for n in trap_list) if trap_list else ""
            hits_str = ", ".join(str(n) for n in hit_list) if hit_list else ""

            parts = []
            if traps_str:
                parts.append(f"[최근 함정 번호 (과거 예측이 자주 틀린 번호)] {traps_str}")
            if hits_str:
                parts.append(f"[최근 적중 번호 (과거 예측이 자주 맞춘 번호)] {hits_str}")
            if parts:
                feedback_section = "\n" + "\n".join(parts) + "\n"
    except Exception as e:  # noqa: BLE001
        logger.debug("LLM 프롬프트 피드백 섹션 스킵: %s", e)

    prompt = f"""당신은 로또 6/45 분석 전문가입니다.

[데이터 범위] 1회차 ~ {last_draw_no}회차 (총 {len(draws)}회차 분석)
[예측 대상] {target_draw_no}회차

[최근 50회 당첨번호]
{draw_text}

[전체 빈도 상위 10] {', '.join(hot)}
[전체 빈도 하위 10] {', '.join(cold)}

[30회 이상 미출현 번호] {overdue_str}
[최근 5회 핫스트릭 번호] {hot_streak_str}
[홀짝 추세] {odd_even_str}
[동반출현 상위 5쌍 (최근 200회)] {pairs_str}
{feedback_section}
[규칙]
- 1~45 중 6개 번호를 선택
- {n_sets}세트를 제시
- 각 세트마다 선택 근거를 1줄로 설명
- 신뢰도(50~99)를 부여

[출력 형식 — 반드시 이 형식만 사용]
SET1: 번호1,번호2,번호3,번호4,번호5,번호6 | 신뢰도:XX | 근거:설명
SET2: ...
SET3: ...
SET4: ...
SET5: ...

번호는 오름차순 정렬. 다른 텍스트 없이 위 형식만 출력."""

    try:
        # Python 3.13 호환: get_event_loop() 대신 get_running_loop() 사용
        # 실행 중 루프가 없으면 RuntimeError → None 처리
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is not None:
            # FastAPI 등 이벤트 루프가 이미 실행 중인 경우:
            # 별도 스레드에서 새 루프로 실행 (중첩 루프 방지)
            with concurrent.futures.ThreadPoolExecutor() as pool:
                response = pool.submit(asyncio.run, _llm_call(prompt)).result()
        else:
            # CLI/스크립트 등 루프 없는 경우: 직접 asyncio.run (Python 3.7+ 권장)
            response = asyncio.run(_llm_call(prompt))
    except Exception as e:
        logger.warning("LLM 예측 호출 실패: %s — 통계 두뇌로 대체", e)
        fallback = _statistical_predict(draws, n_sets)
        for x in fallback:
            x["source"] = "statistical_fallback"
        return fallback

    if not response:
        fallback = _statistical_predict(draws, n_sets)
        for x in fallback:
            x["source"] = "statistical_fallback"
        return fallback

    # 파싱
    results = []
    for line in response.strip().split("\n"):
        line = line.strip()
        if not line.startswith("SET"):
            continue
        try:
            parts = line.split("|")
            nums_part = parts[0].split(":", 1)[1].strip()
            nums = sorted([int(x.strip()) for x in nums_part.split(",")])
            if len(nums) != 6 or any(n < 1 or n > 45 for n in nums):
                continue

            confidence = 70.0
            reasoning = ""
            for p in parts[1:]:
                p = p.strip()
                if p.startswith("신뢰도"):
                    try:
                        confidence = float(p.split(":", 1)[1].strip())
                    except ValueError:
                        pass
                elif p.startswith("근거"):
                    reasoning = p.split(":", 1)[1].strip()

            results.append(
                {
                    "nums": nums,
                    "confidence": min(confidence, 99.0),
                    "reasoning": reasoning or "LLM 분석",
                    "source": "llm",
                }
            )
        except Exception:
            continue

    if len(results) < n_sets:
        # 부족분은 통계로 보충
        extra = _statistical_predict(draws, n_sets - len(results))
        for e in extra:
            e["reasoning"] = "LLM 부족분 통계 보충 — " + e["reasoning"]
            e["source"] = "statistical_fallback"
        results.extend(extra)

    # 방어: source 필드 누락된 원소는 llm으로 간주 (정상 파싱 결과로 추정)
    for r in results:
        r.setdefault("source", "llm")
    results.sort(key=lambda x: x["confidence"], reverse=True)
    return results[:n_sets]
