"""Paper wallet API contracts.

Decimals serialise as **strings**, matching the rest of the API: a JSON float
would round exactly the figures a track record is judged on.

`None` never means zero anywhere in this file. It means the figure has no rows
behind it — no closed trade to average, no priced holding to value — and every
surface renders it as a dash.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import Field

from app.schemas.common import BaseSchema


class RuleOut(BaseSchema):
    """One published rule, as a reader checks a trade against it."""

    label: str
    value: str


class StrategyOut(BaseSchema):
    """A strategy, published in full.

    Everything a reader needs to verify that a trade followed the rules. The
    rules are rendered from the same fields the simulation applies, so the
    published rule and the executed rule cannot drift.
    """

    id: str
    name: str
    version: str
    summary: str
    rules: list[RuleOut]
    #: False when a strategy is declared but does not trade. Published rather
    #: than hidden, so "we have one strategy" and "we have four and run one"
    #: are distinguishable.
    operational: bool
    unavailable_reason: str | None = None
    #: True for the strategy this wallet actually follows.
    is_active: bool = False


class PositionOut(BaseSchema):
    """One simulated trade.

    The entry block was written once and is never updated — fixing the exits at
    entry is what stops a target being recomputed favourably after the fact.
    """

    mint_address: str
    name: str | None = None
    symbol: str | None = None

    status: str
    opened_at: datetime
    #: The Radar place the token held when it was bought. The entry rule is
    #: stated in terms of it, so a reader can check the trade against the rule.
    entry_rank: int
    entry_price: Decimal
    entry_observed_price: Decimal | None = None
    size_usd: Decimal
    quantity: Decimal
    entry_execution_model_version: str | None = None
    entry_execution_price_impact_pct: Decimal | None = None
    entry_execution_fee_usd: Decimal | None = None
    entry_execution_route: str | None = None
    entry_execution_quoted_at: datetime | None = None
    entry_execution_confidence: str | None = None
    entry_execution_fallback_reason: str | None = None
    #: The market as it stood when the position opened. Recorded, never used to
    #: size anything.
    entry_market_cap: Decimal | None = None
    entry_liquidity_usd: Decimal | None = None

    #: Fixed at entry, never recomputed. `None` where the strategy publishes no
    #: such rule — since Sprint 30 the live strategy has no target, no fixed
    #: stop and no expiry, and a zero would read as a rule sitting at zero.
    target_price: Decimal | None = None
    stop_price: Decimal | None = None
    expires_at: datetime | None = None
    #: The trailing fraction fixed at entry. 0.25 is "25% back from the high".
    trailing_drawdown: Decimal | None = None
    #: Where the trailing stop currently sits: the running high less the fixed
    #: fraction. Derived at read time from `peak_price`, never stored — a stored
    #: level would be a second source of truth for the one rule that matters.
    trailing_stop_price: Decimal | None = None

    #: Latest observed price. `None` for a token nobody has priced since — the
    #: holding is unmeasured, not worthless.
    current_price: Decimal | None = None
    #: Percent from entry, on the current price. `None` follows `current_price`.
    current_pct: Decimal | None = None
    #: When the price above was observed. Sprint 28.1: without it the wallet
    #: implies a live quote for an open position whose token may not have been
    #: priced in hours. For a closed trade this is the exit time — a settled
    #: result does not go stale.
    current_price_at: datetime | None = None
    #: Percent from entry at the highest price observed while open. For a closed
    #: trade this stops at the exit: a high printed after the position closed
    #: belongs to the token, not to the trade.
    peak_pct: Decimal | None = None

    closed_at: datetime | None = None
    exit_price: Decimal | None = None
    exit_observed_price: Decimal | None = None
    exit_execution_model_version: str | None = None
    exit_execution_price_impact_pct: Decimal | None = None
    exit_execution_fee_usd: Decimal | None = None
    exit_execution_route: str | None = None
    exit_execution_quoted_at: datetime | None = None
    exit_execution_confidence: str | None = None
    exit_execution_fallback_reason: str | None = None
    #: `target` | `stop` | `expiry` | `manual`. Manual is paper-only and must
    #: stay distinguishable from automated V1 exits.
    exit_reason: str | None = None
    manual_action_at: datetime | None = None
    #: Realised for a closed trade, marked-to-market for an open one, `None`
    #: when the token has no current reading.
    pnl_usd: Decimal | None = None


class ManualSellPreviewOut(BaseSchema):
    """The exact paper-only close the user is being asked to confirm."""

    mint_address: str
    name: str | None = None
    symbol: str | None = None
    short_mint: str
    entry_price: Decimal
    entry_observed_price: Decimal | None = None
    latest_price: Decimal
    quote_observed_at: datetime
    quote_age_seconds: Decimal
    is_stale: bool
    warning: str | None = None
    entry_market_cap: Decimal | None = None
    current_market_cap: Decimal | None = None
    liquidity_usd: Decimal | None = None
    gross_return_usd: Decimal
    gross_return_pct: Decimal
    fee_usd: Decimal | None = None
    slippage_usd: Decimal | None = None
    net_return_usd: Decimal | None = None
    net_return_pct: Decimal | None = None
    cost_unavailable_reason: str | None = None
    execution_model_version: str | None = None
    exit_execution_price_impact_pct: Decimal | None = None
    exit_execution_fee_usd: Decimal | None = None
    exit_execution_route: str | None = None
    exit_execution_quoted_at: datetime | None = None
    execution_confidence: str | None = None
    execution_fallback_reason: str | None = None


class ManualSellOut(BaseSchema):
    """Result of one confirmed paper-only manual close."""

    closed: bool
    preview: ManualSellPreviewOut
    audited: bool
    opened: int
    candidates: int
    candidates_truncated: bool
    refusals: dict[str, int] = Field(default_factory=dict)


class BenchmarkOut(BaseSchema):
    """One comparison, with its own difference already computed.

    `difference_pct` is served rather than left to the client so the two
    surfaces that show it cannot disagree about the subtraction.

    Every benchmark starts with the wallet's capital at the wallet's own start
    instant (Sprint 30 §2). A comparison drawn over a different period is not a
    comparison, and this schema carries the constituent counts so a reader can
    see what each figure was measured over.
    """

    id: str
    label: str
    description: str
    #: `None` when the comparison cannot be measured. The reason is then set.
    return_pct: Decimal | None = None
    difference_pct: Decimal | None = None
    unavailable_reason: str | None = None
    #: How many tokens the comparison held, and how many were in its universe
    #: but unpriceable at one end. The second is published rather than dropped:
    #: silently excluding them would hand the benchmark survivorship it did not
    #: earn.
    positions: int = 0
    unpriced: int = 0


class MetricsOut(BaseSchema):
    """Everything the wallet reports about itself. All derived, none stored."""

    starting_balance: Decimal
    cash: Decimal
    #: Cash plus open holdings. `None` when any holding is unpriced.
    equity: Decimal | None = None
    roi_pct: Decimal | None = None
    open_value: Decimal | None = None
    #: What the open holdings cost, as committed at entry. Never `None`: an
    #: unpriced holding has an unknown *value* but a known cost, and letting
    #: "invested" disappear with a price would misreport how much is deployed.
    invested_usd: Decimal = Decimal(0)
    #: How many open positions could not be priced. The reason equity is null.
    unpriced_positions: int = 0

    open_positions: int = 0
    closed_positions: int = 0

    realised_pnl: Decimal
    win_rate_pct: Decimal | None = None
    average_win: Decimal | None = None
    average_loss: Decimal | None = None
    #: Gross profit over gross loss. `None` while nothing has lost — the ratio
    #: is undefined, not infinite, and printing ∞ reads as a claim.
    profit_factor: Decimal | None = None
    largest_winner: Decimal | None = None
    largest_loser: Decimal | None = None
    #: Deepest fall of the **realised** equity curve. The path between closes is
    #: not reconstructed, so this is a floor on the true drawdown.
    max_drawdown_pct: Decimal | None = None
    max_drawdown_note: str
    average_hold_hours: Decimal | None = None
    exits_by_reason: dict[str, int] = Field(default_factory=dict)


class WaitingOut(BaseSchema):
    """Why the wallet is idle, whenever it is.

    Two distinct states, named by `reason`:

    * `no_qualified_token` — cash enough for a position, nothing on the Radar
      passing the entry conditions. Sprint 30 §9.
    * `cash_below_trade_size` — something may qualify, but what is left will not
      fund a whole position and the strategy never part-fills. This is a wait
      for a **close**, not for an opportunity.

    Served only when one of them is true. A page that claimed to be waiting for
    an opportunity while one sat in front of it, fundable, would be worse than
    one that said nothing.

    `refusals` is a count per published entry condition, and `eligible` is how
    many tokens would be bought if the cash were there. A denominator is what
    turns "idle" from a claim into a measurement.
    """

    #: Stable code. The client switches on this, never on the message text.
    reason: str
    message: str
    idle_cash: Decimal
    trade_size: Decimal
    #: How far the cash is short of one position. Zero when it is not short.
    shortfall: Decimal = Decimal(0)
    considered: int
    eligible: int = 0
    refusals: dict[str, int] = Field(default_factory=dict)
    #: The sentence each refusal code renders as, so the client never composes
    #: prose from a code. Rewording stays a deploy, not a migration.
    labels: dict[str, str] = Field(default_factory=dict)


class LastTradeOut(BaseSchema):
    """The most recent thing the wallet did, whichever kind it was.

    `action` is `opened` or `closed`. Both are shown because a wallet that has
    been fully invested for a day did something last — it just was not an exit,
    and reporting only closes would make it look idle.
    """

    action: str
    mint_address: str
    symbol: str | None = None
    at: datetime
    price_usd: Decimal | None = None
    exit_reason: str | None = None
    pnl_usd: Decimal | None = None


class AuditEntryOut(BaseSchema):
    """One completed trade, exactly as it was written down.

    Never recomputed at read time. The market cap and depth are the ones
    observed at each end of the trade, and the fee and impact were charged
    against that depth when it was still on record.
    """

    mint_address: str
    symbol: str | None = None

    entry_at: datetime
    entry_price: Decimal
    entry_observed_price: Decimal | None = None
    entry_market_cap: Decimal | None = None
    entry_liquidity_usd: Decimal | None = None
    size_usd: Decimal
    quantity: Decimal

    exit_at: datetime
    exit_price: Decimal
    exit_observed_price: Decimal | None = None
    exit_market_cap: Decimal | None = None
    exit_liquidity_usd: Decimal | None = None

    gross_return_usd: Decimal
    gross_return_pct: Decimal
    #: `None` together, with the reason set, when the venue reported no depth at
    #: one end. A half-costed trade is worse than an uncosted one.
    fee_usd: Decimal | None = None
    slippage_usd: Decimal | None = None
    net_return_usd: Decimal | None = None
    net_return_pct: Decimal | None = None
    cost_unavailable_reason: str | None = None

    exit_reason: str
    manual_action_at: datetime | None = None
    strategy_id: str
    strategy_version: str
    wallet_generation: int
    hold_hours: Decimal | None = None
    execution_model_version: str | None = None
    entry_execution_model_version: str | None = None
    exit_execution_model_version: str | None = None
    entry_execution_price_impact_pct: Decimal | None = None
    exit_execution_price_impact_pct: Decimal | None = None
    entry_execution_fee_usd: Decimal | None = None
    exit_execution_fee_usd: Decimal | None = None
    entry_execution_route: str | None = None
    exit_execution_route: str | None = None
    entry_execution_quoted_at: datetime | None = None
    exit_execution_quoted_at: datetime | None = None
    execution_confidence: str | None = None
    execution_fallback_reason: str | None = None


class AuditOut(BaseSchema):
    """The permanent record, newest exit first. Losers are never filtered out."""

    items: list[AuditEntryOut]
    total: int
    enabled: bool
    #: What the net figures include and what they refuse. Both halves.
    disclosure: str
    observed_at: datetime


class ArchivedWalletOut(BaseSchema):
    """A retired generation, for internal historical comparison only.

    Not linked from the product. Its figures are frozen at the moment it was
    archived, including any position that was still open — those never settle,
    and this schema says so rather than letting a reader assume they closed at a
    fair price.
    """

    strategy_id: str
    strategy_name: str
    strategy_version: str
    generation: int
    starting_balance: Decimal
    started_at: datetime
    archived_at: datetime
    archive_reason: str | None = None
    open_positions: int
    closed_positions: int
    #: Stated on every archived wallet with unsettled positions.
    frozen_note: str


class ArchiveOut(BaseSchema):
    items: list[ArchivedWalletOut]
    note: str
    observed_at: datetime


class WalletOut(BaseSchema):
    """The wallet, its strategy, its metrics and its benchmarks."""

    #: False when the feature flag is off. The wallet is then reported as not
    #: running rather than served empty, which would look like a strategy that
    #: traded nothing.
    enabled: bool
    strategy: StrategyOut
    metrics: MetricsOut
    benchmarks: list[BenchmarkOut]
    #: Which launch this is, and when it began. The benchmarks above start from
    #: the same instant — that is the point of publishing it.
    generation: int = 1
    started_at: datetime | None = None
    #: Set when both benchmarks currently hold the same tokens. They are
    #: distinct measurements that happen to coincide, and saying so beats hiding
    #: one or implying two independent checks.
    benchmark_note: str | None = None
    #: Present only while the wallet is holding fundable cash with nothing
    #: eligible in front of it.
    waiting: WaitingOut | None = None
    last_trade: LastTradeOut | None = None
    #: The next moment the Radar's ranking can change, from the sweep's own
    #: cadence. Exits do not wait for it — they resolve from stored readings.
    next_radar_evaluation_at: datetime | None = None
    #: How many trades are in the permanent record.
    audited_trades: int = 0
    #: Realised profit from trades closed since midnight UTC. Realised only —
    #: an open position's unrealised move is not a figure anyone can act on.
    pnl_today: Decimal
    #: Stated on every response. This is a simulation over stored history: no
    #: wallet is connected, no order is routed, no chain is touched.
    disclosure: str
    observed_at: datetime


class PositionsOut(BaseSchema):
    """Every position, open and closed.

    Not paginated. The wallet holds one position per token it has ever taken,
    which is bounded by the Radar's own admission — and the Track Record needs
    all of them at once to answer "was this token traded?".
    """

    items: list[PositionOut]
    enabled: bool
    observed_at: datetime


class StrategiesOut(BaseSchema):
    items: list[StrategyOut]
    active_id: str


# --- Strategy Lab -------------------------------------------------------------


class LabRuleOut(BaseSchema):
    label: str
    value: str


class EquityPointOut(BaseSchema):
    at: datetime
    equity: Decimal
    drawdown_pct: Decimal


class LabStrategyOut(BaseSchema):
    """One research rule replayed over the Generation 2 paper entries."""

    id: str
    name: str
    description: str
    rules: list[LabRuleOut]
    is_baseline: bool
    rank: int

    invested: Decimal
    total_return_pct: Decimal | None = None
    realised_return_pct: Decimal | None = None
    open_share_pct: Decimal | None = None
    net_return_pct: Decimal | None = None
    cost_drag_pct: Decimal | None = None
    costed_trades: int = 0
    uncosted_trades: int = 0
    baseline_difference_pct: Decimal | None = None
    annualised_return_pct: Decimal | None = None
    annualised_unavailable_reason: str | None = None

    closed_count: int
    open_count: int
    win_rate_pct: Decimal | None = None
    profit_factor: Decimal | None = None
    expectancy: Decimal | None = None
    average_win: Decimal | None = None
    average_loss: Decimal | None = None
    average_winner: Decimal | None = None
    average_loser: Decimal | None = None
    largest_winner: Decimal | None = None
    largest_loser: Decimal | None = None
    max_drawdown_pct: Decimal | None = None
    average_hold_hours: Decimal | None = None
    average_peak_pct: Decimal | None = None
    average_capture_pct: Decimal | None = None
    average_giveback_pct: Decimal | None = None
    fees_usd: Decimal | None = None
    slippage_usd: Decimal | None = None
    average_slippage_usd: Decimal | None = None
    capital_utilization_pct: Decimal | None = None
    exits_by_reason: dict[str, int] = Field(default_factory=dict)

    equity_curve: list[EquityPointOut] = Field(default_factory=list)
    return_distribution: list[Decimal] = Field(default_factory=list)
    hold_distribution: list[Decimal] = Field(default_factory=list)


class UnavailableStrategyOut(BaseSchema):
    """A rule that was asked for and cannot be measured honestly."""

    id: str
    name: str
    reason: str


class LabFindingOut(BaseSchema):
    """A conclusion drawn only from the figures above.

    Every finding names the metric it rests on. Nothing here is an opinion about
    what a reader should do; it is a statement about what the replay measured.
    """

    headline: str
    detail: str
    strategy_id: str | None = None


class EntryDivergenceOut(BaseSchema):
    """Deprecated compatibility shell for older clients."""

    positions: int = 0
    median_ratio: Decimal | None = None
    worst_ratio: Decimal | None = None
    wallet_paid_more: int = 0
    median_lag_hours: Decimal | None = None
    explanation: str = ""


class LabDataIntegrityOut(BaseSchema):
    scoped_generation: int
    scoped_strategy_id: str
    positions: int
    open_positions: int
    closed_positions: int
    audited_closed_positions: int
    missing_audit_rows: int
    manual_overrides: int
    legacy_execution_model_rows: int
    jupiter_execution_model_rows: int
    unknown_execution_model_rows: int
    archived_generation_positions: int
    archived_missing_audit_rows: int
    verdict: str


class ExecutionModelPerformanceOut(BaseSchema):
    model_version: str
    label: str
    trades: int
    gross_return_usd: Decimal
    net_return_usd: Decimal
    win_rate_pct: Decimal | None = None
    profit_factor: Decimal | None = None
    fees_usd: Decimal
    slippage_usd: Decimal


class SegmentRowOut(BaseSchema):
    name: str
    n: int
    net_return_pct: Decimal | None = None
    win_rate_pct: Decimal | None = None
    profit_factor: Decimal | None = None
    average_return_pct: Decimal | None = None
    slippage_drag_pct: Decimal | None = None


class PatternAnalysisOut(BaseSchema):
    entry_market_cap: list[SegmentRowOut] = Field(default_factory=list)
    liquidity: list[SegmentRowOut] = Field(default_factory=list)
    radar_score: list[SegmentRowOut] = Field(default_factory=list)
    age: list[SegmentRowOut] = Field(default_factory=list)
    holding_time: list[SegmentRowOut] = Field(default_factory=list)


class TradeCardOut(BaseSchema):
    mint_address: str
    symbol: str | None = None
    net_return_pct: Decimal | None = None
    gross_return_pct: Decimal | None = None
    entry_market_cap: Decimal | None = None
    entry_liquidity_usd: Decimal | None = None
    radar_score: Decimal | None = None
    confidence: Decimal | None = None
    category: str | None = None
    age_hours_at_entry: Decimal | None = None
    hold_hours: Decimal | None = None
    exit_reason: str | None = None


class RecommendationOut(BaseSchema):
    title: str
    confidence: str
    sample_size: int
    expected_improvement: str
    trade_offs: str


class RejectedIdeaOut(BaseSchema):
    strategy_id: str
    reason: str
    sample_size: int


class LabOut(BaseSchema):
    strategies: list[LabStrategyOut]
    unavailable: list[UnavailableStrategyOut]
    findings: list[LabFindingOut]
    baseline_id: str
    data_integrity: LabDataIntegrityOut
    execution_models: list[ExecutionModelPerformanceOut] = Field(default_factory=list)
    production_summary: LabStrategyOut
    pattern_analysis: PatternAnalysisOut
    largest_winners: list[TradeCardOut] = Field(default_factory=list)
    largest_losers: list[TradeCardOut] = Field(default_factory=list)
    suggestions: list[RecommendationOut] = Field(default_factory=list)
    rejected_ideas: list[RejectedIdeaOut] = Field(default_factory=list)
    final_decision_code: str
    final_decision: str
    #: Detections replayed, and how many were never priced so never entered.
    detections: int = 0
    unpriced_detections: int = 0
    observed_days: Decimal | None = None
    #: Why a lab return is not a wallet balance. Served on every response.
    methodology: str
    #: What the net figures charge, and the three things they refuse to model.
    cost_disclosure: str
    entry_divergence: EntryDivergenceOut = Field(default_factory=EntryDivergenceOut)
    #: The published rates the net figures apply, so a reader can check them.
    cost_rules: list[LabRuleOut] = Field(default_factory=list)
    observed_at: datetime


class TokenComparisonOut(BaseSchema):
    mint_address: str
    symbol: str | None = None
    #: The highest the token reached while held, as a percent of entry.
    peak_pct: Decimal | None = None
    #: strategy id -> return percent.
    returns: dict[str, Decimal | None] = Field(default_factory=dict)
    #: Which rule captured the largest share of the peak. Null when the token
    #: never rose — there was no move to capture.
    best_strategy_id: str | None = None
    best_capture_pct: Decimal | None = None


class LabTokensOut(BaseSchema):
    items: list[TokenComparisonOut]
    strategy_ids: list[str]
    observed_at: datetime
