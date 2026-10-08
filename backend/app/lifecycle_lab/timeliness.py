"""Event timeliness — OUTCOME measurement, not a decision input.

This module deliberately reads market points observed *after* ``detected_at``:
its whole purpose is to ask "what happened to the price after we noticed?".
That is look-ahead by design, which is why it must **never** feed a decision —
not the strategy, not event detection, not a lifecycle state. It takes raw
``MarketPoint``s rather than an ``InformationState`` precisely so it cannot be
mistaken for a point-in-time engine.

* ``price_at_detection`` — the newest priced point with
  ``available_at <= detected_at``, provided it was observed within ``lookback``
  of detection (an older price is not "the price at detection").
* ``price_before_detection`` — the newest priced point observed at or before
  ``detected_at - lookback``, within the horizon tolerance of that target.
* ``returns[h]`` for each ``TIMELINESS_HORIZONS`` entry — the *first* priced
  point observed at or after ``detected_at + h``, accepted only within
  ``max(h / 2, 10 minutes)`` of the target; otherwise
  ``Unavailable("no_point_near_horizon")``. A price from 20 hours later is not
  the 1-hour outcome.

Pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal

from app.lifecycle_lab.domain import (
    TIMELINESS_HORIZONS,
    MarketPoint,
    Measured,
    Timeliness,
    Unavailable,
)

MIN_TOLERANCE = timedelta(minutes=10)
NO_POINT_NEAR_HORIZON = "no_point_near_horizon"


def tolerance(span: timedelta) -> timedelta:
    return max(span / 2, MIN_TOLERANCE)


def _return(end: Decimal, start: Decimal) -> Measured:
    if start == 0:
        return Unavailable("zero_denominator")
    return end / start - 1


def timeliness(
    *,
    detected_at: datetime,
    mint_address: str,
    points: Sequence[MarketPoint],
    lookback: timedelta = timedelta(hours=1),
) -> Timeliness:
    priced = sorted(
        (p for p in points if p.mint_address == mint_address and p.price_usd is not None),
        key=lambda p: (p.observed_at, p.available_at, p.source, p.data_class.value),
    )

    at_detection: Measured = Unavailable("no_price_at_detection")
    known = [p for p in priced if p.available_at <= detected_at]
    if known:
        latest = max(known, key=lambda p: (p.observed_at, p.available_at, p.source))
        if latest.observed_at >= detected_at - lookback and latest.price_usd is not None:
            at_detection = latest.price_usd
        else:
            at_detection = Unavailable("stale_price_at_detection")

    before: Measured = Unavailable("no_point_near_lookback")
    target = detected_at - lookback
    earlier = [p for p in priced if p.observed_at <= target]
    if earlier:
        ref = earlier[-1]
        if ref.observed_at >= target - tolerance(lookback) and ref.price_usd is not None:
            before = ref.price_usd

    run_up: Measured
    if isinstance(at_detection, Unavailable):
        run_up = at_detection
    elif isinstance(before, Unavailable):
        run_up = before
    else:
        run_up = _return(at_detection, before)

    returns: dict[timedelta, Measured] = {}
    for horizon in TIMELINESS_HORIZONS:
        if isinstance(at_detection, Unavailable):
            returns[horizon] = at_detection
            continue
        goal = detected_at + horizon
        after = next((p for p in priced if p.observed_at >= goal), None)
        if (
            after is None
            or after.price_usd is None
            or after.observed_at - goal > tolerance(horizon)
        ):
            returns[horizon] = Unavailable(NO_POINT_NEAR_HORIZON)
        else:
            returns[horizon] = _return(after.price_usd, at_detection)

    return Timeliness(
        detected_at=detected_at,
        mint_address=mint_address,
        price_before_detection=before,
        price_at_detection=at_detection,
        returns=returns,
        run_up_before_detection=run_up,
    )
