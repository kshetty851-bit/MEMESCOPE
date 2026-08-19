"""The record of what was emailed, and what failed.

Exactly-once delivery is a database constraint here, not a convention. The
scheduler runs on a short beat so that a failed attempt retries without waiting
for tomorrow, which means the same report date is evaluated many times a day —
and the only thing standing between that and a mailbox full of duplicates is the
partial unique index below.

Attempts are rows, not counters. A failure that is later retried successfully
leaves both rows, because "it eventually worked" and "it worked first time" are
different operational facts and the second is the one worth alerting on.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    DateTime,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DeliveryStatus(enum.StrEnum):
    """Outcome of one attempt. Persisted as a string, so append-only."""

    SENT = "sent"
    FAILED = "failed"
    #: Nothing was attempted: no recipients, feature disabled, or no SMTP
    #: credentials. Recorded rather than silent so an absent report is
    #: explicable a week later.
    SKIPPED = "skipped"


class ReportKind(enum.StrEnum):
    DAILY_PAPER_WALLET = "daily_paper_wallet"
    #: Manual sends never satisfy a scheduled day — see the partial index.
    TEST = "test"


class ReportDelivery(Base):
    """One attempt to deliver one report to one recipient."""

    __tablename__ = "report_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    #: The *local* date the report covers, in the configured report timezone.
    #: Not derivable from `sent_at`: a 09:00 Dubai report is still the previous
    #: UTC day for part of the year.
    report_date: Mapped[date] = mapped_column(nullable=False)
    recipient: Mapped[str] = mapped_column(String(320), nullable=False)

    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: SMTP does not return one; kept for providers that do.
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # The exactly-once guarantee. Partial on `status = 'sent'` so failures
        # and skips may repeat freely while a success may not — which is what
        # makes the retry loop safe to run every few minutes.
        Index(
            "uq_report_delivery_sent_once",
            "kind",
            "report_date",
            "recipient",
            unique=True,
            postgresql_where=text("status = 'sent'"),
        ),
        Index("ix_report_delivery_date", "report_date"),
    )
