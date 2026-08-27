"""Paper Wallet V2 persistence. **Separate tables, on purpose.**

V2 could have been a discriminator column on `paper_positions`. It is not, and
the reason is the requirement that made it: V1 and V2 must not be able to
contaminate each other's capital. A shared table makes isolation a property of
every query anyone writes from now on — one forgotten `WHERE wallet_kind = ...`
and a V2 rug lands in V1's equity. Separate tables make isolation a property of
the schema, which nobody can forget.

The cost is duplicated column definitions. That is the cheaper mistake.

Two differences from V1's shape, both forced by the ladder:

  * **A position has many exits.** `paper_v2_fills` is a child table rather than
    `target_1_*`, `target_2_*`, `target_3_*` columns, because the number of
    exits is a property of the rule and the rules are still being chosen. Four
    fixed slots would have to be widened the first time a ladder gets a fifth
    rung.
  * **`remaining_quantity` is stored, not derived.** It is the one figure a
    restart must not recompute from prices: re-deriving which rungs had fired
    would fire them all again. `filled_rungs` is stored for the same reason.

Everything else — cash, equity, P&L — stays derived from these rows, exactly as
V1 derives its own. **Nothing here touches a chain.**
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

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


class PaperV2Wallet(Base):
    """The V2 wallet. One live row, like V1 — and never in V1's lineage."""

    __tablename__ = "paper_v2_wallets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    #: Human name. "Paper Wallet V2" — deliberately not a generation number, so
    #: it can never be mistaken for the next generation of the original wallet.
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    #: New simulated capital. Never inherited from V1.
    starting_balance: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    trade_size_usd: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archive_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # One live V2 wallet, same guarantee V1 has on its own table.
        Index(
            "uq_paper_v2_wallets_live",
            func.cast(True, Boolean),
            unique=True,
            postgresql_where=archived_at.is_(None),
        ),
    )


class PaperV2Position(Base):
    """One V2 trade. Opened once, sold up to four times."""

    __tablename__ = "paper_v2_positions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("paper_v2_wallets.id", ondelete="CASCADE"), nullable=False
    )
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    token_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("discovered_tokens.id", ondelete="SET NULL")
    )

    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    initial_notional: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    initial_quantity: Mapped[Decimal] = mapped_column(_QUANTITY, nullable=False)
    #: Authoritative. Never re-derived from prices — see the module docstring.
    remaining_quantity: Mapped[Decimal] = mapped_column(_QUANTITY, nullable=False)
    #: Rung indices already executed, e.g. `[0, 1]`. The idempotence record.
    filled_rungs: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )

    status: Mapped[str] = mapped_column(String(16), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    final_exit_reason: Mapped[str | None] = mapped_column(String(24))

    entry_liquidity_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    entry_market_cap: Mapped[Decimal | None] = mapped_column(_MONEY)
    entry_cost_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    entry_rank: Mapped[int | None] = mapped_column(Integer)

    #: Why this entry was allowed, copied from the shared upstream gate so V1
    #: and V2 can be compared on identical provenance rather than on trust.
    decision_provenance: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    last_evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("wallet_id", "mint_address", name="uq_paper_v2_positions_wallet_mint"),
        Index("ix_paper_v2_positions_open", "wallet_id", "last_evaluated_at",
              postgresql_where=status == "open"),
        Index("ix_paper_v2_positions_mint", "mint_address"),
    )


class PaperV2Fill(Base):
    """One sale out of a position. Rungs and the final exit both land here."""

    __tablename__ = "paper_v2_fills"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    position_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("paper_v2_positions.id", ondelete="CASCADE"), nullable=False
    )
    #: Index into the ladder's rungs, or NULL for a clock-driven exit.
    rung_index: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(24), nullable=False)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(_QUANTITY, nullable=False)
    #: What was got. For a rung this is the rung's level; for an expiry it is
    #: the observed price. The difference is the execution model, and it is
    #: recorded per fill so a reader can check which convention applied.
    execution_price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    #: What the market actually printed at that instant.
    observed_price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    gross_proceeds: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    fee_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    impact_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    net_proceeds: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    liquidity_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    execution_model_version: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # A rung is a one-time event, enforced by the database and not only by
        # the resolver. Partial unique index: many NULL rung_index rows (the
        # final exits) are legal, one row per rung is not.
        Index(
            "uq_paper_v2_fills_rung",
            "position_id",
            "rung_index",
            unique=True,
            postgresql_where=rung_index.is_not(None),
        ),
        Index("ix_paper_v2_fills_position", "position_id", "filled_at"),
    )
