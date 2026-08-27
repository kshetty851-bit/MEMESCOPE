"""The one shared execution model. No strategy may get better fills than another."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.lab import execution

D = Decimal
T0 = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


def test_buy_and_sell_round_trip_costs_about_60_bps_plus_impact():
    qty = execution.buy_quantity(D(10), D(1), D("1000000"))
    back = execution.sell_proceeds(qty, D(1), D("1000000"))
    assert D("9.90") < back < D("9.99")


def test_impact_scales_with_size_against_shallow_depth():
    deep = execution.sell_proceeds(execution.buy_quantity(D(50), D(1), D("1000000")),
                                   D(1), D("1000000"))
    thin = execution.sell_proceeds(execution.buy_quantity(D(50), D(1), D("20000")),
                                   D(1), D("20000"))
    assert thin < deep


def test_unpriceable_markets_return_none_or_zero_never_a_guess():
    assert execution.buy_quantity(D(10), D(0), D("100000")) is None
    assert execution.buy_quantity(D(10), D(1), D(0)) is None
    assert execution.sell_proceeds(D(1), D(1), D(0)) == 0


def test_stale_guard_is_fifteen_minutes():
    assert execution.is_stale(T0 - timedelta(seconds=899), T0) is False
    assert execution.is_stale(T0 - timedelta(seconds=901), T0) is True


def test_glitch_band_is_symmetric():
    assert execution.off_band(D("31"), D("10")) is True     # implausible spike
    assert execution.off_band(D("3"), D("10")) is True      # implausible crash
    assert execution.off_band(D("25"), D("10")) is False
    assert execution.off_band(D("5"), D("10")) is False


def test_no_median_means_no_band_rather_than_a_guess():
    assert execution.off_band(D("1000"), None) is False


def test_rolling_median_needs_three_prints_inside_ten_minutes():
    few = [(T0 - timedelta(minutes=i), D(10)) for i in (1, 2)]
    assert execution.rolling_median(few, T0) is None
    enough = [(T0 - timedelta(minutes=i), D(i)) for i in (1, 2, 3)]
    assert execution.rolling_median(enough, T0) == D(2)
    old = [(T0 - timedelta(minutes=i), D(i)) for i in (11, 12, 13)]
    assert execution.rolling_median(old, T0) is None


def test_fill_drift_cap_bounds_a_gap_up_but_allows_the_print():
    # target 2x from an entry of $1: a $2.05 print fills at $2.05
    assert execution.capped_fill_price(D("2.05"), D(1), D(2)) == D("2.05")
    # a $9 print does not: it fills at 2 * 1.15
    assert execution.capped_fill_price(D("9"), D(1), D(2)) == D("2.30")


def test_market_exits_have_no_cap():
    assert execution.capped_fill_price(D("0.01"), D(1), None) == D("0.01")
