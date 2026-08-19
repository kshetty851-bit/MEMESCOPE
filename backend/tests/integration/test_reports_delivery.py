"""Delivery: exactly once, never fatal, never a real send.

The guarantee under test is that a beat running every fifteen minutes cannot
produce two emails for the same day. `TestExactlyOnce` is the whole point of the
partial unique index, and it is checked both through the service's own guard and
by writing a duplicate row directly, because the index is what holds when two
workers race.

Every test passes a `RecordingProvider`. Nothing here can reach a mail server.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models.report_delivery import DeliveryStatus, ReportDelivery, ReportKind
from app.reports.email import RecordingProvider
from app.reports.service import send_daily_report

pytestmark = pytest.mark.asyncio

# 05:00 UTC is 09:00 in Asia/Dubai — due.
DUE = datetime(2026, 8, 12, 5, 0, tzinfo=UTC)
# 03:00 UTC is 07:00 — not yet.
NOT_DUE = datetime(2026, 8, 12, 3, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _report_settings(monkeypatch):
    """A configured, enabled deployment — without any real credentials."""
    monkeypatch.setattr(settings, "DAILY_REPORT_ENABLED", True)
    monkeypatch.setattr(settings, "DAILY_REPORT_RECIPIENTS", ["ops@example.com"])
    monkeypatch.setattr(settings, "DAILY_REPORT_TIMEZONE", "Asia/Dubai")
    monkeypatch.setattr(settings, "DAILY_REPORT_HOUR", 9)
    monkeypatch.setattr(settings, "DAILY_REPORT_MINUTE", 0)
    # `email_configured` is a property over these two.
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.invalid")
    monkeypatch.setattr(settings, "SMTP_USERNAME", "reports@example.invalid")


async def _count(session, **filters) -> int:
    stmt = select(func.count(ReportDelivery.id))
    for field, value in filters.items():
        stmt = stmt.where(getattr(ReportDelivery, field) == value)
    return await session.scalar(stmt) or 0


class TestExactlyOnce:
    async def test_a_second_run_on_the_same_day_does_not_resend(self, db_session):
        provider = RecordingProvider()

        first = await send_daily_report(db_session, now=DUE, provider=provider)
        second = await send_daily_report(db_session, now=DUE, provider=provider)

        assert first.sent == 1
        assert second.sent == 0
        assert second.skipped == 1
        assert len(provider.sent) == 1

    async def test_the_index_refuses_a_duplicate_sent_row(self, db_session):
        """The guarantee when two workers race past the service's own check."""
        from sqlalchemy.exc import IntegrityError

        provider = RecordingProvider()
        await send_daily_report(db_session, now=DUE, provider=provider)

        db_session.add(
            ReportDelivery(
                kind=ReportKind.DAILY_PAPER_WALLET.value,
                report_date=DUE.date(),
                recipient="ops@example.com",
                status=DeliveryStatus.SENT.value,
                attempted_at=DUE,
                sent_at=DUE,
            )
        )
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()

    async def test_failures_may_repeat(self, db_session):
        """Only success is unique. A failed attempt must be retryable."""
        failing = RecordingProvider(fail_with="temporary")
        await send_daily_report(db_session, now=DUE, provider=failing)
        await send_daily_report(db_session, now=DUE, provider=failing)

        assert (
            await _count(
                db_session,
                status=DeliveryStatus.FAILED.value,
                recipient="ops@example.com",
            )
            == 2
        )

    async def test_a_failure_then_a_success_delivers(self, db_session):
        await send_daily_report(
            db_session, now=DUE, provider=RecordingProvider(fail_with="temporary")
        )
        good = RecordingProvider()
        outcome = await send_daily_report(db_session, now=DUE, provider=good)

        assert outcome.sent == 1
        assert len(good.sent) == 1


class TestScheduleGuards:
    async def test_not_due_sends_nothing(self, db_session):
        provider = RecordingProvider()
        outcome = await send_daily_report(db_session, now=NOT_DUE, provider=provider)
        assert outcome.reason == "not_due"
        assert provider.sent == []

    async def test_disabled_sends_nothing(self, db_session, monkeypatch):
        monkeypatch.setattr(settings, "DAILY_REPORT_ENABLED", False)
        provider = RecordingProvider()
        outcome = await send_daily_report(db_session, now=DUE, provider=provider)
        assert outcome.reason == "disabled"
        assert provider.sent == []

    async def test_no_recipients_sends_nothing(self, db_session, monkeypatch):
        monkeypatch.setattr(settings, "DAILY_REPORT_RECIPIENTS", [])
        provider = RecordingProvider()
        outcome = await send_daily_report(db_session, now=DUE, provider=provider)
        assert outcome.reason == "no_recipients"
        assert provider.sent == []

    async def test_force_overrides_the_clock_but_not_the_duplicate_check(
        self, db_session
    ):
        provider = RecordingProvider()
        first = await send_daily_report(
            db_session, now=NOT_DUE, provider=provider, force=True
        )
        second = await send_daily_report(
            db_session, now=NOT_DUE, provider=provider, force=True
        )

        assert first.sent == 1
        assert second.sent == 0
        assert len(provider.sent) == 1

    async def test_missing_credentials_records_a_skip(self, db_session, monkeypatch):
        monkeypatch.setattr(settings, "SMTP_HOST", "")
        monkeypatch.setattr(settings, "SMTP_USERNAME", "")
        provider = RecordingProvider()

        outcome = await send_daily_report(db_session, now=DUE, provider=provider)

        assert outcome.reason == "email_not_configured"
        assert provider.sent == []
        assert await _count(db_session, status=DeliveryStatus.SKIPPED.value) == 1


class TestTestEmail:
    async def test_is_labelled_and_does_not_consume_the_scheduled_day(
        self, db_session
    ):
        provider = RecordingProvider()

        await send_daily_report(
            db_session, now=DUE, provider=provider, is_test=True, force=True
        )
        assert provider.sent[0].subject == "MEMESCOPE — Test Paper Wallet Report"
        assert "TEST EMAIL" in provider.sent[0].html_body

        # The scheduled report for the same day is still owed.
        scheduled = await send_daily_report(db_session, now=DUE, provider=provider)
        assert scheduled.sent == 1
        assert len(provider.sent) == 2

    async def test_is_recorded_under_its_own_kind(self, db_session):
        await send_daily_report(
            db_session,
            now=DUE,
            provider=RecordingProvider(),
            is_test=True,
            force=True,
        )
        assert await _count(db_session, kind=ReportKind.TEST.value) == 1
        assert await _count(db_session, kind=ReportKind.DAILY_PAPER_WALLET.value) == 0

    async def test_may_be_sent_repeatedly(self, db_session):
        """A test is a diagnostic; it must not be rate-limited by the index."""
        provider = RecordingProvider()
        for _ in range(3):
            await send_daily_report(
                db_session, now=DUE, provider=provider, is_test=True, force=True
            )
        assert len(provider.sent) == 3


class TestFailureIsContained:
    async def test_a_provider_failure_is_recorded_not_raised(self, db_session):
        outcome = await send_daily_report(
            db_session, now=DUE, provider=RecordingProvider(fail_with="smtp down")
        )
        assert outcome.failed == 1
        assert outcome.sent == 0

        stored = await db_session.scalar(
            select(ReportDelivery).where(
                ReportDelivery.status == DeliveryStatus.FAILED.value
            )
        )
        assert stored is not None
        assert stored.error == "smtp down"


class TestMultipleRecipients:
    async def test_each_recipient_is_tracked_independently(
        self, db_session, monkeypatch
    ):
        monkeypatch.setattr(
            settings, "DAILY_REPORT_RECIPIENTS", ["a@example.com", "b@example.com"]
        )
        provider = RecordingProvider()

        outcome = await send_daily_report(db_session, now=DUE, provider=provider)

        assert outcome.sent == 2
        assert {e.recipients[0] for e in provider.sent} == {
            "a@example.com",
            "b@example.com",
        }

    async def test_a_rerun_resends_to_nobody(self, db_session, monkeypatch):
        monkeypatch.setattr(
            settings, "DAILY_REPORT_RECIPIENTS", ["a@example.com", "b@example.com"]
        )
        provider = RecordingProvider()
        await send_daily_report(db_session, now=DUE, provider=provider)
        second = await send_daily_report(db_session, now=DUE, provider=provider)

        assert second.sent == 0
        assert second.skipped == 2
        assert len(provider.sent) == 2
