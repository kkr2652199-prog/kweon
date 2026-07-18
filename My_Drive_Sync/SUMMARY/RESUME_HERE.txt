# RESUME_HERE — 테스트로또 복원 앵커 (kweon)

> 매 작업 push 시 이 파일을 최신화한다. 압축 복원용 단일 진입점.

## 지금 어디까지

테스트로또(`app/testlotto/`)는 7뇌 UI·상세·아카이브·학습 파이프라인까지 구축된 상태이며, **예측 3뇌(통계요정·흐름술사·복습왕) + 보조 4뇌** 구조로 `brains/coordinator.py`가 조율한다. 배선 수정(학습 조정값 → 번호/확률 반영) 착수 **직전** — `20260718` 전체 백업(`backups/20260718_테스트뇌_배선전/`, SHA `fae01f67…`)과 본 RESUME_HERE를 신설했다. **다음**: 통계요정 `learn_state` 조정값 → 빈도(`freq`) 배선 (백업 후).

## 살아있는 진실 (헷갈림 방지)

- **실제 예측뇌** = `app/testlotto/brains/predict_stat_fairy.py`, `predict_flow_shaman.py`, `predict_review_king.py` — 옛 `predict_statistical.py` / `predict_markov.py`는 **내부 엔진**(래퍼가 호출).
- **테스트 뇌** = 예측 3(stat/markov/review) + 보조 4(aux_*).
- **배선 현황**: 복습왕=**연결됨** (`carry_boost` → 가중 샘플링) · 통계요정=**신뢰도만**(번호확률 미연결) · 흐름술사=**미연결** (동반쌍은 reasoning만).
- **R34**: 1~3군 = **memoy** (`D:\MONEY lol`) · 4군/테스트로또 = **kweon** (`d:\3kweon`).

## 다음 한 걸음

- **통계요정** `learn_state` 조정값 → `freq` / PMF 배선 (백업: `backups/20260718_테스트뇌_배선전/`).
