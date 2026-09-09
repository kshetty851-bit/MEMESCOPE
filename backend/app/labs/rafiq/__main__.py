"""`python -m app.labs.rafiq tick` — the lab's own entry point.

Exists so the lab is runnable without registering anything in the platform's
Celery beat. `tick` is idempotent and safe to run late: it settles what is
open, asks the breaker, then considers what is fresh.
"""

from __future__ import annotations

import asyncio
import json
import sys

from app.labs.rafiq.scheduler import tick


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] != "tick":
        sys.stderr.write("usage: python -m app.labs.rafiq tick\n")
        return 2
    sys.stdout.write(json.dumps(asyncio.run(tick()), indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
