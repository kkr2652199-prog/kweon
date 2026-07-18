"""로또 전용 LLM 클라이언트 — app.testlotto 독립 패키지."""
import aiohttp
import logging

logger = logging.getLogger(__name__)

# 로또 전용 LLM 설정 (하드코딩 — config.json 비의존)
LOTTO_LLM_ENDPOINT = "http://localhost:1234"
LOTTO_LLM_MODEL = "google/gemma-4-e2b"
# True = LM Studio 홀딩(로컬AI 미호출, 통계 대체). 되돌리려면 False.
LOTTO_LLM_HOLD = True


async def lotto_llm_call(prompt: str, system: str = "") -> str | None:
    """
    로또 전용 LLM 호출.
    knowledge_engine, provider.py, config.json을 거치지 않음.
    LM Studio localhost:1234 직접 호출.

    Returns:
        응답 텍스트 또는 None (실패시)
    """
    if not system:
        system = "너는 로또 번호 분석 전문가다. 통계와 패턴을 기반으로 분석한다."

    url = f"{LOTTO_LLM_ENDPOINT}/v1/chat/completions"
    payload = {
        "model": LOTTO_LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "stream": False,
    }

    try:
        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    logger.error("로또 LLM 오류 (%d): %s", resp.status, error[:200])
                    return None
                data = await resp.json()
                return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.warning("로또 LLM 호출 실패: %s", e)
        return None


async def is_lotto_llm_available() -> bool:
    """LM Studio 로또 모델 사용 가능 여부 확인."""
    if LOTTO_LLM_HOLD:
        return False
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{LOTTO_LLM_ENDPOINT}/v1/models",
                timeout=aiohttp.ClientTimeout(total=3),
            ) as resp:
                return resp.status == 200
    except Exception:
        return False


def is_lotto_llm_available_sync() -> bool:
    """동기 환경(FastAPI/CLI)용 LM Studio 가용성 — 홀딩 시 즉시 False."""
    if LOTTO_LLM_HOLD:
        return False
    try:
        import urllib.request

        req = urllib.request.Request(
            f"{LOTTO_LLM_ENDPOINT}/v1/models",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False
