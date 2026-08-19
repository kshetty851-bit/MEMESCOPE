"""Paper wallet persistence.

Three tables. Everything the wallet *reports* — cash, equity, ROI, win rate,
drawdown — is still **derived** from these rows and from
`token_market_snapshots` at read time.

That is the design rule, not an optimisation. A stored balance is a second
source of truth that drifts from its positions the moment one write lands
without the other, and a wallet whose balance disagrees with its own trades is
worth less than no wallet at all. Prices are never copied onto a *running*
position either: the market already stores them, and a second copy could
disagree with the first.

`paper_trade_audit` is the deliberate exception, and Sprint 30's addition. It
records each **completed** trade once, including the figures that are perishable
rather than derivable: the market cap and pool depth observed at each end, and
the fee and price impact computed against that depth. Those inputs are pruned
with the snapshots that carried them, so a record that only pointed at them
would decay into "unavailable" for exactly the trades furthest in the past. A
derived figure that cannot be re-derived is not derived, it is lost.

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
#: Quantity is price-scaled: a $100 position in a token at 4.8e-10 is a very
#: large number of units, and rounding it would misreport the exit value.
_QUANTITY = Numeric(48, 18)
#: Percentages are reported to two places everywhere else; the audit stores them
#: with room to spare so a 40,000% winner is a figure rather than an overflow.
_PCT = Numeric(20, 4)
#: The trailing fraction, as published: 0.25 is "a quarter back from the high".
_FRACTION = Numeric(6, 4)
#: Basis points, with room for a venue that charges whole percents.
_BPS = Numeric(10, 4)
_JSON = JSONB().with_variant(JSON(), "sqlite")


class PaperWallet(Base):
    """One wallet per *generation* of a strategy.

    Not per user. The strategy is entirely mechanical — it enters on the Radar's
    own ranking and exits on a rule fixed at entry, with no manual step anywhere —
    so a per-user wallet would hold rows identical to every other user's. That is
    duplicated data with no added truth.

    One published wallet also makes this a *checkable* track record: the numbers
    a reader sees are the numbers everyone sees, against the same positions.

    **Sprint 30 made a wallet a generation rather than a singleton.** The
    platform relaunched with fresh capital, and the previous wallet's trades are
    a permanent record that must neither be deleted nor mixed into the new
    figures. So a wallet is archived, never emptied: `archived_at` is set once,
    its positions stay exactly as they were, and every read of the live wallet
    filters to the one row where `archived_at IS NULL`.
    """

    __tablename__ = "paper_wallets"
    __table_args__ = (
        # Identity is (strategy, generation) now that a strategy can be relaunched.
        # The old one-wallet-per-strategy constraint made a reset impossible to
        # represent: archiving a wallet and starting another under the same rules
        # is exactly what Sprint 30 does.
        UniqueConstraint(
            "strategy_id", "generation", name="uq_paper_wallets_strategy_generation"
        ),
        # **Exactly one live wallet exists at a time**, enforced by the database
        # rather than by convention. A constant expression with a partial
        # predicate is the standard way to say "at most one row satisfying this":
        # two live wallets would double every trade and halve every figure, and
        # "the only wallet shown to users" would become an application promise
        # instead of a fact.
        Index(
            "uq_paper_wallets_live",
            text("(true)"),
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
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
    #: Which launch this is, counted across every wallet rather than per
    #: strategy: 1 is the original, 2 the Sprint 30 relaunch. A reader refers to
    #: "the V2 wallet" meaning the second one this platform ran, whatever rules
    #: it followed — numbering per strategy would have made a relaunch under new
    #: rules "v1" again. Stored rather than inferred from `created_at` so an
    #: archived wallet can be named without ordering a table by timestamp.
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: Configurable, and written once. Every return is measured against it, so
    #: editing it later would restate results that were already published.
    starting_balance: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    #: The moment this wallet began. **The benchmarks start here too** — that is
    #: the whole reason it is a column rather than `created_at`: a comparison
    #: drawn from a different instant than the wallet's own start measures a
    #: different period and flatters or punishes the strategy for free.
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    #: Set once, when the wallet is retired. Never cleared: an archived wallet
    #: that could be revived would let a past result re-enter a live figure.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Why it was archived, in the words the internal comparison view prints.
    archive_reason: Mapped[str | None] = mapped_column(Text)
    #: An explicit, one-way boundary used when a historical generation is
    #: deliberately resumed.  Evaluators must ignore every observation before
    #: this instant, even if the position's legacy watermark is older.
    resume_watermark_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: The time the historical record was made live again.  It is published so
    #: readers do not mistake a resumed record for one continuous experiment.
    resumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Preserve the former archive record instead of overwriting history when
    #: `archived_at` is cleared for the explicit, authorised resume.
    restored_archive_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restored_archive_reason: Mapped[str | None] = mapped_column(Text)

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
    #: The market price that triggered the buy decision. For legacy rows this
    #: is null because `entry_price` carried both the decision mark and the
    #: execution assumption. Future Jupiter rows keep the two separate:
    #: decision price here, execution estimate in `entry_price`.
    entry_observed_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    size_usd: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(_QUANTITY, nullable=False)
    #: Which execution model produced the entry quantity/price. Null on legacy
    #: historical rows so adding V2 does not rewrite history.
    entry_execution_model_version: Mapped[str | None] = mapped_column(String(64))
    entry_execution_quote: Mapped[dict[str, object] | None] = mapped_column(_JSON)
    entry_execution_quoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    entry_execution_context_slot: Mapped[int | None] = mapped_column(Integer)
    entry_execution_price_impact_pct: Mapped[Decimal | None] = mapped_column(_PCT)
    entry_execution_fee_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    entry_execution_route: Mapped[str | None] = mapped_column(Text)
    entry_execution_confidence: Mapped[str | None] = mapped_column(String(32))
    entry_execution_fallback_reason: Mapped[str | None] = mapped_column(Text)
    #: Nullable since Sprint 30. The relaunched wallet runs a **trailing stop
    #: only** — no target, no fixed stop, no holding period — so these three
    #: carry no value for its positions and a zero would read as a rule that
    #: exists and sits at zero. The generation-1 rows keep the figures they were
    #: written with; nothing rewrites them.
    target_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    stop_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: The trailing fraction fixed at entry — 0.25 for Trailing Stop 25%. Fixed
    #: here for the same reason a target was: a trailing distance that could be
    #: re-read from configuration after the fact could be re-read favourably.
    trailing_drawdown: Mapped[Decimal | None] = mapped_column(_FRACTION)
    #: Fixed 2x activation gate for the forward experiment.  Null on older
    #: archived strategies which never used activation.
    trailing_activation_multiple: Mapped[Decimal | None] = mapped_column(_FRACTION)
    #: The market observed at the moment of entry. Perishable — the snapshot
    #: carrying them is prunable — and both are required by the audit record, so
    #: they are captured here rather than looked up again at close.
    entry_market_cap: Mapped[Decimal | None] = mapped_column(_MONEY)
    entry_liquidity_usd: Mapped[Decimal | None] = mapped_column(_MONEY)

    # --- Moved by the evaluator ---------------------------------------------

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    #: Highest price observed while the position was open. Carried forward
    #: rather than recomputed, so it survives snapshot pruning — a peak that was
    #: observed once is a fact and must not shrink when its row ages out.
    peak_price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    #: Persisted when (and only when) an observed quote first activates the
    #: trailing rule.  This makes a restart replay neither forget nor invent
    #: activation state.
    trailing_activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trailing_activation_observed_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    #: The current theoretical 25%-below-high threshold.  Stored for the audit
    #: surface and monotonic update checks; it is never an assumed fill price.
    trailing_stop_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    #: Written only on an automated trailing close: the theoretical threshold
    #: that was breached and the actual observed quote that breached it.
    trailing_trigger_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    trailing_trigger_observed_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    #: How far the observation series has been walked. Exits are resolved from
    #: every reading after this point, in order, which is what makes the result
    #: independent of when the evaluator ran.
    last_evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    #: The observed market price that breached the exit rule. Future Jupiter
    #: rows keep the decision mark here while `exit_price` stores the execution
    #: estimate. Legacy rows leave this null because the old model had one
    #: trigger-level price.
    exit_observed_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    exit_execution_model_version: Mapped[str | None] = mapped_column(String(64))
    exit_execution_quote: Mapped[dict[str, object] | None] = mapped_column(_JSON)
    exit_execution_quoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_execution_context_slot: Mapped[int | None] = mapped_column(Integer)
    exit_execution_price_impact_pct: Mapped[Decimal | None] = mapped_column(_PCT)
    exit_execution_fee_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    exit_execution_route: Mapped[str | None] = mapped_column(Text)
    exit_execution_confidence: Mapped[str | None] = mapped_column(String(32))
    exit_execution_fallback_reason: Mapped[str | None] = mapped_column(Text)
    #: `target` | `stop` | `expiry` | `manual`. Manual is a paper-only override,
    #: permanently distinguishable from exits chosen by the published rule.
    exit_reason: Mapped[str | None] = mapped_column(String(16))
    #: When the manual override was requested. Distinct from `closed_at`, which
    #: remains the timestamp of the market observation used as the exit quote.
    manual_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PaperTradeAudit(Base):
    """One completed trade, recorded once and never rewritten.

    Sprint 30 §11. The wallet already derived its metrics from `paper_positions`,
    and it still does — this table adds nothing the summary reads. What it adds
    is **durability of the inputs**: the market cap and the pool depth observed
    at each end, and the fee and price impact charged against that depth.

    Those come from `token_market_snapshots`, which is pruned. A trade whose
    costs were merely *derivable* would report them for a while and then report
    "unavailable" forever, and the oldest trades — the ones a track record is
    actually judged on — would be the first to go dark. So the figures are
    written at the moment they are known, from the rows that were there.

    **Nothing in the application ever updates this table.** `AuditRepository`
    contains one INSERT with `ON CONFLICT DO NOTHING` and no UPDATE and no
    DELETE, so a re-run of the same close is a no-op rather than a rewrite. A
    correction is a new row in a later system, not an edit here.
    """

    __tablename__ = "paper_trade_audit"
    __table_args__ = (
        # One audit row per position, ever. This is what makes a duplicate
        # evaluation pass harmless rather than a second entry in the record.
        UniqueConstraint("position_id", name="uq_paper_trade_audit_position"),
        # How the log reads: one wallet, newest exit first.
        Index("ix_paper_trade_audit_wallet_exit", "wallet_id", "exit_at"),
        Index("ix_paper_trade_audit_mint", "mint_address"),
        Index("ix_paper_trade_audit_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    #: `RESTRICT`, not `CASCADE`: the audit outlives convenience. Deleting a
    #: position that has been audited has to be a deliberate act against a
    #: refusal, not a side effect of tidying a table.
    position_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("paper_positions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("paper_wallets.id", ondelete="RESTRICT"), nullable=False
    )
    #: Copied, not joined. A symbol is what the token was called when it traded;
    #: pump.fun symbols collide and get reused (Sprint 28 found nine distinct
    #: mints named TNOS), so resolving it at read time would relabel history.
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(32))

    # --- Entry, as observed --------------------------------------------------

    entry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    entry_observed_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    entry_market_cap: Mapped[Decimal | None] = mapped_column(_MONEY)
    entry_liquidity_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    size_usd: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(_QUANTITY, nullable=False)

    # --- Exit, as observed ---------------------------------------------------

    exit_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    exit_observed_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    exit_market_cap: Mapped[Decimal | None] = mapped_column(_MONEY)
    exit_liquidity_usd: Mapped[Decimal | None] = mapped_column(_MONEY)

    # --- The result, gross and net ------------------------------------------

    gross_return_usd: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    gross_return_pct: Mapped[Decimal] = mapped_column(_PCT, nullable=False)
    #: Null when the venue reported no depth at one end, with the reason beside
    #: it. A half-costed trade is worse than an uncosted one: it looks complete.
    fee_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    slippage_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    net_return_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    net_return_pct: Mapped[Decimal | None] = mapped_column(_PCT)
    cost_unavailable_reason: Mapped[str | None] = mapped_column(Text)

    # --- Which rule did this -------------------------------------------------

    exit_reason: Mapped[str] = mapped_column(String(16), nullable=False)
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The version that was running when the trade closed. A later version bump
    #: leaves this row saying which rules produced it, which is the entire point
    #: of versioning a strategy at all.
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    wallet_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    #: The cost model's published fee, stored beside the figure it produced. A
    #: rate change later must not silently restate a net return already served.
    swap_fee_bps: Mapped[Decimal | None] = mapped_column(_BPS)
    #: Null on historical rows. Future rows say which model produced net costs.
    execution_model_version: Mapped[str | None] = mapped_column(String(64))
    entry_execution_model_version: Mapped[str | None] = mapped_column(String(64))
    exit_execution_model_version: Mapped[str | None] = mapped_column(String(64))
    entry_execution_quote: Mapped[dict[str, object] | None] = mapped_column(_JSON)
    exit_execution_quote: Mapped[dict[str, object] | None] = mapped_column(_JSON)
    entry_execution_quoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_execution_quoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    entry_execution_context_slot: Mapped[int | None] = mapped_column(Integer)
    exit_execution_context_slot: Mapped[int | None] = mapped_column(Integer)
    entry_execution_price_impact_pct: Mapped[Decimal | None] = mapped_column(_PCT)
    exit_execution_price_impact_pct: Mapped[Decimal | None] = mapped_column(_PCT)
    entry_execution_fee_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    exit_execution_fee_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    entry_execution_route: Mapped[str | None] = mapped_column(Text)
    exit_execution_route: Mapped[str | None] = mapped_column(Text)
    execution_confidence: Mapped[str | None] = mapped_column(String(32))
    execution_fallback_reason: Mapped[str | None] = mapped_column(Text)
    #: Set only for paper-only overrides. `exit_at` remains the observed quote's
    #: timestamp; this records when the action was confirmed.
    manual_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
