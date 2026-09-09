"""The Rafiq Lab's own three tables. Prefix `rafiq_lab_`.

WHY `rafiq_lab_` AND NOT `rafiq_`
---------------------------------
`rafiq_wallets`, `rafiq_opportunities`, `rafiq_positions`, `rafiq_fills` and
`rafiq_events` are already taken by an unmerged `rafiq-wallet` branch (a
different experiment, verdict NO-GO, never deployed). The brief asked for a
`rafiq_` prefix; `rafiq_lab_` is that prefix, and it is the version that
survives if that branch is ever merged.

**No balance is stored.** Cash, equity and P&L are derived from these rows at
read time, exactly as the paper and Karthik wallets do it, because a stored
balance is a second source of truth that drifts the moment one write lands
without the other.

**Nothing here touches a chain.**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# These tables are on the PLATFORM's `Base`, and that is a deliberate reversal.
#
# A separate `DeclarativeBase` was tried first, so that `alembic check` could
# not see the lab at all. It made the isolation WORSE, not better: autogenerate
# compares the platform's metadata against the database, so three tables
# present in one and absent from the other came out as `drop_table` operations.
# The next person to run `alembic revision --autogenerate` would have been
# handed a migration that deletes the lab's ledger.
#
# Sharing the metadata costs one thing — a stray `Base.metadata.create_all` can
# now build these tables — and buys the thing that matters: the schema tool
# agrees with the schema. The isolation the brief asked for is untouched,
# because it was never about metadata: the lab reads the shared feed through
# `feed.py` and writes nothing but `rafiq_lab_*`, and tests hold both directly.

#: Matches `token_market_snapshots.price_usd`, so a price round-trips unchanged.
_PRICE = Numeric(38, 18)
_MONEY = Numeric(24, 4)
#: Price-scaled: $50 of a token at 4.8e-10 is a very large number of units.
_QUANTITY = Numeric(48, 18)


class RafiqLabStrategy(Base):
    """One strategy's book. Five rows, created once at first tick.

    `starting_equity` and `profile_digest` are copied onto the row rather than
    read from code at display time: changing a constant later must not restate
    a return that was already published under the old one.
    """

    __tablename__ = "rafiq_lab_strategies"
    __table_args__ = (
        UniqueConstraint("code", name="uq_rafiq_lab_strategies_code"),
        Index("ix_rafiq_lab_strategies_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    #: `A` | `B` | `C` | `D` | `E`.
    code: Mapped[str] = mapped_column(String(2), nullable=False)
    #: Rafiq's own `StrategyProfile.lane`, copied verbatim.
    lane: Mapped[str] = mapped_column(String(48), nullable=False)
    starting_equity: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    #: SHA-256 over every constant that changes a result. A mismatch against
    #: the code stops the runner rather than trading a drifted rule into a
    #: record opened under a different one.
    profile_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class RafiqLabPosition(Base):
    """One simulated trade, from entry to close.

    The entry block — price, quantity, stop, target, trail, hold — is written
    once and never updated. Fixing the exit geometry at entry is the
    anti-hindsight guarantee: a stop that could be recomputed later could be
    recomputed favourably, and the difference would be invisible in the result.
    """

    __tablename__ = "rafiq_lab_positions"
    __table_args__ = (
        # One position per token per strategy, ever. Exactly-once held by the
        # database, so a retried task and two concurrent ticks collapse to one.
        UniqueConstraint("strategy_id", "mint_address",
                         name="uq_rafiq_lab_positions_strategy_mint"),
        Index("ix_rafiq_lab_positions_open", "strategy_id", "last_evaluated_at",
              postgresql_where="status = 'open'"),
        Index("ix_rafiq_lab_positions_closed_at", "strategy_id", "closed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rafiq_lab_strategies.id", ondelete="CASCADE"),
        nullable=False,
    )
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(32))

    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # --- Written once at entry, never updated -------------------------------
    entry_price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    #: The market price the decision was made from, kept apart from the fill
    #: above so a reader can see what execution cost.
    entry_observed_price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(_QUANTITY, nullable=False)
    cost_basis: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    entry_liquidity_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    #: The geometry, frozen. `stop_price` is C's liquidity-derived level for C
    #: and E, and the profile's flat `stop_mult` for A, B and D.
    stop_price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    target_price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    stop_pct: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    trailing_frac: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    max_hold_seconds: Mapped[int] = mapped_column(Integer, nullable=False)

    # --- Moved by the evaluator ---------------------------------------------
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open", server_default=text("'open'")
    )
    #: Highest price observed while open. Carried forward rather than
    #: recomputed, so it survives snapshot pruning.
    peak_price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    last_evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    #: The last price actually observed while open. Mark-to-market equity is
    #: computed from THIS, never from `peak_price` and never from the cost
    #: basis: a book marked at its peak is the same lie as a book marked at
    #: what it was paid for, and Strategy D's breaker exists to see through
    #: exactly that. Null only between an entry and its first evaluation.
    last_mark_price: Mapped[Decimal | None] = mapped_column(_PRICE)

    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    exit_observed_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    exit_proceeds_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    #: `stop` | `take_profit` | `trailing` | `max_hold`. There are no others:
    #: these are the four ways out Rafiq's `ExitRules` defines.
    exit_reason: Mapped[str | None] = mapped_column(String(16))
    exit_evidence: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class RafiqLabDailyState(Base):
    """Strategy D's daily baseline, one row per strategy per UTC day.

    A row per day rather than a mutable "current day" row, so a halt is a
    permanent record of a day that happened rather than a flag that gets
    cleared and leaves nothing behind.
    """

    __tablename__ = "rafiq_lab_daily_state"
    __table_args__ = (
        UniqueConstraint("strategy_id", "day", name="uq_rafiq_lab_daily_state_day"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rafiq_lab_strategies.id", ondelete="CASCADE"),
        nullable=False,
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    #: Mark-to-market equity at the day's first tick. Never a cost basis.
    day_open_equity: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    realised_today: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, default=Decimal(0), server_default=text("0")
    )
    halted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    halted_reason: Mapped[str | None] = mapped_column(Text)
    halted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
