"""Timeliness is outcome measurement: it reads prices after detection on
purpose, and must therefore be exact about which point answers which horizon.
A price from twenty hours later is not the one-hour outcome."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.lifecycle_lab.domain import TIMELINESS_HORIZONS, DataClass, MarketPoint, Unavailable
from app.lifecycle_lab.timeliness import timeliness

pytestmark = pytest.mark.unit

T = datetime(2026, 9, 1, 12, tzinfo=UTC)
MINT = "Mint1"


def p(offset: timedelta, price: str, *, available: timedelta | None = None) -> MarketPoint:
    at = T + offset
    return MarketPoint(
        MINT,
        at,
        T + (available if available is not None else offset),
        DataClass.FORWARD,
        Decimal(price),
    )


def test_every_horizon_reports_return_from_price_at_detection() -> None:
    points = [p(timedelta(hours=-1), "0.5"), p(timedelta(0), "1")]
    points += [p(h, str(1 + i)) for i, h in enumerate(TIMELINESS_HORIZONS, start=1)]
    result = timeliness(detected_at=T, mint_address=MINT, points=points)
    assert result.price_at_detection == Decimal(1)
    assert result.price_before_detection == Decimal("0.5")
    assert result.run_up_before_detection == Decimal(1)
    assert list(result.returns) == list(TIMELINESS_HORIZONS)
    assert [result.returns[h] for h in TIMELINESS_HORIZONS] == [
        Decimal(i) for i in range(1, 8)
    ]


def test_price_at_detection_only_from_points_available_by_then() -> None:
    """The detection price is what was knowable at detection — a point
    observed earlier but delivered later does not qualify."""
    points = [
        p(timedelta(minutes=-10), "1"),
        p(timedelta(minutes=-2), "9", available=timedelta(minutes=1)),
    ]
    assert timeliness(
        detected_at=T, mint_address=MINT, points=points
    ).price_at_detection == Decimal(1)


def test_horizon_without_a_nearby_point_is_unavailable() -> None:
    """Tolerance is max(h/2, 10 min): for 1h a point 40 minutes late is too
    late; for 5m nothing within 10 minutes means no answer."""
    points = [
        p(timedelta(0), "1"),
        p(timedelta(hours=1, minutes=40), "5"),
        p(timedelta(hours=2, minutes=30), "3"),
    ]
    result = timeliness(detected_at=T, mint_address=MINT, points=points)
    assert result.returns[timedelta(hours=1)] == Unavailable("no_point_near_horizon")
    assert result.returns[timedelta(minutes=5)] == Unavailable("no_point_near_horizon")
    assert result.returns[timedelta(hours=2)] == Decimal(2)  # 30 min late, within 1h
    assert result.price_before_detection == Unavailable("no_point_near_lookback")


def test_no_price_at_detection_makes_every_return_unavailable() -> None:
    result = timeliness(detected_at=T, mint_address=MINT, points=[p(timedelta(hours=1), "2")])
    assert isinstance(result.price_at_detection, Unavailable)
    assert all(isinstance(v, Unavailable) for v in result.returns.values())
    assert isinstance(result.run_up_before_detection, Unavailable)


def test_other_mints_and_null_prices_are_ignored_and_order_does_not_matter() -> None:
    points = [
        p(timedelta(0), "1"),
        MarketPoint(
            "Other",
            T + timedelta(minutes=5),
            T + timedelta(minutes=5),
            DataClass.FORWARD,
            Decimal(50),
        ),
        MarketPoint(
            MINT, T + timedelta(minutes=5), T + timedelta(minutes=5), DataClass.FORWARD, None
        ),
        p(timedelta(minutes=6), "2"),
    ]
    first = timeliness(detected_at=T, mint_address=MINT, points=points)
    assert first.returns[timedelta(minutes=5)] == Decimal(1)
    rng = random.Random(5)
    for _ in range(3):
        rng.shuffle(points)
        assert timeliness(detected_at=T, mint_address=MINT, points=points) == first
