"""Paper wallet persistence.

Two tables, and deliberately only two. Everything else the wallet reports —
cash, equity, ROI, win rate, drawdown — is **derived** from these rows and from
`token_market_snapshots` at read time.

That is the design rule, not an optimisation. A stored balance is a second
source of truth that drifts from its positions the moment one write lands
without the other, and a wallet whose balance disagrees with its own trades is
worth less than no wallet at all. Prices are never copied here either: the
market already stores them, and a second copy could disagree with the first.

There is no `paper_strategies` table. Strategies are code in
`app/paper/strategy.py`, published through the API — a row describing a rule
could disagree with the rule the simulation actually applied, and a reader would
have no way to tell which one produced the trades.

**Nothing here touches a chain.** A position is a row recording what a published
rule would have done, with no wallet, no order and no custody of anything.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

#: Matches `token_market_snapshots.price_usd`, so a price round-trips unchanged.
_PRICE = Numeric(38, 18)
_MONEY = Numeric(24, 4)
#: Quantity is price-scaled: a $100 position in a token at 4.8e-10 is a very
#: large number of units, and rounding it would misreport the exit value.
_QUANTITY = Numeric(48, 18)


class PaperWallet(Base):
    """One wallet per strategy.

    Not per user. The strategy is entirely mechanical — it enters on the Radar's
    own ranking and exits on rules fixed at entry, with no manual step anywhere —
    so a per-user wallet would hold rows identical to every other user's. That is
    duplicated data with no added truth.

    One wallet per strategy also makes this a *published* track record: the
    numbers a reader sees are the numbers everyone sees, and they can be checked
    against the same positions. Per-user wallets become meaningful when
    strategies become user-configurable, and not before.
    """

    __tablename__ = "paper_wallets"
    __table_args__ = (
        # One wallet per strategy, enforced by the database. Two wallets running
        # the same rules would double every trade and halve every figure.
        UniqueConstraint("strategy_id", name="uq_paper_wallets_strategy"),
        Index("ix_paper_wallets_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    #: The strategy in `app/paper/strategy.py` whose rules this wallet follows.
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Pinned at creation so a later change to the strategy's version is visible
    #: as a difference rather than silently rewriting the wallet's history.
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Configurable, and written once. Every return is measured against it, so
    #: editing it later would restate results that were already published.
    starting_balance: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PaperPosition(Base):
    """One simulated trade, from entry to close.

    The entry block — `opened_at`, `entry_price`, `size_usd`, `quantity`,
    `target_price`, `stop_price`, `expires_at` — is written once and never
    updated. **Fixing the exits at entry is the anti-hindsight guarantee.** A
    target that could be recomputed later could be recomputed favourably, and
    the difference is invisible in the result.

    Only the evaluator's own columns move: the running peak, the watermark, and
    the closing block.
    """

    __tablename__ = "paper_positions"
    __table_args__ = (
        # One position per token per wallet, **ever**. This is the published
        # entry rule expressed as a constraint: the strategy buys a token the
        # *first* time it reaches the top ten, so re-entry is not a policy the
        # application enforces, it is a state the database cannot represent.
        UniqueConstraint("wallet_id", "mint_address", name="uq_paper_positions_wallet_mint"),
        # The evaluator's own working set: open positions, oldest watermark
        # first. Partial, because closed rows are never re-evaluated and there
        # will eventually be far more of them.
        Index(
            "ix_paper_positions_open_watermark",
            "wallet_id",
            "last_evaluated_at",
            postgresql_where="status = 'open'",
        ),
        # The closed record, newest first — how the positions page reads.
        Index("ix_paper_positions_closed_at", "wallet_id", "closed_at"),
        Index("ix_paper_positions_mint", "mint_address"),
        # `TimestampMixin` is not used here, but `created_at` still needs its
        # index declared or `alembic check` fails on the next autogenerate.
        Index("ix_paper_positions_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("paper_wallets.id", ondelete="CASCADE"), nullable=False
    )
    #: Denormalised from `radar_tokens` deliberately: a position must stay
    #: readable as a record even if the Radar row it came from is one day
    #: reclassified, and the mint is the only permanent identifier a token has.
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    token_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("discovered_tokens.id", ondelete="SET NULL")
    )

    # --- Written once at entry, never updated -------------------------------

    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: The Radar place the token held when it was bought. Stored because the
    #: entry rule is stated in terms of it, so a reader can check the trade
    #: against the rule without reconstructing a past ranking.
    entry_rank: Mapped[int] = mapped_column(nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    size_usd: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(_QUANTITY, nullable=False)
    target_price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    stop_price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # --- Moved by the evaluator ---------------------------------------------

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    #: Highest price observed while the position was open. Carried forward
    #: rather than recomputed, so it survives snapshot pruning — a peak that was
    #: observed once is a fact and must not shrink when its row ages out.
    peak_price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    #: How far the observation series has been walked. Exits are resolved from
    #: every reading after this point, in order, which is what makes the result
    #: independent of when the evaluator ran.
    last_evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    #: `target` | `stop` | `expiry`. There is no `manual`: nothing may close a
    #: position for a reason a reader cannot check against the published rule.
    exit_reason: Mapped[str | None] = mapped_column(String(16))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
