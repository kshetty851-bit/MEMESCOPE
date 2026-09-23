"""The recorder's task. Its own try block, so a failure here costs a pass and
nothing else — the same rule the retention worker learned the hard way."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)


@celery_app.task(name="app.labs.rhood.scheduler.rhood_record")
def rhood_record() -> dict[str, Any]:
    """Record Robinhood Chain locks. Never raises."""
    return run_async(_record())


async def _record() -> dict[str, Any]:
    from app.labs.rhood import recorder

    try:
        async with SessionFactory() as session:
            return await recorder.record(session)
    except Exception as exc:   # every failure ends here; see the docstring
        logger.warning("rhood_record_failed", error=str(exc)[:200],
                       kind=type(exc).__name__)
        return {"failed": type(exc).__name__}
