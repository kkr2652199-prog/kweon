"""테스트로또 뇌 레지스트리 — 3 미래예측 + 4 보조."""

from __future__ import annotations

PREDICT_BRAINS: list[dict[str, str]] = [
    {
        "tag": "stat",
        "code": "stat_fairy",
        "name": "통계요정",
        "role": "predict",
        "desc": "빈도·끝수·이월수 가중 통계",
        "short_desc": "최근 빈도·끝수·이월수로 자주 나온 흐름을 잡는다",
    },
    {
        "tag": "markov",
        "code": "flow_shaman",
        "name": "흐름술사",
        "role": "predict",
        "desc": "전이행렬·동반출현 흐름",
        "short_desc": "직전 회차와의 전이·궁합수 연결을 추적한다",
    },
    {
        "tag": "review",
        "code": "review_king",
        "name": "복습왕",
        "role": "predict",
        "desc": "전회차 복습·반복률 학습형",
        "short_desc": "과거 오답을 복습해 놓쳤던 구간을 보정한다",
    },
]

AUX_BRAINS: list[dict[str, str]] = [
    {
        "tag": "miss_aux",
        "code": "miss_detective",
        "name": "오답탐정",
        "role": "aux",
        "desc": "과거 오답 패턴 페널티",
        "short_desc": "자주 틀린 패턴을 찾아 경고한다",
    },
    {
        "tag": "pattern_aux",
        "code": "pattern_spotlight",
        "name": "패턴돋보기",
        "role": "aux",
        "desc": "쌍수·연속수·AC값 신호",
        "short_desc": "쌍수·연속수·AC값 신호를 읽는다",
    },
    {
        "tag": "balance_aux",
        "code": "balance_keeper",
        "name": "균형지킴이",
        "role": "aux",
        "desc": "홀짝·고저·구간 쏠림 방지",
        "short_desc": "홀짝·고저·합계 균형을 점검한다",
    },
    {
        "tag": "referee_aux",
        "code": "referee",
        "name": "심판관",
        "role": "aux",
        "desc": "최근 성적 좋은 예측뇌 가중치 배분",
        "short_desc": "세트 간 겹침·쏠림을 최종 판정한다",
    },
]

SETS_PER_PREDICT_BRAIN = 5

METHOD_TO_TAG: dict[str, str] = {
    "통계요정": "stat",
    "흐름술사": "markov",
    "복습왕": "review",
}

DISPLAY_NAMES: dict[str, str] = {b["tag"]: b["name"] for b in PREDICT_BRAINS + AUX_BRAINS}
SHORT_DESCS: dict[str, str] = {b["tag"]: b.get("short_desc", "") for b in PREDICT_BRAINS + AUX_BRAINS}
ALL_BRAINS: list[dict[str, str]] = PREDICT_BRAINS + AUX_BRAINS


def get_brain_meta(tag: str) -> dict[str, str]:
    """뇌 tag → 이름·역할·필살기 한 줄."""
    for b in ALL_BRAINS:
        if b["tag"] == tag:
            return {
                "tag": tag,
                "name": b["name"],
                "role": b["role"],
                "desc": b.get("desc", ""),
                "short_desc": b.get("short_desc", ""),
            }
    return {"tag": tag, "name": DISPLAY_NAMES.get(tag, tag), "role": "", "desc": "", "short_desc": ""}


def get_short_desc(tag: str) -> str:
    return SHORT_DESCS.get(tag, "")
