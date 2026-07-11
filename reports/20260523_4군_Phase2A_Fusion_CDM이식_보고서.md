# 4군 Phase 2A — Fusion PMF + CDM 이식 보고서

- **날짜**: 2026-05-23
- **목적**: hyena consensus를 CDM+stat PMF Fusion으로 강화
- **범위**: `app/lotto4/brains/` (신규 2, 수정 2)
- **1~3군 간섭**: 0건

---

## STEP 0 — 확인 (첫 3줄)

**RULES_FIXED.md**: `# 🛡️ RULES_FIXED.md (불변 룰)`  
**STATUS_LATEST.md**: `# STATUS_LATEST (2026-05-19 기억77)` / `## 3군: 패치 A~J+M...`  
**CURSOR_RULES.md**: `# CURSOR_RULES.md — 커서 행동 강제 규칙` / `# 최종 갱신: 2026-05-16`

### SHA256 (변경 전)
| 파일 | SHA256 |
|------|--------|
| hyena_commander.py | 2c3c6c978b69a4f0973126c5bb95648ab9f2f81f699821968dfe6fbc0abffada |
| ensemble.py | 41eea023e66f67dc6399cc18fb61cbe81cc8cef9c01ccadc1d53074ae117d8d8 |
| stat_generator.py | 6fefacdaae34bc6c0ba5b1f9dd366678c706bf5e58d5fed93a5ab44bb027f6d6 |

---

## 1. 3군 원본 함수 분석 (READ-ONLY)

### predict_cdm.py
| 항목 | 내용 |
|------|------|
| **핵심 함수** | `army3_cdm_prob_vector(training_draws) → dict[int,float]`, `army3_cdm_predict(...) → list[dict]` |
| **로직 3줄** | Dirichlet α=1 + 출현 count → 사후 PMF / 최근 50회 2배 가중 / PMF 비복원 6개 샘플+tier1 |
| **DB** | 직접 쿼리 없음 — `training_draws` 인자 (v12_models.get_v12_training_draws) |
| **의존성** | app.lotto.filters.tier1_filter, v12_models win_avoid |

### v12_fusion_v5.py
| 항목 | 내용 |
|------|------|
| **핵심 함수** | `v12_fusion_v5_predict(training, target_draw, n_sets) → list[dict]` |
| **로직 3줄** | 4뇌 PMF(stat/markov/combo/lstm)×DB가중 합성 / entropy×cluster 곱 / Top-K Greedy 1 + random 4 |
| **합성 PMF** | v12_stat(CDM), v12_markov, v12_combo, v12_lstm |
| **가중치** | lotto_brain_weights_army3 동적 + fallback 고정 |

### predict_cooccur.py (Phase 2B 사전)
| 항목 | 내용 |
|------|------|
| **함수** | `army3_cooccur_predict`, 공동출현 그래프→커뮤니티 6개 표집 |
| **반환** | brain_tag=v12_run, 5세트 list[dict] |
| **의존성** | tier1_filter, v12_models |

---

## 2. 신규 파일

### stat_cdm_brain.py
전문: `app/lotto4/brains/stat_cdm_brain.py` (110행)

```python
class StatCDMBrain:
    def get_pmf(self, target_draw, db_path) -> dict[int, float]  # Dirichlet 사후
    def predict(self, target_draw, db_path, n_sets=5) -> list[list[int]]  # Top15→15C6
```

### fusion_brain.py
전문: `app/lotto4/brains/fusion_brain.py` (90행)

```python
class FusionBrain:
    def get_fused_pmf(self, pmf_list, weights) -> dict[int, float]  # 가중평균 정규화
    def predict(self, target_draw, db_path, pmf_list, weights, n_sets=5) -> list[list[int]]
```

---

## 3. 수정 파일 diff 요약

### stat_generator.py
- **추가**: `get_pmf(target_draw, db_path)` — 최근 100회 빈도 PMF

### hyena_commander.py
- **Phase 2A**: CDM PMF + stat PMF → Fusion(0.5/0.5) → `_pick_from_consensus`
- **보존**: `_legacy_freq_consensus()` (Phase 1 200세트 빈도)
- **fallback**: Fusion 실패 시 legacy

### ensemble.py
- **변경 없음** (hyena 위임 유지, SHA 동일)

---

## 4. 단위 테스트 8개

| # | 테스트 | 결과 |
|---|--------|------|
| 1 | StatCDMBrain.get_pmf(1200) — 45키, Σ≈1 | ✅ |
| 2 | StatCDMBrain.predict(1200) — 5세트, 필터 | ✅ |
| 3 | stat_generator.get_pmf(1200) — 45키, Σ≈1 | ✅ |
| 4 | FusionBrain.get_fused_pmf — 45키, Σ≈1 | ✅ |
| 5 | FusionBrain.predict — 5세트 | ✅ |
| 6 | hyena predict(1200) 결정론적 | ✅ |
| 7 | ensemble == hyena | ✅ |
| 8 | 소요 시간 | **0.11s** (< 5s) |

---

## 5. 미니 백테스트 (1100~1222, 496s)

| 뇌 | avg | 4+% | max |
|----|-----|-----|-----|
| **v13_ensemble** | **0.8098** | 0.16% | 4 |
| v13_struct | 0.8992 | 0.00% | 3 |
| v13_evolution | 0.8829 | 0.33% | 4 |
| v13_diversity | 0.8585 | 0.16% | 4 |
| v13_seq | 0.8211 | 0.16% | 4 |

---

## 6. 비교표

| 방식 | avg | 4+% | max | 판정 |
|------|-----|-----|-----|------|
| Random | 0.800 | — | — | 기준 |
| B안 ML필터 | 0.797 | 0.33% | 3 | ❌ |
| **Phase1 hyena** | **0.893** | 0.33% | 4 | ⚠️ 최고 |
| **Phase2A fusion+CDM** | **0.810** | 0.16% | 4 | ❌ **Phase1 대비 -0.083** |
| 목표 | >= 1.2 | — | — | ❌ 미달 |
| 3군 hyena 원본 | 2.076 | — | — | 참조 |

---

## 7. Phase1 → Phase2A 분석

**Phase 2A는 Phase 1 대비 성능 하락(-0.083).**

원인 추정:
1. **200세트 co-occurrence consensus 상실** — Phase 1은 필터 통과 조합 내 번호 동시출현 빈도, Phase 2A는 marginal PMF만 사용
2. **CDM+stat PMF가 과도하게 평탄** — Top-15 풀이 Phase 1과 달라져 15C6 최적 조합 품질 저하
3. **3군 Fusion V5 미구현 요소** — entropy×cluster, 4뇌 PMF, DB 동적 가중치, lstm PMF 부재
4. **equal 0.5/0.5** — CDM과 stat PMF가 유사해 다양성 기여 미미

---

## 8. 3군 대비 격차 + Phase 2B 계획

| 격차 요소 | Phase 2A | Phase 2B 제안 |
|----------|----------|---------------|
| PMF 소스 | CDM + stat (2개) | +cooccur, sumrange, constraint, lstm |
| consensus | marginal PMF | **하이브리드**: 200세트 빈도 + fused PMF 블렌드 |
| Fusion | 단순 가중평균 | entropy×cluster, Hedge 가중치 |
| 하위4 제외 | N/A | hyena consensus에서 하위 PMF 제외 |
| 목표 avg | 0.810 | 1.2+ (Phase1 0.893 회복 후 상향) |

**즉시 롤백 옵션**: hyena `_legacy_freq_consensus`를 primary로, fused PMF를 보조 가중(예: 0.7 freq + 0.3 fused) 블렌드.

---

## 9. SHA256 (변경 후)

| 파일 | SHA256 |
|------|--------|
| hyena_commander.py | 0ac3fc39be13774ccf4d0acc5cbceee865786667fc7aff34cd734956395c56f8 |
| ensemble.py | 41eea023e66f67dc6399cc18fb61cbe81cc8cef9c01ccadc1d53074ae117d8d8 (미변경) |
| stat_generator.py | b85fe41d78640a1dbe8df6e8d3d126eabcf0b0393ea04059174d2593820b230f |
| stat_cdm_brain.py (신규) | 3b4d7c3b842b4b44011cf68351bbd3e2272be23328c45c048fb44dd568f4b342 |
| fusion_brain.py (신규) | 85fa72d8483c4b9bbb0b5d7e986866e88455f07679c7eaf9f1bb9969145f5f9d |

---

## 10. 1~3군 간섭: 0건

---

## 현재 파이프라인

`CDM PMF + stat PMF → Fusion(0.5/0.5) → Top15 → 15C6 → 필터 → 5세트`  
fallback: Phase 1 `_legacy_freq_consensus`
