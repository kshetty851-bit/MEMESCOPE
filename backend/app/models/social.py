"""Point-in-time social readings from pump.fun's own listing API.

The first signal on this platform that is not price, liquidity, volume or
wallet flow. Eleven experiments have varied those four and none produced an
edge; comment activity is orthogonal to all of them.

## Why raw counts and not velocity

`reply_count` is CUMULATIVE — it only ever grows over a coin's life — so it is
a proxy for AGE as much as for interest, and ranking on it selects coins that
have been around long enough to accumulate comments. A model trained on it
would rediscover survivorship: coins that lived longer have more replies
because they lived longer.

What is actually wanted is VELOCITY, replies gained per hour, and that cannot
be observed in one reading. So this table stores the raw count with a
timestamp and nothing else, and velocity is derived from consecutive rows at
read time. Computing a rate at write time would bake in whichever gap happened
to separate two polls.

## What `at_ath` is for

`usd_market_cap / ath_market_cap`. A coin at its own all-time high is what the
explore page means by a mover — LAPTOP, WOTF and WOFI all sat at 99.9-100% of
ATH when this was written. Stored as the two raw figures rather than the ratio,
because a ratio cannot be re-derived if either definition changes.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

USD = Numeric(24, 4)


class PumpfunSocialSnapshot(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One observation of one coin's social and market state."""

    __tablename__ = "pumpfun_social_snapshots"

    mint_address: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    #: Cumulative. Velocity is derived from consecutive rows, never stored.
    reply_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    usd_market_cap: Mapped[Decimal | None] = mapped_column(USD, nullable=True)
    ath_market_cap: Mapped[Decimal | None] = mapped_column(USD, nullable=True)

    #: Bonding curve finished — the coin has graduated to an AMM pool.
    complete: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_currently_live: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    #: Which listing surfaced it. Kept because the sort IS the population: a
    #: coin seen under `last_reply` is being discussed now, one seen under
    #: `market_cap` is merely large, and pooling them would blend two samples.
    source_sort: Mapped[str] = mapped_column(String(24), nullable=False)

    __table_args__ = (
        # The velocity read: one mint's readings in time order.
        Index("ix_pf_social_mint_at", "mint_address", "observed_at"),
        Index("ix_pf_social_at", "observed_at"),
    )
