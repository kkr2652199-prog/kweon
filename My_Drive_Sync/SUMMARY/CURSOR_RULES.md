# CURSOR_RULES.md — 커서 행동 강제 규칙
# 최종 갱신: 2026-07-18 (push 검증·RESUME_HERE 반영)
# 이 파일은 READ-ONLY. 형(사용자)만 수정 가능.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 0. 최우선 원칙
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

커서는 코드를 작성하는 도구이다.
커서는 스스로 판단하지 않는다.
커서는 지시서에 없는 작업을 하지 않는다.
커서는 "알아서" 하지 않는다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 1. 매 작업 시작 시 필수 읽기 (R28 강제)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

모든 작업 시작 전 아래 3파일을 읽고 첫 줄에 확인 출력:

 파일 1: D:\3kweon\My_Drive_Sync\SUMMARY\RULES_FIXED.md
 파일 2: D:\3kweon\My_Drive_Sync\SUMMARY\STATUS_LATEST.md
 파일 3: D:\3kweon\My_Drive_Sync\SUMMARY\CURSOR_RULES.md

출력 형식:
 ✅ RULES_FIXED.md 확인 (R1~R33)
 ✅ STATUS_LATEST.md 확인 (기억XX, 4군 현황: ...)
 ✅ CURSOR_RULES.md 확인

이 3줄이 없으면 작업을 시작하지 않는다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 2. 절대 수정 금지 영역
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

아래 폴더/파일은 어떤 이유로도 수정하지 않는다:

 ❌ app/lotto/ (1군 — memoy 관할, kweon 내 READ-ONLY)
 ❌ app/lotto2/ (2군 — memoy 관할, kweon 내 READ-ONLY)
 ❌ RULES_FIXED.md (형만 수정)
 ❌ CURSOR_RULES.md (형만 수정)

memoy(1·2·3군) 앱 원본: D:\MONEY lol — 절대 미접촉.

위반 시: 즉시 작업 중단, 보고서에 "⛔ 금지영역 접근 시도" 기록.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 3. 작업 완료 시 필수 저장 체크리스트
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

모든 작업/정찰/백테스트 완료 후 아래를 반드시 수행:

### 3-1. 보고서 저장 (R7)
 경로: d:\3kweon\reports\YYYYMMDD_4군_{작업명}_보고서.md
 필수 포함:
 - SHA256 비교 (변경 전 vs 후)
 - 성적표 (해당 시)
 - 변경 파일 목록
 - 1~3군 간섭 여부 (반드시 "0건" 확인)

### 3-2. STATUS_LATEST.md 갱신 (R10)
 경로: D:\3kweon\My_Drive_Sync\SUMMARY\STATUS_LATEST.md
 갱신 항목:
 - 기억 번호 업데이트
 - 4군 현재 단계/상태
 - 최신 백테스트 점수 (해당 시)
 - 다음 작업 예고

### 3-3. 기억 파일 저장 (R18/R25)
 경로: D:\3kweon\My_Drive_Sync\동생기억\YYYYMMDD_기억{N}_v1.md
 필수 포함:
 - 이전 기억 번호 (체인 연결)
 - 작업 요약 1줄
 - 변경된 파일/DB 요약
 - 다음 작업

### 3-4. Drive 보고서 복사 (R8)
 경로: D:\3kweon\My_Drive_Sync\커서보고서\{보고서파일명}

### 3-5. git push + 원격 재확인 (R34 kweon만)
 `git add` → `commit` → **`push origin main` (kweon)** — memoy push 금지.
 push 후 **원격에서 파일 존재·커밋 SHA 대조**까지 해야 "완료":
 - `git rev-parse HEAD` 로컬 SHA
 - `git ls-remote origin refs/heads/main` 원격 SHA 일치 확인
 - (선택) `git show origin/main:My_Drive_Sync/SUMMARY/RESUME_HERE.md` 원격 파일 존재 확인

### 3-6. RESUME_HERE.md 갱신 (매 push 동반)
 경로: `D:\3kweon\My_Drive_Sync\SUMMARY\RESUME_HERE.md` (+ 동일 `.txt`)
 3섹션 고정: **지금 어디까지** / **살아있는 진실** / **다음 한 걸음**
 push할 때마다 "지금 어디까지"·"다음 한 걸음"을 최신화.

### 3-7. 완료 확인 출력
 작업 마지막에 아래 체크리스트 출력:

 📋 저장 체크리스트:
 [ ] 보고서 저장 → d:\3kweon\reports\...
 [ ] STATUS_LATEST 갱신 → 기억{N}, 상태: ...
 [ ] 기억 파일 저장 → 기억{N}_v1.md
 [ ] Drive 복사 완료 → 커서보고서\...
 [ ] RESUME_HERE.md 갱신 + .txt
 [ ] push origin main (kweon) + 원격 SHA 대조
 [ ] 1~3군 간섭: 0건

 모든 항목 [✅] 확인 후에만 "작업 완료" 선언.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 4. 보고서 형식 규칙
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 - 8000자 이내 (R22). 초과 시 _1, _2로 분할.
 - 코드블록 1개에 언어 태그 필수 (R20)
 - 마크다운 형식 (R24)
 - 거짓 금지: 실행하지 않은 결과를 "완료"라 쓰지 않는다.
 - "TBD", "예정", "placeholder" 금지 — 빈칸이면 빈칸이라 쓴다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 5. 백테스트/DB 규칙
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 - 커닝 금지: predict(N)은 draw_no < N 데이터만 사용 (R13)
 - DB 초기화 후 반드시 COUNT(*) = 0 검증 출력
 - skip 발생 시 로그에 명시 + 원인 기록
 - 풀 백테스트 완료 = 모든 회차 OK, skip 0건

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 6. 4군 뇌 체계 (현행)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 총 9뇌 = 7활성 + 2Hidden

 [Ace - 번호 생성]
 v13_seq : LSTM(45→128→64) + Attention + Sigmoid
 v13_struct : XGBoost 7모델 (구조변수 예측)

 [RiskScore - 후보 평가]
 v13_gap : Z-score 갭 분석
 v13_diversity: Jaccard + 십단위 커버리지
 v13_ev : 인기도 역수 기대값

 [Meta - 감독]
 v13_evolution: Ace 2뇌 동적 가중치 (seq, struct만)

 [Commander]
 v13_ensemble : 18C6 전수평가, FINAL = 0.30·cons + 0.30·struct
 + 0.10·gap + 0.20·div + 0.10·ev

 [Hidden - 미호출]
 v13_cdm, v13_cond_prob

 뇌 수 변경 시: 반드시 "4군 뇌 수 변경 선언" + STATUS 갱신

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 7. 폴더 구조 (저장 위치)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 d:\3kweon\
 ├── app/lotto4/brains/ ← 4군 뇌 코드
 ├── app/lotto4/ ← 엔진, 라우트
 ├── app/static/ ← UI (js/css/html)
 ├── tools/ ← 백테스트, 분석 스크립트
 ├── reports/ ← 보고서 저장
 ├── data/lotto4.db ← DB
 └── run_v13.py ← 서버 진입점

 D:\3kweon\My_Drive_Sync\
 ├── SUMMARY/
 │ ├── RESUME_HERE.md ← **복원 앵커 (매 push 최신화, 3섹션 고정)**
 │ ├── README_START.md ← 복원 진입점(레거시)
 │ ├── RULES_FIXED.md ← 마스터 룰 (READ-ONLY)
 │ ├── STATUS_LATEST.md ← 현황 (매 작업 후 갱신)
 │ ├── NEXT_ACTIONS.md ← 대기 작업
 │ ├── DECISION_LOG.md ← 결정 근거
 │ └── CURSOR_RULES.md ← 커서 행동 규칙 (READ-ONLY)
 ├── 동생기억/ ← 기억N_v1.md 파일
 └── 커서보고서/ ← 보고서 Drive 복사본

 D:\MONEY lol\ ← memoy(1·2·3군) 원본 — kweon 작업 시 미접촉

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 8. 저장소·경로 지도 (혼동 방지, 20260711 박제)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 memoy 저장소 = 1·2·3군 앱 = 로컬 D:\MONEY lol
 kweon 저장소 = 4군 앱 + 효도로또(1.5군) = 로컬 D:\3kweon
 1·2·3군은 memoy에서만, 4군·효도로또는 kweon에서만 작업

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 9. 효도로또(1.5군) 원칙 (20260711)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 목적: 적중률 향상 아님 → 학습형 통계 엔진 실험 + 시스템 정직성 완성
 1군(memoy) 절대 미접촉. 효도로또는 4군앱 복사본(app/hyodo)에서 독립 진화
 LSTM 누수·50회차 재학습 구조 수정은 효도로또에서만 실험 후 검증

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 10. 위반 시 처리
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 - 금지영역 수정 → 즉시 중단 + 롤백
 - 보고서 미저장 → 작업 완료 불인정
 - STATUS 미갱신 → 작업 완료 불인정
 - 기억 미저장 → 작업 완료 불인정
 - push 미수행·원격 SHA 미대조 → 작업 완료 불인정
 - RESUME_HERE 미갱신 → 작업 완료 불인정
 - 위 항목 중 하나라도 빠지면 "⛔ 불완전 작업" 표시

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 11. push 검증 절차 (20260718 박제)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 1. `git status` — memoy·1~3군 파일 staged 여부 확인 (있으면 unstage)
 2. `git add` (해당 작업 파일만)
 3. `git commit -m "…"`
 4. `git push origin main`
 5. `git fetch origin && git rev-parse HEAD && git rev-parse origin/main` — SHA 일치
 6. 원격 경로 spot-check: `RESUME_HERE.md`, 백업 README 등 이번 커밋 산출물
 7. 완료 보고에 **로컬 SHA·원격 SHA·백업 경로** 명시
