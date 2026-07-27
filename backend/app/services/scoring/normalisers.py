"""Bounded transforms from raw measurements to 0-100 component scores.

Every function here is pure, Decimal-only, and total: any finite input produces a
value inside the declared range, and no input raises. That totality is what lets
components stay free of defensive branches - a missing measurement is decided
once, by the component, rather than guarded at every arithmetic step.

Two design notes:

  * **Decimal, not float.** Scores are persisted as `NUMERIC(5,2)` and compared
    against golden files, so the arithmetic has to be reproducible across
    machines. Binary floats are not.
  * **A fixed context.** `decimal.getcontext()` is thread-local and mutable by
    any code in the process, so relying on it would make the engine's output
    depend on who ran before it. `SCORING_CONTEXT` is applied explicitly instead.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Context, Decimal
from itertools import pairwise

# 28 significant digits is Python's default precision and far more than the two
# decimal places we persist; the headroom keeps intermediate products from
# rounding before the final quantisation. Banker's rounding matches the
# quantisation rule in the design (section 8.4).
SCORING_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)

QUANTUM = Decimal("0.01")

ZERO = Decimal(0)
ONE = Decimal(1)
HUNDRED = Decimal(100)

#: An ascending table of (input, score) points defining a piecewise-linear curve.
Anchors = tuple[tuple[Decimal, Decimal], ...]


def anchors(*points: tuple[str, str]) -> Anchors:
    """Build a validated anchor table from string literals.

    Strings rather than floats so the declared curve is exactly the curve:
    `Decimal(0.05)` is not 0.05, `Decimal("0.05")` is.

    Anchors must ascend on the input axis. They need not ascend on the score
    axis - `survival_age` and the FDV sanity band are deliberately non-monotone,
    since both "too new" and "too old" are worse than the middle.
    """
    if len(points) < 2:
        raise ValueError("an anchor table needs at least two points")

    table = tuple((Decimal(x), Decimal(y)) for x, y in points)
    inputs = [x for x, _ in table]
    if any(later <= earlier for earlier, later in pairwise(inputs)):
        raise ValueError("anchor inputs must ascend strictly")
    return table


def clamp(value: Decimal, lower: Decimal = ZERO, upper: Decimal = HUNDRED) -> Decimal:
    """Constrain a value to a range. The engine's only bounds guarantee."""
    if value < lower:
        return lower
    return upper if value > upper else value


def interpolate(value: Decimal, table: Anchors) -> Decimal:
    """Piecewise-linear lookup, flat beyond the first and last anchors.

    Flat rather than extrapolated on purpose: extending the final segment would
    let a $50M pool score above 100, and every curve here saturates by design.
    """
    first_x, first_y = table[0]
    if value <= first_x:
        return first_y

    last_x, last_y = table[-1]
    if value >= last_x:
        return last_y

    for (low_x, low_y), (high_x, high_y) in pairwise(table):
        if low_x <= value <= high_x:
            span = high_x - low_x
            # Guarded by the strict-ascent check in `anchors`, but a zero span
            # here would be a silent division by zero rather than a loud one.
            if span == ZERO:  # pragma: no cover - unreachable via `anchors`
                return low_y
            position = (value - low_x) / span
            return low_y + (high_y - low_y) * position

    return last_y  # pragma: no cover - the loop above is exhaustive


def _log_compress(value: Decimal) -> Decimal:
    """log10(1 + x) for x >= 0; negatives compress to 0.

    The +1 keeps the transform defined at zero, which matters because a token
    with no liquidity at all is the common case, not an edge case.
    """
    if value <= ZERO:
        return ZERO
    return (ONE + value).log10()


def log_interpolate(value: Decimal, table: Anchors) -> Decimal:
    """`interpolate` with both axes' inputs compressed logarithmically.

    Money and trade counts span orders of magnitude: the difference between $2k
    and $25k of liquidity matters far more than the difference between $1M and
    $1.02M. Linear interpolation over raw dollars would treat those as equal.
    """
    compressed = tuple((_log_compress(anchor_x), anchor_y) for anchor_x, anchor_y in table)
    return interpolate(_log_compress(value), compressed)


def saturating_ratio(
    value: Decimal, baseline: Decimal, *, saturation: Decimal = Decimal(10)
) -> Decimal:
    """Score a value against an expected baseline, saturating at `saturation`x.

    Used for momentum: "this token did N times its uniform-rate volume in the
    last five minutes". The log compression means 10x the baseline scores 100
    while 100x also scores 100 - past a point, more acceleration is not more
    information, and letting it run would make one wild candle dominate.

    A non-positive baseline yields 0: there is nothing to be a multiple of.
    """
    if baseline <= ZERO:
        return ZERO

    ratio = value / baseline if value > ZERO else ZERO
    ceiling = _log_compress(saturation)
    if ceiling <= ZERO:  # pragma: no cover - saturation is a positive constant
        return ZERO
    return clamp(_log_compress(ratio) / ceiling * HUNDRED)


def ratio_of(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    """Safe division. `None` when either side is missing or the base is zero.

    Returning `None` rather than 0 is the point: "no market cap recorded" and "a
    market cap of zero" are different facts, and only the caller knows which one
    should make its component unavailable.
    """
    if numerator is None or denominator is None or denominator <= ZERO:
        return None
    return numerator / denominator


def quantize(value: Decimal) -> Decimal:
    """Round to the two decimal places the database stores."""
    return value.quantize(QUANTUM, rounding=ROUND_HALF_EVEN)


def power(base: Decimal, exponent: Decimal) -> Decimal:
    """`base ** exponent` for base >= 0, evaluated in the scoring context."""
    if base <= ZERO:
        return ZERO
    return SCORING_CONTEXT.power(base, exponent)
