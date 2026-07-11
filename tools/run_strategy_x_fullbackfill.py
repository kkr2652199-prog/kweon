"""전략 X 5뇌 era_C 전회차 walk-forward 적재 실행."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.lotto4.strategy_x_fullbackfill import ERA_C_END, ERA_C_START, run_fullbackfill

OUT = Path(r"d:\3kweon\tools\_strategy_x_fullbackfill_result.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=ERA_C_START)
    ap.add_argument("--end", type=int, default=ERA_C_END)
    ap.add_argument("--checkpoint-every", type=int, default=25)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    result = run_fullbackfill(
        start_draw=args.start,
        end_draw=args.end,
        checkpoint_every=args.checkpoint_every,
        force=args.force,
    )
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
