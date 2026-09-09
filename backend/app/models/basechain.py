"""Launches on EVM chains, stamped by US because the discovery window is short.

GeckoTerminal's `new_pools` feed reaches back about seventy minutes — ten pages
at roughly seven minutes each, measured 2026-09-09. A pool older than that is
simply not discoverable through it, so "what happens in the hour after a Base
token launches" is unanswerable retrospectively for anything we did not catch
at the time.

The fix is the same one the pump.fun graduation collector uses: stamp the event
ourselves, continuously, and let the analysis come later.

What is DIFFERENT here, and better: minute OHLCV is available per pool
retroactively, so this table records only the LAUNCH. There is no need to poll
a price at five, fifteen, thirty and sixty minutes and hope the poll lands —
the candles can be fetched afterwards, at their true resolution, for any pool
whose address is stored here. That removes the largest source of error in the
Solana study, where a mark is whatever a poll happened to see.

`network` is a column rather than an assumption. The Solana side of this
platform has no chain field anywhere and is Solana by implication, which is
exactly the thing that makes adding a second chain expensive. This one starts
with the column.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

#: Liquidity arrives as USD floats and can be enormous or dust. Wide, and never
#: clamped — an implausible value is rejected upstream rather than stored as a
#: number somebody later trusts.
_USD = Numeric(30, 4)


class EvmLaunch(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One pool, the first time we ever saw it listed as new."""

    __tablename__ = "evm_launches"

    #: "base", "bsc", … — GeckoTerminal's network id, stored verbatim so a
    #: second network needs no schema change and no interpretation.
    network: Mapped[str] = mapped_column(String(32), nullable=False)

    #: The POOL, which is what OHLCV is keyed by. Unique per network.
    pool_address: Mapped[str] = mapped_column(String(64), nullable=False)

    #: The traded token. Kept alongside the pool because a token can have
    #: several pools and the analysis may want to collapse them.
    base_token_address: Mapped[str | None] = mapped_column(String(64))

    name: Mapped[str | None] = mapped_column(String(128))
    dex_id: Mapped[str | None] = mapped_column(String(64))

    #: THE SOURCE'S timestamp for pool creation.
    pool_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: OUR stamp: the first poll at which we saw it. Accurate to the poll
    #: interval, which is the whole point of the collector.
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    #: Liquidity AT THAT SIGHTING, recorded once and never recomputed. A launch
    #: liquidity inferred later is an assumption; this is an observation.
    liquidity_usd_at_sighting: Mapped[Decimal | None] = mapped_column(_USD)

    __table_args__ = (
        UniqueConstraint("network", "pool_address", name="uq_evm_launches_pool"),
        Index("ix_evm_launches_seen", "network", first_seen_at.desc()),
        Index("ix_evm_launches_created", "network", pool_created_at.desc()),
    )
