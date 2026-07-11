# 3군 hyena / lstm / fusion Walk-Forward 무결성 정찰 보고서

- **날짜**: 2026-05-29
- **이름**: 동생 → 커서
- **모드**: READ-ONLY (코드·DB 수정 **0줄**)
- **1~3군 간섭**: **0건** (열람만, `My_Library/app/lotto3` + `app/lotto/predict_lstm.py`)
- **SHA256**: 변경 없음 (정찰 전용)

---

## 작업 시작 전 3파일 확인

```
✅ RULES_FIXED.md 확인 (R1~R30, R4 세션 필독 / R13 Walk-Forward+Embargo)
✅ STATUS_LATEST.md 확인 (기억86, 3군 hyena 해부 완료)
✅ CURSOR_RULES.md 확인 (§1 매작업 3파일, §2 lotto3 수정 금지)
```

---

## 소스 위치

| 경로 | 상태 |
|------|------|
| `d:\3kweon\app\lotto3\` | **없음** |
| `D:\MONEY lol\My_Library\app\lotto3\` | **3군 실제 소스** |
| LSTM 코어 | `D:\MONEY lol\My_Library\app\lotto\predict_lstm.py` (1군, 3군이 import) |

---

## 1. predict_lstm.py (3군 래퍼 + 1군 코어)

### 1-A. 3군 `app/lotto3/predict_lstm.py`

**학습 데이터 슬라이싱 변수**: 3군 파일 자체는 슬라이싱 없음. 인자 `miss_draws`를 그대로 1군에 전달.

```15:18:D:\MONEY lol\My_Library\app\lotto3\predict_lstm.py
def army3_lstm_prob_vector(miss_draws: list[dict]) -> dict[int, float]:
    if not miss_draws or len(miss_draws) < 10:
        return {n: 1.0 / 45 for n in range(1, 46)}
    return get_lstm_prob_vector(miss_draws)
```

```21:30:D:\MONEY lol\My_Library\app\lotto3\predict_lstm.py
def army3_lstm_predict(
    miss_draws: list[dict],
    n_sets: int = 5,
    target_draw_no: int | None = None,
) -> list[dict]:
    """LSTM PMF 기반 샘플링."""
    if not miss_draws or len(miss_draws) < 10:
        return []

    pmf = get_lstm_prob_vector(miss_draws)
```

- `target_draw_no`는 **win_avoid(직전 당첨 Jaccard)** 용만 사용 (`get_recent_winning_sets(target_draw_no)`).
- **PMF/LSTM fit 입력 범위를 자르는 변수는 없음** → 상위 `get_v12_training_draws(target_draw_no)`에 의존.

### 1-B. 1군 `app/lotto/predict_lstm.py` — fit 상한

**정렬·길이·학습 입력**:

```267:275:D:\MONEY lol\My_Library\app\lotto\predict_lstm.py
    d_sorted = _sort_by_draw_no(draws)
    n = len(d_sorted)
    if n < SEQ_LEN + 1:
        r0 = _uniform_pmf()
        _assert_pmf(r0)
        return r0

    prefer_cuda = T.cuda.is_available()
    _ensure_model_ready(n, d_sorted, prefer_cuda)
```

**학습쌍 생성 (블록 슬라이스, target 회차 직접 참조 없음)**:

```106:111:D:\MONEY lol\My_Library\app\lotto\predict_lstm.py
        for k in range(n):
            block = draws[k : k + SEQ_LEN + 1]
            seq = [_multihot_from_draw(block[j]) for j in range(SEQ_LEN)]
            target = _multihot_from_draw(block[SEQ_LEN])
            xs.append(seq)
            ys.append(target)
```

**추론 윈도우 (전달된 draws의 마지막 50회)**:

```279:281:D:\MONEY lol\My_Library\app\lotto\predict_lstm.py
    win = d_sorted[-SEQ_LEN:]
    seq = [_multihot_from_draw(w) for w in win]
    x1 = T.tensor([seq], dtype=T.float32)
```

**재학습 조건 (전역 + 체크포인트)**:

```196:234:D:\MONEY lol\My_Library\app\lotto\predict_lstm.py
    def _ensure_model_ready(n_draws: int, d_sorted: list[dict], prefer_cuda: bool) -> None:
        global _MODEL, _LAST_TRAINED_LEN, _DEVICE_USED
        need_train = False
        if _MODEL is None:
            ck = _load_checkpoint()
            if ck and "model_state" in ck:
                ...
                    _LAST_TRAINED_LEN = int(ck.get("last_trained_on", 0))
                    if n_draws - _LAST_TRAINED_LEN >= RETRAIN_INTERVAL:
                        need_train = True
                    else:
                        ...  # 체크포인트 가중치 로드, 재학습 스kip
        else:
            if n_draws - _LAST_TRAINED_LEN >= RETRAIN_INTERVAL:
                need_train = True

        if need_train or _MODEL is None:
            m_fit, dused = _fit_model(d_sorted, prefer_cuda=prefer_cuda)
            _MODEL = m_fit
            _LAST_TRAINED_LEN = n_draws
```

- `RETRAIN_INTERVAL = 50` (L39).
- fit 시 **`d_sorted` 전체**를 `_fit_model` → `_train_on_device`에 사용 (별도 `< target` 코드 없음, **입력 list가 past-only이면 준수**).

**스케일러/정규화**: multihot 0/1만 사용. **mean/std 전구간 사전계산 없음**. ✅

### 1-C. 모델 `.pt` — 회차별 재학습 vs 고정

| 항목 | raw |
|------|-----|
| 체크포인트 경로 | `CKPT_PATH = _PROJECT_ROOT / "models" / "lstm_lotto.pt"` (L42) |
| 파일 mtime | `2026-04-24 23:32:47` |
| 파일 내 `last_trained_on` | **1219** (실측 `torch.load`) |
| 백테스트 루프 내 삭제/초기화 | **코드상 없음** (`run_v12_chunk_backtest`에 LSTM reset 없음) |

**판정**:

- ✅ **순방향 백테스트 단일 프로세스**에서 `n_draws`가 증가할 때마다 `RETRAIN_INTERVAL`마다 **당시 `training` list로 재학습** — 입력 list가 `< target`이면 walk-forward 준수.
- ⚠️ **누수 의심: [app/lotto/predict_lstm.py:196-220]** — 세션 시작 시 **기존 `lstm_lotto.pt`(last_trained_on=1219)를 로드**한 뒤, 초기 회차에서 `n_draws(≈50~100) - 1219 < 50`이면 **재학습 없이 미래까지 학습된 가중치 사용**. 백테스트 **재실행·중간 회차 단독 검증** 시 avg 부풀릴 수 있음.
- ⚠️ **누수 의심: [app/lotto/predict_lstm.py:45-47, 전역 _MODEL]** — 프로세스 간 전역 캐시. 체크포인트/전역 상태 **clear 없이** draw 6부터 chunk 재실행하면 동일 위험.

---

## 2. v12_fusion_v5.py

### 2-A. 하위 PMF 입력 범위

```129:157:D:\MONEY lol\My_Library\app\lotto3\v12_fusion_v5.py
def _v12_load_brain_pmfs(training_draws: list[dict]) -> dict[str, dict[int, float]]:
    pmfs: dict[str, dict[int, float]] = {}
    ...
        pmfs["v12_stat"] = army3_cdm_prob_vector(training_draws)
    ...
        pmfs["v12_lstm"] = army3_lstm_prob_vector(training_draws)
    return pmfs
```

```245:273:D:\MONEY lol\My_Library\app\lotto3\v12_fusion_v5.py
def v12_fusion_v5_predict(
    training_draws: list[dict],
    target_draw_no: int,
    n_sets: int = 5,
) -> list[dict]:
    ...
    pmfs = _v12_load_brain_pmfs(training_draws)
    combined_pmf = _v12_combine_pmfs(pmfs, brain_weights)
    entropy_w = _v12_get_entropy_weights(training_draws)
    cluster_w = _v12_get_cluster_weights(target_draw_no)
    final_pmf = _v12_apply_entropy_cluster(combined_pmf, entropy_w, cluster_w)
```

- PMF·entropy 입력 = **`training_draws`** (엔진에서 `get_v12_training_draws` 결과).
- **`< target` 자르기는 fusion 파일 내부에 없음** → 엔진 위임.

### 2-B. cluster / entropy — API 불일치 (누수 아님, 기능 무력)

```105:114:D:\MONEY lol\My_Library\app\lotto3\v12_fusion_v5.py
def _v12_get_cluster_weights(target_draw_no: int) -> dict[int, float]:
    try:
        from app.lotto.predict_cluster import get_cluster_weights
        cw = get_cluster_weights(target_draw_no=target_draw_no)
```

1군 실제 시그니처:

```11:15:D:\MONEY lol\My_Library\app\lotto\predict_cluster.py
def get_cluster_weights(
    draws: list[dict],
    prob_vector: dict[int, float],
    n_clusters: int = 5,
) -> dict[int, float]:
```

```117:126:D:\MONEY lol\My_Library\app\lotto3\v12_fusion_v5.py
def _v12_get_entropy_weights(training_draws: list[dict]) -> dict[int, float]:
    try:
        from app.lotto.predict_entropy import get_entropy_weights
        ew = get_entropy_weights(training_draws)
```

1군 실제 시그니처:

```10:10:D:\MONEY lol\My_Library\app\lotto\predict_entropy.py
def get_entropy_weights(prob_vector: dict[int, float]) -> dict[int, float]:
```

→ **항상 except → `{n: 1.0}` uniform fallback** (L114-115, L126-127).  
**누수 아님**. 다만 **Fusion V5의 entropy×cluster 보정은 3군 경로에서 사실상 미동작**.

### 2-C. 1군 fusion 회피 (간접 의존)

```44:58:D:\MONEY lol\My_Library\app\lotto3\v12_fusion_v5.py
def _v12_load_army1_fusion_sets(target_draw_no: int) -> list[set[int]]:
    ...
            SELECT num1, num2, num3, num4, num5, num6
            FROM lotto_predictions
            WHERE target_draw_no = ? AND brain_tag = ?
            (target_draw_no, _ARMY1_FUSION_TAG),
```

- **동일 `target_draw_no`의 1군 fusion 저장분**을 읽어 Jaccard 회피만 수행.
- 3군 PMF 학습 범위와는 별도. **1군 예측이 컨닝이면 간접 오염 가능** — 3군 코드만으로 1군 무결성 **코드상 불명확**.

### 2-D. walk-forward (fusion 경로)

✅ **walk-forward 준수 (조건부)**: PMF는 `training_draws`만 사용하고, `training_draws`는 엔진에서 `get_v12_training_draws(target)` (아래 §3). **단, lstm PMF가 §1-C 체크포인트 누수면 fusion·hyena도 연쇄 오염**.

---

## 3. v12_engine.py — training 슬라이스 & backtest

### 3-A. `get_v12_training_draws` (핵심 컷)

```82:116:D:\MONEY lol\My_Library\app\lotto3\v12_models.py
def get_v12_training_draws(target_draw_no: int) -> list[dict]:
    """V11 학습 데이터: 1군 미당첨 회차 + 최 recent 50회차 (중복 제거).

    컷닝 0%: target_draw_no 미만만.
    """
    ...
            WHERE d.draw_no < ?
              AND d.draw_no IN (
                SELECT target_draw_no FROM lotto_predictions
                ...
                  AND target_draw_no < ?
    ...
            WHERE draw_no < ?
            ORDER BY draw_no DESC
            LIMIT ?
            (target_draw_no, target_draw_no),
            (target_draw_no, V11_RECENT_BOOST),
```

- **`< target_draw_no` (strict)** — `<=` 아님. ✅ R13 부합.

### 3-B. `run_prediction_v12` 파이프라인

```313:346:D:\MONEY lol\My_Library\app\lotto3\v12_engine.py
    training = get_v12_training_draws(target_draw_no)
    if len(training) < 5:
        return {"status": "error", "reason": "insufficient_training_data", ...}

    fresh.extend(_retag(army3_cdm_predict(training, ...), "v12_stat", ...))
    ...
    fresh.extend(_retag(army3_lstm_predict(training, SETS_PER_BRAIN_V12, target_draw_no), "v12_lstm", ...))
    fresh.extend(v12_fusion_predict(training, target_draw_no, SETS_PER_BRAIN_V12))

    hyena_sets = _v12_hyena_predict(fresh, SETS_PER_BRAIN_V12, target_draw_no)
```

- hyena 입력 `fresh` = **동일 `target_draw_no`·동일 `training`에서 생성된 30세트** + hyena 5. ✅ 동일 회차 walk-forward.

### 3-C. hyena 합의 — 하위4 제외 (avg 격차 설명)

```45:48:D:\MONEY lol\My_Library\app\lotto3\v12_engine.py
_EXCLUDE_LOWER4_FROM_CONSENSUS: frozenset[str] = frozenset(
    {"v12_stat", "v12_run", "v12_offset", "v12_contrarian"}
)
```

```80:86:D:\MONEY lol\My_Library\app\lotto3\v12_engine.py
        w = float(weights.get(tag, 0.0))
        if tag in _EXCLUDE_LOWER4_FROM_CONSENSUS:
            w = 0.0
        if w <= 0.0:
            continue
```

→ **hyena avg 2.06은 stat/run/offset/contrarian(≈0.8)과 독립**. 합의는 **v12_lstm + v12_fusion** 위주.

### 3-D. `run_v12_chunk_backtest`

```496:498:D:\MONEY lol\My_Library\app\lotto3\v12_engine.py
    for n, draw_no in enumerate(range(start_draw, end_draw + 1), 1):
        try:
            r = run_prediction_v12(draw_no)
```

- 루프 내 **`training = df[draw_no < N]` 형태 직접 없음** — `run_prediction_v12` → `get_v12_training_draws(draw_no)` 위임.
- **LSTM/전역 상태 초기화 없음**.

### 3-E. 가중치 업데이트 (같은 회차 채점 후)

```400:401:D:\MONEY lol\My_Library\app\lotto3\v12_engine.py
        _score_v12_predictions(target_draw_no)
        update_v12_weights(target_draw_no)
```

```308:314:D:\MONEY lol\My_Library\app\lotto3\v12_models.py
            WHERE target_draw_no <= ? AND target_draw_no > ?
              AND matched_count >= 0
            (target_draw_no, target_draw_no - last_n, *V11_BRAINS),
```

- 회차 N 예측 **생성 시점**에는 DB 가중치 = N-1까지 반영. N 채점·가중치 갱신은 **저장 후**. ✅

### 3-F. 캐시 경로

```305:311:D:\MONEY lol\My_Library\app\lotto3\v12_engine.py
    if existing and len(existing) >= 40:
        return {"status": "cached", ...}
```

- 40행 이상 있으면 **재계산·재채점 없이 return**. 백테스트 2회차부터는 **1회차 결과 고정**. 무결성 재검증 시 **DELETE 또는 cached 분기 우회 필요** — 코드상 불명확(운영 절차 문제).

---

## 4. 모델 파일 타임스탬프 (실측)

| 파일 | Size | mtime | `last_trained_on` |
|------|------|-------|-------------------|
| `D:\MONEY lol\My_Library\models\lstm_lotto.pt` | 913,698 B | 2026-04-24 23:32 | **1219** |

- **회차마다 갱신되는 구조 아님** — `RETRAIN_INTERVAL`마다 `_save_checkpoint` (L235-240)이나, **파일 mtime이 4/24 고정** → 최근 chunk 백테스트가 디스크에 반영 안 됐거나, 로드-only 세션 가능.
- **코드상**: 백테스트 중 **매 draw 파일 touch 보장 없음**. in-memory `_MODEL`만 갱신될 수 있음.

---

## 5. lstm cnt 6055 vs 6080 (6075 vs 6100 실측)

**DB raw** (`lotto_predictions_army3`, `D:\MONEY lol\My_Library\data\lotto.db`):

| brain_tag | 행 수 (matched≥0) |
|-----------|------------------|
| v12_lstm | **6075** |
| v12_fusion | 6100 |
| v12_hyena | 6100 |
| v12_stat | 6100 |

- 차이 **25행** = **5회차 × 5세트**.
- **lstm 없는 회차 (fusion 대비)**: `[6, 7, 8, 9, 10]` (5회차).

**원인 (코드)**:

```27:28:D:\MONEY lol\My_Library\app\lotto3\predict_lstm.py
    if not miss_draws or len(miss_draws) < 10:
        return []
```

→ 초기 회차 `len(training)<10` 이면 lstm·hyena lstm 기여 **0**. **컨닝 아님**, 데이터 부족.

---

## 6. 종합 판정 — hyena avg 2.06 정당성

| 구분 | 판정 |
|------|------|
| training 슬라이스 (`draw_no < target`) | ✅ 준수 (`v12_models.py:93,98,111`) |
| fusion PMF 입력 | ✅ `training_draws` only (조건부) |
| hyena 합의 입력 | ✅ 동일 회차 fresh; stat~contrarian 합의 제외 |
| stat~contrarian avg≈0.8 | ✅ 단순 PMF/제약 — hyena 합의와 **분리** |
| lstm/fusion/hyena avg↑ | **△** 구조적으로 lstm+fusion 합의·가중·5005 전수 — **설계상 stat보다 높을 수 있음** |
| LSTM 체크포인트/전역 | ⚠️ **재백테스트·초기 회차 stale `.pt` 누수 의심** |
| Fusion entropy×cluster | ⚠️ API 불일치로 **no-op** (성능 부풀림 요인 아님) |
| 1군 fusion 회피 DB read | **코드상 불명확** (1군 무결성 별도 정찰 필요) |

### 결론 (R2 준수)

- **「단순 stat≈0.8 vs 복잡 hyena≈2.06」격차만으로 R4/R13 컨닝 확정 불가.**
- **코드상 확인된 누수 의심 1건**: LSTM **전역 모델 + `lstm_lotto.pt`(last_trained_on=1219) 재사용** 시, 초·중간 회차에 **미래 학습 가중치** 적용 가능.
- **avg 2.06 재검증 권고**: chunk 백테스트 전 **`lstm_lotto.pt` 삭제 + `_MODEL=None` 프로세스 신규** 후 1→1221 **순방향 단일 실행**, cached 분기 비활성.

---

## 7. 1~3군 간섭

| 항목 | 건수 |
|------|------|
| `app/lotto/` 수정 | 0 |
| `app/lotto2/` 수정 | 0 |
| `app/lotto3/` 수정 | 0 |
| `My_Library/app/lotto3/` 수정 | 0 |

---

## 8. STATUS / 기억

- 지시서: **「형 결정 후 STATUS·기억 저장」** → 본 정찰에서는 **갱신 안 함**.
