"""Indicator maths on closed candles. Pure functions, plain Python, no I/O.

Every series function returns a list aligned to its input: index i holds the
value on candle i, or None until enough history exists. The conventions,
because reference implementations differ on seeding:

* **EMA** seeds with the simple mean of the first `period` values, then
  smooths with k = 2 / (period + 1).
* **ATR** is Wilder's. TR[0] = high - low (there is no previous close); the
  first ATR is the mean of the first `period` true ranges; after that
  ATR = (ATR_prev * (period - 1) + TR) / period.
* **+DI, -DI, ADX** are Wilder's. Directional movement starts on candle 1.
  +DM, -DM and TR are Wilder-summed over `period` (first value a plain sum
  of candles 1..period, then S = S_prev - S_prev / period + x). DI = 100 *
  S_DM / S_TR, DX = 100 * |+DI - -DI| / (+DI + -DI), and ADX seeds with the
  mean of the first `period` DX values then smooths like ATR. The first ADX
  therefore lands on candle 2 * period - 1.
* **Donchian** at i is the highest high and lowest low of candles
  i - period + 1 .. i.
* A **swing high** at i is a high strictly above every high in the
  `lookback` candles on each side (a plateau is not a swing); it is
  confirmed once candle i + lookback has closed. Swing lows mirror it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class HasOHLC(Protocol):
    high: object
    low: object
    close: object


def ema(values: Sequence[float], period: int) -> list[float | None]:
    if period < 1:
        raise ValueError("period must be >= 1")
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    k = 2.0 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1.0 - k)
        out[i] = prev
    return out


def true_range(candles: Sequence[HasOHLC]) -> list[float]:
    out: list[float] = []
    prev_close: float | None = None
    for c in candles:
        high, low = float(c.high), float(c.low)
        if prev_close is None:
            out.append(high - low)
        else:
            out.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        prev_close = float(c.close)
    return out


def wilder_average(values: Sequence[float | None], period: int) -> list[float | None]:
    """Seed with the mean of the first `period` values after the first
    non-None, then ATR-style smoothing. Shared by ATR and ADX."""
    if period < 1:
        raise ValueError("period must be >= 1")
    out: list[float | None] = [None] * len(values)
    first = next((i for i, v in enumerate(values) if v is not None), None)
    if first is None or len(values) - first < period:
        return out
    window = [float(v) for v in values[first:first + period]]  # type: ignore[arg-type]
    prev = sum(window) / period
    out[first + period - 1] = prev
    for i in range(first + period, len(values)):
        prev = (prev * (period - 1) + float(values[i])) / period  # type: ignore[arg-type]
        out[i] = prev
    return out


def atr(candles: Sequence[HasOHLC], period: int = 14) -> list[float | None]:
    return wilder_average(true_range(candles), period)


def adx(
    candles: Sequence[HasOHLC], period: int = 14,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Returns (+DI, -DI, ADX), each aligned to `candles`."""
    if period < 1:
        raise ValueError("period must be >= 1")
    n = len(candles)
    plus_di: list[float | None] = [None] * n
    minus_di: list[float | None] = [None] * n
    if n < period + 1:
        return plus_di, minus_di, [None] * n

    highs = [float(c.high) for c in candles]
    lows = [float(c.low) for c in candles]
    tr = true_range(candles)
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    for i in range(1, n):
        up, down = highs[i] - highs[i - 1], lows[i - 1] - lows[i]
        if up > down and up > 0:
            plus_dm[i] = up
        elif down > up and down > 0:
            minus_dm[i] = down

    def wilder_sum(x: list[float]) -> list[float | None]:
        out: list[float | None] = [None] * n
        s = sum(x[1:period + 1])
        out[period] = s
        for i in range(period + 1, n):
            s = s - s / period + x[i]
            out[i] = s
        return out

    s_tr, s_plus, s_minus = wilder_sum(tr), wilder_sum(plus_dm), wilder_sum(minus_dm)
    dx: list[float | None] = [None] * n
    for i in range(period, n):
        total = s_tr[i] or 0.0
        pdi = 100.0 * (s_plus[i] or 0.0) / total if total else 0.0
        mdi = 100.0 * (s_minus[i] or 0.0) / total if total else 0.0
        plus_di[i], minus_di[i] = pdi, mdi
        dx[i] = 100.0 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi else 0.0
    return plus_di, minus_di, wilder_average(dx, period)


def donchian(
    candles: Sequence[HasOHLC], period: int,
) -> tuple[list[float | None], list[float | None]]:
    """(upper, lower): the highest high and lowest low of the last `period`
    candles, at every index that has them."""
    if period < 1:
        raise ValueError("period must be >= 1")
    n = len(candles)
    upper: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n
    for i in range(period - 1, n):
        window = candles[i - period + 1:i + 1]
        upper[i] = max(float(c.high) for c in window)
        lower[i] = min(float(c.low) for c in window)
    return upper, lower


# --- swing structure ----------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Swing:
    index: int
    price: float


@dataclass(frozen=True, slots=True)
class SwingStructure:
    #: The last two confirmed swing highs and lows, oldest first. Fewer than
    #: two of either and the structure is MIXED.
    highs: tuple[Swing, ...]
    lows: tuple[Swing, ...]
    #: `HH_HL` | `LH_LL` | `MIXED`
    structure: str


def find_swings(candles: Sequence[HasOHLC], lookback: int) -> tuple[list[Swing], list[Swing]]:
    """Every swing high and low in the series, by index."""
    if lookback < 1:
        raise ValueError("lookback must be >= 1")
    highs = [float(c.high) for c in candles]
    lows = [float(c.low) for c in candles]
    swing_highs: list[Swing] = []
    swing_lows: list[Swing] = []
    for i in range(lookback, len(candles) - lookback):
        around = list(range(i - lookback, i)) + list(range(i + 1, i + lookback + 1))
        if all(highs[i] > highs[j] for j in around):
            swing_highs.append(Swing(i, highs[i]))
        if all(lows[i] < lows[j] for j in around):
            swing_lows.append(Swing(i, lows[i]))
    return swing_highs, swing_lows


def classify(highs: Sequence[Swing], lows: Sequence[Swing]) -> str:
    if len(highs) < 2 or len(lows) < 2:
        return "MIXED"
    if highs[-1].price > highs[-2].price and lows[-1].price > lows[-2].price:
        return "HH_HL"
    if highs[-1].price < highs[-2].price and lows[-1].price < lows[-2].price:
        return "LH_LL"
    return "MIXED"


def known_swings(candles: Sequence[HasOHLC], lookback: int) -> list[SwingStructure]:
    """What was KNOWN on each candle: the last two swing highs and lows
    confirmed by then, and their label. A swing counts from the candle that
    confirms it (its index + lookback), never earlier. This is what makes
    `bars_in_state` and the structure veto free of hindsight."""
    swing_highs, swing_lows = find_swings(candles, lookback)
    out: list[SwingStructure] = []
    hi = lo = 0
    seen_h: list[Swing] = []
    seen_l: list[Swing] = []
    for i in range(len(candles)):
        while hi < len(swing_highs) and swing_highs[hi].index + lookback <= i:
            seen_h.append(swing_highs[hi])
            hi += 1
        while lo < len(swing_lows) and swing_lows[lo].index + lookback <= i:
            seen_l.append(swing_lows[lo])
            lo += 1
        highs, lows = tuple(seen_h[-2:]), tuple(seen_l[-2:])
        out.append(SwingStructure(highs, lows, classify(highs, lows)))
    return out


def structure_series(candles: Sequence[HasOHLC], lookback: int) -> list[str]:
    """The structure label as it was known on each candle."""
    return [s.structure for s in known_swings(candles, lookback)]


def swing_structure(candles: Sequence[HasOHLC], lookback: int) -> SwingStructure:
    """The last two confirmed swing highs and lows, and what they say."""
    swing_highs, swing_lows = find_swings(candles, lookback)
    last = len(candles) - 1
    highs = tuple(s for s in swing_highs if s.index + lookback <= last)[-2:]
    lows = tuple(s for s in swing_lows if s.index + lookback <= last)[-2:]
    return SwingStructure(highs, lows, classify(highs, lows))
