#!/usr/bin/env python3
"""세트별 적중 분포 API 검증 (READ ONLY)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.testlotto.detail_service import get_set_hit_distribution

REQUIRED = {"honesty_warning", "brains", "set_ranking", "summary_narrative"}


def check(start: int, end: int) -> dict:
    data = get_set_hit_distribution(start, end)
    out: dict = {"start": start, "end": end, "ok": True}
    missing = REQUIRED - set(data.keys())
    if missing:
        return {"start": start, "end": end, "ok": False, "error": f"missing {sorted(missing)}"}
    if not data.get("honesty_warning"):
        return {"start": start, "end": end, "ok": False, "error": "honesty_warning empty"}
    brains = data.get("brains") or {}
    for tag in ("stat", "markov", "review"):
        b = brains.get(tag) or {}
        sets = b.get("sets") or {}
        if len(sets) != 5:
            return {"start": start, "end": end, "ok": False, "error": f"{tag} sets != 5"}
        cmp = b.get("comparison") or {}
        if "official_best" not in cmp or "posthoc_range_best" not in cmp:
            return {"start": start, "end": end, "ok": False, "error": f"{tag} comparison missing"}
    out["warning_len"] = len(data["honesty_warning"])
    out["ranking_top"] = (data.get("set_ranking") or [])[:3]
    out["stat_set1"] = brains.get("stat", {}).get("sets", {}).get("1")
    out["summary"] = data.get("summary_narrative")
    return out


def main() -> int:
    ok = True
    for start, end in [(1212, 1231), (2, 20)]:
        r = check(start, end)
        print(json.dumps(r, ensure_ascii=False))
        if not r.get("ok"):
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
