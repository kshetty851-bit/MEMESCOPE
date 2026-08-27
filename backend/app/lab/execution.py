"""The V6 frozen execution model, shared identically by all 20 strategies.

No strategy may get better fills than another — that is the whole point of a
tournament, and it is enforced by there being exactly one of each function here.

Calibrated against 320 live Karthik Jupiter quotes (V3): a $10 buy moves the
price ~11.96x more than naive `S/(liq/2)` predicts, so effective depth is
`(liquidity/2)/12`. Fees are 30 bps a side. Level exits fill at no better than
`trigger * 1.15` (the fill-drift cap), because a gap-up print is a real fill but
an unlimited one is fiction. Prints more than 3x off the 10-minute rolling
median do not fill in either direction. Nothing is acted on across a gap of more
than 15 minutes. A pool the provider reports inactive settles at $0.00 — never
at its last healthy print.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

FEE = Decimal("0.003")
IMPACT_DIVISOR = Decimal("12")
GLITCH_BAND = Decimal("3")
GLITCH_WINDOW_SECONDS = 600
FILL_DRIFT_CAP = Decimal("1.15")
STALE_GUARD_SECONDS = 900


def _depth(liquidity: Decimal) -> Decimal:
    return (liquidity / 2) / IMPACT_DIVISOR


def buy_quantity(size_usd: Decimal, price: Decimal, liquidity: Decimal) -> Decimal | None:
    """Tokens `size_usd` buys. None when the market cannot be priced at all."""
    if size_usd <= 0 or price <= 0 or liquidity <= 0:
        return None
    spend = size_usd * (1 - FEE)
    return spend / (price * (1 + spend / _depth(liquidity)))


def sell_proceeds(quantity: Decimal, price: Decimal, liquidity: Decimal) -> Decimal:
    """USD a sale of `quantity` actually returns, after impact and fee."""
    if quantity <= 0 or price <= 0 or liquidity <= 0:
        return Decimal(0)
    gross = quantity * price
    return (gross / (1 + gross / _depth(liquidity))) * (1 - FEE)


def is_stale(captured_at: datetime, now: datetime) -> bool:
    """True when the freshest print is too old to act on."""
    return (now - captured_at).total_seconds() > STALE_GUARD_SECONDS


def off_band(price: Decimal, median: Decimal | None) -> bool:
    """True when a print is a glitch rather than a market you can trade against.

    Symmetric on purpose: an implausible crash is no more fillable than an
    implausible spike, and treating only spikes as suspect would let a strategy
    'stop out' at a price nobody could have sold into.
    """
    if median is None or median <= 0 or price <= 0:
        return False
    return price > median * GLITCH_BAND or price < median / GLITCH_BAND


def capped_fill_price(price: Decimal, entry_price: Decimal,
                      trigger_multiple: Decimal | None) -> Decimal:
    """Level exits fill at the print, but never better than trigger x 1.15."""
    if trigger_multiple is None:
        return price
    return min(price, entry_price * trigger_multiple * FILL_DRIFT_CAP)


def rolling_median(prices: list[tuple[datetime, Decimal]], at: datetime) -> Decimal | None:
    """Median of quotable prices in the 10 minutes before `at`; None under 3."""
    window = [p for t, p in prices
              if at - timedelta(seconds=GLITCH_WINDOW_SECONDS) <= t <= at and p > 0]
    if len(window) < 3:
        return None
    window.sort()
    return window[len(window) // 2]
