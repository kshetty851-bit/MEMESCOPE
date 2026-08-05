"""Deciding when a position closed, from stored observations alone.

This module holds the property the whole wallet rests on.

**Exits are resolved against the observation series, not against the price at
the moment somebody looked.** The obvious implementation — every few minutes,
compare the latest price to the target — is not reproducible: a worker that was
down for an hour sees a different "latest price" than one that was not, and the
same stored history yields two different track records. It also silently
improves the result, because a position that spiked through its stop and
recovered before anyone checked never gets stopped out.

So `resolve_exit` walks the observations in time order and closes at the
**first** one that breaches a rule. Replaying the same rows always produces the
same exit, whatever the worker did or when it ran.

Pure: no I/O, no clock, no randomness. `now` is a parameter.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from app.paper.models import Exit, ExitReason, OpenPosition, Quote


def resolve_exit(
    position: OpenPosition, quotes: Sequence[Quote], *, now: object = None
) -> Exit | None:
    """The first rule this position breached, or `None` if it is still running.

    `quotes` must be every observation since the position was last evaluated,
    oldest first. Order is the whole algorithm — the earliest breach wins, so a
    token that hit its stop on Tuesday and its target on Wednesday is a loss,
    which is what actually would have happened.

    Ties within a single observation resolve to the **stop**. A single snapshot
    that satisfies both bounds means the price moved further than one reading
    can distinguish, and the honest reading of an ambiguous bar is the adverse
    one; the alternative books a win the data does not support.

    Expiry is checked against each observation's own timestamp rather than
    against `now`, so a position that should have expired at noon closes at
    noon's price even if nothing evaluated it until midnight.

    A bound that is `None` is skipped: since Sprint 30 a position may carry no
    target, no fixed stop and no holding period at all, and **a rule that does
    not exist cannot be breached**. For the frozen Equal Weight bracket, where
    all three are set, the behaviour is unchanged — which is what
    `test_paper_exits.py` asserts across every ordering.
    """
    for quote in quotes:
        if position.expires_at is not None and quote.captured_at >= position.expires_at:
            # The published holding period elapsed at or before this reading, so
            # this is the first price at which the rule could have been applied.
            return Exit(
                price_usd=quote.price_usd,
                at=quote.captured_at,
                reason=ExitReason.EXPIRY,
            )
        if position.stop_price is not None and quote.price_usd <= position.stop_price:
            return Exit(
                price_usd=position.stop_price,
                at=quote.captured_at,
                reason=ExitReason.STOP,
            )
        if position.target_price is not None and quote.price_usd >= position.target_price:
            return Exit(
                price_usd=position.target_price,
                at=quote.captured_at,
                reason=ExitReason.TARGET,
            )
    return None


def peak_through(position: OpenPosition, quotes: Sequence[Quote]) -> Decimal:
    """The highest price this position has seen, including what it already held.

    Carried forward from the stored `peak_price` rather than recomputed from the
    full history, so the figure survives snapshot pruning: a peak that was
    observed once is a fact, and it must not quietly shrink when the row that
    recorded it is aged out.
    """
    peak = position.peak_price
    for quote in quotes:
        if quote.price_usd > peak:
            peak = quote.price_usd
    return peak


def peak_before(position: OpenPosition, quotes: Sequence[Quote], exit_at: object) -> Decimal:
    """The highest price up to and including the exit observation.

    A peak recorded *after* the position closed belongs to a token, not to a
    trade. Reporting it as the trade's peak would credit the strategy with a
    move it had already sold out of — the most flattering error available here,
    and therefore the one worth spending a function on.
    """
    peak = position.peak_price
    for quote in quotes:
        if quote.captured_at > exit_at:  # type: ignore[operator]
            break
        if quote.price_usd > peak:
            peak = quote.price_usd
    return peak


def market_value(position: OpenPosition, price: Decimal | None) -> Decimal | None:
    """What an open position is worth at a given price.

    `None` in, `None` out. A position whose token has no current reading has an
    unknown value, not a zero one, and the wallet reports its equity as partly
    unmeasured rather than marking the holding to zero.
    """
    if price is None:
        return None
    return position.quantity * price
