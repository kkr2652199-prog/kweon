# 테스트뇌 배선 수정 전 스냅샷

- **백업 시각**: 2026-07-18 (KST)
- **백업 시점 git SHA (kweon)**: `fae01f67272d804c82ff65e4f82d62c4ec091bd3`
- **목적**: 통계요정·흐름술사·복습왕 `learn_state` 배선 수정 착수 전 안전망

## 코드 백업

| 항목 | 값 |
|------|-----|
| 원본 | `d:\3kweon\app\testlotto\` |
| 백업 | `backups/20260718_테스트뇌_배선전/app_testlotto/` |
| 파일 수 | **47** (.py, `__pycache__` 제외) |

### 배선 대상 핵심 파일 (반드시 포함 확인 ✅)

| 파일 | 백업 경로 |
|------|-----------|
| `brains/predict_stat_fairy.py` | `app_testlotto/brains/predict_stat_fairy.py` |
| `brains/predict_flow_shaman.py` | `app_testlotto/brains/predict_flow_shaman.py` |
| `brains/predict_review_king.py` | `app_testlotto/brains/predict_review_king.py` |
| `learn_state.py` | `app_testlotto/learn_state.py` |
| `brains/coordinator.py` | `app_testlotto/brains/coordinator.py` |
| `predict_statistical.py` | `app_testlotto/predict_statistical.py` |
| `predict_markov.py` | `app_testlotto/predict_markov.py` |

## DB 백업

| 파일 | 크기 | 주요 테이블·행수 |
|------|------|------------------|
| `data/lotto_testlotto.db` | **37,974,016 B** (~36.2 MiB) | `lotto_draws` **1,231** · `lotto_predictions` **1,245** · `testlotto_brain_page` **3,689** · `testlotto_brain_review` **3,689** · `testlotto_brain_learn_state` **3** · `testlotto_draw_features` **1,231** · `testlotto_draw_prize_tiers` **6,155** |
| `data/lotto_patterns_testlotto.db` | **미존재** (백업 시점) | 코드상 경로만 정의 (`pattern_store.py`) |

스냅샷: SQLite READ-ONLY 조회 (`mode=ro`). WAL sidecar(`-shm`/`-wal`)는 백업본에서 제외.

## 복원 방법 (3줄)

1. `app/testlotto/` 전체를 `app_testlotto/` 백업으로 덮어쓰기 (또는 git checkout 해당 커밋의 `app/testlotto/`).
2. `data/lotto_testlotto.db`를 `data/lotto_testlotto.db`로 복사 (기존 파일 rename 후 교체 권장).
3. 서버 재시작 후 `RESUME_HERE.md`의 백업 SHA(`fae01f67…`)와 파일 목록 대조.

## 관련 앵커

- 복원 진입점: `My_Drive_Sync/SUMMARY/RESUME_HERE.md`
- 커밋 메시지: `20260718 [테스트로또] 배선전 전체백업 + RESUME_HERE 복원앵커 신설`
