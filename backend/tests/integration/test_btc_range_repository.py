"""The candle table is the live paper book's record, so it must not move.

The properties defended here:

* re-ingesting is a no-op (idempotent), and says so by returning 0 written;
* a CLOSED candle is never changed by any later payload, however different;
* a FORMING candle is refreshed until it closes, and is then frozen;
* readers get closed candles only, ascending, with a total ordering.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from app.labs.btc_range import ingest, repository
from app.labs.btc_range.source import BinanceKlineClient, Kline
from app.labs.btc_range.types import Candle

pytestmark = pytest.mark.integration

STEP = timedelta(minutes=15)
T0 = datetime(2026, 10, 8, 0, 0, tzinfo=UTC)


def k(i: int, *, close="100.00", now: datetime, high="101.00") -> Kline:
    open_time = T0 + i * STEP
    close_time = open_time + STEP - timedelta(milliseconds=1)
    c = Candle(
        open_time, Decimal("100"), Decimal(high), Decimal("99"), Decimal(close), Decimal("5")
    )
    return Kline(c, close_time, close_time < now)


def raw(i: int, close: str = "100.50") -> list:
    open_time = T0 + i * STEP
    ms = int(open_time.timestamp() * 1000)
    return [
        ms,
        "100.00",
        "101.00",
        "99.00",
        close,
        "5.0",
        ms + 900_000 - 1,
        "500",
        10,
        "2",
        "200",
        "0",
    ]


async def test_upsert_is_idempotent(db_session) -> None:
    now = T0 + 10 * STEP
    rows = [k(i, now=now) for i in range(5)]
    assert await repository.upsert_candles(db_session, rows) == 5
    assert await repository.upsert_candles(db_session, rows) == 0
    count, first, last = await repository.stats(db_session)
    assert (count, first, last) == (5, T0, T0 + 4 * STEP)


async def test_empty_input_writes_nothing(db_session) -> None:
    assert await repository.upsert_candles(db_session, []) == 0
    assert await repository.stats(db_session) == (0, None, None)
    assert await repository.latest_candle(db_session) is None
    assert await repository.closed_candles(db_session) == []


async def test_a_closed_candle_is_not_overwritten_by_a_later_payload(db_session) -> None:
    now = T0 + 10 * STEP
    await repository.upsert_candles(db_session, [k(0, now=now, close="100.00")])
    # The source "revises" the print, and even claims it is still forming.
    revised = k(0, now=now, close="555.55", high="999")
    assert await repository.upsert_candles(db_session, [revised]) == 0
    forming_claim = Kline(revised.candle, revised.close_time, False)
    assert await repository.upsert_candles(db_session, [forming_claim]) == 0

    (stored,) = await repository.closed_candles(db_session)
    assert stored.close == Decimal("100.00")
    assert stored.high == Decimal("101.00")


async def test_a_forming_candle_updates_until_it_closes_and_is_then_frozen(db_session) -> None:
    during = T0 + timedelta(minutes=5)
    await repository.upsert_candles(db_session, [k(0, now=during, close="100.00")])
    assert await repository.closed_candles(db_session) == []  # forming is not closed
    latest = await repository.latest_candle(db_session)
    assert latest is not None and latest[1] is False and latest[0].close == Decimal("100.00")

    # Still forming, new print.
    assert await repository.upsert_candles(db_session, [k(0, now=during, close="103.25")]) == 1
    latest = await repository.latest_candle(db_session)
    assert latest is not None and latest[0].close == Decimal("103.25")

    # The payload that closes it.
    after = T0 + STEP + timedelta(seconds=1)
    assert await repository.upsert_candles(db_session, [k(0, now=after, close="104.00")]) == 1
    latest = await repository.latest_candle(db_session)
    assert latest is not None and latest[1] is True and latest[0].close == Decimal("104.00")

    # Frozen from here on.
    assert await repository.upsert_candles(db_session, [k(0, now=after, close="1.00")]) == 0
    (stored,) = await repository.closed_candles(db_session)
    assert stored.close == Decimal("104.00")


async def test_numeric_precision_round_trips_exactly(db_session) -> None:
    c = Candle(
        T0,
        Decimal("62100.12345678"),
        Decimal("62100.12345678"),
        Decimal("0.00000001"),
        Decimal("62100.1"),
        Decimal("1234.00000009"),
    )
    await repository.upsert_candles(db_session, [Kline(c, T0 + STEP, True)])
    (stored,) = await repository.closed_candles(db_session)
    assert stored.open == Decimal("62100.12345678")
    assert stored.low == Decimal("0.00000001")
    assert stored.volume == Decimal("1234.00000009")


async def test_duplicate_keys_in_one_batch_do_not_error(db_session) -> None:
    now = T0 + 10 * STEP
    n = await repository.upsert_candles(
        db_session, [k(0, now=now, close="1.00"), k(0, now=now, close="2.00")]
    )
    assert n == 1
    (stored,) = await repository.closed_candles(db_session)
    assert stored.close == Decimal("2.00")  # last wins


async def _seed(db_session, n: int = 10, *, forming: bool = True) -> None:
    now = T0 + n * STEP + (timedelta(minutes=1) if forming else timedelta(0))
    # Inserted out of order on purpose: ordering must come from the query.
    rows = [k(i, now=now) for i in reversed(range(n + (1 if forming else 0)))]
    await repository.upsert_candles(db_session, rows)


async def test_closed_candles_are_ascending_and_exclude_the_forming_one(db_session) -> None:
    await _seed(db_session, 10)
    out = await repository.closed_candles(db_session)
    assert [c.open_time for c in out] == [T0 + i * STEP for i in range(10)]


async def test_limit_takes_the_oldest_n_by_default(db_session) -> None:
    await _seed(db_session, 10)
    out = await repository.closed_candles(db_session, limit=3)
    assert [c.open_time for c in out] == [T0 + i * STEP for i in range(3)]


async def test_newest_takes_the_newest_n_but_returns_them_ascending(db_session) -> None:
    await _seed(db_session, 10)
    out = await repository.closed_candles(db_session, limit=3, newest=True)
    assert [c.open_time for c in out] == [T0 + i * STEP for i in (7, 8, 9)]


async def test_start_is_inclusive_and_end_is_exclusive(db_session) -> None:
    await _seed(db_session, 10)
    out = await repository.closed_candles(db_session, start=T0 + 2 * STEP, end=T0 + 5 * STEP)
    assert [c.open_time for c in out] == [T0 + i * STEP for i in (2, 3, 4)]
    out = await repository.closed_candles(
        db_session, start=T0 + 2 * STEP, end=T0 + 9 * STEP, limit=2, newest=True
    )
    assert [c.open_time for c in out] == [T0 + i * STEP for i in (7, 8)]


async def test_stats_count_closed_only(db_session) -> None:
    await _seed(db_session, 10)
    assert await repository.stats(db_session) == (10, T0, T0 + 9 * STEP)
    latest = await repository.latest_candle(db_session)
    assert latest is not None
    assert latest[1] is False and latest[0].open_time == T0 + 10 * STEP


# --- ingest end to end, through a fake transport ----------------------------


def _client(rows: list[list]) -> BinanceKlineClient:
    def handler(request: httpx.Request) -> httpx.Response:
        start = int(request.url.params["startTime"])
        limit = int(request.url.params["limit"])
        return httpx.Response(200, json=[r for r in rows if r[0] >= start][:limit])

    return BinanceKlineClient(
        "https://data-api.binance.vision",
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


async def test_ingest_latest_catches_up_then_only_refreshes_the_forming_candle(
    db_session,
) -> None:
    rows = [raw(i) for i in range(6)]
    now = T0 + 5 * STEP + timedelta(minutes=3)  # candles 0-4 closed, 5 forming
    client = _client(rows)

    first = await ingest.ingest_latest(db_session, client, now=now)
    assert first.written == 6
    assert (await repository.stats(db_session))[0] == 5

    # A minute later the forming candle has a new print; nothing else changed.
    rows[5] = raw(5, close="777.00")
    again = await ingest.ingest_latest(
        db_session, _client(rows), now=now + timedelta(minutes=1)
    )
    assert again.written == 1
    latest = await repository.latest_candle(db_session)
    assert latest is not None and latest[0].close == Decimal("777.00") and latest[1] is False

    # Candle 5 closes: it becomes part of the record, once.
    later = T0 + 6 * STEP + timedelta(seconds=5)
    rows.append(raw(6))
    done = await ingest.ingest_latest(db_session, _client(rows), now=later)
    assert done.written == 2  # candle 5 closing, candle 6 forming
    assert (await repository.stats(db_session)) == (6, T0, T0 + 5 * STEP)


async def test_backfill_is_repeatable(db_session) -> None:
    now = T0 + timedelta(days=3, minutes=1)
    day_start = (now - timedelta(days=3)).replace(minute=0, second=0, microsecond=0)
    n = 3 * 96 + 1
    first_open = day_start
    rows = []
    for i in range(n):
        ms = int((first_open + i * STEP).timestamp() * 1000)
        rows.append([ms, "1", "2", "0.5", "1.5", "3", ms + 899_999, "0", 0, "0", "0", "0"])
    c = _client(rows)

    one = await ingest.backfill(db_session, c, days=3, now=now)
    two = await ingest.backfill(db_session, c, days=3, now=now)
    assert one.written == n
    assert two.written == 1  # only the forming candle is refreshed
    assert (await repository.stats(db_session))[0] == n - 1
