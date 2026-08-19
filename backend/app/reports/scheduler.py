"""The beat entry for the daily paper-wallet report.

Mirrors `app.paper.scheduler`: a thin Celery task that owns its session, commits
explicitly, and does no work of its own beyond calling the service.

**This task can never break trading.** Every exception is caught and logged.
The paper wallet, the scanner and the enrichment loop are separate beats in the
same worker, and an SMTP timeout must not take a shared process down with it —
a missed email is an inconvenience, a stalled scanner is an outage.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from app.db.session import SessionFactory
from app.reports.service import send_daily_report
from app.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(name="app.reports.scheduler.daily_paper_report")
def daily_paper_report() -> dict[str, object]:
    """Send today's report if it is due and has not gone out yet.

    Returns a dict rather than raising, so a failure shows up in the task
    result and in the log without triggering Celery's retry machinery — the
    fifteen-minute beat is already the retry.
    """
    import asyncio

    async def run() -> dict[str, object]:
        async with SessionFactory() as session:
            outcome = await send_daily_report(session, now=datetime.now(UTC))
            return outcome.as_dict

    try:
        return asyncio.run(run())
    except Exception as exc:
        logger.exception("daily_report_task_failed", error_type=type(exc).__name__)
        return {"error": type(exc).__name__}
