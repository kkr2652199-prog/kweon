"""4군 오프라인 백테·엔진 경로: 1군(LLM) 모듈이 로드되면 즉시 실패.

LM Studio 등 외부 LLM에 의존하지 않도록, 실수로 `app.lotto.predict_llm*` 이
import되면 RuntimeError로 중단한다."""

from __future__ import annotations

import sys

_PREFIXES: tuple[str, ...] = (
    "app.lotto.predict_llm",
    "app.lotto.predict_llm_client",
)


def assert_army1_predict_llm_not_loaded(where: str = "") -> None:
    """`sys.modules`에 1군 LLM 엔트리가 있으면 예외."""
    hit: list[str] = []
    for name in sys.modules:
        for p in _PREFIXES:
            if name == p or name.startswith(f"{p}."):
                hit.append(name)
                break
    if hit:
        loc = f" ({where})" if where else ""
        raise RuntimeError(
            "4군 백테스트/엔진은 1군 LLM을 사용할 수 없습니다. "
            f"로드된 모듈: {sorted(set(hit))}{loc}"
        )
