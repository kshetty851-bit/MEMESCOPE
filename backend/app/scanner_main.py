"""Scanner process entrypoint.

    python -m app.scanner_main

Runs as its own container rather than inside the API: it is a long-lived
stateful stream consumer, and coupling it to request-serving processes would
mean N gunicorn workers opening N duplicate subscriptions.
"""

from __future__ import annotations

import asyncio
import sys

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.services.scanner.scanner import run_scanner

logger = get_logger(__name__)


def main() -> int:
    configure_logging()

    if not settings.FEATURE_SCANNER_ENABLED:
        logger.warning("scanner_disabled", reason="FEATURE_SCANNER_ENABLED is false")
        return 0

    if not settings.helius_configured:
        logger.error("scanner_misconfigured", reason="HELIUS_API_KEY is not set")
        return 1

    try:
        asyncio.run(run_scanner())
    except KeyboardInterrupt:
        logger.info("scanner_interrupted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
