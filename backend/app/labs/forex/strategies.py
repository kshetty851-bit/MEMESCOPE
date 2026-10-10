"""Signal generation for the three baseline strategies. Pure.

A `Signal` at index i is decided at the CLOSE of bar i; the engine enters at
bar i+1's open. Strategies emit raw signals for both directions and never look
at `cfg.direction`, `cfg.session_filter` or the risk limits — the engine owns
those, so the same signal list can be replayed under different restrictions.

Nothing here reads past bar i when deciding bar i. The tests prove it by
truncation: signals on a prefix must equal the prefix of signals on the whole.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from app.labs.forex.indicators import atr, bollinger, ema, htf_values_at, rsi
from app.labs.forex.sessions import in_session, minute_of_day
from app.labs.forex.types import (
    TIMEFRAME_SECONDS,
    BacktestConfig,
    Candle,
    Direction,
    Instrument,
    Session,
    Signal,
    StopMethod,
    StrategyId,
    StrategyParams,
    TakeProfitMethod,
)

#: Fraction of the expected Asian bars that must be present, as a ratio
#: (4/5) so the comparison stays in integers.
_MIN_COVERAGE_NUM = 4
_MIN_COVERAGE_DEN = 5


def generate_signals(
    cfg: BacktestConfig,
    candles: Sequence[Candle],
    htf_candles: Sequence[Candle] | None,
    instrument: Instrument,
) -> list[Signal]:
    if (
        cfg.params.stop_method is StopMethod.RANGE
        and cfg.strategy is not StrategyId.LONDON_BREAKOUT
    ):
        raise ValueError("StopMethod.RANGE is only defined for the London breakout")
    if cfg.strategy is StrategyId.LONDON_BREAKOUT:
        return london_breakout(cfg, candles, htf_candles, instrument)
    if cfg.strategy is StrategyId.RSI_PULLBACK:
        return rsi_pullback(cfg, candles, htf_candles, instrument)
    if cfg.strategy is StrategyId.BOLLINGER_REVERSION:
        return bollinger_reversion(cfg, candles, htf_candles, instrument)
    raise ValueError(f"unknown strategy {cfg.strategy!r}")


def _trend_ema(
    cfg: BacktestConfig,
    candles: Sequence[Candle],
    htf_candles: Sequence[Candle] | None,
) -> list[float | None] | None:
    """Trend EMA aligned to the execution bars, or None when the filter is off
    (so a disabled filter never demands higher-timeframe data)."""
    p = cfg.params
    if not p.trend_filter:
        return None
    if p.trend_timeframe == cfg.timeframe:
        return ema([c.close for c in candles], p.trend_ema_period)
    if htf_candles is None:
        raise ValueError("trend_timeframe differs from timeframe but htf_candles is None")
    htf_ema = ema([c.close for c in htf_candles], p.trend_ema_period)
    return htf_values_at(candles, cfg.timeframe, htf_candles, p.trend_timeframe, htf_ema)


def _distances(
    p: StrategyParams,
    pip: float,
    direction: Direction,
    close: float,
    atr_i: float | None,
    asian_high: float | None = None,
    asian_low: float | None = None,
) -> tuple[float, float | None] | None:
    """(stop distance, take-profit distance), or None when the stop cannot be
    set honestly (indicator unavailable, or a non-positive distance)."""
    if p.stop_method is StopMethod.ATR:
        if atr_i is None:
            return None
        stop = atr_i * p.stop_atr_multiple
    elif p.stop_method is StopMethod.FIXED_PIPS:
        stop = p.stop_pips * pip
    else:
        if asian_high is None or asian_low is None:
            raise ValueError("StopMethod.RANGE needs the Asian range")
        buffer = p.range_stop_buffer_pips * pip
        if direction is Direction.LONG:
            stop = close - (asian_low - buffer)
        else:
            stop = (asian_high + buffer) - close
    if stop <= 0:
        return None
    if p.take_profit_method is TakeProfitMethod.R_MULTIPLE:
        return stop, p.risk_reward * stop
    if p.take_profit_method is TakeProfitMethod.FIXED_PIPS:
        return stop, p.take_profit_pips * pip
    return stop, None


def _atr_needed(p: StrategyParams, *, distance_filter: bool = False) -> bool:
    return p.stop_method is StopMethod.ATR or distance_filter


def _tf_minutes(cfg: BacktestConfig) -> int:
    return TIMEFRAME_SECONDS[cfg.timeframe] // 60


def _window_minutes(s: Session) -> tuple[int, int]:
    start = s.start_hour * 60 + s.start_minute
    end = s.end_hour * 60 + s.end_minute
    return start, end


def london_breakout(
    cfg: BacktestConfig,
    candles: Sequence[Candle],
    htf_candles: Sequence[Candle] | None,
    instrument: Instrument,
) -> list[Signal]:
    p = cfg.params
    pip = instrument.pip_size
    trend = _trend_ema(cfg, candles, htf_candles)
    atr_vals = atr(candles, p.atr_period) if _atr_needed(p) else None

    a_start, a_end = _window_minutes(p.asian_session)
    t_start, t_end = _window_minutes(p.trading_session)
    # A wrapping or whole-day window has no single "that day" to take a range
    # from; refusing beats silently building a range from the wrong bars.
    if not (a_start < a_end and t_start < t_end):
        raise ValueError("london breakout sessions must not wrap midnight")
    tf_min = _tf_minutes(cfg)
    expected = -(-(a_end - a_start) // tf_min)
    buffer = p.breakout_buffer_pips * pip
    need = max(1, p.breakout_confirmation_bars)

    signals: list[Signal] = []
    day: date | None = None
    a_high = float("-inf")
    a_low = float("inf")
    a_count = 0
    range_ok: bool | None = None
    up_run = 0
    down_run = 0
    long_done = False
    short_done = False

    for i, c in enumerate(candles):
        d = c.open_time.date()
        if d != day:
            day = d
            a_high, a_low, a_count = float("-inf"), float("inf"), 0
            range_ok = None
            up_run = down_run = 0
            long_done = short_done = False
        if in_session(c.open_time, p.asian_session):
            a_high = max(a_high, c.high)
            a_low = min(a_low, c.low)
            a_count += 1
        # The range is only final once the Asian window has closed; a trading
        # bar inside it would be trading a range still being drawn.
        if (
            not in_session(c.open_time, p.trading_session)
            or minute_of_day(c.open_time) < a_end
        ):
            up_run = down_run = 0
            continue
        if range_ok is None:
            range_ok = (
                a_count * _MIN_COVERAGE_DEN >= expected * _MIN_COVERAGE_NUM
                and p.min_range_pips <= round((a_high - a_low) / pip, 6) <= p.max_range_pips
            )
        if not range_ok:
            continue

        up_run = up_run + 1 if c.close > a_high + buffer else 0
        down_run = down_run + 1 if c.close < a_low - buffer else 0
        ema_i = trend[i] if trend is not None else None
        if trend is not None and ema_i is None:
            continue
        atr_i = atr_vals[i] if atr_vals is not None else None

        long_open = not (p.one_trade_per_side_per_day and long_done)
        short_open = not (p.one_trade_per_side_per_day and short_done)
        if up_run >= need and long_open and (ema_i is None or c.close > ema_i):
            dist = _distances(p, pip, Direction.LONG, c.close, atr_i, a_high, a_low)
            if dist is not None:
                signals.append(
                    Signal(i, Direction.LONG, dist[0], dist[1], "asian_high_breakout")
                )
                long_done = True
        if down_run >= need and short_open and (ema_i is None or c.close < ema_i):
            dist = _distances(p, pip, Direction.SHORT, c.close, atr_i, a_high, a_low)
            if dist is not None:
                signals.append(
                    Signal(i, Direction.SHORT, dist[0], dist[1], "asian_low_breakout")
                )
                short_done = True
    return signals


def rsi_pullback(
    cfg: BacktestConfig,
    candles: Sequence[Candle],
    htf_candles: Sequence[Candle] | None,
    instrument: Instrument,
) -> list[Signal]:
    p = cfg.params
    pip = instrument.pip_size
    trend = _trend_ema(cfg, candles, htf_candles)
    rsi_vals = rsi([c.close for c in candles], p.rsi_period)
    atr_vals = atr(candles, p.atr_period) if _atr_needed(p) else None

    signals: list[Signal] = []
    for i in range(1, len(candles)):
        prev, cur = rsi_vals[i - 1], rsi_vals[i]
        if prev is None or cur is None:
            continue
        close = candles[i].close
        ema_i = trend[i] if trend is not None else None
        if trend is not None and ema_i is None:
            continue
        atr_i = atr_vals[i] if atr_vals is not None else None

        if prev < p.rsi_long_level <= cur and (ema_i is None or close > ema_i):
            dist = _distances(p, pip, Direction.LONG, close, atr_i)
            if dist is not None:
                signals.append(
                    Signal(i, Direction.LONG, dist[0], dist[1], "rsi_pullback_long")
                )
        if prev > p.rsi_short_level >= cur and (ema_i is None or close < ema_i):
            dist = _distances(p, pip, Direction.SHORT, close, atr_i)
            if dist is not None:
                signals.append(
                    Signal(i, Direction.SHORT, dist[0], dist[1], "rsi_pullback_short")
                )
    return signals


def bollinger_reversion(
    cfg: BacktestConfig,
    candles: Sequence[Candle],
    htf_candles: Sequence[Candle] | None,
    instrument: Instrument,
) -> list[Signal]:
    p = cfg.params
    pip = instrument.pip_size
    trend = _trend_ema(cfg, candles, htf_candles)
    closes = [c.close for c in candles]
    _, upper, lower = bollinger(closes, p.bb_period, p.bb_std)
    rsi_vals = rsi(closes, p.rsi_period)
    distance_filter = p.trend_filter and p.trend_max_distance_atr > 0
    atr_vals = (
        atr(candles, p.atr_period) if _atr_needed(p, distance_filter=distance_filter) else None
    )

    signals: list[Signal] = []
    long_setup: int | None = None
    short_setup: int | None = None

    for i, close in enumerate(closes):
        lo, up, r = lower[i], upper[i], rsi_vals[i]
        if lo is None or up is None:
            continue
        if long_setup is not None and i > long_setup + p.reentry_window_bars:
            long_setup = None
        if short_setup is not None and i > short_setup + p.reentry_window_bars:
            short_setup = None

        ema_i = trend[i] if trend is not None else None
        atr_i = atr_vals[i] if atr_vals is not None else None

        # A re-entry consumes the setup whether or not the trend filter lets it
        # through: the excursion is over either way, and waiting on a veto would
        # turn a "re-entry" into a later, different trade.
        if long_setup is not None and close > lo:
            long_setup = None
            if _bb_trend_ok(p, Direction.LONG, close, ema_i, atr_i, trend is not None):
                dist = _distances(p, pip, Direction.LONG, close, atr_i)
                if dist is not None:
                    signals.append(
                        Signal(i, Direction.LONG, dist[0], dist[1], "bb_reentry_long")
                    )
        if short_setup is not None and close < up:
            short_setup = None
            if _bb_trend_ok(p, Direction.SHORT, close, ema_i, atr_i, trend is not None):
                dist = _distances(p, pip, Direction.SHORT, close, atr_i)
                if dist is not None:
                    signals.append(
                        Signal(i, Direction.SHORT, dist[0], dist[1], "bb_reentry_short")
                    )

        if r is not None:
            if close < lo and r < p.rsi_oversold:
                long_setup = i
            if close > up and r > p.rsi_overbought:
                short_setup = i
    return signals


def _bb_trend_ok(
    p: StrategyParams,
    direction: Direction,
    close: float,
    ema_i: float | None,
    atr_i: float | None,
    filter_on: bool,
) -> bool:
    if not filter_on:
        return True
    if ema_i is None:
        return False
    # Signed gap on the side that would count as "stretched away from trend".
    stretch = (ema_i - close) if direction is Direction.LONG else (close - ema_i)
    if p.trend_max_distance_atr > 0:
        if atr_i is None:
            return False
        return stretch <= p.trend_max_distance_atr * atr_i
    return stretch < 0
