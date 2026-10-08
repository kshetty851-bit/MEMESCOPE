"""Market features: change metrics never read absence as "no change"."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.lifecycle_lab.domain import (
    AgeBucket,
    DataClass,
    InformationState,
    MarketPoint,
    Meme,
    ResearchMode,
    TokenInfo,
    Unavailable,
)
from app.lifecycle_lab.market import age_bucket, market_features

pytestmark = pytest.mark.unit

T = datetime(2026, 9, 1, 12, tzinfo=UTC)
MINT = "Mint1"


def point(minutes_ago: int, price: str | None, **kw: object) -> MarketPoint:
    at = T - timedelta(minutes=minutes_ago)
    return MarketPoint(
        MINT,
        at,
        at,
        DataClass.FORWARD,
        Decimal(price) if price else None,
        **kw,  # type: ignore[arg-type]
    )


def state(points: list[MarketPoint], token: TokenInfo | None = None) -> InformationState:
    return InformationState(
        as_of=T,
        mode=ResearchMode.AUTHORITATIVE,
        meme=Meme("m1", "dog", "Dog", T - timedelta(days=9)),
        aliases=(),
        links=(),
        tokens=(token,) if token else (),
        observations=(),
        market=tuple(points),
        sources=(),
    )


@pytest.mark.parametrize(
    ("age", "bucket"),
    [
        (None, AgeBucket.UNKNOWN),
        (timedelta(seconds=-1), AgeBucket.UNKNOWN),
        (timedelta(0), AgeBucket.M0_5),
        (timedelta(minutes=5), AgeBucket.M5_30),
        (timedelta(hours=1), AgeBucket.M30_H2),
        (timedelta(hours=3), AgeBucket.H2_6),
        (timedelta(hours=7), AgeBucket.H6_24),
        (timedelta(days=2), AgeBucket.D1_3),
        (timedelta(days=4), AgeBucket.D3_7),
        (timedelta(days=7), AgeBucket.D7_PLUS),
    ],
)
def test_age_buckets(age: timedelta | None, bucket: AgeBucket) -> None:
    assert age_bucket(age) is bucket


def test_changes_from_latest_and_reference_points() -> None:
    points = [
        point(70, "1", volume_1h=Decimal(100), liquidity_usd=Decimal(1000)),
        point(
            5,
            "1.5",
            volume_1h=Decimal(300),
            liquidity_usd=Decimal(1500),
            market_cap=Decimal(9),
        ),
    ]
    token = TokenInfo(MINT, None, None, None, T - timedelta(hours=3))
    f = market_features(state(points, token), MINT)
    assert f.price_usd == Decimal("1.5")
    assert f.price_change == Decimal("0.5")
    assert f.volume_growth == Decimal(3)
    assert f.liquidity_change == Decimal("0.5")
    assert f.market_cap == Decimal(9)
    assert f.data_age_seconds == Decimal(300)
    assert f.token_age == timedelta(hours=3)
    assert f.age_bucket is AgeBucket.H2_6


def test_stale_latest_point_is_not_a_zero_change() -> None:
    """A price last seen three hours ago compared with itself would read 0%:
    absence posing as a measurement."""
    f = market_features(state([point(400, "1"), point(180, "1")]), MINT)
    assert f.price_change == Unavailable("no_recent_point")


def test_unreported_liquidity_and_no_data_are_unavailable() -> None:
    f = market_features(state([point(70, "1"), point(1, "2")]), MINT)
    assert f.liquidity_usd == Unavailable("liquidity_not_reported")
    assert f.liquidity_change == Unavailable("liquidity_not_reported")
    empty = market_features(state([]), MINT)
    assert empty.price_usd == Unavailable("no_market_data")
    assert empty.age_bucket is AgeBucket.UNKNOWN


def test_candle_volume_requires_complete_bars() -> None:
    bars = [
        MarketPoint(
            MINT,
            T - timedelta(minutes=15 * i),
            T - timedelta(minutes=15 * i),
            DataClass.BACKFILL,
            Decimal(1),
            bar_volume=Decimal(10 if i < 4 else 5),
            bar_seconds=900,
        )
        for i in range(8)
    ]
    f = market_features(state(bars), MINT)
    assert f.volume_1h == Decimal(40)
    assert f.volume_growth == Decimal(2)
    partial = market_features(state(bars[:5]), MINT)
    assert partial.volume_growth == Unavailable("incomplete_bars")
