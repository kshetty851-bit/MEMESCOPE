"""Signals plus engine, composed in memory. Pure.

Research replays the same market hundreds of times (a grid, a walk-forward, a
sensitivity sweep), so the market is loaded ONCE into a `Market` and every
replay is `run(cfg, market, trade_from, trade_to)` - no I/O between replays.

Two properties are the point of this module, and both are tested:

* `trade_to` is a hard edge. Candles at or after it are cut away BEFORE signals
  are generated, so nothing after the window can reach a decision inside it.
  A run over a development window therefore equals the same window of any
  longer run, regardless of what data sits behind it.
* `trade_from` is where TRADING starts, not where data starts. The candles
  before it are warm-up, so an EMA(200) is already settled on the first day
  rather than seeded from nothing; the engine ignores signals earlier than it.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.labs.forex.data import slice_window
from app.labs.forex.engine import run_backtest
from app.labs.forex.strategies import generate_signals
from app.labs.forex.types import (
    INSTRUMENTS,
    TIMEFRAME_SECONDS,
    BacktestConfig,
    BacktestResult,
    Candle,
    Timeframe,
)

#: Never warm up on less than this, however short the indicators are.
MIN_WARMUP = timedelta(days=10)
#: Weekends remove two days in seven, so 1.5x the bars' nominal duration.
WARMUP_SAFETY = 1.5


class NoDataError(ValueError):
    """The market holds no candle in the requested range."""


@dataclass(frozen=True)
class Market:
    """Everything a replay reads, already loaded and sorted ascending."""

    symbol: str
    timeframe: Timeframe
    #: Execution candles, warm-up included.
    candles: tuple[Candle, ...]
    htf: tuple[Candle, ...] | None = None
    htf_timeframe: Timeframe | None = None
    #: 1-minute candles that order a stop and a target inside one bar.
    lower: tuple[Candle, ...] | None = None
    sources: tuple[str, ...] = ()
    #: "stored" or "resampled_from_1m".
    exec_derived: str = "stored"
    #: "stored", "resampled" or "none" (filter off, or same timeframe).
    htf_derived: str = "none"


def needs_htf(cfg: BacktestConfig) -> bool:
    p = cfg.params
    return p.trend_filter and p.trend_timeframe != cfg.timeframe


def warmup_for(cfg: BacktestConfig) -> timedelta:
    """How far before the first trading day the indicators need data."""
    p = cfg.params
    exec_s = TIMEFRAME_SECONDS[cfg.timeframe]
    need = max(p.atr_period, p.rsi_period, p.bb_period) * exec_s
    if p.trend_filter:
        need = max(need, p.trend_ema_period * TIMEFRAME_SECONDS[p.trend_timeframe])
    return max(MIN_WARMUP, timedelta(seconds=need * WARMUP_SAFETY))


def fingerprint(candles: Sequence[Candle], symbol: str, timeframe: Timeframe) -> str:
    """sha256 of "symbol|tf|count|first|last|sum(close)".

    Two runs with the same fingerprint read the same candles for every purpose
    that matters here; a late import into the range changes the count or the sum.
    """
    if candles:
        first = candles[0].open_time.isoformat()
        last = candles[-1].open_time.isoformat()
        total = math.fsum(c.close for c in candles)
    else:
        first = last = ""
        total = 0.0
    text = f"{symbol}|{timeframe.value}|{len(candles)}|{first}|{last}|{total:.6f}"
    return hashlib.sha256(text.encode()).hexdigest()


def combined_fingerprint(prints: Sequence[str]) -> str:
    """One fingerprint for several markets (a comparison). A single market's own
    fingerprint is returned unchanged, so a one-config comparison matches its
    backtest."""
    if len(prints) == 1:
        return prints[0]
    return hashlib.sha256("|".join(prints).encode()).hexdigest()


def run(
    cfg: BacktestConfig, market: Market, trade_from: datetime, trade_to: datetime
) -> BacktestResult:
    """Replay `cfg` over `market`, trading in [trade_from, trade_to)."""
    if cfg.symbol != market.symbol or cfg.timeframe != market.timeframe:
        raise ValueError("market_does_not_match_config")
    if trade_to <= trade_from:
        raise ValueError("end_not_after_start")
    instrument = INSTRUMENTS[cfg.symbol]

    candles = slice_window(market.candles, None, trade_to)
    if not candles or candles[-1].open_time < trade_from:
        # Nothing at or after trade_from before the edge: no bar to trade.
        raise NoDataError("no_candles_in_window")

    htf: Sequence[Candle] | None = None
    if needs_htf(cfg):
        if market.htf is None or market.htf_timeframe != cfg.params.trend_timeframe:
            raise ValueError("market_lacks_trend_timeframe")
        htf = slice_window(market.htf, None, trade_to)

    lower: Sequence[Candle] | None = None
    if market.lower and cfg.timeframe is not Timeframe.M1:
        lower = slice_window(market.lower, None, trade_to)

    signals = generate_signals(cfg, candles, htf, instrument)
    return run_backtest(
        cfg, candles, signals, instrument=instrument, lower_tf=lower, trade_from=trade_from
    )
