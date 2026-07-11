"""로또 데이터 수집·조회·통계 서비스 — app.hyodo 독립 패키지."""
import json
import logging
import re
import time
from collections import Counter
from datetime import date, timedelta
from itertools import combinations

import requests

from app.hyodo.models import get_lotto_db, init_lotto_db

logger = logging.getLogger(__name__)

DHLOTTERY_API = "https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={draw_no}"

# lotteryextreme displayball: `<li>6` / `<li class="dbx">` 등 한 자리·두 자리 추출
_RE_LOTTERYEXTREME_LI_NUM = re.compile(r"<li[^>]*>(\d{1,2})")

# 전체 수집(fetch_all) 백그라운드 완료 후, 프론트가 읽는 직전 결과(단일 스레드 기준)
_last_fetch_all_result: dict | None = None

# 1회차(2002-12-07 토) + 매주 토요일 (update_draw_dates.py·동일 규칙)
_LOTTO_FIRST_DRAW = date(2002, 12, 7)


def draw_date_for_draw_no(draw_no: int) -> str:
    """N회 추첨일(추정): 2002-12-07 + (N-1)*7일."""
    if draw_no < 1:
        return ""
    d = _LOTTO_FIRST_DRAW + timedelta(days=(draw_no - 1) * 7)
    return d.isoformat()


def get_collection_hint() -> dict:
    """DB·다음 회차·예정 추첨일(자동) 안내용."""
    init_lotto_db()
    conn = get_lotto_db()
    row = conn.execute("SELECT MAX(draw_no), MIN(draw_no), COUNT(*) FROM lotto_draws").fetchone()
    conn.close()
    if not row or not row[0]:
        nxt = 1
        return {
            "max_draw_no": 0,
            "min_draw_no": 0,
            "row_count": 0,
            "contiguous_1_to_max": False,
            "next_draw_no": nxt,
            "next_draw_date": draw_date_for_draw_no(nxt),
        }
    max_e, min_e, cnt = int(row[0]), int(row[1]), int(row[2])
    cont = min_e == 1 and cnt == max_e
    nxt = max_e + 1
    return {
        "max_draw_no": max_e,
        "min_draw_no": min_e,
        "row_count": cnt,
        "contiguous_1_to_max": cont,
        "next_draw_no": nxt,
        "next_draw_date": draw_date_for_draw_no(nxt),
    }


def get_last_fetch_all_result() -> dict | None:
    return _last_fetch_all_result


def _user_message_fetch_all(
    fetched: int,
    failed: int,
    tail_unavailable: int,
    no_gaps_1_to_max: bool,
    max_after: int,
) -> str:
    if fetched > 0:
        return f"신규 {fetched}회차가 저장되었습니다. (DB 최대 {max_after}회)"
    if failed > 0:
        return f"누락/오류로 API에서 받지 못한 구간이 {failed}회입니다. (네트워크·동행 API 응답 확인)"
    nxt = max_after + 1
    d = draw_date_for_draw_no(nxt)
    if no_gaps_1_to_max and tail_unavailable > 0:
        return (
            f"1~{max_after}회차는 이미 모두 있습니다. "
            f"다음 {nxt}회 예정일은 {d}(토)이며, 아직 추첨이 없을 수 있어(미추첨) "
            f"API에 당첨이 없는 것은 정상입니다. 추첨 이후 '최신 회차 수집'을 실행하세요."
        )
    return f"신규 저장 없음. (최대 {max_after}회, 연속 1~{max_after} 여부에 따라 수집 범위가 달라질 수 있음.)"


# ═══════════════════════════════════════════
# 1. 데이터 수집
# ═══════════════════════════════════════════

def _parse_lotteryextreme_displayball_ul(block: str) -> tuple[list[int], int] | None:
    """displayball ul 내부 HTML에서 메인 6개·보너스 1개를 추출한다."""
    dbx_idx = block.find("dbx")
    if dbx_idx >= 0:
        before = block[:dbx_idx]
        after = block[dbx_idx:]
        main_strs = _RE_LOTTERYEXTREME_LI_NUM.findall(before)
        bonus_strs = _RE_LOTTERYEXTREME_LI_NUM.findall(after)
        if len(main_strs) < 6 or not bonus_strs:
            return None
        main = [int(x) for x in main_strs[:6]]
        bonus = int(bonus_strs[0])
    else:
        li_nums = _RE_LOTTERYEXTREME_LI_NUM.findall(block)
        if len(li_nums) < 7:
            return None
        main = [int(x) for x in li_nums[:6]]
        bonus = int(li_nums[6])
    if len(main) != 6 or len(set(main)) != 6:
        return None
    if not all(1 <= n <= 45 for n in main) or not (1 <= bonus <= 45):
        return None
    return main, bonus


def _fallback_fetch_from_lotteryextreme(draw_no: int) -> dict | None:
    """동행복권 API 실패 시 lotteryextreme.com 목록 페이지에서 당첨번호를 가져온다."""
    try:
        url = "https://www.lotteryextreme.com/southkorea/lotto645/results"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        html = resp.text
        pattern = rf"\({int(draw_no)}\).*?<ul[^>]*displayball[^>]*>(.*?)</ul>"
        match = re.search(pattern, html, re.DOTALL)
        if not match:
            logger.warning("lotteryextreme에서 %d회차를 찾을 수 없음", draw_no)
            return None
        parsed = _parse_lotteryextreme_displayball_ul(match.group(1))
        if not parsed:
            logger.warning("lotteryextreme %d회차: displayball 파싱 실패", draw_no)
            return None
        main, bonus = parsed
        nums = sorted(main)
        logger.info("lotteryextreme fallback 성공: %d회차 %s + %d", draw_no, nums, bonus)
        return {
            "draw_no": int(draw_no),
            "draw_date": draw_date_for_draw_no(draw_no),
            "num1": nums[0],
            "num2": nums[1],
            "num3": nums[2],
            "num4": nums[3],
            "num5": nums[4],
            "num6": nums[5],
            "bonus": bonus,
            "total_sales": 0,
            "first_prize": 0,
            "first_winners": 0,
        }
    except Exception as e:
        logger.warning("lotteryextreme fallback 에러 (%d회): %s", draw_no, e)
    return None


def fetch_single_draw(draw_no: int) -> dict | None:
    """동행복권 API에서 특정 회차 당첨번호를 가져온다."""
    try:
        url = DHLOTTERY_API.format(draw_no=draw_no)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.dhlottery.co.kr/",
        }
        resp = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        resp.raise_for_status()

        # 동행복권은 Content-Type이 text/html이면서 본문은 JSON인 경우가 있음
        body = resp.text.strip()
        if not body.startswith("{"):
            logger.warning("로또 %d회차: JSON이 아닌 응답, fallback 시도", draw_no)
            return _fallback_fetch_from_lotteryextreme(draw_no)

        data = json.loads(body)
        if data.get("returnValue") != "success":
            return _fallback_fetch_from_lotteryextreme(draw_no)
        return {
            "draw_no": data["drwNo"],
            "draw_date": data["drwNoDate"],
            "num1": data["drwtNo1"],
            "num2": data["drwtNo2"],
            "num3": data["drwtNo3"],
            "num4": data["drwtNo4"],
            "num5": data["drwtNo5"],
            "num6": data["drwtNo6"],
            "bonus": data["bnusNo"],
            "total_sales": data.get("totSellamnt", 0),
            "first_prize": data.get("firstWinamnt", 0),
            "first_winners": data.get("firstPrzwnerCo", 0),
        }
    except Exception as e:
        logger.error("로또 %d회차 수집 에러: %s, fallback 시도", draw_no, e)
        return _fallback_fetch_from_lotteryextreme(draw_no)


def save_draw(draw: dict) -> bool:
    """회차 데이터를 lotto_hyodo.db에 저장한다 (중복이면 무시)."""
    conn = get_lotto_db()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO lotto_draws
               (draw_no, draw_date, num1, num2, num3, num4, num5, num6,
                bonus, total_sales, first_prize, first_winners)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                draw["draw_no"],
                draw["draw_date"],
                draw["num1"],
                draw["num2"],
                draw["num3"],
                draw["num4"],
                draw["num5"],
                draw["num6"],
                draw["bonus"],
                draw["total_sales"],
                draw["first_prize"],
                draw["first_winners"],
            ),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.warning("로또 저장 실패 %d회차: %s", draw["draw_no"], e)
        return False
    finally:
        conn.close()


# 1군 자동 예측 생성 대상 (6뇌 + lead1, miss/snake 제외)
_ARMY1_AUTO_SIX: tuple[str, ...] = ("stat", "markov", "llm", "lstm", "fusion", "hyena")
_ARMY1_MIN_SETS = 5


def _army1_brain_set_count(conn, draw_no: int, brain_tag: str) -> int:
    if brain_tag == "llm":
        row = conn.execute(
            "SELECT COUNT(*) FROM lotto_predictions WHERE target_draw_no=? "
            "AND brain_tag IN ('llm','llm_fallback')",
            (draw_no,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) FROM lotto_predictions WHERE target_draw_no=? AND brain_tag=?",
            (draw_no, brain_tag),
        ).fetchone()
    return int(row[0] or 0)


def _army1_predictions_ready(conn, draw_no: int) -> bool:
    """6뇌×5 + lead1×5 준비 여부."""
    for tag in _ARMY1_AUTO_SIX:
        if _army1_brain_set_count(conn, draw_no, tag) < _ARMY1_MIN_SETS:
            return False
    lead1 = conn.execute(
        "SELECT COUNT(*) FROM lotto_predictions WHERE target_draw_no=? AND brain_tag='lead1'",
        (draw_no,),
    ).fetchone()[0]
    return int(lead1 or 0) >= _ARMY1_MIN_SETS


def maybe_generate_army1_next_predictions(scored_draw_no: int) -> dict:
    """당첨 확정 회차 N 처리 후 N+1 1군 예측 자동 생성.

    - N회차 당첨 확정(num1) 필수
    - run_prediction(N+1): _get_draws_before(N+1) → 1~N만 사용 (컨닝 방지)
    - lead1: save_brain7_predictions (5뇌 READ-ONLY)
    - 멱등: 6뇌+lead1 이미 5세트씩 있으면 skip
    - 6뇌 예측 알고리즘 코드 변경 없음 (기존 run_prediction 호출만)
    """
    next_no = scored_draw_no + 1
    conn = get_lotto_db()
    try:
        row = conn.execute(
            "SELECT num1 FROM lotto_draws WHERE draw_no = ?", (scored_draw_no,),
        ).fetchone()
        if not row or row[0] is None:
            return {
                "generated": False,
                "reason": "scored_draw_not_confirmed",
                "scored_draw_no": scored_draw_no,
            }

        if _army1_predictions_ready(conn, next_no):
            return {
                "generated": False,
                "reason": "already_exists",
                "target_draw_no": next_no,
            }

        draws = _get_draws_before(next_no)
        if not draws:
            return {
                "generated": False,
                "reason": "no_prior_draws",
                "target_draw_no": next_no,
            }
        max_prior = max(d["draw_no"] for d in draws)
        if max_prior >= next_no:
            return {
                "generated": False,
                "reason": "contamination",
                "target_draw_no": next_no,
                "max_prior": max_prior,
            }
    finally:
        conn.close()

    from app.hyodo.engine import run_prediction
    from app.hyodo.predict_brain7 import save_brain7_predictions

    conn_pre = get_lotto_db()
    try:
        need_six = not all(
            _army1_brain_set_count(conn_pre, next_no, t) >= _ARMY1_MIN_SETS
            for t in _ARMY1_AUTO_SIX
        )
        lead1_cnt = int(conn_pre.execute(
            "SELECT COUNT(*) FROM lotto_predictions WHERE target_draw_no=? AND brain_tag='lead1'",
            (next_no,),
        ).fetchone()[0] or 0)
    finally:
        conn_pre.close()

    six_result: dict | str = "skipped_already_complete"
    if need_six:
        pred = run_prediction(next_no, brain_filter=_ARMY1_AUTO_SIX)
        if "error" in pred:
            return {
                "generated": False,
                "reason": pred["error"],
                "target_draw_no": next_no,
                "max_draw_no_data": max_prior,
            }
        six_result = {"total_sets": pred.get("total_sets"), "status": pred.get("status")}

    lead1_n = 0
    if lead1_cnt < _ARMY1_MIN_SETS:
        conn3 = get_lotto_db()
        try:
            lead1_n = save_brain7_predictions(conn3, next_no)
            conn3.commit()
        finally:
            conn3.close()

    logger.info(
        "[army1_auto] next predictions draw=%d (after scored=%d) six=%s lead1=%d max_data=%d",
        next_no, scored_draw_no, six_result, lead1_n, max_prior,
    )
    return {
        "generated": True,
        "scored_draw_no": scored_draw_no,
        "target_draw_no": next_no,
        "max_draw_no_data": max_prior,
        "six_brain": six_result,
        "lead1_sets": lead1_n if lead1_n else lead1_cnt,
    }


# 2군 V11 자동 예측 (7뇌×5 = 35세트, v11_*)
_ARMY2_MIN_V11_SETS = 35


def _army2_v11_set_count(conn, draw_no: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM lotto_predictions_army2 "
        "WHERE target_draw_no=? AND brain_tag LIKE 'v11_%'",
        (draw_no,),
    ).fetchone()
    return int(row[0] or 0)


def _army2_v11_predictions_ready(conn, draw_no: int) -> bool:
    return _army2_v11_set_count(conn, draw_no) >= _ARMY2_MIN_V11_SETS


def maybe_generate_army2_next_predictions(scored_draw_no: int) -> dict:
    """효도로또: 2·3군 미사용 — no-op."""
    return {"generated": False, "reason": "hyodo_army1_only", "scored_draw_no": scored_draw_no}



def _army3_v12_set_count(conn, draw_no: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM lotto_predictions_army3 "
        "WHERE target_draw_no=? AND brain_tag LIKE 'v12_%'",
        (draw_no,),
    ).fetchone()
    return int(row[0] or 0)


def _army3_v12_predictions_ready(conn, draw_no: int) -> bool:
    return _army3_v12_set_count(conn, draw_no) >= _ARMY3_MIN_V12_SETS


def maybe_generate_army3_next_predictions(scored_draw_no: int) -> dict:
    """효도로또: 2·3군 미사용 — no-op."""
    return {"generated": False, "reason": "hyodo_army1_only", "scored_draw_no": scored_draw_no}



def refresh_all_army_prediction_scores(target_draw_no: int) -> None:
    """효도로또 1군 단독: 당첨 확정 시 채점·가중치·N+1 예측."""
    from app.hyodo.engine import refresh_prediction_scores_for_target_draw
    from app.hyodo.feedback import maybe_update_brain_weights_after_scoring

    refresh_prediction_scores_for_target_draw(target_draw_no)
    maybe_update_brain_weights_after_scoring(target_draw_no)
    maybe_generate_army1_next_predictions(scored_draw_no=target_draw_no)
    from app.hyodo.postmortem_engine import maybe_build_postmortem_after_scoring

    maybe_build_postmortem_after_scoring(target_draw_no)



def backfill_unscored_army2_army3_predictions() -> dict:
    """효도로또: 2·3군 미사용 — no-op."""
    return {"army2": 0, "army3": 0, "skipped": True}



def fetch_all_draws(delay: float = 0.3) -> dict:
    """1회차부터 최신까지 전체 당첨번호를 수집한다.
    이미 DB에 있는 회차는 건너뛴다.
    """
    global _last_fetch_all_result
    _last_fetch_all_result = {"status": "running", "user_message": "로또 전체 수집 작업 중…"}

    init_lotto_db()
    conn = get_lotto_db()
    existing = {row[0] for row in conn.execute("SELECT draw_no FROM lotto_draws").fetchall()}
    conn.close()

    max_e = max(existing) if existing else 0
    # 1~max_e 연속 + max_e 충분히 큼(1100+)이면, max+1~+5 API 미응답은 '미개최'로만 집계(실패에서 제외)
    TAIL_WHEN_MAX_GE = 1100
    no_gaps_1_to_max = bool(
        existing
        and min(existing) == 1
        and len(existing) == max_e
        and max_e >= TAIL_WHEN_MAX_GE
    )

    draw_no = 1
    fetched = 0
    skipped = 0
    failed = 0
    tail_unavailable = 0  # max 이후(미개최·API 미응답) — '실패'로 보지 않음

    try:
        while True:
            if draw_no in existing:
                draw_no += 1
                skipped += 1
                continue

            draw = fetch_single_draw(draw_no)
            if draw is None:
                # max_e 이후 5회차만 탐색 후 종료(미공개/JSON 없음)
                if draw_no > max_e + 5:
                    break
                if no_gaps_1_to_max and draw_no > max_e:
                    tail_unavailable += 1
                else:
                    failed += 1
                draw_no += 1
                continue

            save_draw(draw)
            refresh_all_army_prediction_scores(draw["draw_no"])
            fetched += 1
            draw_no += 1

            if fetched % 50 == 0:
                logger.info("로또 수집 진행: %d회차까지 완료", draw_no - 1)

            time.sleep(delay)

        logger.info(
            "로또 수집 완료: 신규 %d건, 기존(스킵) %d건, 누락·API오류(실패) %d건, "
            "최신이후탐색(미개최/미응답) %d회",
            fetched,
            skipped,
            failed,
            tail_unavailable,
        )
        conn2 = get_lotto_db()
        max_row = conn2.execute("SELECT MAX(draw_no) FROM lotto_draws").fetchone()
        conn2.close()
        max_after = int(max_row[0]) if max_row and max_row[0] is not None else 0
        next_no = max_after + 1
        out: dict = {
            "fetched": fetched,
            "skipped": skipped,
            "failed": failed,
            "tail_unavailable": tail_unavailable,
            "total": fetched + skipped,
            "max_draw_no": max_after,
            "next_draw_no": next_no,
            "next_draw_date": draw_date_for_draw_no(next_no),
            "ok": True,
            "user_message": _user_message_fetch_all(
                fetched, failed, tail_unavailable, no_gaps_1_to_max, max_after
            ),
        }
        _last_fetch_all_result = out
        return out
    except Exception as e:
        logger.exception("fetch_all_draws 실패: %s", e)
        _last_fetch_all_result = {
            "ok": False,
            "user_message": f"전체 수집 중 오류: {e}",
        }
        raise


def fetch_latest_draw() -> dict | None:
    """DB에 없는 최신 1회차만 가져와 저장한다."""
    init_lotto_db()
    conn = get_lotto_db()
    row = conn.execute("SELECT MAX(draw_no) FROM lotto_draws").fetchone()
    conn.close()
    last = row[0] if row and row[0] else 0
    next_no = last + 1

    draw = fetch_single_draw(next_no)
    if draw:
        save_draw(draw)
        refresh_all_army_prediction_scores(draw["draw_no"])
        return draw
    return None


# ═══════════════════════════════════════════
# 2. 통계 분석
# ═══════════════════════════════════════════

def get_all_draws() -> list[dict]:
    """DB에서 전체 회차를 가져온다."""
    conn = get_lotto_db()
    rows = conn.execute("SELECT * FROM lotto_draws ORDER BY draw_no").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def analyze_number_frequency(draws: list[dict] | None = None) -> dict:
    """번호별 출현 빈도 분석."""
    if draws is None:
        draws = get_all_draws()

    counter = Counter()
    bonus_counter = Counter()
    for d in draws:
        nums = [d["num1"], d["num2"], d["num3"], d["num4"], d["num5"], d["num6"]]
        counter.update(nums)
        bonus_counter[d["bonus"]] += 1

    total = len(draws)
    result = {}
    for n in range(1, 46):
        result[n] = {
            "number": n,
            "count": counter.get(n, 0),
            "percentage": round(counter.get(n, 0) / max(total * 6, 1) * 100, 2),
            "bonus_count": bonus_counter.get(n, 0),
            "total_draws": total,
        }

    return result


def analyze_pair_frequency(draws: list[dict] | None = None, top_n: int = 30) -> list[dict]:
    """동반출현 번호 쌍 분석."""
    if draws is None:
        draws = get_all_draws()

    pair_counter = Counter()
    for d in draws:
        nums = sorted([d["num1"], d["num2"], d["num3"], d["num4"], d["num5"], d["num6"]])
        for pair in combinations(nums, 2):
            pair_counter[pair] += 1

    return [
        {"pair": list(pair), "count": count} for pair, count in pair_counter.most_common(top_n)
    ]


def analyze_range_distribution(draws: list[dict] | None = None) -> dict:
    """구간별 출현 분포 (1~10, 11~20, 21~30, 31~40, 41~45)."""
    if draws is None:
        draws = get_all_draws()

    ranges = {"1-10": 0, "11-20": 0, "21-30": 0, "31-40": 0, "41-45": 0}
    for d in draws:
        for n in [d["num1"], d["num2"], d["num3"], d["num4"], d["num5"], d["num6"]]:
            if n <= 10:
                ranges["1-10"] += 1
            elif n <= 20:
                ranges["11-20"] += 1
            elif n <= 30:
                ranges["21-30"] += 1
            elif n <= 40:
                ranges["31-40"] += 1
            else:
                ranges["41-45"] += 1
    return ranges


def analyze_odd_even(draws: list[dict] | None = None) -> dict:
    """홀짝 비율 분석."""
    if draws is None:
        draws = get_all_draws()

    patterns = Counter()
    for d in draws:
        nums = [d["num1"], d["num2"], d["num3"], d["num4"], d["num5"], d["num6"]]
        odd = sum(1 for n in nums if n % 2 == 1)
        even = 6 - odd
        patterns[f"홀{odd}짝{even}"] += 1

    return dict(patterns.most_common())


def analyze_sum_range(draws: list[dict] | None = None) -> dict:
    """당첨번호 합계 분석."""
    if draws is None:
        draws = get_all_draws()

    sums = []
    for d in draws:
        s = d["num1"] + d["num2"] + d["num3"] + d["num4"] + d["num5"] + d["num6"]
        sums.append({"draw_no": d["draw_no"], "sum": s})

    total_sums = [x["sum"] for x in sums]
    return {
        "data": sums,
        "average": round(sum(total_sums) / max(len(total_sums), 1), 1),
        "min": min(total_sums) if total_sums else 0,
        "max": max(total_sums) if total_sums else 0,
    }


def analyze_consecutive(draws: list[dict] | None = None) -> dict:
    """연속번호 출현 분석."""
    if draws is None:
        draws = get_all_draws()

    with_consecutive = 0
    for d in draws:
        nums = sorted([d["num1"], d["num2"], d["num3"], d["num4"], d["num5"], d["num6"]])
        for i in range(len(nums) - 1):
            if nums[i + 1] - nums[i] == 1:
                with_consecutive += 1
                break

    total = len(draws)
    return {
        "draws_with_consecutive": with_consecutive,
        "total_draws": total,
        "percentage": round(with_consecutive / max(total, 1) * 100, 1),
    }


def get_comprehensive_stats() -> dict:
    """전체 종합 통계를 반환한다."""
    draws = get_all_draws()
    if not draws:
        return {"error": "데이터 없음. 먼저 데이터를 수집하세요."}

    return {
        "total_draws": len(draws),
        "latest_draw": draws[-1]["draw_no"],
        "latest_date": draws[-1]["draw_date"],
        "frequency": analyze_number_frequency(draws),
        "pair_frequency": analyze_pair_frequency(draws),
        "range_distribution": analyze_range_distribution(draws),
        "odd_even": analyze_odd_even(draws),
        "sum_range": analyze_sum_range(draws),
        "consecutive": analyze_consecutive(draws),
    }


def _get_draws_before(target_draw_no: int) -> list[dict]:
    """컨닝 방지 핵심: target_draw_no 이전 회차만 반환."""
    conn = get_lotto_db()
    rows = conn.execute(
        "SELECT * FROM lotto_draws WHERE draw_no < ? ORDER BY draw_no",
        (target_draw_no,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
