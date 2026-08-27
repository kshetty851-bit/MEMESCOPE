"""The Karthik paper wallet's own storage.

Three tables, none of them shared with the Original Paper Wallet. That is the
point of the module rather than an implementation detail: Karthik is a second,
deliberately simpler experiment running beside the first, and the two must be
impossible to confuse in a query, a migration or a report.

Sharing `paper_wallets` was considered and refused for two reasons, either of
which is sufficient:

* `uq_paper_wallets_live` is a unique index on `(true) WHERE archived_at IS
  NULL` — **exactly one live paper wallet may exist**. Making room for Karthik
  there means weakening the constraint that guarantees the Original wallet's
  figures are the only figures, which is a change to the Original wallet.
* Karthik's capital must never be reachable from the Original wallet's cash
  computation. Separate tables make that a fact about the schema instead of a
  promise about a `WHERE` clause.

Like the paper wallet, **nothing here stores a balance**. Cash, equity and P&L
are derived from these rows at read time, because a stored balance is a second
source of truth that drifts the moment one write lands without the other.

**Nothing here touches a chain.** A position is a row recording what a published
rule would have done, with no wallet, no order and no custody of anything.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

#: Matches `token_market_snapshots.price_usd`, so a price round-trips unchanged.
_PRICE = Numeric(38, 18)
_MONEY = Numeric(24, 4)
#: Price-scaled: $10 of a token at 4.8e-10 is a very large number of units, and
#: rounding it would misreport the exit value.
_QUANTITY = Numeric(48, 18)
_PCT = Numeric(20, 4)
_JSON = JSONB().with_variant(JSON(), "sqlite")


class KarthikWallet(Base):
    """The single Karthik wallet, created once by a deliberate activation.

    `activated_at` is the whole eligibility rule. A Track Record admission is
    Karthik's to trade only if it was admitted **after** this instant, so the
    column is written once at activation and never updated — the same write-once
    contract `radar_tokens.first_*` holds, and for the same reason: a watermark
    that could move could be moved backwards, and backfill would look identical
    to forward trading in the resulting book.

    `starting_capital` is copied onto the row rather than read from settings at
    display time, so changing the setting later cannot restate a published
    return.
    """

    __tablename__ = "karthik_wallets"
    __table_args__ = (
        # **Exactly one Karthik wallet exists, ever.** A constant expression
        # with a unique index is the standard way to say "at most one row", and
        # it is what makes "activate once" a fact rather than an instruction in
        # a runbook. A second activation is refused by the database.
        Index("uq_karthik_wallets_singleton", text("(true)"), unique=True),
        Index("ix_karthik_wallets_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    #: Shown on the page. Stored so the wallet names itself rather than the UI
    #: naming it, which is what keeps an API response self-describing.
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    starting_capital: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    #: The fixed order size, pinned at activation for the same reason the
    #: starting capital is: the book must remain readable against the rule that
    #: produced it.
    trade_size: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    #: The take-profit multiple, pinned at activation. 1.25.
    take_profit_multiple: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class KarthikOpportunity(Base):
    """One irreversible decision per Track Record admission.

    This table is the exactly-once guarantee, and it is a guarantee because the
    **database** holds it: `uq_karthik_opportunities_wallet_mint` means a
    duplicate Track Record event, a retried task, a restarted worker and two
    concurrent passes all collapse to one row. The service inserts with `ON
    CONFLICT DO NOTHING` and reads back whether it won; nothing relies on an
    in-process lock.

    It also records the *misses*, which is why it is a separate table from
    `karthik_positions` rather than a status on it. An opportunity that arrived
    when the wallet held less than one trade size is a permanent skip — it is
    never queued and never revisited — and an experiment that silently dropped
    those would report a capture rate it had not earned.
    """

    __tablename__ = "karthik_opportunities"
    __table_args__ = (
        # One decision per mint per wallet, **ever**. The published rule is
        # "at most one Karthik entry per new Track Record token"; this is that
        # rule expressed as a state the database cannot represent twice.
        UniqueConstraint(
            "wallet_id", "mint_address", name="uq_karthik_opportunities_wallet_mint"
        ),
        # How the page reads, and how the entry scan finds undecided admissions.
        Index("ix_karthik_opportunities_wallet_seen", "wallet_id", "track_record_at"),
        Index("ix_karthik_opportunities_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("karthik_wallets.id", ondelete="CASCADE"),
        nullable=False,
    )
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    #: `radar_tokens.first_detected_at` — the moment the token entered the Track
    #: Record, which is the moment that decides eligibility. Copied here so the
    #: ledger stays readable if the Radar row is ever reclassified.
    track_record_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: `entered` | `skipped_insufficient_cash` | `skipped_no_market`.
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class KarthikPosition(Base):
    """One simulated Karthik trade, from entry to close.

    The entry block is written once and never updated, including
    `target_price`. **Fixing the target at entry is the anti-hindsight
    guarantee**: a target that could be recomputed later could be recomputed
    favourably, and the difference would be invisible in the result.

    Only the evaluator's columns move — the running peak, the watermarks, and
    the closing block.
    """

    __tablename__ = "karthik_positions"
    __table_args__ = (
        # One position per token per wallet, **ever**. The second constraint
        # behind exactly-once: even if the opportunity ledger were bypassed, the
        # database still cannot hold two Karthik entries in the same mint.
        UniqueConstraint("wallet_id", "mint_address", name="uq_karthik_positions_wallet_mint"),
        # The evaluator's working set: open positions, oldest watermark first,
        # which is what stops a growing book from starving its own tail.
        Index(
            "ix_karthik_positions_open_watermark",
            "wallet_id",
            "last_evaluated_at",
            postgresql_where="status = 'open'",
        ),
        Index("ix_karthik_positions_closed_at", "wallet_id", "closed_at"),
        Index("ix_karthik_positions_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("karthik_wallets.id", ondelete="CASCADE"),
        nullable=False,
    )
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    token_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("discovered_tokens.id", ondelete="SET NULL")
    )
    symbol: Mapped[str | None] = mapped_column(String(32))
    token_name: Mapped[str | None] = mapped_column(String(128))

    # --- The three moments, and never a substitute for one of them ----------
    #: When MEMESCOPE first saw the mint at all — the minimum of
    #: `discovered_tokens.discovered_at` and the earliest transport observation.
    #: **Null when no discovery row supports it.** It is never filled with the
    #: entry time or with the Track Record time: those are different facts, and
    #: an entry delay measured against a substitute would be fiction.
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: When the token entered the Track Record. This is the eligibility clock.
    track_record_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: When Karthik bought.
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # --- Written once at entry, never updated -------------------------------
    entry_price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    #: The market price that triggered the decision, kept separate from the
    #: execution estimate above so a reader can see what each one contributed.
    entry_observed_price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    #: The observation the decision was made from. Distinct from `opened_at`:
    #: this is when the market was seen, that is when Karthik acted on it.
    entry_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    #: Exactly the trade size. Named for what it is on the books.
    cost_basis: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(_QUANTITY, nullable=False)
    #: Read at entry and stored, so the exit quote never has to find them again
    #: — and so an exit can always be quoted for a position that could be
    #: entered. Without this the sell side would silently fall back.
    decimals: Mapped[int] = mapped_column(Integer, nullable=False)
    target_price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)

    #: The market observed at entry. Perishable — the snapshot carrying them is
    #: prunable — so they are captured here rather than looked up again.
    pool_address: Mapped[str | None] = mapped_column(String(44))
    entry_liquidity_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    entry_market_cap: Mapped[Decimal | None] = mapped_column(_MONEY)

    entry_execution_model_version: Mapped[str | None] = mapped_column(String(64))
    entry_execution_quote: Mapped[dict[str, object] | None] = mapped_column(_JSON)
    entry_execution_price_impact_pct: Mapped[Decimal | None] = mapped_column(_PCT)
    entry_execution_fee_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    entry_execution_route: Mapped[str | None] = mapped_column(Text)
    entry_execution_confidence: Mapped[str | None] = mapped_column(String(32))
    entry_execution_fallback_reason: Mapped[str | None] = mapped_column(Text)

    # --- Moved by the evaluator ---------------------------------------------
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    #: Highest price observed while open. Carried forward rather than
    #: recomputed, so it survives snapshot pruning — and so a spike that was
    #: never executable at the target is still visible as a spike.
    peak_price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    #: How far the observation series has been walked.
    last_evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    #: When a quote was last *attempted*, whether or not one was returned.
    #: Separate from `last_evaluated_at`, which implies a usable observation.
    last_market_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    exit_observed_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    #: What the sale actually returned to cash. On a `dead_zero` close this is
    #: zero, and zero is the claim: nothing could be sold.
    exit_proceeds_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    #: `target_1_25x` | `dead_zero`. There are no other ways out — no stop, no
    #: expiry, no manual override.
    exit_reason: Mapped[str | None] = mapped_column(String(16))
    exit_execution_model_version: Mapped[str | None] = mapped_column(String(64))
    exit_execution_quote: Mapped[dict[str, object] | None] = mapped_column(_JSON)
    exit_execution_price_impact_pct: Mapped[Decimal | None] = mapped_column(_PCT)
    exit_execution_fee_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    exit_execution_route: Mapped[str | None] = mapped_column(Text)
    exit_execution_confidence: Mapped[str | None] = mapped_column(String(32))
    exit_evidence: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
