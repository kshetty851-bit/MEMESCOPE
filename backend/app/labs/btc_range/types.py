"""The BTC Range Lab's domain types — the contract between engine, data and API.

Pure data. No I/O, no clock, no SQLAlchemy. Every price and money figure is a
`Decimal`; the API serialises them as strings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

SYMBOL = "BTCUSDT"
#: The only timeframe in the MVP. Lookbacks, holds and cooldowns are counted
#: in candles of this size.
TIMEFRAME = "15m"
TIMEFRAME_SECONDS = 15 * 60
#: Bumped whenever a default in `StrategyConfig` changes. The live paper book is
#: keyed by it, so a changed default starts a new book instead of silently
#: restating the old one.
CONFIG_VERSION = 1


@dataclass(frozen=True, slots=True)
class Candle:
    """One CLOSED candle. `open_time` is the candle's start, UTC."""

    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


class Call(StrEnum):
    LONG = "long"
    SHORT = "short"
    WAIT = "wait"


class Regime(StrEnum):
    RANGE = "range"
    TRENDING = "trending"
    BREAKOUT_UP = "breakout_up"
    BREAKOUT_DOWN = "breakout_down"
    #: Not enough candles, or a degenerate (zero-width) window.
    UNDEFINED = "undefined"


class Reason(StrEnum):
    """Stable reason codes. Prose is rendered from these by the API, never stored."""

    NEAR_SUPPORT = "near_support"
    NEAR_RESISTANCE = "near_resistance"
    MID_RANGE = "mid_range"
    TRENDING = "trending"
    BREAKOUT_UP = "breakout_up"
    BREAKOUT_DOWN = "breakout_down"
    LOW_CONFIDENCE = "low_confidence"
    RANGE_TOO_NARROW = "range_too_narrow"
    RANGE_TOO_WIDE = "range_too_wide"
    POOR_REWARD_RISK = "poor_reward_risk"
    COSTS_EXCEED_TARGET = "costs_exceed_target"
    SIDE_DISABLED = "side_disabled"
    INSUFFICIENT_DATA = "insufficient_data"


class ExitReason(StrEnum):
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    TIME_STOP = "time_stop"
    #: Still open when the candles ran out. Backtests close it at the last
    #: close so its P&L is counted; the live book reports it as open instead.
    END_OF_DATA = "end_of_data"


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    """Every tunable. Defaults are the live book's config (see CONFIG_VERSION).

    Fractions of the range are of its width W = resistance - support.
    Percentages are plain percent (1.0 == 1%). Basis points are 1/10,000.
    """

    # --- range detection -----------------------------------------------------
    #: Candles in the range window, excluding the candle being evaluated.
    lookback: int = 96
    #: A candle "touches" support when its low is within this fraction of W of
    #: support (resistance: high within it of resistance).
    touch_tolerance: Decimal = Decimal("0.05")
    #: Touches required on EACH side for full touch credit in confidence.
    min_touches: int = 2
    min_width_pct: Decimal = Decimal("0.8")
    max_width_pct: Decimal = Decimal("6.0")
    #: Kaufman efficiency ratio of closes over the window, 0..1. Above this the
    #: window is directional, not a range.
    max_trend_efficiency: Decimal = Decimal("0.35")
    min_confidence: int = 60

    # --- entries and exits ---------------------------------------------------
    #: LONG when price is within this fraction of W above support; SHORT when
    #: within it below resistance.
    entry_zone: Decimal = Decimal("0.20")
    #: TP as a position in the range: long TP = support + tp_target*W, short
    #: TP = resistance - tp_target*W.
    tp_target: Decimal = Decimal("0.50")
    #: SL beyond the boundary: long SL = support - sl_buffer*W, short SL =
    #: resistance + sl_buffer*W.
    sl_buffer: Decimal = Decimal("0.15")
    min_reward_risk: Decimal = Decimal("1.0")
    #: Exit at the close after this many candles in a trade. 0 disables.
    max_hold_candles: int = 96
    #: Candles to stay flat after any exit.
    cooldown_candles: int = 4
    allow_long: bool = True
    allow_short: bool = True

    # --- paper account -------------------------------------------------------
    starting_balance: Decimal = Decimal("1000")
    #: Equity lost if the stop is hit, before costs, as a percent of equity.
    risk_per_trade_pct: Decimal = Decimal("1.0")
    #: Notional cap: equity * max_leverage.
    max_leverage: Decimal = Decimal("1.0")
    #: Per side, on notional.
    fee_bps: Decimal = Decimal("10")
    #: Adverse, on every fill.
    slippage_bps: Decimal = Decimal("2")


@dataclass(frozen=True, slots=True)
class RangeState:
    support: Decimal
    resistance: Decimal
    mid: Decimal
    width: Decimal
    #: width / mid * 100
    width_pct: Decimal
    #: (price - support) / width. Below 0 or above 1 means outside the range.
    position: Decimal
    touches_support: int
    touches_resistance: int
    trend_efficiency: Decimal
    #: 0..100
    confidence: int
    regime: Regime


@dataclass(frozen=True, slots=True)
class Signal:
    """The strategy's call at the close of the candle opening at `at`."""

    at: datetime
    price: Decimal
    call: Call
    confidence: int
    range: RangeState | None
    #: Set on LONG/SHORT. On WAIT they are None — never estimated.
    entry: Decimal | None
    take_profit: Decimal | None
    stop_loss: Decimal | None
    reward_risk: Decimal | None
    #: First reason is the decisive one.
    reasons: tuple[Reason, ...]


@dataclass(frozen=True, slots=True)
class Trade:
    side: Call
    signal_at: datetime
    entry_at: datetime
    entry_price: Decimal
    take_profit: Decimal
    stop_loss: Decimal
    quantity: Decimal
    notional: Decimal
    exit_at: datetime
    exit_price: Decimal
    exit_reason: ExitReason
    #: Entry + exit fees.
    fees: Decimal
    #: Net of fees and slippage.
    pnl: Decimal
    #: pnl / planned risk amount.
    r_multiple: Decimal | None


@dataclass(frozen=True, slots=True)
class OpenPosition:
    side: Call
    signal_at: datetime
    entry_at: datetime
    entry_price: Decimal
    take_profit: Decimal
    stop_loss: Decimal
    quantity: Decimal
    notional: Decimal
    entry_fee: Decimal
    mark_price: Decimal
    #: At mark, after entry fee, before exit fee.
    unrealised_pnl: Decimal


@dataclass(frozen=True, slots=True)
class Metrics:
    trades: int
    wins: int
    losses: int
    #: Percent. None with no trades.
    win_rate: Decimal | None
    net_pnl: Decimal
    gross_profit: Decimal
    gross_loss: Decimal
    #: gross_profit / |gross_loss|. None with no losing trade (undefined, not ∞).
    profit_factor: Decimal | None
    #: Mean net P&L per trade, USD. None with no trades.
    expectancy: Decimal | None
    #: Peak-to-trough of the mark-to-market equity curve, percent. None with
    #: no trades — an untested account has no measured drawdown.
    max_drawdown_pct: Decimal | None
    return_pct: Decimal
    ending_equity: Decimal


@dataclass(frozen=True, slots=True)
class EquityPoint:
    at: datetime
    equity: Decimal


@dataclass(frozen=True, slots=True)
class BacktestResult:
    config: StrategyConfig
    start: datetime | None
    end: datetime | None
    candles: int
    signal_counts: dict[Call, int]
    wait_reasons: dict[Reason, int]
    trades: tuple[Trade, ...]
    open_position: OpenPosition | None
    #: One point per candle close, mark-to-market. The API downsamples.
    equity_curve: tuple[EquityPoint, ...]
    metrics: Metrics
    long_metrics: Metrics
    short_metrics: Metrics
    #: The call at the last candle.
    last_signal: Signal | None = None
    extra: dict[str, str] = field(default_factory=dict)
