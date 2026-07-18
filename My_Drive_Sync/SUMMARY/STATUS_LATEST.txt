# STATUS_LATEST.md — kweon 현재 상태

📅 최종 갱신: 2026-07-18 KST (테스트로또 회차정밀분석 Phase A/B + UX — GitHub push 확인)

## 기본 정보
| 항목 | 값 |
|------|-----|
| 저장소 | kkr2652199-prog/kweon |
| 로컬 경로 | D:\3kweon |
| 앱 | 4군(v13) + 효도로또(보존) + **테스트로또(실험)** |
| 서버 | run_v13.py · 포트 **6124** |
| Git HEAD | `1406231` (origin/main 동기화) |

## 테스트로또 — 최신

### 인프라
| 항목 | 경로/값 |
|------|---------|
| 패키지 | app/testlotto/ |
| API | /api/testlotto/* |
| 독립 DB | data/lotto_testlotto.db (로컬, git 미포함) |
| UI | index.html 탭 + **testlotto-detail.html** (`?v=20260711r`) |

### 7뇌
| 분류 | tag |
|------|-----|
| 예측 | stat · markov · review (각 5세트) |
| 보조 | miss_aux · pattern_aux · balance_aux · referee_aux |

### 복습 루프 — **완료**
- 2~1231 walk-forward: **reviewed 1230**, skipped 0
- learn_state: stat/review 다음 예측 반영 · markov Phase C 예정

### 상세페이지 (2026-07-11~18)
- **증거 보관소** · **오답노트** · **학습 연결 안내**
- **Phase A** — `analysis_board` API (`draw_snapshot.py`)
- **Phase B** — ④ 1~45 히트맵 + ②↔④ 클릭 연동
- **UX** — 글자 크기 확대 (`20260711r`)

### 탭↔상세 — **단일화**
- 1순위 detail API (brain_review) · 미래만 predictions 폴백

### 다음 (P0)
- Phase C: detect_missed_patterns 확장 + markov learn_state
- Phase D: Before/After 튜닝 검증
- 판매점 SPA (pending 1098회)

### 데이터 현황
| 테이블 | 범위/건수 |
|--------|-----------|
| brain_review | 1230회 × 3뇌 |
| draw_features | 1231회 |
| draw_detail | **1231회** (gap 0) |
| prize_tiers | **1231회** |
| win_stores | **0회** |

## 효도로또 — 보존
- app/hyodo/ · 테스트로또 검증 후 동기화

## 최신 보고서
- `reports/20260718_테스트로또_회차정밀분석_세션푸시정리.md`
- `reports/20260711_회차정밀분석_PhaseB.md`
- `reports/20260711_회차정밀분석_PhaseA.md`

## 관리 문서
| 파일 | 용도 |
|------|------|
| HYODO_PLAN.md | P1~P5 체크리스트 |
| STATUS_LATEST.md | 본 파일 |
