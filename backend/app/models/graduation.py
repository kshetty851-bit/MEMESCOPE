"""Graduation events, timestamped by US because nobody else timestamps them.

pump.fun's API exposes `complete` — whether the bonding curve has filled — but
no graduation timestamp anywhere. So "what happens in the hour after a coin
graduates" is unanswerable from a snapshot: every measurement of it ends up
bucketing by CREATION age, which is not the same thing, because a coin created
45 minutes ago may have graduated five minutes ago.

The fix is to stamp the event ourselves. Polling the freshly-created graduates
every minute means the first sighting is within a minute of the real
graduation, and that stamp is what makes a forward measurement possible.

The reference market cap is recorded AT THAT SIGHTING and never recomputed.
A graduation price inferred later from the curve's constants is an assumption;
this is an observation.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

#: Market caps arrive as float USD and can be enormous. Wide, and NEVER
#: clamped — an implausible value is rejected upstream rather than stored as a
#: number somebody later trusts.
_MCAP = Numeric(30, 4)


class PumpfunGraduation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One coin, the first time we ever saw it complete."""

    __tablename__ = "pumpfun_graduations"

    mint_address: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    #: OUR stamp: the first poll at which this coin read `complete`. Accurate to
    #: the poll interval, which is the whole point of the collector.
    first_seen_complete_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    #: pump.fun's own creation time. Kept so the lag from launch to graduation
    #: is measurable, and so a coin that graduated long before we started
    #: watching can be excluded — it would otherwise enter the cohort with a
    #: graduation stamp that is really a "we noticed" stamp.
    created_at_source: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: The reference price. Everything downstream is measured against this.
    mcap_usd_at_graduation: Mapped[Decimal | None] = mapped_column(_MCAP, nullable=True)
    ath_mcap_usd_at_graduation: Mapped[Decimal | None] = mapped_column(_MCAP, nullable=True)
    reply_count_at_graduation: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        Index("ix_pumpfun_graduations_seen", first_seen_complete_at.desc()),
    )


class PumpfunGraduationMark(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One follow-up reading of a graduated coin.

    Separate rows rather than `mcap_5m`/`mcap_15m` columns: a missed poll is
    then an ABSENT row, which is honest, where a column would leave a NULL that
    reads identically to "we looked and it was nothing".
    """

    __tablename__ = "pumpfun_graduation_marks"

    graduation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pumpfun_graduations.id", ondelete="CASCADE"), nullable=False
    )
    mint_address: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Whole minutes since `first_seen_complete_at`, so a cohort can be sliced
    #: without recomputing the difference in every query.
    minutes_since: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mcap_usd: Mapped[Decimal | None] = mapped_column(_MCAP, nullable=True)
    ath_mcap_usd: Mapped[Decimal | None] = mapped_column(_MCAP, nullable=True)

    __table_args__ = (
        # One reading per coin per target age. A retry cannot double-count.
        UniqueConstraint("graduation_id", "minutes_since",
                         name="uq_graduation_mark_once"),
        Index("ix_graduation_marks_mint", "mint_address", observed_at.desc()),
    )
