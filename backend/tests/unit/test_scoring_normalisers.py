"""Normaliser tests.

These are the engine's foundation: if a transform can return a value outside
0-100, or blow up on a zero, every component above it inherits the defect. The
sweeps below stand in for property-based testing - deterministic, exhaustive
over the interesting ranges, and no new dependency.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.scoring.normalisers import (
    HUNDRED,
    ONE,
    ZERO,
    anchors,
    clamp,
    interpolate,
    log_interpolate,
    power,
    quantize,
    ratio_of,
    saturating_ratio,
)

pytestmark = pytest.mark.unit

RISING = anchors(("0", "0"), ("10", "50"), ("20", "100"))
FALLING_TAIL = anchors(("0", "10"), ("10", "90"), ("20", "30"))


# --- anchors ------------------------------------------------------------------


def test_anchors_require_two_points() -> None:
    with pytest.raises(ValueError, match="two points"):
        anchors(("1", "1"))


def test_anchors_reject_non_ascending_inputs() -> None:
    with pytest.raises(ValueError, match="ascend"):
        anchors(("10", "0"), ("5", "50"))


def test_anchors_reject_duplicate_inputs() -> None:
    with pytest.raises(ValueError, match="ascend"):
        anchors(("10", "0"), ("10", "50"))


def test_anchors_allow_falling_scores() -> None:
    """Non-monotone curves are deliberate: survival age peaks in the middle."""
    table = anchors(("0", "100"), ("10", "0"))
    assert interpolate(Decimal(5), table) == Decimal(50)


def test_anchors_parse_exactly() -> None:
    """String literals, so the declared curve is the actual curve."""
    table = anchors(("0.05", "1"), ("0.1", "2"))
    assert table[0][0] == Decimal("0.05")


# --- clamp --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [("-5", "0"), ("0", "0"), ("50", "50"), ("100", "100"), ("140", "100")],
)
def test_clamp_bounds(value: str, expected: str) -> None:
    assert clamp(Decimal(value)) == Decimal(expected)


def test_clamp_honours_custom_range() -> None:
    assert clamp(Decimal("2"), ZERO, ONE) == ONE


# --- interpolate --------------------------------------------------------------


def test_interpolate_hits_anchor_points_exactly() -> None:
    for anchor_x, anchor_y in RISING:
        assert interpolate(anchor_x, RISING) == anchor_y


def test_interpolate_is_linear_between_anchors() -> None:
    assert interpolate(Decimal(5), RISING) == Decimal(25)
    assert interpolate(Decimal(15), RISING) == Decimal(75)


def test_interpolate_is_flat_outside_the_table() -> None:
    """Extrapolating would let an enormous pool score above 100."""
    assert interpolate(Decimal(-100), RISING) == ZERO
    assert interpolate(Decimal(10**9), RISING) == HUNDRED


def test_interpolate_stays_within_the_declared_score_range() -> None:
    """Sweep: no input anywhere produces a value outside the anchors' range."""
    for step in range(-50, 300):
        value = Decimal(step) / Decimal(10)
        for table in (RISING, FALLING_TAIL):
            scores = [score for _, score in table]
            assert min(scores) <= interpolate(value, table) <= max(scores)


def test_interpolate_is_monotone_for_a_rising_table() -> None:
    previous = interpolate(Decimal(-10), RISING)
    for step in range(-100, 300):
        current = interpolate(Decimal(step) / Decimal(10), RISING)
        assert current >= previous
        previous = current


# --- log_interpolate ----------------------------------------------------------


def test_log_interpolate_compresses_the_input_axis() -> None:
    """Equal ratios, not equal differences, produce equal steps."""
    table = anchors(("0", "0"), ("1000000", "100"))
    low = log_interpolate(Decimal(1000), table)
    high = log_interpolate(Decimal(100000), table)
    assert ZERO < low < high < HUNDRED


def test_log_interpolate_handles_zero_and_negative() -> None:
    table = anchors(("0", "5"), ("100", "80"))
    assert log_interpolate(ZERO, table) == Decimal(5)
    assert log_interpolate(Decimal(-10), table) == Decimal(5)


def test_log_interpolate_saturates() -> None:
    table = anchors(("0", "0"), ("1000", "100"))
    assert log_interpolate(Decimal(10**12), table) == HUNDRED


def test_log_interpolate_never_leaves_the_range() -> None:
    table = anchors(("0", "0"), ("2000", "10"), ("1000000", "100"))
    for exponent in range(0, 15):
        value = Decimal(10) ** exponent
        assert ZERO <= log_interpolate(value, table) <= HUNDRED


# --- saturating_ratio ---------------------------------------------------------


def test_saturating_ratio_at_baseline_is_mid_range() -> None:
    score = saturating_ratio(Decimal(100), Decimal(100))
    assert ZERO < score < HUNDRED


def test_saturating_ratio_saturates_at_the_ceiling() -> None:
    assert saturating_ratio(Decimal(1000), Decimal(100)) == HUNDRED
    # Past saturation adds nothing: one wild candle must not dominate.
    assert saturating_ratio(Decimal(10**9), Decimal(100)) == HUNDRED


def test_saturating_ratio_without_a_baseline_is_zero() -> None:
    """Nothing to be a multiple of."""
    assert saturating_ratio(Decimal(500), ZERO) == ZERO
    assert saturating_ratio(Decimal(500), Decimal(-1)) == ZERO


def test_saturating_ratio_of_no_activity_is_zero() -> None:
    assert saturating_ratio(ZERO, Decimal(100)) == ZERO
    assert saturating_ratio(Decimal(-5), Decimal(100)) == ZERO


def test_saturating_ratio_is_monotone_and_bounded() -> None:
    previous = ZERO
    for step in range(0, 2000, 7):
        current = saturating_ratio(Decimal(step), Decimal(100))
        assert ZERO <= current <= HUNDRED
        assert current >= previous
        previous = current


# --- ratio_of -----------------------------------------------------------------


def test_ratio_of_divides() -> None:
    assert ratio_of(Decimal(1), Decimal(4)) == Decimal("0.25")


@pytest.mark.parametrize(
    ("numerator", "denominator"),
    [(None, Decimal(1)), (Decimal(1), None), (Decimal(1), ZERO), (Decimal(1), Decimal(-2))],
)
def test_ratio_of_returns_none_rather_than_zero(
    numerator: Decimal | None, denominator: Decimal | None
) -> None:
    """"Not recorded" and "is zero" are different facts; only None says the first."""
    assert ratio_of(numerator, denominator) is None


# --- quantize -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("71.404", "71.40"),
        ("71.406", "71.41"),
        # Banker's rounding: exact halves go to the even digit, which is what
        # keeps repeated rounding from drifting upward.
        ("71.405", "71.40"),
        ("71.415", "71.42"),
        ("-0.005", "-0.00"),
    ],
)
def test_quantize_uses_banker_s_rounding(value: str, expected: str) -> None:
    assert quantize(Decimal(value)) == Decimal(expected)


def test_quantize_is_idempotent() -> None:
    once = quantize(Decimal("12.3456"))
    assert quantize(once) == once


# --- power --------------------------------------------------------------------


def test_power_of_zero_is_zero() -> None:
    """Evidence must collapse when a factor collapses, not raise."""
    assert power(ZERO, Decimal("0.75")) == ZERO


def test_power_of_one_is_one() -> None:
    assert power(ONE, Decimal("0.75")) == ONE


def test_power_is_monotone_between_zero_and_one() -> None:
    previous = ZERO
    for step in range(0, 101):
        current = power(Decimal(step) / HUNDRED, Decimal("0.75"))
        assert ZERO <= current <= ONE
        assert current >= previous
        previous = current


def test_power_discounts_gently() -> None:
    """A fractional exponent must soften, not amplify, a partial value."""
    assert power(Decimal("0.5"), Decimal("0.75")) > Decimal("0.5")


def test_power_of_negative_base_is_zero() -> None:
    assert power(Decimal(-1), Decimal("0.5")) == ZERO
