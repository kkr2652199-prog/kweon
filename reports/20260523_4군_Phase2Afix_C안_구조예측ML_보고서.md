# 4군 Phase 2A-fix + C안 — 구조예측ML + 하이브리드 보고서

- **날짜**: 2026-05-23
- **목적**: Phase1 성능 복원(하이브리드) + 구조예측 ML + 3등 집중 전략
- **범위**: `app/lotto4/brains/` (신규 1, 수정 1)
- **1~3군 간섭**: 0건

---

## STEP 0 — 확인 (첫 3줄)

**RULES_FIXED.md**: `# 🛡️ RULES_FIXED.md (불변 룰)`  
**STATUS_LATEST.md**: `# STATUS_LATEST (2026-05-23 기억78)` / `## 3군: 패치 A~J+M...`  
**CURSOR_RULES.md**: `# CURSOR_RULES.md — 커서 행동 강제 규칙` / `# 최종 갱신: 2026-05-16`

### SHA256

| 파일 | 변경 전 | 변경 후 |
|------|---------|---------|
| hyena_commander.py | `0ac3fc39be13774ccf4d0acc5cbceee865786667fc7aff34cd734956395c56f8` | `75d3c76d4eb266cc8965506f1b0e3c468a26396f0dc78dbbf8a26604918a1d2cf` |
| ensemble.py | `41eea023e66f67dc6399cc18fb61cbe81cc8cef9c01ccadc1d53074ae117d8d8` | (동일) |
| stat_generator.py | `b85fe41d78640a1dbe8df6e8d3d126eabcf0b0393ea04059174d2593820b230f` | (동일) |
| stat_cdm_brain.py | `3b4d7c3b842b4b44011cf68351bbd3e2272be23328c45c048fb44dd568f4b342` | (동일) |
| fusion_brain.py | `85fa72d8483c4b9bbb0b5d7e986866e88455f07679c7eaf9f1bb9969145f5f9d` | (동일) |
| struct_predictor.py | (신규) | `2c7760ec8110346a1486d95904a64c78718056b2a0a08d9e0387eb54fe1abec8` |

---

## STEP 1 — 하이브리드 consensus 복원

Phase 2A 순수 Fusion(0.810) 대비 Phase 1 freq(0.893)가 우수 → **0.7 freq + 0.3 fused PMF** 하이브리드.

핵심 변경 (`hyena_commander.py`):

```python
def _build_hybrid_consensus(target_draw, db_path):
    freq = _normalize_scores(_build_freq_consensus(...))  # 200세트 빈도
    fused = _fused_pmf_consensus(...)                      # CDM+stat Fusion
    hybrid[n] = 0.7 * freq[n] + 0.3 * fused[n]
    return _normalize_scores(hybrid)
```

- Phase 2A 순수 Fusion: `_legacy_fusion_only()` 보존
- Phase 1 freq only: `_legacy_freq_consensus()` 보존

---

## STEP 2 — struct_predictor.py (구조예측 ML 뇌)

번호를 예측하지 않고 **7개 구조 변수**를 XGBoost multiclass로 예측.

| 변수 | 클래스 | 설명 |
|------|--------|------|
| sum_zone | A/B/C/D | 합계 80~120 / 121~150 / 151~180 / 181+ |
| odd_count | 0~6 | 홀수 개수 |
| high_count | 0~6 | 고번호(23~45) 개수 |
| consec_pairs | 0/1/2/3+ | 연번 쌍 수 |
| ac_zone | 0/1/2 | AC ≤6 / 7~8 / 9+ |
| tail_max_dup | 1/2/3+ | 끝수 최대 중복 |
| decade_spread | 1~5 | 십단위 분포 수 |

- 특성: 10회×7 + MA5/MA10 + delta = **91차원**
- 학습: walk-forward, 최근 500회, max_depth=3, n_estimators=50
- `predict_struct()` → 예측값 + 확률분포
- `get_struct_filter()` → combo별 0~1 점수 (7변수 확률 평균)

### 학습 데이터 클래스 분포 (draw 1222 기준, 500회)

| 변수 | 분포 |
|------|------|
| sum_zone | B 37.6%, A 28.2%, C 24.2%, D 10.0% |
| odd_count | 3: 31.4%, 4: 28.2%, 2: 21.0%, 5: 9.2% |
| high_count | 3: 31.6%, 4: 25.4%, 2: 23.4% |
| consec_pairs | 0: 48.2%, 1: 40.6%, 2: 9.8% |
| ac_zone | 1: 51.0%, 2: 33.2%, 0: 15.8% |
| tail_max_dup | 2: 69.2%, 1: 21.4%, 3: 9.4% |
| decade_spread | 4: 53.8%, 3: 30.4%, 5: 12.2% |

### struct_predictor.py 전체 코드

```python
# app/lotto4/brains/struct_predictor.py (309 lines)
# SHA256: 2c7760ec8110346a1486d95904a64c78718056b2a0a08d9e0387eb54fe1abec8
# → d:\3kweon\app\lotto4\brains\struct_predictor.py 참조
```

(전체 소스: `d:\3kweon\app\lotto4\brains\struct_predictor.py`)

---

## STEP 3 — hyena 통합

```
consensus = hybrid(0.7freq + 0.3fusion)
→ StructPredictor.train + get_struct_filter
→ Top15 → 15C6 전수
→ final = consensus_score × (1 + 0.5 × struct_bonus)
→ _select_top5_concentrated (Jaccard 0.6 → 0.8)
```

---

## STEP 4 — 단위 테스트 (9/9 PASS)

| # | 테스트 | 결과 |
|---|--------|------|
| 1 | StructPredictor.train(1200) → 7모델 | PASS |
| 2 | predict_struct → 7변수 + 확률분포 | PASS |
| 3 | get_struct_filter → 0~1 float | PASS (0.257) |
| 4 | hyena.predict(1200) → 5세트 | PASS (0.69s) |
| 5 | 결정론적 (2회 동일) | PASS |
| 6 | 5세트 Jaccard ≤ 0.6 (집중) | PASS (max 0.5) |
| 7 | 5세트 struct_score 기록 | PASS (0.42~0.49) |
| 8 | ensemble == hyena | PASS |
| 9 | 단일 호출 < 10s | PASS (0.69s) |

**draw 1200 구조 비교**

| 변수 | 실제 | 예측 | 적중 |
|------|------|------|------|
| sum_zone | A | B | ✗ |
| odd_count | 1 | 4 | ✗ |
| high_count | 1 | 3 | ✗ |
| consec_pairs | 1 | 0 | ✗ |
| ac_zone | 1 | 1 | ✓ |
| tail_max_dup | 2 | 2 | ✓ |
| decade_spread | 3 | 4 | ✗ |

적중 2/7 (28.6%)

---

## STEP 5 — 미니 백테스트 (1100~1222, 497s)

```powershell
python tools/reset_fullback_army4_db.py
python -u tools/full_backtest_v13.py --start 1100 --end 1222 --force --log-file reports/miniback_phase2afix_c_1100to1222.log
python tools/analyze_fullbacktest.py --from 1100 --to 1222
```

### 비교표

| 방식 | avg | 4+회 비율 | max | 판정 |
|------|-----|-----------|-----|------|
| Random | 0.800 | ~0.1% | — | 기준 |
| B안 ML필터 | 0.797 | 0.33% | 3 | ❌ |
| Phase1 hyena | 0.893 | 0.33% | 4 | 이전 최고 |
| Phase2A fusion | 0.810 | 0.16% | 4 | ❌ 후퇴 |
| **Phase2A-fix+C** | **0.862** | **0.16%** | **4** | ❌ 목표 미달 |
| 3군 hyena | 2.076 | — | — | 참조 |

- **목표**: avg ≥ 1.0, 4+ ≥ 2% → **미달**
- Phase2A 대비 **+0.052** 개선, Phase1 대비 **-0.031** 미복원

### v13_ensemble 상세

| avg | 분포(0/1/2/3/4/5/6) | 4+% | max |
|-----|---------------------|-----|-----|
| 0.8618 | 236/256/96/26/1/0/0 | 0.16% | 4 |

### 구조 예측 적중률 (1100~1222, n=123)

| 변수 | 정확도 |
|------|--------|
| sum_zone | 30.9% |
| odd_count | 21.1% |
| high_count | 27.6% |
| consec_pairs | 48.0% |
| ac_zone | 47.2% |
| tail_max_dup | 65.0% |
| decade_spread | 45.5% |

### 4+ 적중 회차

| 회차 | max 적중 | 당첨번호 | 구조 예측 일치 |
|------|----------|----------|----------------|
| 1134 | 4 | 3,7,9,13,19,24 | 2/7 (consec_pairs, tail_max_dup) |

- set1: `3,7,13,19,34,44` → 4적중 (9→34 miss)
- 5세트 모두 3~4적중 (집중 전략 효과: 동일 코어 3,7,13)

### 5세트 평균 Jaccard (집중도)

- **0.438** (Phase1 Jaccard 0.4 대비 완화 → 집중 배팅 성공)

---

## Phase1 → Phase2A-fix+C 분석

| 항목 | Phase1 | Phase2A | Phase2A-fix+C | 변화 |
|------|--------|---------|---------------|------|
| consensus | 200세트 freq | pure Fusion PMF | 0.7freq+0.3fusion | 하이브리드 복원 |
| 구조 ML | 없음 | 없음 | XGBoost 7변수 | 신규 |
| 선택 | Jaccard 0.4 | Jaccard 0.4 | Jaccard 0.6~0.8 | 집중 완화 |
| avg | 0.893 | 0.810 | 0.862 | +0.052 vs 2A |
| 4+% | 0.33% | 0.16% | 0.16% | 동일 |

**결론**:
1. 하이브리드로 Phase2A 회귀는 일부 복구(+0.052)했으나 Phase1(0.893) 미달
2. 구조예측 ML 단독 정확도 21~65% — struct_bonus가 consensus 방향을 왜곡할 가능성
3. 3등 집중(Jaccard 0.6)은 1134회차에서 4적중 1건 달성, 그러나 4+% 목표(2%) 미달
4. XGBoost 매 회차 학습으로 백테스트 497s (Phase2A 496s와 유사)

---

## 1~3군 간섭: 0건

- 수정: `app/lotto4/brains/hyena_commander.py`, `struct_predictor.py` (신규)
- `app/lotto/`, `lotto2/`, `lotto3/`, `My_Library/` 미수정

---

## 체크리스트

- [x] 보고서 저장 (`d:\3kweon\reports\`)
- [x] STATUS_LATEST 갱신 (기억79)
- [x] 기억79 저장
- [x] Drive 복사 (`커서보고서\`)
- [x] 1~3군 간섭 0건
