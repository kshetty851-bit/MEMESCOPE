"""The Karthik rule, stated once, in one place.

    $1,000 of capital. $10 per new Track Record token. Sell all of it at 1.25x.
    No stop loss. No time exit. Otherwise hold until the token is genuinely
    dead.

That is the entire strategy, and this module is the entire implementation of
the parts that are a *decision* rather than a query. Everything here is pure —
no I/O, no clock, no randomness, `now` is always a parameter — for the same
reason `app/paper/exits.py` and `app/radar` are: a rule that reads a clock
cannot be replayed, and a rule that cannot be replayed cannot be checked.

## Why there is no stop loss, and why "goes to zero" is not one

A stop loss is a rule about *price*. "Goes to zero" is a claim about
*executability*: the position is settled when there is nothing left to sell,
not when the price has fallen far enough. So a token at 0.05x is held, exactly
like a token at 1.10x is held, and only a provider's own report that the pool
has no meaningful liquidity left ends the trade.

## Why the target is not "book 1.25 x cost"

A price print is not a fill. A drained pool can print any number, and a rule
that read the print would turn a rug into a winning trade — the single most
important thing this experiment must not do. So `target_reached` is necessary
but never sufficient: the caller must also obtain a real executable sell quote
for the whole position, and the proceeds are that quote's, never `1.25 x cost`.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

#: Karthik's capital, at activation. Copied onto the wallet row there, so
#: changing this constant can never restate a return that was already published.
STARTING_CAPITAL = Decimal("1000.00")

#: Every entry is exactly this, or there is no entry. Not a maximum and not a
#: fraction of equity: a fixed size is what makes the capture rate and the win
#: rate mean what they appear to mean.
TRADE_SIZE = Decimal("10.00")

#: Sell 100% here. One number, one exit.
TAKE_PROFIT_MULTIPLE = Decimal("1.25")

#: A pool reporting no depth cannot be sold into, whatever it prints. Checked
#: before a quote is even requested, so a zero-liquidity print never reaches the
#: execution path at all.
MIN_EXECUTABLE_LIQUIDITY_USD = Decimal("1")


class Decision(enum.StrEnum):
    """What Karthik did about one Track Record admission. Recorded once, ever."""

    ENTERED = "entered"
    #: Below one trade size at the moment the opportunity arrived. **Permanent.**
    #: The token is never queued and never bought later: an experiment that
    #: bought its backlog once cash freed up would be reporting a capture rate
    #: it did not have, and its entries would be priced hours after the signal.
    SKIPPED_INSUFFICIENT_CASH = "skipped_insufficient_cash"
    #: No usable, fresh, tradeable observation at the moment Karthik looked.
    #: Also permanent, and for a related reason: Karthik's entry price must be
    #: one it could actually have paid at its own decision point, so an
    #: opportunity it could not price is one it missed.
    SKIPPED_NO_MARKET = "skipped_no_market"


class ExitReason(enum.StrEnum):
    """The only two ways a Karthik position ends."""

    TARGET_1_25X = "target_1_25x"
    DEAD_ZERO = "dead_zero"


class Hold(enum.StrEnum):
    """Why an open position stayed open. Counted and shown, never inferred."""

    #: Below the target. Covers 1.24x and 0.05x alike — there is no stop.
    BELOW_TARGET = "below_target"
    #: At or above the target, but the pool reports no depth to sell into.
    TARGET_NOT_EXECUTABLE = "target_not_executable"
    #: At or above the target, but no route would quote the whole position.
    #: The target is unmet until something will actually buy it.
    NO_EXECUTABLE_QUOTE = "no_executable_quote"
    #: Nothing fresh enough to judge. Held, and said so, rather than closed.
    NO_FRESH_MARKET = "no_fresh_market"


@dataclass(frozen=True, slots=True)
class Observation:
    """One market reading, reduced to what the rule actually consults."""

    price_usd: Decimal | None
    liquidity_usd: Decimal | None
    captured_at: datetime
    #: The provider's own word. `"inactive"` means indexed with no meaningful
    #: liquidity left — the only evidence this module accepts for death.
    trading_status: str


def target_price_for(entry_price: Decimal) -> Decimal:
    """The price that ends the trade, fixed at entry and never recomputed."""
    return entry_price * TAKE_PROFIT_MULTIPLE


def is_fresh(observation: Observation, *, now: datetime, max_age_seconds: int) -> bool:
    """Whether a reading is recent enough to stand in for the market *now*.

    A future-dated reading is fresh: clock skew between the enrichment worker
    and the reviewer is not evidence of staleness, and rejecting it would make
    the wallet's behaviour depend on which container was ahead.
    """
    return observation.captured_at >= now - timedelta(seconds=max_age_seconds)


def is_dead(observation: Observation) -> bool:
    """Whether the provider says there is nothing left to sell.

    This is the *only* death test, and it is deliberately not a price test. A
    token down 95% is a losing position, not a dead one, and Karthik holds it.
    """
    return observation.trading_status == "inactive"


def is_tradeable_entry(observation: Observation) -> bool:
    """Whether an entry can honestly be priced from this reading.

    A price is required because there is otherwise nothing to buy at. Depth is
    required because a $10 order against unknown depth has an unknowable cost,
    and the project's rule is to refuse rather than to assume a deep pool.
    """
    if observation.price_usd is None or observation.price_usd <= 0:
        return False
    if is_dead(observation):
        return False
    return (
        observation.liquidity_usd is not None
        and observation.liquidity_usd >= MIN_EXECUTABLE_LIQUIDITY_USD
    )


def target_reached(observation: Observation, *, target_price: Decimal) -> bool:
    """Whether the observed price is at or above the target.

    Necessary, never sufficient. See the module docstring: the caller must still
    obtain an executable quote before this becomes an exit.
    """
    return observation.price_usd is not None and observation.price_usd >= target_price


def can_execute_exit(observation: Observation) -> bool:
    """Whether the pool has enough depth to be worth asking a router about.

    The guard that makes "drained pool prints 2x" structurally incapable of
    producing a winning trade: with no reported depth the target is refused
    here, before any quote is requested, so there is no path on which a fantasy
    print reaches the closing write.
    """
    return (
        observation.liquidity_usd is not None
        and observation.liquidity_usd >= MIN_EXECUTABLE_LIQUIDITY_USD
        and not is_dead(observation)
    )


def entry_decision(*, cash: Decimal, observation: Observation | None) -> Decision:
    """The one decision Karthik makes about a new Track Record token.

    Ordered so the answer is the *first* true reason rather than the most
    convenient one: a token that could not be priced and could not be afforded
    is recorded as unaffordable, because that is the condition the wallet was
    in when the opportunity arrived.
    """
    if cash < TRADE_SIZE:
        return Decision.SKIPPED_INSUFFICIENT_CASH
    if observation is None or not is_tradeable_entry(observation):
        return Decision.SKIPPED_NO_MARKET
    return Decision.ENTERED


def hold_reason(
    observation: Observation | None,
    *,
    target_price: Decimal,
    now: datetime,
    max_age_seconds: int,
) -> Hold | None:
    """Why this position is still open, or `None` when the target is executable.

    `None` does not close anything. It means "ask the router" — the last word
    belongs to a real quote, and this function has none.
    """
    if observation is None or not is_fresh(
        observation, now=now, max_age_seconds=max_age_seconds
    ):
        return Hold.NO_FRESH_MARKET
    if not target_reached(observation, target_price=target_price):
        return Hold.BELOW_TARGET
    if not can_execute_exit(observation):
        return Hold.TARGET_NOT_EXECUTABLE
    return None
