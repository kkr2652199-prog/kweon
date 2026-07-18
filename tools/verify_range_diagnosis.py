#!/usr/bin/env python3
"""구간 진단 summary API 검증 (READ ONLY)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.testlotto.detail_service import get_reviews_range

REQUIRED_BRAIN_KEYS = {
    "avg_match",
    "trend",
    "trend_label",
    "tier5_plus_count",
    "missed_pattern_top3",
    "narrative",
    "equity_curve",
}


def check_range(start: int, end: int) -> dict:
    data = get_reviews_range(start, end, brain_tag=None, limit=500)
    summary = data.get("summary") or {}
    brains = summary.get("brains") or {}
    out: dict = {"start": start, "end": end, "ok": True, "brains": {}}
    if not summary:
        out["ok"] = False
        out["error"] = "summary missing"
        return out
    for tag in ("stat", "markov", "review"):
        b = brains.get(tag) or {}
        missing = REQUIRED_BRAIN_KEYS - set(b.keys())
        if missing:
            out["ok"] = False
            out["error"] = f"{tag} missing {sorted(missing)}"
            return out
        out["brains"][tag] = {
            "draw_count": b.get("draw_count"),
            "avg_match": b.get("avg_match"),
            "trend": b.get("trend"),
            "top3": b.get("missed_pattern_top3"),
            "narrative": b.get("narrative"),
            "curve_len": len(b.get("equity_curve") or []),
        }
    return out


def main() -> int:
    all_ok = True
    for start, end in [(2, 20), (1180, 1231)]:
        r = check_range(start, end)
        print(json.dumps(r, ensure_ascii=False))
        if not r.get("ok"):
            all_ok = False
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
