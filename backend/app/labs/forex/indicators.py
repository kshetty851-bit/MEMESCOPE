"""Causal technical indicators. Pure.

Every function returns a list aligned 1:1 with its input, `None` while the
indicator is still warming up. Causal means the value at index i is a function
of inputs[0..i] only, so a series computed on a prefix equals the prefix of the
series computed on the whole — which is what lets the strategies promise no
look-ahead and lets the tests check it by truncation.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import timedelta

from app.labs.forex.types import TIMEFRAME_SECONDS, Candle, Timeframe


def _check_period(period: int) -> None:
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")


def sma(values: Sequence[float], period: int) -> list[float | None]:
    _check_period(period)
    out: list[float | None] = [None] * len(values)
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= period:
            running -= values[i - period]
        if i >= period - 1:
            out[i] = running / period
    return out


def ema(values: Sequence[float], period: int) -> list[float | None]:
    """Seeded with the SMA of the first `period` values, alpha = 2 / (period + 1).

    Seeding with the first value instead would make early readings depend on an
    arbitrary start; the SMA seed is the conventional, reproducible choice.
    """
    _check_period(period)
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    alpha = 2.0 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = alpha * values[i] + (1.0 - alpha) * prev
        out[i] = prev
    return out


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0.0:
        return 50.0 if avg_gain == 0.0 else 100.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def rsi(closes: Sequence[float], period: int = 14) -> list[float | None]:
    """Wilder RSI; first value at index `period` (needs `period` changes)."""
    _check_period(period)
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return out
    gain = 0.0
    loss = 0.0
    for i in range(1, period + 1):
        change = closes[i] - closes[i - 1]
        gain += max(change, 0.0)
        loss += max(-change, 0.0)
    avg_gain = gain / period
    avg_loss = loss / period
    out[period] = _rsi_value(avg_gain, avg_loss)
    for i in range(period + 1, len(closes)):
        change = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period
        out[i] = _rsi_value(avg_gain, avg_loss)
    return out


def atr(candles: Sequence[Candle], period: int = 14) -> list[float | None]:
    """Wilder ATR. True range needs the previous close, so it is undefined at
    index 0 and the first ATR (mean of TR[1..period]) lands at index `period`."""
    _check_period(period)
    out: list[float | None] = [None] * len(candles)
    if len(candles) <= period:
        return out
    tr = [0.0] * len(candles)
    for i in range(1, len(candles)):
        c = candles[i]
        prev_close = candles[i - 1].close
        tr[i] = max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close))
    prev = sum(tr[1 : period + 1]) / period
    out[period] = prev
    for i in range(period + 1, len(candles)):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return out


def bollinger(
    closes: Sequence[float], period: int = 20, num_std: float = 2.0
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """(mid, upper, lower) with population standard deviation (ddof=0)."""
    _check_period(period)
    mid = sma(closes, period)
    upper: list[float | None] = [None] * len(closes)
    lower: list[float | None] = [None] * len(closes)
    for i, m in enumerate(mid):
        if m is None:
            continue
        window = closes[i - period + 1 : i + 1]
        std = math.sqrt(sum((v - m) ** 2 for v in window) / period)
        upper[i] = m + num_std * std
        lower[i] = m - num_std * std
    return mid, upper, lower


def htf_values_at(
    exec_candles: Sequence[Candle],
    exec_tf: Timeframe,
    htf_candles: Sequence[Candle],
    htf_tf: Timeframe,
    htf_values: Sequence[float | None],
) -> list[float | None]:
    """Map a higher-timeframe series onto execution bars without look-ahead.

    An execution bar is only known at its close, so it may see only HTF candles
    that had already closed by then (HTF close time <= exec close time). A 5m
    bar closing at 10:10 therefore sees the 15m candle that closed at 10:00,
    not the one closing at 10:15 — whose OHLC includes prices from after this
    bar. Both inputs must be ascending; the scan is linear.
    """
    if len(htf_values) != len(htf_candles):
        raise ValueError("htf_values must align with htf_candles")
    exec_delta = timedelta(seconds=TIMEFRAME_SECONDS[exec_tf])
    htf_delta = timedelta(seconds=TIMEFRAME_SECONDS[htf_tf])
    out: list[float | None] = []
    j = 0
    n = len(htf_candles)
    for c in exec_candles:
        exec_close = c.open_time + exec_delta
        while j < n and htf_candles[j].open_time + htf_delta <= exec_close:
            j += 1
        out.append(htf_values[j - 1] if j > 0 else None)
    return out
