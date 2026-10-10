"""Wire models for `/labs/btc-range/*`.

These mirror `frontend/src/labs/btc-range/types.ts` field for field - the page
is already built against it, so a renamed or retyped field breaks the page and
nothing at build time says so. `test_btc_range_api` pins the exact key sets.

Money and price figures are `str` (a Decimal rendered with `format(d, "f")`, so
never exponent notation); percent fields are already percent. Timestamps are
`datetime` and serialise as ISO-8601 UTC.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

from app.labs.btc_range.bounds import BOUNDS
from app.labs.btc_range.types import Call, ExitReason, Regime, StrategyConfig

# --- responses ---------------------------------------------------------------


class ReasonOut(BaseModel):
    code: str
    text: str


class WaitReasonOut(ReasonOut):
    count: int


class RangeOut(BaseModel):
    support: str
    resistance: str
    mid: str
    width_pct: str
    position: str
    touches_support: int
    touches_resistance: int
    trend_efficiency: str
    confidence: int
    regime: Regime


class SignalOut(BaseModel):
    at: datetime
    price: str
    call: Call
    confidence: int
    range: RangeOut | None
    entry: str | None
    take_profit: str | None
    stop_loss: str | None
    reward_risk: str | None
    reasons: list[ReasonOut]


class MetricsOut(BaseModel):
    trades: int
    wins: int
    losses: int
    win_rate: str | None
    net_pnl: str
    gross_profit: str
    gross_loss: str
    profit_factor: str | None
    expectancy: str | None
    max_drawdown_pct: str | None
    return_pct: str
    ending_equity: str


class TradeOut(BaseModel):
    side: Call
    signal_at: datetime
    entry_at: datetime
    entry_price: str
    take_profit: str
    stop_loss: str
    quantity: str
    notional: str
    exit_at: datetime
    exit_price: str
    exit_reason: ExitReason
    fees: str
    pnl: str
    r_multiple: str | None


class OpenPositionOut(BaseModel):
    side: Call
    signal_at: datetime
    entry_at: datetime
    entry_price: str
    take_profit: str
    stop_loss: str
    quantity: str
    notional: str
    mark_price: str
    unrealised_pnl: str


class EquityPointOut(BaseModel):
    at: datetime
    equity: str


class CandleOut(BaseModel):
    t: datetime
    o: str
    h: str
    l: str  # noqa: E741 - the wire name
    c: str


class StrategyConfigOut(BaseModel):
    lookback: int
    touch_tolerance: str
    min_touches: int
    min_width_pct: str
    max_width_pct: str
    max_trend_efficiency: str
    min_confidence: int
    entry_zone: str
    tp_target: str
    sl_buffer: str
    min_reward_risk: str
    max_hold_candles: int
    cooldown_candles: int
    allow_long: bool
    allow_short: bool
    starting_balance: str
    risk_per_trade_pct: str
    max_leverage: str
    fee_bps: str
    slippage_bps: str


class BookOut(BaseModel):
    started_at: datetime
    config_version: int
    config: StrategyConfigOut
    metrics: MetricsOut
    long: MetricsOut
    short: MetricsOut
    open_position: OpenPositionOut | None
    trades: list[TradeOut]
    equity_curve: list[EquityPointOut]


class DataOut(BaseModel):
    candles: int
    first_at: datetime | None
    last_closed_at: datetime | None
    stale: bool


class PriceOut(BaseModel):
    value: str
    at: datetime
    candle_closed: bool


class StatusOut(BaseModel):
    running: bool
    reason: str | None
    symbol: str
    timeframe: str
    paper_only: Literal[True] = True
    price: PriceOut | None
    data: DataOut
    signal: SignalOut | None
    book: BookOut | None
    candles: list[CandleOut]


class FieldBoundsOut(BaseModel):
    min: str
    max: str
    step: str
    label: str
    help: str
    kind: Literal["int", "decimal", "bool"]
    group: Literal["range", "entries", "account"]


class ConfigOut(BaseModel):
    config_version: int
    defaults: StrategyConfigOut
    bounds: dict[str, FieldBoundsOut]
    data_first_at: datetime | None
    data_last_at: datetime | None


class SignalCountsOut(BaseModel):
    long: int
    short: int
    wait: int


class BacktestOut(BaseModel):
    available: bool
    reason: str | None
    config: StrategyConfigOut
    start: datetime | None
    end: datetime | None
    candles: int
    signal_counts: SignalCountsOut
    wait_reasons: list[WaitReasonOut]
    metrics: MetricsOut
    long: MetricsOut
    short: MetricsOut
    trades: list[TradeOut]
    equity_curve: list[EquityPointOut]


# --- requests ----------------------------------------------------------------


class ConfigIn(BaseModel):
    """Any subset of `StrategyConfig`. Omitted (or null) fields take the defaults.

    Every value is checked against `BOUNDS`; one outside it is a 422 naming the
    field, not a clamp. Unknown keys are refused for the same reason: a typo'd
    name that is silently ignored would report a result for a config the reader
    did not ask for.
    """

    model_config = ConfigDict(extra="forbid")

    lookback: int | None = None
    touch_tolerance: Decimal | None = None
    min_touches: int | None = None
    min_width_pct: Decimal | None = None
    max_width_pct: Decimal | None = None
    max_trend_efficiency: Decimal | None = None
    min_confidence: int | None = None
    entry_zone: Decimal | None = None
    tp_target: Decimal | None = None
    sl_buffer: Decimal | None = None
    min_reward_risk: Decimal | None = None
    max_hold_candles: int | None = None
    cooldown_candles: int | None = None
    allow_long: bool | None = None
    allow_short: bool | None = None
    starting_balance: Decimal | None = None
    risk_per_trade_pct: Decimal | None = None
    max_leverage: Decimal | None = None
    fee_bps: Decimal | None = None
    slippage_bps: Decimal | None = None

    @field_validator("*", mode="after")
    @classmethod
    def _within_bounds(cls, value: object, info: ValidationInfo) -> object:
        bound = BOUNDS.get(info.field_name or "")
        if value is None or bound is None or bound.kind == "bool":
            return value
        number = Decimal(value)  # type: ignore[arg-type]
        # NaN and infinity are not comparable (ordering a NaN raises), and are
        # never inside a range.
        if not number.is_finite() or not bound.min <= number <= bound.max:
            raise ValueError(
                f"must be between {format(bound.min, 'f')} and {format(bound.max, 'f')}"
            )
        return value

    def to_config(self) -> StrategyConfig:
        given = {
            name: getattr(self, name)
            for name in self.model_fields_set
            if getattr(self, name) is not None
        }
        return StrategyConfig(**given)


class BacktestIn(BaseModel):
    """`start` and `end` are instants. A candle is in the window when it OPENS in
    `[start, end]`; naive timestamps are read as UTC."""

    model_config = ConfigDict(extra="forbid")

    config: ConfigIn = ConfigIn()
    start: datetime | None = None
    end: datetime | None = None


# --- Monthly long/short book (monthly.py) -----------------------------------

class MonthlyMonthOut(BaseModel):
    month: str  # YYYY-MM
    side: Literal["long", "short"]
    entry: str
    exit: str
    liquidation_price: str
    liquidated: bool
    pnl_usd: str
    pct: str
    running: bool
    live: bool


class MonthlySummaryOut(BaseModel):
    months: int
    up: int
    total_pnl_usd: str
    best_usd: str | None
    worst_usd: str | None
    liquidated: int


class MonthlyOut(BaseModel):
    enabled: bool
    leverage: int
    capital_usd: str
    fee_pct_per_side: str
    live_start: str  # YYYY-MM
    current_price: str | None
    current: MonthlyMonthOut | None
    live: MonthlySummaryOut
    backtest: MonthlySummaryOut
    months: list[MonthlyMonthOut]  # newest first
