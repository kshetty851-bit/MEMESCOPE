"""Manual control over the daily paper-wallet report.

Two operations, both behind the alpha gate that `AlphaAccessMiddleware` applies
to every route not on its allowlist — this router is deliberately not on it.
There is no unauthenticated way to make this deployment send mail.

`POST /reports/daily/test` is the one to reach for. It is labelled as a test in
the subject and the body, and it records under `ReportKind.TEST`, so sending one
neither satisfies nor consumes a scheduled day.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import DbSession
from app.core.config import settings
from app.reports.service import send_daily_report

router = APIRouter(prefix="/reports", tags=["reports"])


class DeliveryOut(BaseModel):
    """What one send attempt did."""

    report_date: str
    attempted: int
    sent: int
    skipped: int
    failed: int
    reason: str | None = None


class ReportConfigOut(BaseModel):
    """The report's configuration, with no secret in it.

    Deliberately omits host, username and password. The frontend needs to know
    *whether* mail can be sent, never how.
    """

    enabled: bool
    email_configured: bool = Field(
        description="Whether SMTP credentials are present. Never exposes them."
    )
    recipients: list[str]
    hour: int
    minute: int
    timezone: str


@router.get(
    "/daily/config",
    response_model=ReportConfigOut,
    summary="Daily paper-wallet report settings",
)
async def get_config() -> ReportConfigOut:
    return ReportConfigOut(
        enabled=settings.DAILY_REPORT_ENABLED,
        email_configured=settings.email_configured,
        recipients=list(settings.DAILY_REPORT_RECIPIENTS),
        hour=settings.DAILY_REPORT_HOUR,
        minute=settings.DAILY_REPORT_MINUTE,
        timezone=settings.DAILY_REPORT_TIMEZONE,
    )


@router.post(
    "/daily/test",
    response_model=DeliveryOut,
    summary="Send a clearly-labelled test report now",
)
async def send_test(session: DbSession) -> DeliveryOut:
    """Send a test copy immediately.

    Ignores the schedule and the enabled flag — the point is to prove delivery
    works — but records as `TEST`, so the scheduled report for the same day is
    unaffected in either direction.
    """
    outcome = await send_daily_report(session, now=datetime.now(UTC), is_test=True, force=True)
    return DeliveryOut(**outcome.as_dict)  # type: ignore[arg-type]


@router.post(
    "/daily/send",
    response_model=DeliveryOut,
    summary="Send today's real report now",
)
async def send_now(session: DbSession) -> DeliveryOut:
    """Send the real report ahead of its schedule.

    `force` skips the due-time check only. The duplicate check still applies,
    so this cannot produce a second copy of a report that already went out.
    """
    outcome = await send_daily_report(session, now=datetime.now(UTC), force=True)
    return DeliveryOut(**outcome.as_dict)  # type: ignore[arg-type]
