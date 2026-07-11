"""테스트로또 뇌 레지스트리 — 3 미래예측 + 4 보조."""

from __future__ import annotations

PREDICT_BRAINS: list[dict[str, str]] = [
    {
        "tag": "stat",
        "code": "stat_fairy",
        "name": "통계요정",
        "role": "predict",
        "desc": "빈도·끝수·이월수 가중 통계",
    },
    {
        "tag": "markov",
        "code": "flow_shaman",
        "name": "흐름술사",
        "role": "predict",
        "desc": "전이행렬·동반출현 흐름",
    },
    {
        "tag": "review",
        "code": "review_king",
        "name": "복습왕",
        "role": "predict",
        "desc": "전회차 복습·반복률 학습형",
    },
]

AUX_BRAINS: list[dict[str, str]] = [
    {
        "tag": "miss_aux",
        "code": "miss_detective",
        "name": "오답탐정",
        "role": "aux",
        "desc": "과거 오답 패턴 페널티",
    },
    {
        "tag": "pattern_aux",
        "code": "pattern_spotlight",
        "name": "패턴돋보기",
        "role": "aux",
        "desc": "쌍수·연속수·AC값 신호",
    },
    {
        "tag": "balance_aux",
        "code": "balance_keeper",
        "name": "균형지킴이",
        "role": "aux",
        "desc": "홀짝·고저·구간 쏠림 방지",
    },
    {
        "tag": "referee_aux",
        "code": "referee",
        "name": "심판관",
        "role": "aux",
        "desc": "최근 성적 좋은 예측뇌 가중치 배분",
    },
]

SETS_PER_PREDICT_BRAIN = 5

METHOD_TO_TAG: dict[str, str] = {
    "통계요정": "stat",
    "흐름술사": "markov",
    "복습왕": "review",
}

DISPLAY_NAMES: dict[str, str] = {b["tag"]: b["name"] for b in PREDICT_BRAINS + AUX_BRAINS}
