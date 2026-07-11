# STATUS_LATEST.md — kweon 현재 상태

📅 최종 갱신: 2026-07-11 KST (STEP2.5 현황 스냅샷)

## 기본 정보
| 항목 | 값 |
|------|-----|
| 저장소 | kkr2652199-prog/kweon |
| 로컬 경로 | D:\3kweon |
| 앱 | 4군(v13, army4) + **효도로또(1.5군) 탭 생성 완료** |
| 기억 체인 | kweon-기억1 (현재) |
| 서버 | run_v13.py · 포트 **6124** |

## 효도로또(1.5군) — 현황 스냅샷 (STEP2.5)

### 인프라
| 항목 | 경로/값 |
|------|---------|
| 패키지 | app/hyodo/ (23 .py, 순수 1군 복제 기반) |
| API | /api/hyodo/* |
| 독립 DB | data/lotto_hyodo.db |
| LSTM CKPT | models/lstm_hyodo.pt (P2에서 제거 예정) |
| 가중치 테이블 | hyodo_brain_weights |
| patterns DB | data/lotto_patterns_hyodo.db |
| UI 탭 | 4군 index.html → "효도로또" (4군 v13 army4와 공존) |
| 1군 원본 | D:\MONEY lol\My_Library\app\lotto (READ-ONLY, SHA 불변) |

### 4군앱 기존 자산 (효도로또 분석 활용 예정)
| 자산 | 기능 | 비고 |
|------|------|------|
| **로또조회** 탭 | 회차별 당첨번호 + 814만 순위 + 1등 당첨금 + 당첨자수 | DB 보유 (예: 1231회 = 3,412,808번째) |
| **전체조합** 탭 | 8,145,060 조합 역조회 (순위→번호, 번호→순위) + 합계 + 당첨여부 | data/combos/lotto_part_01~20.db |

### 효도로또 뇌 구성 (확정, 이름 추후 수정 가능)

**예측 3뇌**
| 코드명 | 한글명(안) | 역할 |
|--------|-----------|------|
| stat | 통계요정 | 빈도/끝수/이월수 |
| markov | 흐름술사 | 전이/궁합수 |
| (신규) | 복습왕 | 전회차 복습 학습형 |

**보조 2뇌**
| 코드명 | 한글명(안) | 역할 |
|--------|-----------|------|
| (신규) | 오답탐정 | 오답해부 피드백 |
| (신규) | 패턴돋보기 | 쌍수/연속수/AC값 신호 |

**제외 (P2에서 제거 예정)**
- lstm (누수)
- snake (2군 유래)
- missanalysis (유령)

> 상세 개발 단계: `HYODO_PLAN.md` P1~P5 참조

## 압축대비 스냅샷 (4군)

| 항목 | 경로 |
|------|------|
| 서버 진입점 | run_v13.py |
| FastAPI | app/main_v13.py |
| 4군 API | app/lotto4/v13_routes.py |
| 4군 DB | data/lotto4.db |
| 814만 조합 DB | data/combos/lotto_part_01.db ~ lotto_part_20.db |

## 현재 STEP
- **완료:** STEP2 효도로또 탭 신설 + STEP2.5 현황 스냅샷·PLAN 사전기록
- **다음:** HYODO_PLAN P1 백데이터 정리

## 4군 뇌 수 (R29)
- 7활성 + 2Hidden = 9뇌 (변경 없음)

## 관리 문서
| 파일 | 용도 |
|------|------|
| HYODO_PLAN.md | 효도로또 P1~P5 단계별 체크리스트 |
| NEXT_ACTIONS.md | 대기 작업 목록 |
| DECISION_LOG.md | 결정 근거 누적 |
