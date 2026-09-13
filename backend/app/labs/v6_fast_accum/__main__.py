"""`python -m app.labs.v6_fast_accum` — run the experiment once.

Deliberately a command and not an HTTP route: running it writes an immutable
run row, and that is an operator action rather than something a page refresh
should be able to trigger.
"""

from __future__ import annotations

import asyncio
import json
import sys

from app.db.session import SessionFactory
from app.labs.v6_fast_accum.runner import run


async def _main() -> int:
    async with SessionFactory() as session:
        result = await run(session)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("gate", {}).get("passed") else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
