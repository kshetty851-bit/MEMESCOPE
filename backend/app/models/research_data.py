"""V4 Phase 2 research-data tables: collect information before decisions.

Every table here is instrumentation. None of them is read by a trading rule,
and none of them may be — the V4 verdict is NO VALIDATED EDGE, and this schema
exists so a *future* research round can decide the entry question honestly.

Design rules, inherited from what went wrong before:

* **Flat scalar columns, never a 15 KB JSON blob per row.** The one table that
  ignored this (`radar_decision_snapshots`) wrote 79% of all production bytes.
  JSONB appears only where the value is genuinely a small document (an audit
  of excluded holder addresses, an hourly telemetry payload).
* **Point-in-time by construction.** Rows carry the moment they describe and
  are never updated with later knowledge; anything derived (executable
  outcomes) names its method version so a recomputation is a new fact, not a
  silent rewrite.
* **Provenance beats convenience.** Raw provider readings are annotated
  (`suspect`, on the snapshot table), never deleted or overwritten.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

PCT = Numeric(8, 4)
SHARE = Numeric(8, 6)
MONEY = Numeric(24, 4)
PRICE = Numeric(38, 18)


class NurseryAdmission(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """The lifecycle split between DISCOVERY and TRADING ELIGIBILITY.

    One row per token that scored well enough for the Radar while younger than
    the observation window. The row records what was decided at the window,
    when — and separately whether an admission ever actually happened, so a
    token rejected at its window and admitted hours later shows both facts
    rather than a rewritten one.
    """

    __tablename__ = "nursery_admissions"

    token_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("discovered_tokens.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False, index=True)
    entered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    #: 'observing' -> exactly one of 'qualified' / 'rejected' / 'expired'.
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="observing"
    )
    #: The observation window that applied when this token entered — recorded
    #: per row because the setting can change and history must stay readable.
    window_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Radar score at entry, for later comparison with the score at decision.
    entry_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decision_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Set when a Radar admission actually happened, whatever the window said.
    admitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('observing','qualified','rejected','expired')",
            name="ck_nursery_admissions_status",
        ),
        Index("ix_nursery_admissions_status_entered", "status", "entered_at"),
    )


class WalletFlowSnapshot(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Point-in-time wallet-participation primitives from the trade stream.

    Written by the scanner from its in-memory `WalletFlowTracker`. Two windows
    per row (5m, 1h) as flat columns. `key` is the mint when the chain named
    one (pump.fun) and the pool otherwise (PumpSwap); resolving pool->mint is
    the reader's join, never a socket-loop query.
    """

    __tablename__ = "wallet_flow_snapshots"

    key: Mapped[str] = mapped_column(String(44), nullable=False)
    key_kind: Mapped[str] = mapped_column(String(4), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    w5m_unique_buyers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    w5m_unique_sellers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    w5m_unique_wallets: Mapped[int | None] = mapped_column(Integer, nullable=True)
    w5m_buy_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    w5m_sell_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    w5m_buy_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    w5m_sell_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    w5m_tx_per_wallet: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    w5m_repeat_wallet_ratio: Mapped[Decimal | None] = mapped_column(SHARE, nullable=True)
    w5m_top5_tx_share: Mapped[Decimal | None] = mapped_column(SHARE, nullable=True)
    w5m_top10_tx_share: Mapped[Decimal | None] = mapped_column(SHARE, nullable=True)
    w5m_top5_volume_share: Mapped[Decimal | None] = mapped_column(SHARE, nullable=True)
    w5m_top10_volume_share: Mapped[Decimal | None] = mapped_column(SHARE, nullable=True)
    w5m_largest_buyer_share: Mapped[Decimal | None] = mapped_column(SHARE, nullable=True)
    w5m_largest_seller_share: Mapped[Decimal | None] = mapped_column(SHARE, nullable=True)
    w5m_quality: Mapped[str | None] = mapped_column(String(8), nullable=True)

    w1h_unique_buyers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    w1h_unique_sellers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    w1h_unique_wallets: Mapped[int | None] = mapped_column(Integer, nullable=True)
    w1h_buy_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    w1h_sell_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    w1h_buy_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    w1h_sell_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    w1h_tx_per_wallet: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    w1h_repeat_wallet_ratio: Mapped[Decimal | None] = mapped_column(SHARE, nullable=True)
    w1h_top5_tx_share: Mapped[Decimal | None] = mapped_column(SHARE, nullable=True)
    w1h_top10_tx_share: Mapped[Decimal | None] = mapped_column(SHARE, nullable=True)
    w1h_top5_volume_share: Mapped[Decimal | None] = mapped_column(SHARE, nullable=True)
    w1h_top10_volume_share: Mapped[Decimal | None] = mapped_column(SHARE, nullable=True)
    w1h_largest_buyer_share: Mapped[Decimal | None] = mapped_column(SHARE, nullable=True)
    w1h_largest_seller_share: Mapped[Decimal | None] = mapped_column(SHARE, nullable=True)
    w1h_quality: Mapped[str | None] = mapped_column(String(8), nullable=True)

    __table_args__ = (
        CheckConstraint("key_kind IN ('mint','pool')", name="ck_wallet_flow_key_kind"),
        Index("ix_wallet_flow_snapshots_key_captured", "key", "captured_at"),
    )


class HolderSnapshot(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Point-in-time holder distribution, with its exclusions on the record.

    `accounts` keeps the raw provider top-20 so the derived percentages can be
    re-audited; `excluded` names every address removed from the economic set
    and why. A wrong exclusion is then a visible mistake, not a silent one.
    """

    __tablename__ = "holder_snapshots"

    token_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("discovered_tokens.id", ondelete="CASCADE"),
        nullable=True,
    )
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    #: Why this snapshot was taken (nursery_entry / window_end / admission).
    context: Mapped[str] = mapped_column(String(16), nullable=False)

    supply_raw: Mapped[Decimal | None] = mapped_column(Numeric(40, 0), nullable=True)
    decimals: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    top1_pct: Mapped[Decimal | None] = mapped_column(PCT, nullable=True)
    top5_pct: Mapped[Decimal | None] = mapped_column(PCT, nullable=True)
    top10_pct: Mapped[Decimal | None] = mapped_column(PCT, nullable=True)
    creator_pct: Mapped[Decimal | None] = mapped_column(PCT, nullable=True)
    largest_nonpool_pct: Mapped[Decimal | None] = mapped_column(PCT, nullable=True)
    accounts: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    excluded: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_holder_snapshots_mint_captured", "mint_address", "captured_at"),
    )


class ResearchQuote(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Execution truth for candidates the wallets did NOT trade.

    The research set must be able to tell GOOD OUTCOME BUT NOT EXECUTABLE from
    GOOD OUTCOME AND EXECUTABLE, and only a real router quote can say which.
    Sampled, budgeted, and stored raw.
    """

    __tablename__ = "research_quotes"

    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    token_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("discovered_tokens.id", ondelete="CASCADE"),
        nullable=True,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    size_usd: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    in_amount_raw: Mapped[Decimal | None] = mapped_column(Numeric(30, 0), nullable=True)
    out_amount_raw: Mapped[Decimal | None] = mapped_column(Numeric(30, 0), nullable=True)
    price_impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    route: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Market context at request time, from the latest stored snapshot.
    price_usd_at: Mapped[Decimal | None] = mapped_column(PRICE, nullable=True)
    liquidity_usd_at: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    context: Mapped[str] = mapped_column(String(24), nullable=False)

    __table_args__ = (
        CheckConstraint("side IN ('buy','sell')", name="ck_research_quotes_side"),
        Index("ix_research_quotes_mint_requested", "mint_address", "requested_at"),
    )


class RegimeSnapshot(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Hourly telemetry, two kinds kept deliberately apart.

    `population` describes the pipeline (admission rate, ages, SLA health) —
    things a scanner deploy changes. `market` describes the world (SOL/USD,
    launch activity, liquidity) — things it cannot. Conflating them is how the
    Aug-21 deploy was misread as a market event.
    """

    __tablename__ = "regime_snapshots"

    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        CheckConstraint("kind IN ('population','market')", name="ck_regime_snapshots_kind"),
    )


class RadarExecutableOutcome(Base, TimestampMixin):
    """Derived executable truth beside — never instead of — the raw record.

    The raw Track Record aggregates provider prints, glitches included, and is
    immutable. This table holds what a $10 position could actually have done,
    under the calibrated execution model, suspects excluded. `method_version`
    makes any recomputation a visible new fact.
    """

    __tablename__ = "radar_executable_outcomes"

    radar_token_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("radar_tokens.id", ondelete="CASCADE"),
        primary_key=True,
    )
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    method_version: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Peak of the *sellable* value per $1 in, fees and calibrated impact paid.
    executable_peak_multiple: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    reached_125_24h: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    reached_2x_24h: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    reached_2x_72h: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    final_value_frac_24h: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    #: Whether the 24h horizon has fully elapsed inside stored data.
    decided_24h: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    snapshots_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    suspects_excluded: Mapped[int | None] = mapped_column(Integer, nullable=True)


class JupiterUniverseSnapshot(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Daily point-in-time capture of Jupiter's verified list.

    Exists so a future study of established tokens has the universe *as it
    stood on each day*, not as it stands when the study runs — the
    survivorship trap V2 documented and could not fix retroactively.
    """

    __tablename__ = "jupiter_universe_snapshots"

    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    liquidity_usd: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    market_cap: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    holder_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    organic_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)

    __table_args__ = (
        UniqueConstraint("snapshot_date", "mint_address", name="uq_universe_date_mint"),
        Index("ix_jupiter_universe_snapshot_date", "snapshot_date"),
    )
