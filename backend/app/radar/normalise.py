"""Bounded transforms shared by the Radar dimensions.

Kept in one place so "doubled" scores the same on liquidity as on volume. Every
function is total: no exceptions, no unbounded output, `None` in gives `None`
out. A dimension that has to guard its own arithmetic ends up encoding a
threshold nobody reviewed.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import TypeVar

T = TypeVar("T")


def clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return max(low, min(high, value))


def sub_series(values: Sequence[T], limit: int) -> Sequence[T]:
    """The most recent `limit` items, oldest first.

    The Radar reads recent behaviour; a token observed for months would
    otherwise have its current shape diluted by history that no longer
    describes it.
    """
    if limit <= 0 or len(values) <= limit:
        return values
    return values[-limit:]


def ratio_to_score(multiple: Decimal | None) -> Decimal | None:
    """Map a growth multiple onto 0-100, with 1.0 (unchanged) at 50.

    Piecewise linear rather than logarithmic, because the bands have to be
    explainable to a user reading a waterfall: a 2x doubling reads 75, a halving
    reads 25, and the curve saturates rather than letting a 400x outlier
    dominate a weighted sum.

    The knees are stated priors, not fitted parameters — the same standing as
    the scoring model's weights.
    """
    if multiple is None or multiple < 0:
        return None

    one = Decimal(1)
    if multiple >= one:
        # 1x -> 50, 2x -> 75, 4x and beyond -> 100.
        if multiple >= Decimal(4):
            return Decimal(100)
        if multiple >= Decimal(2):
            return Decimal(75) + (multiple - Decimal(2)) / Decimal(2) * Decimal(25)
        return Decimal(50) + (multiple - one) * Decimal(25)

    # 1x -> 50, 0.5x -> 25, 0x -> 0.
    if multiple >= Decimal("0.5"):
        return Decimal(25) + (multiple - Decimal("0.5")) / Decimal("0.5") * Decimal(25)
    return clamp(multiple / Decimal("0.5") * Decimal(25), Decimal(0), Decimal(25))


def mean(values: Sequence[Decimal]) -> Decimal | None:
    usable = [value for value in values if value is not None]
    if not usable:
        return None
    return sum(usable, Decimal(0)) / Decimal(len(usable))


def ema(values: Sequence[Decimal], periods: int) -> Decimal | None:
    """Exponential moving average, oldest first.

    Seeded with the simple mean of the first `periods` values rather than the
    first value alone, so a single outlier at the start does not bias the whole
    series — the series here are short enough for that to matter.
    """
    usable = [value for value in values if value is not None]
    if len(usable) < periods or periods <= 0:
        return None

    seed = mean(usable[:periods])
    if seed is None:
        return None

    multiplier = Decimal(2) / Decimal(periods + 1)
    current = seed
    for value in usable[periods:]:
        current = (value - current) * multiplier + current
    return current
