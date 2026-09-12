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


class RafiqCandidate(Base):
    """Every candidate F2 decided on, entered or refused, and what happened next.

    ## Why this table exists

    Every statistic in `FINDINGS.md` is conditioned on trades that were taken.
    That makes the most important question unanswerable: a filter cannot be
    evaluated against a population nobody recorded. `rafiq_lab_gate_rejections`
    counts refusals but keeps no features, so it can say the gate refused 4,812
    candidates and nothing about whether refusing them was right.

    This is the other half. One row per (strategy, mint), carrying the feature
    snapshot as it stood at the decision instant, the reason if it was refused,
    and the forward return at three horizons — so "would this filter have
    helped" becomes a query instead of an argument.

    ## One row per candidate, and which decision it holds

    An entry always supersedes an earlier rejection of the same mint: a book
    that refuses a token at 09:00 for a thin pool and buys it at 09:40 made one
    decision that matters, and it is the entry. A repeated *rejection* is
    discarded — the first one is kept, because that is the one whose feature
    snapshot is point-in-time with respect to the forward window measured from
    it.

    ## The forward columns are not backfilled in the entry sense

    They are written later by design — that is what "forward" means — but only
    ever from snapshots strictly after `decided_at`, and never into the feature
    columns. `max_return` is the best the token reached at any observation
    inside the horizon, so it is a ceiling nobody could have captured; it is
    here to bound what any exit rule could have done, not to suggest one did.
    """

    __tablename__ = "rafiq_lab_candidates"
    __table_args__ = (
        UniqueConstraint("strategy_id", "mint_address",
                         name="uq_rafiq_lab_candidates_strategy_mint"),
        # The forward-outcome beat's own query: rows old enough for a horizon
        # whose columns are still null.
        Index("ix_rafiq_lab_candidates_decided", "decided_at"),
        Index("ix_rafiq_lab_candidates_outcome", "outcome", "reject_reason"),
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
    #: When the Radar admitted it, and when this book judged it.
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    #: `entered` or `rejected`. Nothing else.
    outcome: Mapped[str] = mapped_column(String(8), nullable=False)
    #: The first condition that refused it, `None` when it entered. Covers the
    #: cheap filters as well as the gate, because "we never looked at it" and
    #: "we looked and the pool was thin" are different rejections.
    reject_reason: Mapped[str | None] = mapped_column(String(48))
    #: The position it opened, when it entered. Kept as a link rather than a
    #: duplicated P&L so the two tables can never disagree.
    position_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rafiq_lab_positions.id", ondelete="SET NULL"),
    )

    # --- the market as the decision saw it -------------------------------
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    price_usd: Mapped[Decimal | None] = mapped_column(_PRICE)
    liquidity_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    market_cap_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    volume_m5: Mapped[Decimal | None] = mapped_column(_MONEY)
    liquidity_change_15m: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    opportunity_score: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    #: Unique buyers and sellers, trade counts, and the top-10 transaction
    #: share, from `wallet_flow_snapshots`. JSONB because the whole group is
    #: absent together whenever that collector is off, and five null columns
    #: say the same thing less clearly than one absent key set.
    flow: Mapped[dict | None] = mapped_column(JSONB)

    # --- what the sizing and the gate made of it -------------------------
    #: `None` when the candidate was refused before sizing ran.
    notional_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    stop_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    entry_impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))

    # --- the two instrumented features, same source as the position row --
    safety_status: Mapped[str | None] = mapped_column(String(16))
    safety_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    top10_holder_pct: Mapped[Decimal | None] = mapped_column(Numeric(9, 4))
    top10_captured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    lp_status: Mapped[str | None] = mapped_column(String(16))
    lp_reason_codes: Mapped[list | None] = mapped_column(JSONB)
    lp_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    features_error: Mapped[str | None] = mapped_column(String(64))

    # --- forward outcomes, written by the beat once each horizon closes ---
    # Returns against `price_usd`, from `token_market_snapshots` alone: the
    # platform already prices every admitted token about every sixteen
    # seconds, so no external endpoint is called and none can rate-limit this.
    # `dead` is the horizon's last observed liquidity below $1,000.
    max_return_1h: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    final_return_1h: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    dead_1h: Mapped[bool | None] = mapped_column(Boolean)
    max_return_6h: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    final_return_6h: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    dead_6h: Mapped[bool | None] = mapped_column(Boolean)
    max_return_24h: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    final_return_24h: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    dead_24h: Mapped[bool | None] = mapped_column(Boolean)
    #: Which horizons have been attempted, so a token that stopped printing
    #: is not retried for ever. `{"1h": "2026-09-12T...", "6h": null}` — a key
    #: with a null value is an attempt that found no snapshots at all.
    outcomes_attempted: Mapped[dict | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
