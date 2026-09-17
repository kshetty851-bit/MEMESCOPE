"""STRATEGY G1 — MOONSHOT.  Replaces F2.

A memecoin resolves in the first half hour. Either it runs or it is dead money.
Every book in this lab holds for 2 to 12 hours and sits through the dead time.
G1 is the first one built around speed, an uncapped tail, and a floor that only
ever moves up.

THREE CHANGES, EACH FROM A MEASUREMENT
----------------------------------------
1. SPEED.  Time to reach +30% in this lab: median 19.7 min, p75 29.3, p90 60.
   A 45-minute box holds ~90% of every winner that was ever going to win. F2
   held 8 hours and spent 7 of them in positions that had already decided.

2. NO CAP.  F2 took profit at +30% on 22 trades. Four of those tokens went on
   to +72%, +118%, +206% and +214% after F2 sold. Selling 75% at +30% returns
   97.5% of the stake; the remaining 25% then rides free with a wide trail.
   The tail is the only part of this book that can produce a large day.

3. RATCHET.  A high-water floor that never falls. Book reaches $1,400, floor
   becomes $1,358. A run can be given back 3% and no more. This is the
   mechanism for "goes up and does not go back down" — it cannot create a
   profit, but it stops one from being handed back.

WHAT G1 DOES NOT CLAIM
-----------------------
That it will be profitable. Five books before it were not, and the two that
looked it were reporting a broken price feed. What G1 changes is that it is
*measurable in three days*: 45-minute holds should produce 250-400 closed
trades in that window, against F2's 109 in five. Judge it on mean net per
trade, not on equity, which one runner can distort in either direction.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

ZERO = Decimal(0)

MIN_LIQUIDITY_USD = Decimal(200_000)
MIN_MARKET_CAP_USD = Decimal(200_000)

#: The moon-or-nothing cut.
ABANDON_AFTER = timedelta(minutes=10)
ABANDON_UNLESS_GAIN = Decimal("0.08")

#: Sell this much at +30%: 0.75 x 1.30 = 0.975 of the stake back.
SCALE_OUT_AT = Decimal("1.30")
SCALE_OUT_FRACTION = Decimal("0.75")

#: The free-riding remainder. Wide, and deliberately uncapped.
RUNNER_TRAIL = Decimal("0.45")

STOP_MULT = Decimal("0.88")
MAX_HOLD = timedelta(minutes=45)

RATCHET_GIVE_BACK = Decimal("0.03")


class Exit:
    ABANDON = "abandon_flat"
    SCALE_OUT = "scale_out"
    RUNNER_TRAIL = "runner_trail"
    STOP = "stop"
    MAX_HOLD = "max_hold"


def admits(liquidity_usd, market_cap_usd=None):
    """F2's gate, unchanged. It rejects 98% of candidates on liquidity and it is
    the one component in this project with evidence behind it."""
    checks = []
    if liquidity_usd is None:
        return False, "liquidity unknown - refusing", checks
    checks.append("liquidity")
    if Decimal(str(liquidity_usd)) < MIN_LIQUIDITY_USD:
        return False, f"liquidity ${float(liquidity_usd):,.0f} below floor", checks
    if market_cap_usd is not None:
        checks.append("market_cap")
        if Decimal(str(market_cap_usd)) < MIN_MARKET_CAP_USD:
            return False, f"market cap ${float(market_cap_usd):,.0f} below floor", checks
    return True, None, checks


@dataclass
class Position:
    entry_price: Decimal
    opened_at: datetime
    stake_usd: Decimal
    fraction_open: Decimal = Decimal(1)
    peak_price: Decimal = None
    scaled_out: bool = False
    realised_usd: Decimal = ZERO

    def __post_init__(self):
        if self.peak_price is None:
            self.peak_price = self.entry_price

    def mark(self, price: Decimal) -> None:
        if price > self.peak_price:
            self.peak_price = price

    def multiple(self, price: Decimal) -> Decimal:
        return price / self.entry_price


def evaluate(position: Position, price: Decimal, now: datetime,
             abandon_gain: Decimal = ABANDON_UNLESS_GAIN):
    """One observation. Returns (action, fraction_to_sell, reason) or None.

    Order matters and is deliberate: the stop is checked before the abandon
    rule so a token that is collapsing exits as a stop, not as 'flat'.

    `abandon_gain` is the flat-at-ten-minutes threshold, supplied per call so
    the learning layer can move it; the default is the starting value.
    """
    position.mark(price)
    mult = position.multiple(price)
    age = now - position.opened_at

    if mult <= STOP_MULT:
        return ("sell", position.fraction_open, Exit.STOP)

    if not position.scaled_out:
        # The moon-or-nothing cut, only while the whole position is still on.
        if age >= ABANDON_AFTER and mult < (1 + abandon_gain):
            return ("sell", position.fraction_open, Exit.ABANDON)
        if mult >= SCALE_OUT_AT:
            return ("sell", SCALE_OUT_FRACTION, Exit.SCALE_OUT)
    else:
        # The free-riding remainder: wide trail, no cap.
        if price <= position.peak_price * (1 - RUNNER_TRAIL):
            return ("sell", position.fraction_open, Exit.RUNNER_TRAIL)

    if age >= MAX_HOLD:
        return ("sell", position.fraction_open, Exit.MAX_HOLD)

    return None


@dataclass
class EquityRatchet:
    """A floor that follows the high-water mark up and never comes down.

    This is the answer to 'it should go higher every day, not lower'. It cannot
    manufacture a profit. What it does is stop a profit from being handed back:
    once the book prints a new high, at most `give_back` of it can be lost
    before new entries stop.

    It halts entries. It never force-closes — selling every open position at
    once into pools that may already be dead is the exact mechanism behind the
    -100% rows in this lab.
    """

    give_back: Decimal = RATCHET_GIVE_BACK
    high_water: Decimal = Decimal(1000)
    floor: Decimal = Decimal(950)
    enabled: bool = True

    def update(self, equity: Decimal) -> Decimal:
        """Call on every equity change. Returns the current floor."""
        equity = Decimal(str(equity))
        if equity > self.high_water:
            self.high_water = equity
            new_floor = equity * (1 - self.give_back)
            if new_floor > self.floor:      # never down
                self.floor = new_floor
        return self.floor

    def check(self, equity: Decimal):
        if not self.enabled:
            return False, None
        equity = Decimal(str(equity))
        if equity <= self.floor:
            return True, (f"equity ${float(equity):,.2f} at or below ratchet floor "
                          f"${float(self.floor):,.2f} (high-water "
                          f"${float(self.high_water):,.2f}) - no new entries")
        return False, None


def position_size(equity: Decimal, pct: Decimal = Decimal("0.01")) -> Decimal:
    """1% of CURRENT equity, so the bet compounds with the book. A ratcheting
    book that never raises its bet never actually compounds."""
    return (Decimal(str(equity)) * pct).quantize(Decimal("0.01"))
