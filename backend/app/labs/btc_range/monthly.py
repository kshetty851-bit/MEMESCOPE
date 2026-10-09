"""The monthly long/short book (Karthik, 2026-10-09: "yes" to "follow last
month, long and short, 3x" as a paper book; the range strategy stays stopped).

The rule, whole:
  * On the 1st of each month (UTC) take a fresh $1,000.
  * If BTC rose last month (close above open), go LONG; if it fell, go SHORT.
  * Enter at the month's first price, hold to its last, at 3x leverage.
  * Fees: 0.05% + 0.02% slippage per side, on the leveraged amount.
  * If the price moves 1/leverage against the position (less a 0.5% buffer
    for the exchange's maintenance margin) at ANY point in the month, the
    month is liquidated: -$1,000.

Entering at the open and holding to the close means a month is fully described
by its open, close, high and low, so the book needs no per-candle replay.
Funding is NOT counted (a few dollars a month either way at 3x on $1,000).

Pure: no database, no clock. The service hands it monthly bars and a price.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from itertools import pairwise

LEVERAGE = Decimal(3)
CAPITAL = Decimal(1000)
FEE = Decimal("0.0007")
MAINTENANCE = Decimal("0.005")


@dataclass(frozen=True, slots=True)
class MonthBar:
    month: datetime  # first instant of the month, UTC
    open: Decimal
    close: Decimal
    high: Decimal
    low: Decimal
    complete: bool  # has the month ended?


@dataclass(frozen=True, slots=True)
class BookMonth:
    month: datetime
    side: int  # +1 long, -1 short
    entry: Decimal
    exit: Decimal  # month close, or the current price while it runs
    liquidation_price: Decimal
    liquidated: bool
    pnl_usd: Decimal
    running: bool


def liquidation_price(entry: Decimal, side: int, leverage: Decimal = LEVERAGE) -> Decimal:
    move = 1 / leverage - MAINTENANCE
    return entry * (1 - move) if side > 0 else entry * (1 + move)


def book(bars: list[MonthBar], *, current_price: Decimal | None = None,
         leverage: Decimal = LEVERAGE, capital: Decimal = CAPITAL) -> list[BookMonth]:
    """One row per month that has a previous month to read the direction from.
    `bars` ascending; the last may be the running month."""
    out: list[BookMonth] = []
    for prev, bar in pairwise(bars):
        if not prev.complete:
            continue
        side = 1 if prev.close > prev.open else -1
        entry = bar.open
        liq = liquidation_price(entry, side, leverage)
        hit = bar.low <= liq if side > 0 else bar.high >= liq
        running = not bar.complete
        exit_price = bar.close if (bar.complete or current_price is None) else current_price
        if hit:
            pnl = -capital
        else:
            move = side * (exit_price / entry - 1)
            pnl = capital * (leverage * move - 2 * FEE * leverage)
        out.append(BookMonth(bar.month, side, entry, exit_price, liq, hit,
                             pnl.quantize(Decimal("0.01")), running))
    return out
