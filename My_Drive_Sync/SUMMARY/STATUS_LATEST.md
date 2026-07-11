# STATUS_LATEST.md — kweon 현재 상태

📅 최종 갱신: 2026-07-11 KST

## 기본 정보
| 항목 | 값 |
|------|-----|
| 저장소 | kkr2652199-prog/kweon |
| 로컬 경로 | D:\3kweon |
| 앱 | 4군(v13) + 효도로또(1.5군) 예정 |
| 기억 체인 | kweon-기억1 (현재) |

## 압축대비 스냅샷 (2026-07-11)

### 진입점
| 항목 | 경로 |
|------|------|
| 서버 진입점 | run_v13.py |
| FastAPI 앱 | app/main_v13.py |
| API 라우트 | app/lotto4/v13_routes.py |
| UI | app/static/ (index.html, js/lotto4.js, css/lotto4.css) |

### 4군 뇌 파일 (app/lotto4/brains/)
| 뇌 | 파일 |
|----|------|
| seq | seq_brain.py |
| struct | struct_brain.py, struct_predictor.py |
| gap | gap_brain.py |
| diversity | diversity_brain.py |
| ev | ev_brain.py |
| evolution | evolution_brain.py |
| ensemble | ensemble.py, ensemble_backup_v5b.py |
| Hidden | cdm_brain.py, cond_prob_brain.py, stat_cdm_brain.py |
| 기타 | cooccur_brain.py, cooccur_brain_v13.py, constraint_brain.py, coordinator_brain.py, fusion_brain.py, hyena_commander.py, hyena_coordinator_v13.py, hyena_scavenger.py, popularity_freq_brain.py, popularity_pair_brain.py, shape_brain.py, stat_generator.py, sumrange_brain.py, anti_popular.py, bayesian.py, contrarian_v2.py, generator.py, graph.py, rl_agent.py, trend.py, transformer.py, _utils.py, __init__.py |

### DB 위치
| DB | 경로 |
|----|------|
| 메인 | data/lotto4.db |
| 1군(참조) | data/lotto.db |
| 814만 조합(20분할) | data/combos/lotto_part_01.db ~ lotto_part_20.db |

## 현재 STEP
- **완료:** 관리구조 이식 STEP1 (My_Drive_Sync/SUMMARY 5파일 + 경로지도·효도로또 원칙 박제)
- **다음:** 효도로또(1.5군) 탭 신설

## 4군 뇌 수 (R29)
- 7활성(seq, struct, gap, diversity, ev, evolution, ensemble) + 2Hidden(cdm, cond_prob) = 9뇌
