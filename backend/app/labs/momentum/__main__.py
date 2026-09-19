"""`python -m app.labs.momentum universe|tick|prune|arms` — the beat's steps by hand."""

from __future__ import annotations

import asyncio
import json
import sys

from app.labs.momentum.arms import ARMS


def main() -> None:
    step = sys.argv[1] if len(sys.argv) > 1 else ""
    if step == "arms":
        for a in ARMS:
            print(f"{a.name:14} {a.family:8} {a.tf:4} | {a.entry_words} | {a.exit_words}")  # noqa: T201
        return
    if step not in {"universe", "tick", "prune"}:
        sys.exit("usage: python -m app.labs.momentum universe|tick|prune|arms")
    from app.labs.momentum.scheduler import run

    print(json.dumps(asyncio.run(run(step)), default=str))  # noqa: T201


if __name__ == "__main__":
    main()
