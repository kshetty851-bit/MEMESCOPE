"""Lifecycle Lab collector: every attempt leaves a run.

A source that is disabled, failing or raising must still appear in the run log
with its status; one adapter's crash must not stop the next. The repository is
an in-memory fake that honours the real dedupe (first write wins).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.lifecycle_lab.adapters.base import AdapterResult, Subject
from app.lifecycle_lab.adapters.pumpfun_replies import PumpfunRepliesAdapter
from app.lifecycle_lab.collector import collect_once
from app.lifecycle_lab.domain import (
    CollectionRun,
    DataClass,
    MarketPoint,
    Meme,
    Metric,
    Observation,
    Source,
    SourceStatus,
    ValueKind,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


class FakeRepo:
    def __init__(self, *, latest: datetime | None = None, fail_insert: bool = False) -> None:
        self.keys: set[str] = set()
        self.rows: list[Observation] = []
        self.runs: list[CollectionRun] = []
        self.candles: list[tuple[Sequence[MarketPoint], str, datetime]] = []
        self.latest = latest
        self.fail_insert = fail_insert

    async def insert_observations(self, rows: Sequence[Observation]) -> int:
        if self.fail_insert:
            raise RuntimeError("db down")
        n = 0
        for row in rows:
            if row.dedupe_key() not in self.keys:
                self.keys.add(row.dedupe_key())
                self.rows.append(row)
                n += 1
        return n

    async def record_run(self, run: CollectionRun) -> None:
        self.runs.append(run)

    async def upsert_candles(
        self, points: Sequence[MarketPoint], *, source: str, retrieved_at: datetime
    ) -> int:
        self.candles.append((points, source, retrieved_at))
        return len(points)

    async def pumpfun_social_latest_observed_at(self) -> datetime | None:
        return self.latest


def subject(meme_id: str = "m1") -> Subject:
    meme = Meme(id=meme_id, slug=meme_id, display_name="Pepe", tracking_started_at=NOW)
    return Subject(meme=meme, mints=("MINT1",))


def obs(meme_id: str = "m1", value: int = 5) -> Observation:
    return Observation(
        source=Source.WIKIPEDIA,
        metric=Metric.PAGEVIEWS,
        value_kind=ValueKind.WINDOW_COUNT,
        data_class=DataClass.FORWARD,
        source_timestamp=NOW - timedelta(days=1),
        observed_at=NOW,
        retrieved_at=NOW,
        raw_value=Decimal(value),
        meme_id=meme_id,
        window_start=NOW - timedelta(days=1),
        window_end=NOW,
        query="Pepe",
    )


class StubAdapter:
    data_class = DataClass.FORWARD

    def __init__(
        self,
        source: Source,
        result: AdapterResult | None = None,
        *,
        enabled: tuple[bool, str | None] = (True, None),
        raises: bool = False,
    ) -> None:
        self.source = source
        self._result = result
        self._enabled = enabled
        self._raises = raises
        self.calls = 0

    def enabled(self) -> tuple[bool, str | None]:
        return self._enabled

    async def collect(self, subjects: Sequence[Subject], *, now: datetime) -> AdapterResult:
        self.calls += 1
        if self._raises:
            raise ValueError("kaboom")
        assert self._result is not None
        return self._result


async def test_every_adapter_records_a_run_including_failures_and_disabled() -> None:
    repo = FakeRepo()
    ok = StubAdapter(
        Source.WIKIPEDIA,
        AdapterResult(
            Source.WIKIPEDIA,
            SourceStatus.AVAILABLE,
            None,
            (obs(),),
            {"m1": (SourceStatus.AVAILABLE, None)},
        ),
    )
    rate_limited = StubAdapter(
        Source.GDELT,
        AdapterResult(
            Source.GDELT,
            SourceStatus.ERROR,
            "rate_limited",
            (),
            {"m1": (SourceStatus.ERROR, "rate_limited")},
        ),
    )
    disabled = StubAdapter(Source.REDDIT, enabled=(False, "disabled_by_config"))
    runs = await collect_once(
        repo=repo, adapters=[ok, rate_limited, disabled], subjects=[subject()], now=NOW
    )

    by_source = {(r.source, r.meme_id): r for r in runs}
    assert by_source[(Source.WIKIPEDIA, None)].status is SourceStatus.AVAILABLE
    assert by_source[(Source.WIKIPEDIA, None)].observations_written == 1
    assert by_source[(Source.WIKIPEDIA, "m1")].observations_written == 1
    assert by_source[(Source.GDELT, None)].status is SourceStatus.ERROR
    assert by_source[(Source.GDELT, None)].reason == "rate_limited"
    assert by_source[(Source.GDELT, "m1")].reason == "rate_limited"
    assert by_source[(Source.REDDIT, None)].status is SourceStatus.DISABLED
    assert by_source[(Source.REDDIT, None)].reason == "disabled_by_config"
    assert disabled.calls == 0  # a disabled source is never asked
    # Failures and disabled sources wrote nothing: no zero rows.
    assert len(repo.rows) == 1 and repo.rows[0].raw_value == Decimal(5)
    assert repo.runs == runs  # every run was persisted


async def test_observations_carry_the_global_run_id() -> None:
    repo = FakeRepo()
    adapter = StubAdapter(
        Source.WIKIPEDIA,
        AdapterResult(
            Source.WIKIPEDIA,
            SourceStatus.AVAILABLE,
            None,
            (obs(),),
            {"m1": (SourceStatus.AVAILABLE, None)},
        ),
    )
    runs = await collect_once(repo=repo, adapters=[adapter], subjects=[subject()], now=NOW)
    global_run = next(r for r in runs if r.meme_id is None)
    assert repo.rows[0].collection_run_id == global_run.id


async def test_adapter_exception_becomes_error_run_and_others_still_run() -> None:
    repo = FakeRepo()
    bad = StubAdapter(Source.GDELT, raises=True)
    good = StubAdapter(
        Source.WIKIPEDIA,
        AdapterResult(
            Source.WIKIPEDIA,
            SourceStatus.AVAILABLE,
            None,
            (obs(),),
            {"m1": (SourceStatus.AVAILABLE, None)},
        ),
    )
    runs = await collect_once(repo=repo, adapters=[bad, good], subjects=[subject()], now=NOW)
    gdelt = next(r for r in runs if r.source is Source.GDELT)
    assert gdelt.status is SourceStatus.ERROR and gdelt.reason == "adapter_exception"
    assert gdelt.detail == {"exception": "ValueError"}
    assert good.calls == 1 and len(repo.rows) == 1


async def test_write_failure_is_an_error_run_not_a_crash() -> None:
    repo = FakeRepo(fail_insert=True)
    adapter = StubAdapter(
        Source.WIKIPEDIA,
        AdapterResult(
            Source.WIKIPEDIA,
            SourceStatus.AVAILABLE,
            None,
            (obs(),),
            {"m1": (SourceStatus.AVAILABLE, None)},
        ),
    )
    runs = await collect_once(repo=repo, adapters=[adapter], subjects=[subject()], now=NOW)
    assert [(r.status, r.reason) for r in runs] == [(SourceStatus.ERROR, "write_failed")]


async def test_second_pass_is_idempotent_and_reports_zero_written() -> None:
    repo = FakeRepo()
    adapter = StubAdapter(
        Source.WIKIPEDIA,
        AdapterResult(
            Source.WIKIPEDIA,
            SourceStatus.AVAILABLE,
            None,
            (obs(),),
            {"m1": (SourceStatus.AVAILABLE, None)},
        ),
    )
    await collect_once(repo=repo, adapters=[adapter], subjects=[subject()], now=NOW)
    runs = await collect_once(repo=repo, adapters=[adapter], subjects=[subject()], now=NOW)
    assert len(repo.rows) == 1
    assert next(r for r in runs if r.meme_id is None).observations_written == 0


async def test_backfill_candles_go_to_upsert_candles() -> None:
    repo = FakeRepo()
    point = MarketPoint(
        mint_address="MINT1",
        observed_at=NOW,
        available_at=NOW,
        data_class=DataClass.BACKFILL,
        price_usd=Decimal("1.5"),
        bar_volume=Decimal(3),
        bar_seconds=300,
        source="geckoterminal",
    )
    gecko = StubAdapter(
        Source.GECKOTERMINAL,
        AdapterResult(
            Source.GECKOTERMINAL,
            SourceStatus.AVAILABLE,
            None,
            (),
            {"MINT1": (SourceStatus.AVAILABLE, None)},
            (point,),
        ),
    )
    gecko.data_class = DataClass.BACKFILL
    runs = await collect_once(repo=repo, adapters=[gecko], subjects=[subject()], now=NOW)
    assert repo.candles == [((point,), "geckoterminal", NOW)]
    assert all(r.data_class is DataClass.BACKFILL for r in runs)
    mint_run = next(r for r in runs if r.mint_address == "MINT1")
    assert mint_run.meme_id is None  # token-scoped subject key lands on the mint


async def test_pumpfun_probe_receives_repository_freshness() -> None:
    from app.core.config import Settings

    settings = Settings(
        FEATURE_LIFECYCLE_LAB_ENABLED=True, FEATURE_PUMPFUN_SOCIAL_ENABLED=True
    )
    fresh = PumpfunRepliesAdapter(settings)
    stale = PumpfunRepliesAdapter(settings)
    never = PumpfunRepliesAdapter(settings)
    got = {}
    for name, adapter, latest in (
        ("fresh", fresh, NOW - timedelta(minutes=3)),
        ("stale", stale, NOW - timedelta(hours=2)),
        ("never", never, None),
    ):
        runs = await collect_once(
            repo=FakeRepo(latest=latest), adapters=[adapter], subjects=[subject()], now=NOW
        )
        got[name] = (runs[0].status, runs[0].reason)
    assert got == {
        "fresh": (SourceStatus.AVAILABLE, None),
        "stale": (SourceStatus.STALE, "poller_stale"),
        "never": (SourceStatus.UNAVAILABLE, "poller_never_ran"),
    }


async def test_adapters_run_in_deterministic_source_order() -> None:
    repo = FakeRepo()
    adapters = [
        StubAdapter(s, enabled=(False, "disabled_by_config"))
        for s in (Source.X, Source.GDELT, Source.REDDIT, Source.DEXSCREENER)
    ]
    runs = await collect_once(repo=repo, adapters=adapters, subjects=[], now=NOW)
    assert [r.source.value for r in runs] == ["dexscreener", "gdelt", "reddit", "x"]
