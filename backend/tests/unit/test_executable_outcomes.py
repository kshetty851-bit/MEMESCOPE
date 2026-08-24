"""Executable truth math: sellable value, not chart value.

The numbers mirror the calibrated model (30bps/side, 12x impact) and the
incidents that motivated it: a drained pool printing 2x must not be a win,
and a dead pool is $0 whatever it printed last.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.radar.executable import Reading, compute

pytestmark = pytest.mark.unit

T0 = datetime(2026, 8, 24, 0, 0, tzinfo=UTC)


def reading(minutes, price, liq, inactive=False):
    return Reading(
        captured_at=T0 + timedelta(minutes=minutes),
        price_usd=None if price is None else Decimal(str(price)),
        liquidity_usd=None if liq is None else Decimal(str(liq)),
        inactive=inactive,
    )


def test_flat_series_loses_to_costs_and_never_reaches_targets():
    rows = [reading(m, "1.0", "10000") for m in range(0, 26 * 60, 30)]
    out = compute(rows, entered_at=T0, data_end=T0 + timedelta(hours=80))
    assert out is not None and out.decided_24h
    assert out.reached_125_24h is False and out.reached_2x_24h is False
    # fees + 12x impact on a $10 order against a $10k pool: just under par
    assert Decimal("0.9") < out.executable_peak_multiple < Decimal("1.0")


def test_genuine_double_with_depth_reaches_2x():
    rows = [reading(0, "1.0", "50000"), reading(60, "2.5", "50000"),
            reading(25 * 60, "2.5", "50000")]
    out = compute(rows, entered_at=T0, data_end=T0 + timedelta(hours=80))
    assert out is not None and out.reached_2x_24h is True and out.reached_125_24h is True


def test_dead_pool_is_zero_not_last_print():
    rows = [reading(0, "1.0", "20000"), reading(30, "2.0", "20000", inactive=True)]
    out = compute(rows, entered_at=T0, data_end=T0 + timedelta(hours=1))
    assert out is not None
    assert out.decided_24h  # death decides the horizon early
    assert out.final_value_frac_24h == Decimal("0")


def test_price_without_depth_cannot_win():
    # The pre-rug fantasy: price prints 10x while liquidity has left.
    rows = [reading(0, "1.0", "20000"), reading(30, "10.0", "50")]
    out = compute(rows, entered_at=T0, data_end=T0 + timedelta(hours=80))
    assert out is not None
    # selling into $50 of depth at 12x impact nets almost nothing
    assert out.reached_2x_24h is not True or out.executable_peak_multiple < 2


def test_never_fillable_returns_none():
    rows = [reading(0, None, None), reading(10, "1.0", None)]
    assert compute(rows, entered_at=T0, data_end=T0 + timedelta(hours=80)) is None


def test_undecided_horizon_reports_none_not_false():
    rows = [reading(0, "1.0", "20000"), reading(30, "1.1", "20000")]
    out = compute(rows, entered_at=T0, data_end=T0 + timedelta(hours=2))
    assert out is not None
    assert out.decided_24h is False
    assert out.reached_2x_24h is None and out.final_value_frac_24h is None
