#!/usr/bin/env python3
"""탭↔상세 출처 일치 검증 — detail API vs 변환 로직."""
import json
import urllib.request


def detail_to_rows(detail: dict, draw_no: int) -> list[dict]:
    actual = detail.get("actual_nums") or []
    bonus = detail.get("bonus")
    rows = []
    for brain in detail.get("brains") or []:
        for s in brain.get("predicted_sets") or []:
            nums = s.get("nums") or []
            if len(nums) < 6:
                continue
            rows.append(
                {
                    "brain_tag": brain["brain_tag"],
                    "set_no": s.get("set_no"),
                    "nums": nums,
                    "matched_count": s.get("matched_count"),
                    "bonus_matched": s.get("bonus_matched"),
                    "confidence": s.get("confidence"),
                }
            )
    return rows


def main() -> None:
    for draw in [500, 1200, 1231]:
        detail = json.loads(
            urllib.request.urlopen(
                f"http://127.0.0.1:6124/api/testlotto/detail/draw/{draw}"
            ).read()
        )
        rows = detail_to_rows(detail, draw)
        print(f"\n=== {draw}회 (brain_review) ===")
        print(f"  brains: {len(detail.get('brains') or [])}, sets: {len(rows)}")
        for tag in ("stat", "markov", "review"):
            tag_rows = [r for r in rows if r["brain_tag"] == tag]
            print(f"  {tag}: {len(tag_rows)} sets")
            if tag_rows:
                best = max(tag_rows, key=lambda x: x.get("matched_count") or 0)
                print(
                    f"    best match: set{best['set_no']} "
                    f"mc={best['matched_count']} conf={best.get('confidence')}"
                )

    # 1232 future — detail error, predictions fallback
    d1232 = json.loads(
        urllib.request.urlopen("http://127.0.0.1:6124/api/testlotto/detail/draw/1232").read()
    )
    p1232 = json.loads(
        urllib.request.urlopen(
            "http://127.0.0.1:6124/api/testlotto/predictions/draw/1232"
        ).read()
    )
    print("\n=== 1232회 (미래) ===")
    print(f"  detail error: {d1232.get('error')}")
    print(f"  lotto_predictions fallback: {len(p1232.get('predictions') or [])} rows")


if __name__ == "__main__":
    main()
