# STATUS_LATEST.md — kweon 현재 상태

📅 최종 갱신: 2026-07-11 KST (STEP2 완료)

## 기본 정보
| 항목 | 값 |
|------|-----|
| 저장소 | kkr2652199-prog/kweon |
| 로컬 경로 | D:\3kweon |
| 앱 | 4군(v13) + **효도로또(1.5군) 신설 완료** |
| 기억 체인 | kweon-기억1 (현재) |

## 효도로또(1.5군) — app/hyodo

| 항목 | 경로/값 |
|------|---------|
| 패키지 | app/hyodo/ (23 .py, 순수 1군 복제) |
| API | /api/hyodo/* |
| DB | data/lotto_hyodo.db |
| LSTM CKPT | models/lstm_hyodo.pt |
| 가중치 테이블 | hyodo_brain_weights |
| patterns DB | data/lotto_patterns_hyodo.db |
| UI 탭 | 4군 index.html → "효도로또" |
| 1군 원본 | D:\MONEY lol\My_Library\app\lotto (READ-ONLY, SHA 불변) |

## 압축대비 스냅샷 (4군)

| 항목 | 경로 |
|------|------|
| 서버 진입점 | run_v13.py |
| FastAPI | app/main_v13.py |
| 4군 API | app/lotto4/v13_routes.py |
| 4군 DB | data/lotto4.db |

## 현재 STEP
- **완료:** STEP2 효도로또 순수 1군 복제 + app/hyodo 격리 신설
- **다음:** STEP3 LSTM 누수 수정(회차별 walk-forward) 효도로또 실험

## 4군 뇌 수 (R29)
- 7활성 + 2Hidden = 9뇌 (변경 없음)
