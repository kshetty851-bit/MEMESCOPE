"""Market Enrichment Worker entrypoint.

    python -m app.enrichment_main

Separate process from the scanner by design: enrichment must never be able to
slow down or stall token discovery.
"""

from __future__ import annotations

import asyncio
import sys

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.services.market.worker import run_worker

logger = get_logger(__name__)


def main() -> int:
    configure_logging()

    if not settings.FEATURE_ENRICHMENT_ENABLED:
        logger.warning("enrichment_disabled", reason="FEATURE_ENRICHMENT_ENABLED is false")
        return 0

    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        logger.info("enrichment_interrupted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
