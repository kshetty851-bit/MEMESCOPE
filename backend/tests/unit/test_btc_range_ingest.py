"""Ingest paging and the beat task's gate, without a database.

The repository is replaced by an in-memory stand-in so these run as pure unit
tests; the real SQL is covered by `tests/integration/test_btc_range_repository.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.config import settings
from app.labs.btc_range import ingest, repository, scheduler
from app.labs.btc_range.source import MAX_LIMIT, Kline, KlineError
from app.labs.btc_range.types import Candle
from app.workers.celery_app import celery_app

pytestmark = pytest.mark.unit

STEP = timedelta(minutes=15)
T0 = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)


def k(open_time: datetime, now: datetime) -> Kline:
    close_time = open_time + STEP - timedelta(milliseconds=1)
    d = Decimal("100")
    return Kline(Candle(open_time, d, d, d, d, d), close_time, close_time < now)


class FakeSource:
    """Serves a contiguous run of candles from T0, honouring startTime/limit."""

    def __init__(self, count: int) -> None:
        self.count = count
        self.calls: list[tuple[datetime | None, int]] = []

    async def fetch_klines(self, *, start, limit, now):
        self.calls.append((start, limit))
        first = 0 if start is None else max(0, int((start - T0) / STEP))
        stop = min(self.count, first + limit)
        return [k(T0 + i * STEP, now) for i in range(first, stop)]


class FakeRepo:
    def __init__(self, last_closed: datetime | None = None) -> None:
        self.last_closed = last_closed
        self.rows: dict[datetime, Kline] = {}

    async def stats(self, session):
        return (len(self.rows), None, self.last_closed)

    async def upsert_candles(self, session, rows):
        for r in rows:
            self.rows[r.candle.open_time] = r
        return len(rows)


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch) -> FakeRepo:
    fake = FakeRepo()
    monkeypatch.setattr(repository, "stats", fake.stats)
    monkeypatch.setattr(repository, "upsert_candles", fake.upsert_candles)
    return fake


async def test_empty_table_starts_a_small_window_back(repo: FakeRepo) -> None:
    now = T0 + timedelta(days=10, minutes=4)
    src = FakeSource(count=100_000)
    await ingest.ingest_latest(None, src, now=now)  # type: ignore[arg-type]
    start, limit = src.calls[0]
    assert start == T0 + timedelta(days=10) - ingest.DEFAULT_WINDOW  # floored to the candle
    assert limit == MAX_LIMIT


async def test_it_resumes_after_the_last_closed_candle(repo: FakeRepo) -> None:
    repo.last_closed = T0 + 5 * STEP
    now = T0 + 8 * STEP + timedelta(minutes=2)
    src = FakeSource(count=100)
    result = await ingest.ingest_latest(None, src, now=now)  # type: ignore[arg-type]
    assert src.calls[0][0] == T0 + 6 * STEP
    # 6, 7 closed; 8 still forming.
    assert result.fetched == 100 - 6
    assert sorted(repo.rows)[0] == T0 + 6 * STEP


async def test_it_stops_at_a_short_page(repo: FakeRepo) -> None:
    now = T0 + 20 * STEP
    src = FakeSource(count=20)
    result = await ingest.ingest_latest(None, src, now=now)  # type: ignore[arg-type]
    assert result.pages == 1


async def test_paging_is_bounded(repo: FakeRepo) -> None:
    repo.last_closed = T0 - STEP
    now = T0 + timedelta(days=365)
    src = FakeSource(count=50_000)
    result = await ingest.ingest_latest(None, src, now=now)  # type: ignore[arg-type]
    assert result.pages == ingest.MAX_PAGES_LATEST
    assert result.fetched == ingest.MAX_PAGES_LATEST * MAX_LIMIT
    # Contiguous: the second page begins right after the first one ended.
    assert [c[0] for c in src.calls] == [
        T0 + i * MAX_LIMIT * STEP for i in range(ingest.MAX_PAGES_LATEST)
    ]


async def test_a_source_that_ignores_start_time_cannot_loop_for_ever(
    repo: FakeRepo,
) -> None:
    class Stuck:
        calls = 0

        async def fetch_klines(self, *, start, limit, now):
            Stuck.calls += 1
            return [k(T0 + i * STEP, now) for i in range(MAX_LIMIT)]

    repo.last_closed = T0 + 5000 * STEP
    await ingest.ingest_latest(None, Stuck(), now=T0 + timedelta(days=400))  # type: ignore[arg-type]
    assert Stuck.calls <= 2


async def test_backfill_pages_over_the_whole_range(repo: FakeRepo) -> None:
    now = T0 + timedelta(days=30)
    src = FakeSource(count=30 * 96 + 5)
    result = await ingest.backfill(None, src, days=30, now=now)  # type: ignore[arg-type]
    assert result.pages == 3  # 2,880 candles at 1,000 a page
    assert min(repo.rows) == T0
    assert len(repo.rows) == 30 * 96 + 5


async def test_backfill_rejects_a_nonsense_range(repo: FakeRepo) -> None:
    with pytest.raises(ValueError):
        await ingest.backfill(None, FakeSource(1), days=0, now=T0)  # type: ignore[arg-type]


async def test_a_source_error_propagates_after_earlier_pages_were_written(
    repo: FakeRepo,
) -> None:
    class Flaky(FakeSource):
        async def fetch_klines(self, *, start, limit, now):
            if self.calls:
                raise KlineError("boom", status_code=429)
            return await super().fetch_klines(start=start, limit=limit, now=now)

    repo.last_closed = T0 - STEP
    with pytest.raises(KlineError):
        await ingest.ingest_latest(None, Flaky(5000), now=T0 + timedelta(days=100))  # type: ignore[arg-type]
    assert len(repo.rows) == MAX_LIMIT  # page one survived for the caller to commit


# --- the beat task ------------------------------------------------------------


def test_the_task_is_scheduled_every_minute_under_its_name() -> None:
    entry = celery_app.conf.beat_schedule["btc-range-ingest"]
    assert entry["task"] == "btc_range.ingest"
    assert entry["schedule"].minute == set(range(60))
    assert "btc_range.ingest" in celery_app.tasks


async def test_flag_off_returns_before_touching_a_session_or_the_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "LAB_BTC_RANGE_ENABLED", False)

    def boom(*_a, **_k):
        raise AssertionError("must not open a session or a client with the flag off")

    monkeypatch.setattr(scheduler, "SessionFactory", boom)
    monkeypatch.setattr(scheduler, "BinanceKlineClient", boom)
    assert await scheduler.ingest_tick() == {"skipped": "btc_range_disabled"}


async def test_a_source_outage_is_contained(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LAB_BTC_RANGE_ENABLED", True)

    class Boom:
        def __init__(self, *_a, **_k) -> None:
            raise KlineError("HTTP 451", status_code=451)

    monkeypatch.setattr(scheduler, "BinanceKlineClient", Boom)
    assert await scheduler.ingest_tick() == {"error": "btc_range_source_failed"}


def test_settings_defaults() -> None:
    from app.core.config import Settings

    fields = Settings.model_fields
    assert fields["LAB_BTC_RANGE_ENABLED"].default is False
    assert fields["LAB_BTC_RANGE_BINANCE_URL"].default == "https://data-api.binance.vision"
    assert fields["LAB_BTC_RANGE_LIVE_START"].default == datetime(2026, 10, 8, tzinfo=UTC)
