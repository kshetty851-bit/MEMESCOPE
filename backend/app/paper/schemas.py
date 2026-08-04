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
    size_usd: Decimal
    quantity: Decimal

    #: Fixed at entry, never recomputed.
    target_price: Decimal
    stop_price: Decimal
    expires_at: datetime

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
    #: `target` | `stop` | `expiry`. Never `manual` — nothing may close a
    #: position for a reason a reader cannot check against the published rule.
    exit_reason: str | None = None
    #: Realised for a closed trade, marked-to-market for an open one, `None`
    #: when the token has no current reading.
    pnl_usd: Decimal | None = None


class BenchmarkOut(BaseSchema):
    """One comparison, with its own difference already computed.

    `difference_pct` is served rather than left to the client so the two
    surfaces that show it cannot disagree about the subtraction.
    """

    id: str
    label: str
    description: str
    #: `None` when the comparison cannot be measured. The reason is then set.
    return_pct: Decimal | None = None
    difference_pct: Decimal | None = None
    unavailable_reason: str | None = None


class MetricsOut(BaseSchema):
    """Everything the wallet reports about itself. All derived, none stored."""

    starting_balance: Decimal
    cash: Decimal
    #: Cash plus open holdings. `None` when any holding is unpriced.
    equity: Decimal | None = None
    roi_pct: Decimal | None = None
    open_value: Decimal | None = None
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


class WalletOut(BaseSchema):
    """The wallet, its strategy, its metrics and its benchmarks."""

    #: False when the feature flag is off. The wallet is then reported as not
    #: running rather than served empty, which would look like a strategy that
    #: traded nothing.
    enabled: bool
    strategy: StrategyOut
    metrics: MetricsOut
    benchmarks: list[BenchmarkOut]
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
    """One published rule set, replayed over the shared dataset.

    Every figure is measured. `None` means no trade supports it — never zero.
    """

    id: str
    name: str
    description: str
    rules: list[LabRuleOut]
    #: True for Equal Weight v1, the permanent benchmark. Never more than one.
    is_baseline: bool

    invested: Decimal
    #: Every trade, with open positions marked at the latest observed price.
    total_return_pct: Decimal | None = None
    #: **Closed trades only.** Served beside the total because win rate and
    #: profit factor are also closed-only: a rule whose headline return comes
    #: mostly from open marks would otherwise read as though it had earned it.
    realised_return_pct: Decimal | None = None
    #: Share of trades still open — how much of the total is a mark, not a result.
    open_share_pct: Decimal | None = None
    #: Return after the venue's published fee and the order's price impact,
    #: over the trades whose pool depth was reported. Gross stays the headline;
    #: this sits beside it.
    net_return_pct: Decimal | None = None
    #: What execution took, in percentage points, measured over the same subset
    #: as `net_return_pct` so the two compare like with like.
    cost_drag_pct: Decimal | None = None
    #: Coverage of the net figure. Bonding-curve pairs report no liquidity and
    #: are excluded rather than costed against an invented depth.
    costed_trades: int = 0
    uncosted_trades: int = 0
    #: Difference against the baseline, in percentage points. Null for the
    #: baseline itself — a benchmark does not differ from itself.
    baseline_difference_pct: Decimal | None = None
    #: Refused unless the observed history is long enough to annualise without
    #: extrapolating. The reason is served beside it.
    annualised_return_pct: Decimal | None = None
    annualised_unavailable_reason: str | None = None

    closed_count: int
    open_count: int
    win_rate_pct: Decimal | None = None
    profit_factor: Decimal | None = None
    average_win: Decimal | None = None
    average_loss: Decimal | None = None
    largest_winner: Decimal | None = None
    largest_loser: Decimal | None = None
    max_drawdown_pct: Decimal | None = None
    average_hold_hours: Decimal | None = None
    #: How high positions got before exiting, and how much of that was handed
    #: back. Together these explain *why* a rule wins or loses.
    average_peak_pct: Decimal | None = None
    average_giveback_pct: Decimal | None = None
    exits_by_reason: dict[str, int] = Field(default_factory=dict)

    rank: int
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


class LabOut(BaseSchema):
    strategies: list[LabStrategyOut]
    unavailable: list[UnavailableStrategyOut]
    findings: list[LabFindingOut]
    baseline_id: str
    #: Detections replayed, and how many were never priced so never entered.
    detections: int
    unpriced_detections: int
    observed_days: Decimal | None = None
    #: Why a lab return is not a wallet balance. Served on every response.
    methodology: str
    #: What the net figures charge, and the three things they refuse to model.
    cost_disclosure: str
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
