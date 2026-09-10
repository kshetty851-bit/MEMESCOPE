"""`python -m app.labs.crypto_trend tick|run|health` — the lab's own entry point.

Exists so the lab is runnable without registering anything in the platform's
Celery beat. `tick` is one idempotent pass; `run` repeats it every 60 seconds
in the foreground; `health` prints `data_health()`.
"""

from __future__ import annotations

import asyncio
import json
import sys

from app.db.session import SessionFactory
from app.labs.crypto_trend.data import data_health
from app.labs.crypto_trend.scheduler import tick

POLL_SECONDS = 60


async def _run() -> None:
    while True:
        sys.stdout.write(json.dumps(await tick()) + "\n")
        sys.stdout.flush()
        await asyncio.sleep(POLL_SECONDS)


async def _health() -> dict:
    async with SessionFactory() as session:
        return await data_health(session)


def main() -> int:
    command = sys.argv[1] if len(sys.argv) == 2 else None
    if command == "tick":
        sys.stdout.write(json.dumps(asyncio.run(tick()), indent=2) + "\n")
    elif command == "run":
        asyncio.run(_run())
    elif command == "health":
        sys.stdout.write(json.dumps(asyncio.run(_health()), indent=2) + "\n")
    else:
        sys.stderr.write("usage: python -m app.labs.crypto_trend tick|run|health\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
