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
