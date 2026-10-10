"""The Forex Strategy Lab's domain types — the contract between data, engine,
research and API.

Pure data. No I/O, no clock, no SQLAlchemy.

Numbers: prices and indicators are `float` inside the engine, and money is
`Decimal`. A year of 5-minute EUR/USD is ~75,000 bars and a walk-forward run
replays it hundreds of times; Decimal indicator maths would make that minutes
instead of seconds, and an EMA is irrational in any representation anyway.
Prices are rounded to the instrument's quote precision at import and stored as
NUMERIC, so a float here never holds a digit the feed did not quote. Every
money figure that leaves the engine (balance, P&L, costs) is a `Decimal`
quantised to cents, and the API serialises it as a string.

Research and paper only. Nothing in this package holds a broker credential,
places an order or reaches an account — `test_forex_isolation.py` enforces it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

#: Bumped whenever a default in any config below changes, and recorded on every
#: run, so two runs with the "same defaults" can be told apart across deploys.
CONFIG_VERSION = 1

CENT = Decimal("0.01")


class Timeframe(StrEnum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"


TIMEFRAME_SECONDS: dict[Timeframe, int] = {
    Timeframe.M1: 60,
    Timeframe.M5: 300,
    Timeframe.M15: 900,
    Timeframe.H1: 3600,
}


@dataclass(frozen=True, slots=True)
class Instrument:
    """Broker contract specification. Account currency is always USD.

    `pip_size` is the price increment one pip represents; `price_decimals` is
    the quote precision the feed reports (one fractional pip beyond the pip).
    One standard lot is `contract_size` units of the base currency.
    """

    symbol: str
    base: str
    quote: str
    pip_size: float
    price_decimals: int
    contract_size: int = 100_000
    #: Smallest tradable increment, in units. 1,000 = one micro lot.
    min_units: int = 1_000
    #: Whether the lab's data engine is wired for it yet. Future instruments
    #: are listed so the contract is settled, but are refused until enabled.
    enabled: bool = True


INSTRUMENTS: dict[str, Instrument] = {
    "EURUSD": Instrument("EURUSD", "EUR", "USD", 0.0001, 5),
    "GBPUSD": Instrument("GBPUSD", "GBP", "USD", 0.0001, 5),
    "USDJPY": Instrument("USDJPY", "USD", "JPY", 0.01, 3),
}


@dataclass(frozen=True, slots=True)
class Candle:
    """One CLOSED candle. `open_time` is the candle's start, UTC (tz-aware).

    Prices are mid unless the import says otherwise; the engine adds half the
    configured spread on each side. `volume` is tick volume where the source
    has it and 0.0 where it does not — never estimated.
    """

    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class Direction(StrEnum):
    LONG = "long"
    SHORT = "short"


class DirectionMode(StrEnum):
    BOTH = "both"
    LONG_ONLY = "long_only"
    SHORT_ONLY = "short_only"


class StrategyId(StrEnum):
    LONDON_BREAKOUT = "london_breakout"
    RSI_PULLBACK = "rsi_pullback"
    BOLLINGER_REVERSION = "bollinger_reversion"


class StopMethod(StrEnum):
    #: `stop_atr_multiple` x ATR(atr_period) at the signal bar.
    ATR = "atr"
    #: A fixed `stop_pips` distance.
    FIXED_PIPS = "fixed_pips"
    #: London breakout only: the opposite side of the Asian range (+ buffer).
    RANGE = "range"


class TakeProfitMethod(StrEnum):
    #: `risk_reward` x the stop distance.
    R_MULTIPLE = "r_multiple"
    #: A fixed `take_profit_pips` distance.
    FIXED_PIPS = "fixed_pips"
    #: No take-profit; exits by stop, session end or end of data only.
    NONE = "none"


class ExitReason(StrEnum):
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    #: Closed at the end of the strategy's session window (`close_at_session_end`).
    SESSION_END = "session_end"
    #: Equity fell to the margin closeout level; every position was liquidated.
    MARGIN_CLOSEOUT = "margin_closeout"
    #: Still open when the candles ran out; closed at the last close so its P&L
    #: is counted rather than hidden.
    END_OF_DATA = "end_of_data"


class SkipReason(StrEnum):
    """Why a signal was not traded. Stable codes; prose is rendered by the API."""

    DIRECTION_DISABLED = "direction_disabled"
    OUTSIDE_SESSION = "outside_session"
    MAX_OPEN_POSITIONS = "max_open_positions"
    MAX_TRADES_PER_DAY = "max_trades_per_day"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    #: Stop distance so small, or equity so low, that size rounds to < min_units.
    SIZE_BELOW_MINIMUM = "size_below_minimum"
    #: Leverage cap cut the size below `min_units`.
    MARGIN_INSUFFICIENT = "margin_insufficient"
    #: No next bar to enter on (signal on the final candle).
    NO_NEXT_BAR = "no_next_bar"
    #: The next bar is not contiguous with the signal bar (data gap / weekend).
    GAP_BEFORE_ENTRY = "gap_before_entry"


@dataclass(frozen=True, slots=True)
class Session:
    """A daily UTC window [start_hour:start_minute, end_hour:end_minute)."""

    start_hour: int
    end_hour: int
    start_minute: int = 0
    end_minute: int = 0


@dataclass(frozen=True, slots=True)
class StrategyParams:
    """Every strategy parameter. Each strategy reads only the fields it uses.

    Defaults are the brief's baseline hypotheses, not tuned values.
    """

    # Shared
    trend_filter: bool = True
    trend_timeframe: Timeframe = Timeframe.M15
    trend_ema_period: int = 200
    atr_period: int = 14
    stop_method: StopMethod = StopMethod.ATR
    stop_atr_multiple: float = 1.5
    stop_pips: float = 15.0
    take_profit_method: TakeProfitMethod = TakeProfitMethod.R_MULTIPLE
    risk_reward: float = 2.0
    take_profit_pips: float = 30.0
    #: Close any open trade at the end of the trading window.
    close_at_session_end: bool = False

    # London breakout
    asian_session: Session = Session(0, 6)
    trading_session: Session = Session(7, 10)
    #: A breakout must CLOSE this many pips beyond the range to count.
    breakout_buffer_pips: float = 0.0
    #: Consecutive closes beyond the range required (1 = first close).
    breakout_confirmation_bars: int = 1
    #: Extra pips beyond the opposite range side for StopMethod.RANGE.
    range_stop_buffer_pips: float = 2.0
    #: Skip days whose Asian range is narrower / wider than this (pips).
    min_range_pips: float = 5.0
    max_range_pips: float = 60.0
    #: One breakout trade per side per day.
    one_trade_per_side_per_day: bool = True

    # RSI pullback
    rsi_period: int = 14
    rsi_long_level: float = 40.0
    rsi_short_level: float = 60.0

    # Bollinger reversion
    bb_period: int = 20
    bb_std: float = 2.0
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    #: Bars after the outside-band close within which the re-entry close must
    #: happen; an excursion that stays outside longer is abandoned.
    reentry_window_bars: int = 3
    #: Trend filter for mean reversion: refuse LONG when price is more than
    #: `trend_max_distance_atr` ATRs below the trend EMA (and mirror for SHORT).
    #: 0 disables the distance test while `trend_filter` still applies.
    trend_max_distance_atr: float = 3.0


@dataclass(frozen=True, slots=True)
class CostConfig:
    """Execution costs. Spread and slippage in pips; commission in USD per
    standard lot per side; financing in USD per standard lot per night."""

    spread_pips: float = 1.0
    slippage_pips: float = 0.2
    commission_per_lot_side: Decimal = Decimal("3.50")
    #: Overnight swap, charged per standard lot when a position is held through
    #: the 22:00 UTC rollover. Negative = the account pays. Wednesday's
    #: rollover is charged x3 (weekend), as most brokers do.
    swap_long_per_lot: Decimal = Decimal("-7.00")
    swap_short_per_lot: Decimal = Decimal("2.00")
    financing_enabled: bool = True


@dataclass(frozen=True, slots=True)
class RiskConfig:
    initial_capital: Decimal = Decimal("1000")
    max_leverage: int = 20
    #: Percent of current equity risked per trade, sized from the stop distance.
    risk_per_trade_pct: Decimal = Decimal("0.5")
    #: No new entries for the rest of the UTC day once the day's realised plus
    #: unrealised loss reaches this percent of the day's starting equity.
    #: 0 disables.
    max_daily_loss_pct: Decimal = Decimal("3")
    max_trades_per_day: int = 3
    max_open_positions: int = 1
    #: Liquidate everything when equity / used margin falls to this percent.
    margin_closeout_pct: Decimal = Decimal("50")


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """Everything a run depends on. Recorded verbatim with every run."""

    strategy: StrategyId
    symbol: str = "EURUSD"
    timeframe: Timeframe = Timeframe.M5
    direction: DirectionMode = DirectionMode.BOTH
    params: StrategyParams = field(default_factory=StrategyParams)
    costs: CostConfig = field(default_factory=CostConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    #: Extra entry restriction on top of the strategy's own window. None = any time.
    session_filter: Session | None = None


@dataclass(frozen=True, slots=True)
class Signal:
    """A strategy's decision at the CLOSE of bar `index`.

    The engine enters at the OPEN of bar `index + 1` — never at the signal
    bar's close, which was not tradable when the decision was made.

    Distances are positive price distances from the fill. `take_profit_distance`
    None means no take-profit.
    """

    index: int
    direction: Direction
    stop_distance: float
    take_profit_distance: float | None
    #: Stable code naming the rule that fired, e.g. "asian_high_breakout".
    reason: str


@dataclass(frozen=True, slots=True)
class Trade:
    id: int
    direction: Direction
    signal_time: datetime
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    stop_price: float
    take_profit_price: float | None
    units: int
    #: Stop-distance risk in USD at entry.
    risk_usd: Decimal
    gross_pnl: Decimal
    commission: Decimal
    #: Spread + slippage cost in USD (already inside gross vs a mid fill).
    spread_slippage_cost: Decimal
    financing: Decimal
    net_pnl: Decimal
    #: net_pnl / risk_usd.
    r_multiple: float
    exit_reason: ExitReason
    reason: str
    #: SL and TP both inside one bar with no lower-timeframe data to order
    #: them; resolved as STOP (conservative). Counted and disclosed.
    ambiguous_exit: bool = False
    #: Margin used at entry, USD.
    margin_used: Decimal = Decimal(0)


@dataclass(frozen=True, slots=True)
class EquityPoint:
    time: datetime
    balance: Decimal
    equity: Decimal
    #: Used margin / equity, percent. 0 when flat.
    margin_utilization_pct: float = 0.0


@dataclass(frozen=True, slots=True)
class SkippedSignal:
    time: datetime
    direction: Direction
    reason: SkipReason


@dataclass(frozen=True, slots=True)
class BacktestResult:
    config: BacktestConfig
    start: datetime
    end: datetime
    bars: int
    trades: tuple[Trade, ...]
    #: One point per bar would be ~75k for a year; the engine records one per
    #: closed trade plus one per UTC day close, which is what the charts and
    #: daily-return metrics need.
    equity_curve: tuple[EquityPoint, ...]
    skipped: tuple[SkippedSignal, ...]
    final_balance: Decimal
    #: Bars on which SL/TP were resolved by lower-timeframe data.
    exits_resolved_by_lower_tf: int = 0
    #: Bars resolved by the conservative stop-first assumption.
    exits_ambiguous: int = 0
    margin_closeouts: int = 0
    #: Signals the strategy produced (traded + skipped).
    signals: int = 0
    #: Disclosures the dashboard must show verbatim (stable codes).
    assumptions: tuple[str, ...] = ()
