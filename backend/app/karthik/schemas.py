"""What `/api/v1/karthik` serves.

Money is a **string**, never a float, everywhere in this file. The rule is the
platform's, not this module's: a JSON number for a token priced at 4.8e-10
loses the position, and a float that has round-tripped through JavaScript is not
the figure the database holds.

Missing values are `null` and mean *not measured*. Nothing here substitutes one
fact for another — a position with no discovery row reports `detected_at: null`
and the page prints "not available", because reporting the entry time there
would invent a delay of zero.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class KarthikPositionOut(BaseModel):
    mint_address: str
    symbol: str | None
    token_name: str | None

    #: The three moments, each from its own source, none standing in for
    #: another. `detected_at` is the earliest stored discovery instant across
    #: the scanner's insert and the transports' receives.
    detected_at: datetime | None
    track_record_at: datetime
    opened_at: datetime
    #: Seconds from Track Record admission to the entry. Null when the entry
    #: preceded admission, which cannot happen, or when a clock disagrees.
    track_record_delay_seconds: int | None
    #: Seconds from first sight to the entry. Null when detection is unknown.
    detection_delay_seconds: int | None

    entry_price: str
    entry_observed_price: str
    quantity: str
    cost_basis: str
    decimals: int
    target_price: str
    target_multiple: str

    pool_address: str | None
    entry_liquidity_usd: str | None
    entry_market_cap: str | None
    entry_execution_model_version: str | None
    entry_execution_price_impact_pct: str | None
    entry_execution_route: str | None
    entry_execution_confidence: str | None
    entry_execution_fallback_reason: str | None

    status: str
    peak_price: str
    #: Null when nothing has priced this mint recently — never zero.
    current_price: str | None
    current_multiple: str | None
    current_value: str | None
    unrealized_pnl: str | None
    last_market_check_at: datetime | None

    closed_at: datetime | None
    exit_price: str | None
    exit_observed_price: str | None
    exit_proceeds_usd: str | None
    exit_multiple: str | None
    exit_reason: str | None
    exit_execution_route: str | None
    exit_evidence: str | None
    realized_pnl: str | None
    hold_seconds: int | None
    age_seconds: int


class KarthikSkippedOut(BaseModel):
    mint_address: str
    track_record_at: datetime
    decided_at: datetime
    reason: str


class KarthikMetricsOut(BaseModel):
    starting_capital: str
    cash: str
    full_equity: str
    capital_allocated: str
    realized_pnl: str
    unrealized_pnl: str
    return_pct: str

    open_positions: int
    closed_positions: int
    wins: int
    dead_zero: int
    #: Null rather than 0% while nothing has closed. "No trades have finished"
    #: and "every trade lost" are different claims.
    win_rate_pct: str | None
    average_hold_seconds: int | None

    # --- The experiment's own flow -----------------------------------------
    track_record_opportunities: int
    entered: int
    skipped_insufficient_cash: int
    skipped_no_market: int
    #: Entered over opportunities. Null before the first opportunity exists.
    capture_rate_pct: str | None
    targets_hit: int
    dead_zero_count: int
    #: Always zero, and served so a reader can check it rather than trust it.
    historical_backfill: int


class KarthikWalletOut(BaseModel):
    """The wallet, or an honest statement that it has not been activated."""

    activated: bool
    name: str = "Karthik"
    #: The strategy, in the words the page prints. Served rather than hardcoded
    #: in the UI so the rule and the trades come from the same place.
    strategy: str
    entries_paused: bool
    wallet_id: str | None = None
    activated_at: datetime | None = None
    trade_size: str | None = None
    take_profit_multiple: str | None = None
    metrics: KarthikMetricsOut | None = None
    disclosure: str


class KarthikPositionsOut(BaseModel):
    items: list[KarthikPositionOut]


class KarthikSkippedListOut(BaseModel):
    items: list[KarthikSkippedOut]
