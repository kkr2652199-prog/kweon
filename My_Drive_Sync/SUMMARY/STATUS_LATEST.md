# STATUS_LATEST.md — kweon 현재 상태

📅 최종 갱신: 2026-07-11 KST (회차 정밀분석 Phase A — analysis_board API)

## 기본 정보
| 항목 | 값 |
|------|-----|
| 저장소 | kkr2652199-prog/kweon |
| 로컬 경로 | D:\3kweon |
| 앱 | 4군(v13) + 효도로또(보존) + **테스트로또(실험)** |
| 서버 | run_v13.py · 포트 **6124** |

## 테스트로또 — 최신 (2026-07-11)

### 인프라
| 항목 | 경로/값 |
|------|---------|
| 패키지 | app/testlotto/ |
| API | /api/testlotto/* |
| 독립 DB | data/lotto_testlotto.db (로컬, git 미포함) |
| UI | index.html 탭 + **testlotto-detail.html** |

### 7뇌
| 분류 | tag |
|------|-----|
| 예측 | stat · markov · review (각 5세트) |
| 보조 | miss_aux · pattern_aux · balance_aux · referee_aux |

### 복습 루프 — **완료**
- 2~1231 walk-forward: **reviewed 1230**, skipped 0
- 등수 우선 best: `tier_utils.py` + 보너스 채점
- API: `/walkforward/review`, `/progress`, `/detail/draw/{n}`

### 상세페이지
- **증거 보관소** (7뇌 short_desc · confidence · aux_brains)
- **오답노트** (번호별 tags · narrative · 예측vs실제)
- **회차 정밀분석 Phase A** — `analysis_board` API (`draw_snapshot.py`)
  - freq_grid 1~45 · 급등 · HOT/COLD · 6구간 · 쌍 · 보너스 프로필
  - num_explainer: 급등/HOT/6구간/핫쌍 태그 병합
  - UI 그리드(④)는 Phase B

### 탭↔상세 출처 — **단일화**
- 탭 1순위: `/api/testlotto/detail/draw/{n}` (brain_review)
- 미래 회차만 `lotto_predictions` 폴백

### 다음 (P0)
- Phase B: ④ 1~45 히트맵 UI + ②↔④ 연동
- aux_analysis_json 전 구간 일괄 백필 (선택)
- 판매점 SPA 파서 (pending 1098회)

### 데이터 현황
| 테이블 | 범위/건수 |
|--------|-----------|
| brain_review | 1230회 × 3뇌 |
| draw_features | 1231회 |
| draw_detail (archive) | **1231회** (gap 0) |
| prize_tiers (등수) | **1231회** (5등 포함) |
| win_stores (판매점) | **0회** — pending 1098 (SPA 미파싱) |
| lotto_predictions | 83회 불연속 (탭 폴백용) |

## 효도로또 — 보존
- app/hyodo/ · /api/hyodo/* · 테스트로또 검증 후 동기화

## 최신 보고서
- `reports/20260711_회차정밀분석_PhaseA.md`
- `reports/20260711_테스트로또_탭_출처단일화.md`
- `reports/20260711_4군_테스트로또_상세페이지_증거보관소_보고서.md`

## 관리 문서
| 파일 | 용도 |
|------|------|
| HYODO_PLAN.md | P1~P5 체크리스트 |
| STATUS_LATEST.md | 본 파일 |
