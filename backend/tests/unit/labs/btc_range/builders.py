"""Synthetic candles for the BTC range lab's tests.

Every builder is scale-free: it takes a support and a resistance and places
bodies, wicks and touches as fractions of the width, so a test can say "a range
of 1.6% width" without a table of magic prices.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.labs.btc_range.types import TIMEFRAME_SECONDS, Candle, StrategyConfig

T0 = datetime(2026, 1, 1, tzinfo=UTC)
STEP = timedelta(seconds=TIMEFRAME_SECONDS)

SUPPORT = Decimal(60000)
RESISTANCE = Decimal(61000)

#: A small window keeps hand-computed fixtures short. Every default that is not
#: about the window itself is the live book's.
LOOKBACK = 20


def cfg(**overrides: object) -> StrategyConfig:
    values: dict[str, object] = {"lookback": LOOKBACK}
    values.update(overrides)
    return StrategyConfig(**values)  # type: ignore[arg-type]


#: The live book's window. Oscillation fixtures use it because a sine of period
#: 40 spans 2.4 cycles in 96 candles, which is a range; in 20 candles it is
#: half a cycle, which is a trend.
OSC_LOOKBACK = 96


def osc_cfg(**overrides: object) -> StrategyConfig:
    return StrategyConfig(**overrides)  # type: ignore[arg-type]


def candle(
    index: int,
    open_: Decimal | int | str,
    high: Decimal | int | str,
    low: Decimal | int | str,
    close: Decimal | int | str,
) -> Candle:
    return Candle(
        open_time=T0 + STEP * index,
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal(1),
    )


def ranging_window(
    n: int = LOOKBACK,
    support: Decimal = SUPPORT,
    resistance: Decimal = RESISTANCE,
    support_touches: Sequence[int] = (2, 8, 14),
    resistance_touches: Sequence[int] = (5, 11, 17),
    start: int = 0,
) -> list[Candle]:
    """Closes alternating at 40% and 60% of the range, with isolated touches.

    The net move over the window is one step of 0.2W against a path of 0.2W per
    candle, so the efficiency ratio is 1/(n-1): about 0.053 for 20 candles.
    """
    width = resistance - support
    low_close = support + width * Decimal("0.4")
    high_close = support + width * Decimal("0.6")
    body_low = support + width * Decimal("0.35")
    body_high = support + width * Decimal("0.65")
    out: list[Candle] = []
    previous = low_close
    for k in range(n):
        close = low_close if k % 2 == 0 else high_close
        high = resistance if k in resistance_touches else body_high
        low = support if k in support_touches else body_low
        out.append(candle(start + k, previous, high, low, close))
        previous = close
    return out


def with_price(window: list[Candle], price: Decimal | int | str) -> list[Candle]:
    """Append the candle being evaluated, closing at `price`.

    Its wicks stay inside its own body so it cannot disturb anything; it is not
    part of the window it is judged against anyway.
    """
    previous = window[-1].close
    p = Decimal(price)
    return [*window, candle(len(window), previous, max(previous, p), min(previous, p), p)]


def extend(
    candles: list[Candle], rows: Sequence[tuple[object, object, object, object]]
) -> list[Candle]:
    """Append (open, high, low, close) rows after the last candle."""
    out = list(candles)
    for row in rows:
        out.append(candle(len(out), *row))  # type: ignore[arg-type]
    return out


def oscillation(
    n: int, period: int = 40, support: int = 60000, resistance: int = 61000
) -> list[Candle]:
    """A sine wave between the bounds with wicks that reach them each cycle."""
    mid = Decimal(support + resistance) / 2
    amplitude = Decimal(resistance - support) / 2
    out: list[Candle] = []
    previous = mid
    for k in range(n):
        close = mid + amplitude * Decimal(str(round(math.sin(2 * math.pi * k / period), 6)))
        close = close.quantize(Decimal("0.01"))
        high = max(previous, close) + Decimal(30)
        low = min(previous, close) - Decimal(30)
        out.append(
            candle(
                k, previous, min(high, Decimal(resistance)), max(low, Decimal(support)), close
            )
        )
        previous = close
    return out


def trend(n: int, start: int = 60000, step: int = 40) -> list[Candle]:
    out: list[Candle] = []
    previous = Decimal(start)
    for k in range(n):
        close = Decimal(start + step * (k + 1))
        out.append(candle(k, previous, close + 20, previous - 20, close))
        previous = close
    return out


def flat(n: int, price: int = 60000) -> list[Candle]:
    return [candle(k, price, price, price, price) for k in range(n)]
