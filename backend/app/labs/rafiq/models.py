"""The Rafiq Lab's own four tables. Prefix `rafiq_lab_`.

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
from sqlalchemy.dialects.postgresql import JSONB, UUID
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
    #: `A2` | `B2` | `C2` | `D2` | `E2`.
    code: Mapped[str] = mapped_column(String(4), nullable=False)
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
        # One position per token per strategy PER LEG, ever. Exactly-once held
        # by the database, so a retried task and two concurrent ticks collapse
        # to one. `leg` is in the key because C2 deliberately opens two rows
        # per token — without it the second leg would silently not exist.
        UniqueConstraint("strategy_id", "mint_address", "leg",
                         name="uq_rafiq_lab_positions_strategy_mint_leg"),
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
    #: 1-based slice of the position. 1 for every book but C2, which opens
    #: leg 1 (half, +30% target) and leg 2 (half, no target, trails).
    leg: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )

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
    #: Market cap at entry. Recorded because the gate is decided on it, and a
    #: read-out that cannot see the entry reading cannot check the gate.
    entry_market_cap_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    #: Modelled impact for the WHOLE position at entry, and for this leg at
    #: exit. Stored rather than re-derived: the cost model is calibration, and
    #: a recalibration must not silently restate a trade that already happened.
    entry_price_impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))

    # --- the entry decision's two instrumented features ------------------
    # Written ONCE, in the same INSERT as the rest of the row, from the store
    # as it stood at `opened_at`. Nothing in this lab updates them afterwards
    # and nothing backfills them: a value that appeared after the decision was
    # not available to the decision, and writing it here later would turn an
    # honest null into evidence the strategy never had. `_settle` touches only
    # the exit columns, and `test_entry_features_are_never_backfilled` fails if
    # a later-arriving snapshot changes a row that is already open.
    #
    # A null here is a fact about this platform's collectors, not about the
    # token — `entry_features_error` says which store was silent.
    entry_top10_holder_pct: Mapped[Decimal | None] = mapped_column(Numeric(9, 4))
    entry_top10_captured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True))
    entry_lp_status: Mapped[str | None] = mapped_column(String(16))
    entry_lp_reason_codes: Mapped[list | None] = mapped_column(JSONB)
    entry_lp_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True))
    entry_features_error: Mapped[str | None] = mapped_column(String(64))

    #: The geometry, frozen. `stop_price` is C's liquidity-derived level for
    #: E2, and the profile's flat `stop_mult` for A2, B2, C2 and D2.
    stop_price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    #: None for a leg with no take profit — D2 and C2's second leg.
    target_price: Mapped[Decimal | None] = mapped_column(_PRICE)
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
    exit_price_impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
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


class RafiqLabGateRejection(Base):
    """How often each book's entry gate refused, and for which condition.

    A counter per (strategy, reason) rather than a row per rejection: the gate
    refuses most of the stream on most ticks, and a row each would be a table
    of millions that nobody reads. What the read-out actually needs is "A2
    rejected 4,812 candidates, 51% of them for liquidity" — which is this.

    The counters are cumulative since activation and never reset, so a rate can
    always be derived against the book's own age. `last_at` is kept so a reader
    can tell a condition that stopped firing from one that never fired.
    """

    __tablename__ = "rafiq_lab_gate_rejections"
    __table_args__ = (
        UniqueConstraint("strategy_id", "reason",
                         name="uq_rafiq_lab_gate_rejections_strategy_reason"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rafiq_lab_strategies.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: One of `entry_gate.REASONS`. Not an enum in the database: a new reason
    #: must not need a migration before it can be counted.
    reason: Mapped[str] = mapped_column(String(48), nullable=False)
    rejections: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    last_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
