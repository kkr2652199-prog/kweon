"""814만 전체 조합 — 20분할 part DB 적재 (data/combos/, 로컬 전용)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.lotto4.all_combos_service import build_all_combos_parts  # noqa: E402


def main() -> None:
    force = "--force" in sys.argv
    rollback_only = "--rollback" in sys.argv
    if rollback_only:
        from app.lotto4.all_combos_service import rollback_lotto4_single_table

        print(json.dumps(rollback_lotto4_single_table(), ensure_ascii=False, indent=2))
        return
    result = build_all_combos_parts(force=force)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
