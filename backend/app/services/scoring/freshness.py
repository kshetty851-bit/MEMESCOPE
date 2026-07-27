"""Read-time freshness, and the confidence it produces.

Not used by the engine. Confidence is `evidence * sqrt(freshness)`, and freshness
decays with wall-clock time, so computing it at write time would store a number
that is wrong by the time anyone reads it - a token whose enrichment has stalled
would keep serving the confidence it had when its data was fresh.

Storing `evidence` and applying freshness per request is what makes a stale row
*read* as stale without anything having to recompute it. This module lives in the
scoring package because it is pure and belongs with the evidence it completes;
the API layer calls it when serialising.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.services.scoring.normalisers import ONE, ZERO, clamp, power

#: Freshness is discounted gently - the square root - because a slightly stale
#: observation is still informative. Only sustained staleness should collapse
#: confidence, and the linear term inside handles that.
FRESHNESS_EXPONENT = Decimal("0.5")

#: How many refresh intervals of silence reduce freshness to zero.
STALENESS_INTERVALS = Decimal(3)


def freshness_of(
    latest_snapshot_at: datetime | None,
    *,
    now: datetime,
    tier_interval_seconds: int,
) -> Decimal:
    """How current the underlying data is, on a 0-1 scale.

    Relative to the token's own refresh tier, not an absolute clock: two minutes
    of silence is nothing for a six-hourly token and a missed beat for one
    refreshing every thirty seconds.
    """
    if latest_snapshot_at is None or tier_interval_seconds <= 0:
        return ZERO

    age_seconds = Decimal((now - latest_snapshot_at).total_seconds())
    if age_seconds <= ZERO:
        return ONE

    horizon = STALENESS_INTERVALS * Decimal(tier_interval_seconds)
    return clamp(ONE - age_seconds / horizon, ZERO, ONE)


def confidence_of(evidence: Decimal, freshness: Decimal) -> Decimal:
    """Combine stored evidence with read-time freshness into served confidence."""
    return clamp(evidence * power(clamp(freshness, ZERO, ONE), FRESHNESS_EXPONENT))
