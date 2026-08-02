"""Container healthcheck for the scanner: `python -m app.health.probe`.

Exits 0 when discovery is healthy, 1 when it is not, so Docker restarts a
scanner that has stopped finding tokens instead of leaving it `Up` forever.
The four-day outage was invisible precisely because the scanner service had no
healthcheck at all — the process was alive, which is all `restart: unless-stopped`
can see.

Deliberately checks the *outcome* (a token was discovered recently) rather than
the connection, because the connection was never the thing anyone cared about.
The scanner's published state is consulted too, so an unreachable Helius fails
the check immediately instead of waiting out the staleness window.

Runs in the scanner container, which has no HTTP server — hence a module rather
than an endpoint poll.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis, init_redis
from app.db.session import SessionFactory, dispose_engine
from app.health.service import PipelineHealthService

logger = get_logger(__name__)


async def check() -> bool:
    """True when the scanner stage is not `down`.

    `degraded` passes on purpose. Restarting a scanner that is merely quiet
    would turn a slow market into a crash loop, and a restart cannot conjure
    token launches that are not happening.
    """
    if not settings.FEATURE_SCANNER_ENABLED:
        # Nothing to be unhealthy about. A disabled scanner that failed its own
        # healthcheck would block every service that depends on it.
        return True

    await init_redis()
    try:
        async with SessionFactory() as session:
            health = await PipelineHealthService(session).scanner(datetime.now(UTC))
    finally:
        await close_redis()
        await dispose_engine()

    healthy = health.status != "down"
    logger.info(
        "scanner_probe",
        healthy=healthy,
        status=health.status,
        minutes_since_last_token=health.minutes_since_last_token,
        reconnect_attempts=health.reconnect_attempts,
        failure_reason=health.failure_reason,
    )
    return healthy


def main() -> int:
    configure_logging()
    try:
        return 0 if asyncio.run(check()) else 1
    except Exception as exc:
        # An unreachable database is not proof the scanner is broken, but it is
        # proof this check cannot vouch for it. Fail, and let the dependency's
        # own healthcheck explain why.
        logger.error("scanner_probe_failed", error=str(exc), error_type=type(exc).__name__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
