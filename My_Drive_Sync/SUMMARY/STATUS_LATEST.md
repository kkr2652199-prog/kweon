# STATUS_LATEST.md — kweon 현재 상태

📅 최종 갱신: 2026-07-11 KST (테스트로또 상세페이지·walk-forward 완료)

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
- 3뇌 판정 스트립 · 5등+ / 미적중 드롭다운 · brain_verdicts API
- 캐시 버전: `?v=20260711k`

### 데이터 현황
| 테이블 | 범위/건수 |
|--------|-----------|
| brain_review | 1230회 × 3뇌 |
| draw_features | 1231회 |
| draw_detail (archive) | **133회** (134~ 미완 — DB lock) |

### 다음 (P0)
```bash
python tools/run_testlotto_sync_archive.py --start 134 --end 1231 --no-stores
```

## 효도로또 — 보존
- app/hyodo/ · /api/hyodo/* · 테스트로또 검증 후 동기화

## 최신 보고서
- `reports/20260711_4군_테스트로또_상세페이지_7뇌_구현_보고서.md`

## 관리 문서
| 파일 | 용도 |
|------|------|
| HYODO_PLAN.md | P1~P5 체크리스트 |
| STATUS_LATEST.md | 본 파일 |
