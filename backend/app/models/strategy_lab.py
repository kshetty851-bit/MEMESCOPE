"""Strategy Lab persistence. **Its own tables, and never anyone else's.**

Seven tables, all prefixed `strategy_lab_`. Not a discriminator column on
`paper_positions`, and not a second lineage in `paper_wallets`, for the reason
`paper_v2` gives for the same choice: a shared table makes isolation a property
of every query anyone writes from now on, and one forgotten `WHERE` clause puts
a research rug into a wallet's equity. Separate tables make isolation a property
of the schema, which nobody can forget.

Nothing here has a foreign key into `paper_*`, `real_wallet_*`, or any table a
wallet writes. The only outward reference is `strategy_lab_opportunities
.source_decision_id`, which points at a Radar *decision* — an immutable audit
row that no wallet owns.

── WHAT IS STORED RATHER THAN DERIVED, AND WHY ──────────────────────────────

Cash, equity and P&L are derived from fills, exactly as V1 and V2 derive theirs.
Three things are stored, and each is stored because recomputing it would be
wrong rather than merely slow:

  * **`filled_rungs`** — a rung is a one-time event. A resume that re-derived
    which rungs had fired from the price series would fire every one of them
    again on the next pass.
  * **`trail_armed` / `trail_high`** — the running high is path-dependent and
    the series a resume can see may start after the high was set.
  * **`fired_decay`** — a decay rule is evaluated once at its own deadline.

Together they are what makes forward research idempotent across a restart.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_PRICE = Numeric(38, 18)
_MONEY = Numeric(24, 4)
_QUANTITY = Numeric(48, 18)
_RATIO = Numeric(20, 8)


class StrategyLabRun(Base):
    """One replay batch, and the dataset it ran over. Provenance, not results.

    Exists so a leaderboard can say *which* population it was computed on. A
    figure without its candidate count, its date range and its exclusion
    reasons is not a research result.
    """

    __tablename__ = "strategy_lab_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    mode: Mapped[str] = mapped_column(String(24), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canonical_version: Mapped[str] = mapped_column(String(16), nullable=False)
    metrics_version: Mapped[str] = mapped_column(String(16), nullable=False)
    rules_version: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dataset_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    candidates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    usable: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    excluded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: `{reason: count}`. Every excluded candidate is counted under exactly one.
    exclusions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    venues: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_strategy_lab_runs_started", "started_at"),)


class StrategyLabStrategy(Base):
    """A registered, versioned definition. **Immutable once it has results.**

    `definition_hash` is computed from the literals in `strategy_lab.strategies`
    and stored here on first registration. Re-registering the same id+version
    with a different hash is rejected, which is what makes §17's rule a
    constraint rather than a promise: changing a threshold forces a new version
    number, and results already published under the old one keep meaning what
    they meant.
    """

    __tablename__ = "strategy_lab_strategies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    strategy_id: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(96), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    entry_size_usd: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The canonical dict the hash was taken over. Stored so a mismatch can be
    #: diagnosed rather than merely detected.
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    benchmark: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("strategy_id", "version", name="uq_strategy_lab_strategy_version"),
    )


class StrategyLabOpportunity(Base):
    """A canonical opportunity, frozen. **One row per mint, ever.**

    Every column above `created_at` is point-in-time evidence captured at
    `eligible_at`. Nothing here is ever updated after insert — a backfilled
    field would be exactly the look-ahead the whole design exists to prevent —
    and `uq_strategy_lab_opportunity_mint` is what stops a token being offered
    twice.
    """

    __tablename__ = "strategy_lab_opportunities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    #: `radar_decision_snapshots.id`. Not a foreign key: Strategy Lab must stay
    #: readable if Radar's audit rows are ever pruned, and a research result
    #: that vanished with its source row would be worse than an orphaned id.
    source_decision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    eligible_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    entry_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    liquidity_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    market_cap: Mapped[Decimal | None] = mapped_column(_MONEY)
    liq_to_mcap: Mapped[Decimal | None] = mapped_column(_RATIO)
    volume_24h: Mapped[Decimal | None] = mapped_column(_MONEY)
    volume_1h: Mapped[Decimal | None] = mapped_column(_MONEY)
    buys_24h: Mapped[int | None] = mapped_column(Integer)
    sells_24h: Mapped[int | None] = mapped_column(Integer)
    buy_sell_ratio_24h: Mapped[Decimal | None] = mapped_column(_RATIO)
    pool_address: Mapped[str | None] = mapped_column(String(44))
    venue: Mapped[str | None] = mapped_column(String(64))
    trading_pair: Mapped[str | None] = mapped_column(String(96))

    #: Time since **first discovery by this platform**, not since token
    #: creation. Named for what it measures; S9's gate reads it and its
    #: docstring states the limitation.
    discovery_age_seconds: Mapped[Decimal | None] = mapped_column(Numeric(20, 3))
    first_discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    radar_rank: Mapped[int | None] = mapped_column(Integer)
    radar_score: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    risk_score: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    risk_band: Mapped[str | None] = mapped_column(String(32))

    security_status: Mapped[str | None] = mapped_column(String(16))
    security_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    observation_cadence_seconds: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    radar_input_snapshot_count: Mapped[int | None] = mapped_column(Integer)
    evidence_coverage_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))

    canonical_version: Mapped[str] = mapped_column(String(16), nullable=False)
    #: `None` while the opportunity is usable. Set once, at insert.
    excluded_reason: Mapped[str | None] = mapped_column(String(48))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("mint_address", name="uq_strategy_lab_opportunity_mint"),
        Index("ix_strategy_lab_opportunities_eligible", "eligible_at"),
        Index("ix_strategy_lab_opportunities_source", "source_decision_id"),
    )


class StrategyLabWallet(Base):
    """One strategy's simulated money. **Simulated. Never a real balance.**

    A wallet exists per (strategy, version, mode), so the historical replay and
    the forward record are separate books that can never be summed by accident.
    """

    __tablename__ = "strategy_lab_wallets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy_lab_runs.id", ondelete="CASCADE")
    )
    strategy_id: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: `BACKTEST` or `FORWARD_RESEARCH`. Never a live value — `LabState` has no
    #: live member, so no row can carry one.
    mode: Mapped[str] = mapped_column(String(24), nullable=False)
    starting_balance: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    entry_size_usd: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    cash: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)

    #: **Running scalars, never truncated.** Drawdown is a primary input to the
    #: ranking, so it is maintained exactly and incrementally rather than
    #: recomputed from a curve that gets shortened for display.
    peak_equity: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=Decimal(0))
    max_drawdown_pct: Mapped[Decimal] = mapped_column(
        Numeric(9, 4), nullable=False, default=Decimal(0)
    )
    #: `[[iso8601, equity], ...]` for the chart only, most recent first-trimmed
    #: to `EQUITY_CURVE_POINTS`. Losing an old point costs a pixel, never a
    #: metric — see `peak_equity` above.
    #: ponytail: JSONB curve capped at ~6 weeks of 15-minute points; move to a
    #: time-series table if a longer chart is ever wanted.
    equity_curve: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "strategy_id", "version", "mode", "run_id", name="uq_strategy_lab_wallet"
        ),
        Index("ix_strategy_lab_wallets_mode", "mode"),
    )


class StrategyLabPosition(Base):
    """One simulated trade. Opens once per (wallet, opportunity) and never again."""

    __tablename__ = "strategy_lab_positions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("strategy_lab_wallets.id", ondelete="CASCADE"),
        nullable=False,
    )
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("strategy_lab_opportunities.id", ondelete="CASCADE"),
        nullable=False,
    )
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    size_usd: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    initial_quantity: Mapped[Decimal] = mapped_column(_QUANTITY, nullable=False)
    remaining_quantity: Mapped[Decimal] = mapped_column(_QUANTITY, nullable=False)
    entry_cost: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    entry_liquidity_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    venue: Mapped[str | None] = mapped_column(String(64))
    pool_address: Mapped[str | None] = mapped_column(String(44))

    #: Idempotency state. See the module docstring — these three are stored
    #: because re-deriving them across a restart would be wrong, not slow.
    filled_rungs: Mapped[list[int]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    fired_decay: Mapped[list[int]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    trail_armed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    trail_high: Mapped[Decimal | None] = mapped_column(_PRICE)

    observed_peak_multiple: Mapped[Decimal | None] = mapped_column(_RATIO)
    executable_peak_multiple: Mapped[Decimal | None] = mapped_column(_RATIO)
    terminal_multiple: Mapped[Decimal | None] = mapped_column(_RATIO)
    batch_rung_fills: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: How far the forward evaluator has read this position's series. The
    #: resume point, and the reason a restart cannot replay an observation
    #: twice.
    evaluated_through: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_reason: Mapped[str | None] = mapped_column(String(32))
    unsettled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("wallet_id", "opportunity_id", name="uq_strategy_lab_position"),
        Index("ix_strategy_lab_positions_wallet_open", "wallet_id", "closed_at"),
        Index("ix_strategy_lab_positions_mint", "mint_address"),
        Index("ix_strategy_lab_positions_opened", "opened_at"),
    )


class StrategyLabFill(Base):
    """One partial or final sale. A position has many.

    `sequence` is the position-scoped ordinal and carries the uniqueness
    constraint. Without it a restart that re-evaluated one observation would
    insert the same fill twice and book its proceeds twice.
    """

    __tablename__ = "strategy_lab_fills"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    position_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("strategy_lab_positions.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(24), nullable=False)
    price_usd: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(_QUANTITY, nullable=False)
    liquidity_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    rung_indexes: Mapped[list[int]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    trigger_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    #: Both are stored. §7: never present gross as net.
    gross_proceeds: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    execution_cost: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    net_proceeds: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("position_id", "sequence", name="uq_strategy_lab_fill_sequence"),
        Index("ix_strategy_lab_fills_position", "position_id"),
        Index("ix_strategy_lab_fills_at", "filled_at"),
    )


class StrategyLabRefusal(Base):
    """An opportunity a strategy did not take, and why. **Never silent.**

    Recorded because "capital blocked" and "opportunities the gate refused" are
    two of the figures under test, and a strategy that skipped quietly would
    report a capture rate it had not earned.
    """

    __tablename__ = "strategy_lab_refusals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("strategy_lab_wallets.id", ondelete="CASCADE"),
        nullable=False,
    )
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("strategy_lab_opportunities.id", ondelete="CASCADE"),
        nullable=False,
    )
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    refused_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(48), nullable=False)
    cash_at_refusal: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    #: Filled in from the series afterwards, for reporting only. It was not
    #: available when the refusal was made and could not have changed it.
    peak_multiple: Mapped[Decimal | None] = mapped_column(_RATIO)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("wallet_id", "opportunity_id", name="uq_strategy_lab_refusal"),
        Index("ix_strategy_lab_refusals_wallet", "wallet_id", "reason"),
    )
