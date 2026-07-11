#!/usr/bin/env python3
"""오답노트 API 검증."""
import json
import sqlite3
import urllib.request

DB = "data/lotto_testlotto.db"


def fetch_detail(draw: int) -> dict:
    url = f"http://127.0.0.1:6124/api/testlotto/detail/draw/{draw}"
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())


def main() -> None:
    print("=== 1231회 오답노트 ===")
    d = fetch_detail(1231)
    for b in d.get("brains", []):
        wn = b.get("wrong_note") or {}
        print(f"\n{b['brain_tag']}:")
        print(f"  narrative: {wn.get('narrative', '')}")
        for ex in wn.get("num_explains", [])[:3]:
            print(f"  num {ex['num']}: {ex.get('tags')}")
        print(f"  hit: {wn.get('hit_nums')} miss_actual: {wn.get('actual_missed_nums')}")

    c = sqlite3.connect(DB)
    hit = c.execute(
        """
        SELECT draw_no, brain_tag, matched_count
        FROM testlotto_brain_review
        WHERE matched_count >= 3
        ORDER BY matched_count DESC, draw_no DESC
        LIMIT 1
        """
    ).fetchone()
    c.close()
    if hit:
        draw, tag, mc = hit
        print(f"\n=== 적중 회차 {draw} ({tag} mc={mc}) ===")
        hd = fetch_detail(draw)
        brain = next((b for b in hd.get("brains", []) if b["brain_tag"] == tag), None)
        if brain:
            wn = brain.get("wrong_note") or {}
            print(f"  narrative: {wn.get('narrative', '')}")


if __name__ == "__main__":
    main()
