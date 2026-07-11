#!/usr/bin/env python3
"""상세페이지 7뇌·보조뇌 API 검증."""
import json
import urllib.request

DRAWS = [500, 1000, 1231]


def fetch(draw_no: int) -> dict:
    url = f"http://127.0.0.1:6124/api/testlotto/detail/draw/{draw_no}"
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())


def main() -> None:
    for d in DRAWS:
        j = fetch(d)
        print(f"\n=== {d}회 ===")
        verdicts = j.get("brain_verdicts") or []
        for v in verdicts:
            print(
                f"  [{v.get('brain_tag')}] short_desc={bool(v.get('short_desc'))} "
                f"conf_summary={bool(v.get('confidence_summary'))} "
                f"best={v.get('best_set_no')} conf_set={v.get('most_confident_set_no')}"
            )
        aux = j.get("aux_brains") or []
        print(f"  aux_brains: {len(aux)}")
        for a in aux:
            print(f"    {a.get('brain_tag')}: actual={bool(a.get('on_actual'))} preds={len(a.get('on_predict_brains') or [])}")
        brain = (j.get("brains") or [{}])[0]
        sets = (j.get("brains") or [{}])[0].get("predicted_sets") or []
        has_conf = sum(1 for s in sets if s.get("confidence") is not None)
        print(f"  first brain sets with confidence: {has_conf}/{len(sets)}")
        print(f"  aux_analysis stored: {len((j.get('brains') or [{}])[0].get('aux_analysis') or [])}")


if __name__ == "__main__":
    main()
