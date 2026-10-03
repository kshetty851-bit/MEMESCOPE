"""Market features for one linked mint, from an ``InformationState``.

Every change metric compares the newest point against a *reference* point at
or before ``as_of - window``. Two guards keep a change from silently reading 0:

* the newest point must itself be inside the window — a price last seen five
  hours ago compared with itself is "no change", which is absence posing as a
  measurement;
* the reference must be within one further window of its target time — a
  reading from yesterday is not "the price an hour ago".

Either failing yields ``Unavailable(reason)``. Fields a provider did not report
(bonding-curve liquidity, ADR 0002) are Unavailable, never 0.

Pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from decimal import Decimal

from app.lifecycle_lab.domain import (
    AgeBucket,
    InformationState,
    MarketFeatures,
    MarketPoint,
    Measured,
    Unavailable,
)

HOUR = timedelta(hours=1)

NO_MARKET_DATA = "no_market_data"
NO_RECENT_POINT = "no_recent_point"
NO_REFERENCE_POINT = "no_reference_point"
ZERO_DENOMINATOR = "zero_denominator"

_AGE_EDGES: tuple[tuple[timedelta, AgeBucket], ...] = (
    (timedelta(minutes=5), AgeBucket.M0_5),
    (timedelta(minutes=30), AgeBucket.M5_30),
    (timedelta(hours=2), AgeBucket.M30_H2),
    (timedelta(hours=6), AgeBucket.H2_6),
    (timedelta(hours=24), AgeBucket.H6_24),
    (timedelta(days=3), AgeBucket.D1_3),
    (timedelta(days=7), AgeBucket.D3_7),
)


def age_bucket(age: timedelta | None) -> AgeBucket:
    """Lower bound inclusive, upper exclusive. None or negative (a creation
    time after as_of — clock skew or a bad source) is UNKNOWN, not "new"."""
    if age is None or age < timedelta(0):
        return AgeBucket.UNKNOWN
    for edge, bucket in _AGE_EDGES:
        if age < edge:
            return bucket
    return AgeBucket.D7_PLUS


def _key(point: MarketPoint) -> tuple[datetime, datetime, str, str]:
    return (point.observed_at, point.available_at, point.source, point.data_class.value)


def _points(points: Iterable[MarketPoint], mint: str, as_of: datetime) -> list[MarketPoint]:
    return sorted(
        (p for p in points if p.mint_address == mint and p.available_at <= as_of), key=_key
    )


def _seconds(span: timedelta) -> Decimal:
    return Decimal(span // timedelta(microseconds=1)) / Decimal(1_000_000)


def _at_or_before(points: Sequence[MarketPoint], t: datetime) -> MarketPoint | None:
    """Newest point observed at or before ``t`` (``points`` sorted by _key)."""
    found: MarketPoint | None = None
    for point in points:
        if point.observed_at <= t:
            found = point
        else:
            break
    return found


def _change(now: Decimal | None, then: Decimal | None, field: str) -> Measured:
    if now is None or then is None:
        return Unavailable(f"{field}_not_reported")
    if then == 0:
        return Unavailable(ZERO_DENOMINATOR)
    return now / then - 1


def _reference(
    points: Sequence[MarketPoint], as_of: datetime, window: timedelta
) -> tuple[MarketPoint, MarketPoint] | Unavailable:
    if not points:
        return Unavailable(NO_MARKET_DATA)
    latest = points[-1]
    if latest.observed_at <= as_of - window:
        return Unavailable(NO_RECENT_POINT)
    ref = _at_or_before(points, as_of - window)
    if ref is None or ref.observed_at < as_of - 2 * window:
        return Unavailable(NO_REFERENCE_POINT)
    return latest, ref


def price_change_at(
    points: Iterable[MarketPoint], mint_address: str, t: datetime, window: timedelta = HOUR
) -> Measured:
    """Fractional price change over ``window`` ending at ``t``, using only
    points available at ``t``. Shared with the event engine's re-arm check."""
    pair = _reference(_points(points, mint_address, t), t, window)
    if isinstance(pair, Unavailable):
        return pair
    latest, ref = pair
    return _change(latest.price_usd, ref.price_usd, "price")


def _bar_volume(
    points: Sequence[MarketPoint], start: datetime, end: datetime
) -> Decimal | Unavailable:
    """Sum of candle volumes for bars fully inside [start, end], only if the
    bars tile the span completely — a partial hour is not an hour's volume."""
    bars = [
        p
        for p in points
        if p.bar_volume is not None
        and p.bar_seconds
        and p.observed_at - timedelta(seconds=p.bar_seconds) >= start
        and p.observed_at <= end
    ]
    covered = sum((timedelta(seconds=p.bar_seconds or 0) for p in bars), timedelta(0))
    if not bars or covered < end - start:
        return Unavailable("incomplete_bars")
    return sum((p.bar_volume or Decimal(0) for p in bars), Decimal(0))


def _volume_growth(points: Sequence[MarketPoint], as_of: datetime) -> Measured:
    """1h volume now ÷ 1h volume an hour earlier. Snapshot ``volume_1h`` when
    the provider reports it; otherwise summed candle bars."""
    pair = _reference(points, as_of, HOUR)
    if not isinstance(pair, Unavailable):
        latest, ref = pair
        if latest.volume_1h is not None and ref.volume_1h is not None:
            if ref.volume_1h == 0:
                return Unavailable(ZERO_DENOMINATOR)
            return latest.volume_1h / ref.volume_1h
    now = _bar_volume(points, as_of - HOUR, as_of)
    before = _bar_volume(points, as_of - 2 * HOUR, as_of - HOUR)
    if isinstance(now, Unavailable):
        return pair if isinstance(pair, Unavailable) else now
    if isinstance(before, Unavailable):
        return before
    if before == 0:
        return Unavailable(ZERO_DENOMINATOR)
    return now / before


def market_features(
    state: InformationState, mint_address: str, *, window: timedelta = HOUR
) -> MarketFeatures:
    """Market context for ``mint_address`` at ``state.as_of``."""
    as_of = state.as_of
    points = _points(state.market, mint_address, as_of)

    token = next((t for t in state.tokens if t.mint_address == mint_address), None)
    born = None if token is None else (token.created_at or token.discovered_at)
    age = None if born is None or born > as_of else as_of - born

    if not points:
        missing = Unavailable(NO_MARKET_DATA)
        return MarketFeatures(
            as_of=as_of,
            mint_address=mint_address,
            price_usd=missing,
            market_cap=missing,
            liquidity_usd=missing,
            volume_1h=missing,
            volume_growth=missing,
            price_change=missing,
            liquidity_change=missing,
            token_age=age,
            age_bucket=age_bucket(age),
            data_age_seconds=missing,
        )

    latest = points[-1]

    def level(value: Decimal | None, field: str) -> Measured:
        return value if value is not None else Unavailable(f"{field}_not_reported")

    volume_1h: Measured = level(latest.volume_1h, "volume")
    if latest.volume_1h is None:
        bars = _bar_volume(points, as_of - HOUR, as_of)
        if not isinstance(bars, Unavailable):
            volume_1h = bars

    pair = _reference(points, as_of, window)
    if isinstance(pair, Unavailable):
        price_change: Measured = pair
        liquidity_change: Measured = pair
    else:
        price_change = _change(pair[0].price_usd, pair[1].price_usd, "price")
        liquidity_change = _change(pair[0].liquidity_usd, pair[1].liquidity_usd, "liquidity")

    return MarketFeatures(
        as_of=as_of,
        mint_address=mint_address,
        price_usd=level(latest.price_usd, "price"),
        market_cap=level(latest.market_cap, "market_cap"),
        liquidity_usd=level(latest.liquidity_usd, "liquidity"),
        volume_1h=volume_1h,
        volume_growth=_volume_growth(points, as_of),
        price_change=price_change,
        liquidity_change=liquidity_change,
        token_age=age,
        age_bucket=age_bucket(age),
        data_age_seconds=_seconds(as_of - latest.observed_at),
    )
