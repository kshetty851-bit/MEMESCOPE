"""Delivering the daily report, at most once per day per recipient.

The guarantee is: **for a given kind, report date and recipient there is at most
one `sent` row, ever.** It is enforced by a partial unique index rather than by
this code, because two workers can evaluate the same minute and application-side
checks lose that race.

The beat runs every fifteen minutes rather than once at 09:00. That looks
wasteful and is deliberate:

* a worker that was down at 09:00 still sends the report at 09:15,
* a transient SMTP failure retries without waiting a day,
* and the index makes all of it idempotent.

The cost is a cheap query every quarter hour; the alternative is a report that
silently does not arrive because a container restarted at the wrong minute.

Nothing here touches the wallet. It calls `PaperWalletService.read`, which is
the same read the API serves, and renders the result.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.report_delivery import DeliveryStatus, ReportDelivery, ReportKind
from app.paper.service import PaperWalletService
from app.reports import daily_paper, render
from app.reports.email import Email, EmailProvider, SendResult, provider_from_settings

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    """What one run did, for logging and for the manual endpoint."""

    report_date: date
    attempted: int
    sent: int
    skipped: int
    failed: int
    reason: str | None = None

    @property
    def as_dict(self) -> dict[str, object]:
        return {
            "report_date": self.report_date.isoformat(),
            "attempted": self.attempted,
            "sent": self.sent,
            "skipped": self.skipped,
            "failed": self.failed,
            "reason": self.reason,
        }


def is_due(now: datetime, *, tz_name: str, hour: int, minute: int) -> bool:
    """Whether the local wall clock has reached the report time today.

    Deliberately "at or after" rather than "equals": the beat fires on a
    fifteen-minute grid and an exact-minute test would miss the report whenever
    a worker was busy. The delivery index is what stops the looser test from
    sending twice.
    """
    local = now.astimezone(ZoneInfo(tz_name))
    return (local.hour, local.minute) >= (hour, minute)


async def already_sent(
    session: AsyncSession, *, kind: str, report_date: date, recipient: str
) -> bool:
    """Whether a successful delivery is already on record."""
    found = await session.scalar(
        select(ReportDelivery.id).where(
            ReportDelivery.kind == kind,
            ReportDelivery.report_date == report_date,
            ReportDelivery.recipient == recipient,
            ReportDelivery.status == DeliveryStatus.SENT.value,
        )
    )
    return found is not None


async def _record(
    session: AsyncSession,
    *,
    kind: str,
    report_date: date,
    recipient: str,
    status: DeliveryStatus,
    now: datetime,
    result: SendResult | None = None,
) -> bool:
    """Persist one attempt. Returns False when the unique index refused it.

    A refusal is not an error: it means another worker delivered this exact
    report first, which is the index doing its job.
    """
    session.add(
        ReportDelivery(
            kind=kind,
            report_date=report_date,
            recipient=recipient,
            status=status.value,
            attempted_at=now,
            sent_at=now if status is DeliveryStatus.SENT else None,
            provider_message_id=result.provider_message_id if result else None,
            error=result.error if result else None,
        )
    )
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        logger.info(
            "daily_report_duplicate_suppressed",
            report_date=report_date.isoformat(),
            recipient=recipient,
        )
        return False
    return True


async def send_daily_report(
    session: AsyncSession,
    *,
    now: datetime,
    provider: EmailProvider | None = None,
    force: bool = False,
    is_test: bool = False,
) -> DeliveryOutcome:
    """Build and deliver today's report to every configured recipient.

    `force` skips the due-time check but **not** the duplicate check, so a
    manual "send now" cannot produce a second copy of a report that already
    went out. `is_test` bypasses both and records under `ReportKind.TEST`, so a
    test never satisfies — or consumes — a scheduled day.
    """
    tz_name = settings.DAILY_REPORT_TIMEZONE
    _, _, report_date = daily_paper.local_day_bounds(now, tz_name)
    kind = ReportKind.TEST.value if is_test else ReportKind.DAILY_PAPER_WALLET.value
    recipients = [r.strip() for r in settings.DAILY_REPORT_RECIPIENTS if r.strip()]

    if not recipients:
        return DeliveryOutcome(report_date, 0, 0, 0, 0, reason="no_recipients")

    if not is_test and not settings.DAILY_REPORT_ENABLED and not force:
        return DeliveryOutcome(report_date, 0, 0, 0, 0, reason="disabled")

    if (
        not is_test
        and not force
        and not is_due(
            now,
            tz_name=tz_name,
            hour=settings.DAILY_REPORT_HOUR,
            minute=settings.DAILY_REPORT_MINUTE,
        )
    ):
        return DeliveryOutcome(report_date, 0, 0, 0, 0, reason="not_due")

    # Nothing below sends without credentials; the recording provider makes the
    # path identical so an unconfigured deploy is still observable.
    if provider is None:
        provider = provider_from_settings()
    if not settings.email_configured and not is_test:
        for recipient in recipients:
            await _record(
                session,
                kind=kind,
                report_date=report_date,
                recipient=recipient,
                status=DeliveryStatus.SKIPPED,
                now=now,
            )
        await session.commit()
        return DeliveryOutcome(
            report_date, 0, 0, len(recipients), 0, reason="email_not_configured"
        )

    read = await PaperWalletService(session).read(now=now)
    report = daily_paper.build(read=read, now=now, tz_name=tz_name)
    html = render.to_html(report, is_test=is_test)
    text = render.to_text(report, is_test=is_test)
    subject = render.subject_for(report, is_test=is_test)

    sent = failed = skipped = 0
    for recipient in recipients:
        if not is_test and await already_sent(
            session, kind=kind, report_date=report_date, recipient=recipient
        ):
            skipped += 1
            continue

        result = provider.send(
            Email(
                subject=subject,
                html_body=html,
                text_body=text,
                recipients=(recipient,),
                sender=settings.email_sender or "memescope@localhost",
                sender_name=settings.SMTP_FROM_NAME,
            )
        )
        status = DeliveryStatus.SENT if result.sent else DeliveryStatus.FAILED
        stored = await _record(
            session,
            kind=kind,
            report_date=report_date,
            recipient=recipient,
            status=status,
            now=now,
            result=result,
        )
        if not stored:
            skipped += 1
        elif result.sent:
            sent += 1
        else:
            failed += 1
            logger.warning(
                "daily_report_send_failed",
                recipient=recipient,
                report_date=report_date.isoformat(),
                error=result.error,
            )

    await session.commit()
    outcome = DeliveryOutcome(
        report_date, attempted=len(recipients), sent=sent, skipped=skipped, failed=failed
    )
    logger.info("daily_report_run", **outcome.as_dict, kind=kind)
    return outcome
