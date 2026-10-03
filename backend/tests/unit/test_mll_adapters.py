"""Lifecycle Lab source adapters.

The property under test is the Lab's first hard rule: absence is never zero. A
source that is switched off, rate limited, missing or unreadable must surface as
an explicit status with a reason and contribute no observation - never a
zero-valued one. No test touches the network; ``httpx.MockTransport`` answers
and counts every request.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.lifecycle_lab.adapters import (
    DexScreenerAdapter,
    GdeltAdapter,
    GeckoTerminalAdapter,
    PumpfunRepliesAdapter,
    RedditAdapter,
    Subject,
    WikipediaAdapter,
    XAdapter,
    build_adapters,
)
from app.lifecycle_lab.adapters.base import MinIntervalLimiter
from app.lifecycle_lab.domain import (
    AliasKind,
    DataClass,
    Meme,
    MemeAlias,
    Metric,
    Source,
    SourceStatus,
    ValueKind,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 3, 12, 7, tzinfo=UTC)
MINT = "MintAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "FEATURE_LIFECYCLE_LAB_ENABLED": True,
        "MLL_GDELT_MIN_INTERVAL_SECONDS": 0,
    }
    base.update(overrides)
    return Settings(**base)


def make_subject(
    *, title: str | None = "Pepe_the_Frog", mints: tuple[str, ...] = (), meme_id: str = "m1"
) -> Subject:
    meme = Meme(
        id=meme_id,
        slug="pepe",
        display_name="Pepe",
        tracking_started_at=NOW - timedelta(days=3),
        wikipedia_title=title,
    )
    alias = MemeAlias(meme_id, "Rare Pepe", AliasKind.PHRASE, NOW - timedelta(days=3))
    return Subject(meme=meme, aliases=(alias,), mints=mints)


class Recorder:
    """A MockTransport handler that records every request."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._handler = handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))


def json_response(body: Any, status: int = 200) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(status, json=body)


async def no_sleep(_: float) -> None:
    return None


# ---------------------------------------------------------------- disabled


async def test_x_never_calls_the_network_and_is_disabled() -> None:
    rec = Recorder(json_response({}))
    adapter = XAdapter(make_settings(MLL_X_ENABLED=True, MLL_X_BEARER_TOKEN="tok"))
    result = await adapter.collect([make_subject()], now=NOW)
    assert result.status is SourceStatus.DISABLED
    assert result.reason == "not_implemented_no_api_plan"
    assert result.observations == ()
    assert rec.requests == []
    assert XAdapter(make_settings()).enabled() == (False, "disabled_by_config")


async def test_reddit_unconfigured_makes_no_network_call() -> None:
    rec = Recorder(json_response({}))
    async with rec.client() as client:
        # Enabled flag alone is not enough: credentials and a UA are required.
        adapter = RedditAdapter(make_settings(MLL_REDDIT_ENABLED=True), client)
        result = await adapter.collect([make_subject()], now=NOW)
    assert result.status is SourceStatus.DISABLED
    assert result.reason == "disabled_by_config"
    assert result.observations == ()
    assert rec.requests == []


async def test_lab_flag_off_disables_every_adapter_without_network() -> None:
    rec = Recorder(json_response({}))
    async with rec.client() as client:
        adapters = build_adapters(Settings(FEATURE_LIFECYCLE_LAB_ENABLED=False), client)
        assert {a.source for a in adapters} == set(Source)
        for adapter in adapters:
            assert adapter.enabled() == (False, "lab_disabled")
            result = await adapter.collect([make_subject(mints=(MINT,))], now=NOW)
            assert result.status is SourceStatus.DISABLED
            assert result.observations == () and result.market_points == ()
    assert rec.requests == []


# ---------------------------------------------------------------- pump.fun


@pytest.mark.parametrize(
    ("age", "status", "reason"),
    [
        (timedelta(minutes=5), SourceStatus.AVAILABLE, None),
        (timedelta(minutes=20), SourceStatus.AVAILABLE, None),
        (timedelta(minutes=21), SourceStatus.STALE, "poller_stale"),
        (None, SourceStatus.UNAVAILABLE, "poller_never_ran"),
    ],
)
async def test_pumpfun_probe_freshness(
    age: timedelta | None, status: SourceStatus, reason: str | None
) -> None:
    adapter = PumpfunRepliesAdapter(make_settings(FEATURE_PUMPFUN_SOCIAL_ENABLED=True))
    adapter.set_latest_observed_at(None if age is None else NOW - age)
    result = await adapter.collect([make_subject()], now=NOW)
    assert (result.status, result.reason) == (status, reason)
    assert result.observations == ()


async def test_pumpfun_probe_disabled_by_either_flag() -> None:
    social_off = PumpfunRepliesAdapter(make_settings())
    assert social_off.enabled() == (False, "pumpfun_social_disabled")
    mll_off = PumpfunRepliesAdapter(
        make_settings(FEATURE_PUMPFUN_SOCIAL_ENABLED=True, MLL_PUMPFUN_REPLIES_ENABLED=False)
    )
    assert mll_off.enabled() == (False, "disabled_by_config")


# ---------------------------------------------------------------- rate limits


async def test_429_is_error_rate_limited_for_every_http_adapter() -> None:
    rec = Recorder(lambda r: httpx.Response(429, text="slow down"))
    reddit_cfg = {
        "MLL_REDDIT_ENABLED": True,
        "MLL_REDDIT_CLIENT_ID": "id",
        "MLL_REDDIT_CLIENT_SECRET": "secret",
        "MLL_REDDIT_USER_AGENT": "memescope-test/0.1 by owner",
    }
    s = make_settings(**reddit_cfg)
    subject = make_subject(mints=(MINT,))
    async with rec.client() as client:
        adapters = [
            WikipediaAdapter(s, client),
            GdeltAdapter(s, client, sleep=no_sleep),
            DexScreenerAdapter(s, client, sleep=no_sleep),
            GeckoTerminalAdapter(s, client, sleep=no_sleep),
            RedditAdapter(s, client),
        ]
        for adapter in adapters:
            before = len(rec.requests)
            result = await adapter.collect([subject], now=NOW)
            assert result.status is SourceStatus.ERROR, adapter.source
            assert result.reason == "rate_limited", adapter.source
            assert result.observations == () and result.market_points == ()
            # No retry storm: one request, then stop.
            assert len(rec.requests) - before == 1, adapter.source


async def test_rate_limit_stops_remaining_subjects() -> None:
    rec = Recorder(lambda r: httpx.Response(429))
    async with rec.client() as client:
        adapter = WikipediaAdapter(make_settings(), client)
        subjects = [make_subject(meme_id="a"), make_subject(meme_id="b")]
        result = await adapter.collect(subjects, now=NOW)
    assert len(rec.requests) == 1
    assert result.per_subject == {
        "a": (SourceStatus.ERROR, "rate_limited"),
        "b": (SourceStatus.ERROR, "rate_limited"),
    }


async def test_network_error_is_error_not_zero() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    async with Recorder(boom).client() as client:
        result = await WikipediaAdapter(make_settings(), client).collect(
            [make_subject()], now=NOW
        )
    assert (result.status, result.reason) == (SourceStatus.ERROR, "network_error")
    assert result.observations == ()


# ---------------------------------------------------------------- wikipedia


def wiki_body(days: list[tuple[str, int]]) -> dict[str, Any]:
    return {
        "items": [
            {
                "project": "en.wikipedia",
                "article": "Pepe_the_Frog",
                "granularity": "daily",
                "timestamp": f"{d}00",
                "access": "all-access",
                "agent": "user",
                "views": v,
            }
            for d, v in days
        ]
    }


async def test_wikipedia_forward_daily_pageviews_with_provenance() -> None:
    # The three complete UTC days before 2026-10-03.
    days = [("20260930", 100), ("20261001", 250), ("20261002", 0)]
    rec = Recorder(json_response(wiki_body(days)))
    s = make_settings(MLL_WIKIPEDIA_USER_AGENT="TestAgent/1.0 (contact: x@example.org)")
    async with rec.client() as client:
        result = await WikipediaAdapter(s, client).collect([make_subject()], now=NOW)

    assert result.status is SourceStatus.AVAILABLE
    request = rec.requests[0]
    assert request.headers["user-agent"] == "TestAgent/1.0 (contact: x@example.org)"
    assert str(request.url).endswith(
        "/en.wikipedia/all-access/user/Pepe_the_Frog/daily/20260930/20261002"
    )
    obs = result.observations
    assert [o.raw_value for o in obs] == [Decimal(100), Decimal(250), Decimal(0)]
    first = obs[0]
    assert first.metric is Metric.PAGEVIEWS and first.value_kind is ValueKind.WINDOW_COUNT
    assert first.data_class is DataClass.FORWARD and first.source is Source.WIKIPEDIA
    assert first.window_start == datetime(2026, 9, 30, tzinfo=UTC)
    assert first.window_end == datetime(2026, 10, 1, tzinfo=UTC)
    assert first.source_timestamp == first.window_start
    assert first.observed_at == first.window_end
    assert first.retrieved_at == NOW
    assert first.meme_id == "m1" and first.query == "Pepe_the_Frog"
    assert first.source_url and first.source_url.startswith("https://wikimedia.org/")
    assert first.confidence == Decimal(1)


async def test_wikipedia_404_is_unavailable_no_article() -> None:
    async with Recorder(
        lambda r: httpx.Response(404, json={"detail": "x"})
    ).client() as client:
        result = await WikipediaAdapter(make_settings(), client).collect(
            [make_subject()], now=NOW
        )
    assert result.status is SourceStatus.UNAVAILABLE
    assert result.per_subject["m1"] == (SourceStatus.UNAVAILABLE, "no_article")
    assert result.observations == ()


async def test_wikipedia_meme_without_title_is_unavailable_and_not_fetched() -> None:
    rec = Recorder(json_response(wiki_body([])))
    async with rec.client() as client:
        result = await WikipediaAdapter(make_settings(), client).collect(
            [make_subject(title=None)], now=NOW
        )
    assert result.per_subject["m1"] == (SourceStatus.UNAVAILABLE, "no_wikipedia_title")
    assert rec.requests == []


async def test_wikipedia_backfill_is_labelled_backfill() -> None:
    rec = Recorder(json_response(wiki_body([("20260101", 42)])))
    async with rec.client() as client:
        result = await WikipediaAdapter(make_settings(), client).backfill(
            make_subject(),
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 2, tzinfo=UTC),
            NOW,
        )
    assert result.observations[0].data_class is DataClass.BACKFILL
    assert result.observations[0].retrieved_at == NOW
    assert result.observations[0].source_timestamp.year == 2026
    assert "/daily/20260101/20260102" in str(rec.requests[0].url)


async def test_wikipedia_drops_incomplete_current_day() -> None:
    body = wiki_body([("20261002", 9), ("20261003", 3)])  # NOW is midday on the 3rd
    async with Recorder(json_response(body)).client() as client:
        result = await WikipediaAdapter(make_settings(), client).collect(
            [make_subject()], now=NOW
        )
    assert [o.window_start.day for o in result.observations if o.window_start] == [2]


# ---------------------------------------------------------------- gdelt


def gdelt_body(points: list[tuple[str, int]]) -> dict[str, Any]:
    return {
        "query_details": {"title": "x"},
        "timeline": [
            {
                "series": "Article Count",
                "data": [{"date": d, "value": v, "norm": 1000} for d, v in points],
            }
        ],
    }


async def test_gdelt_parses_15_minute_buckets_with_provenance() -> None:
    body = gdelt_body(
        [
            ("20261003T110000Z", 4),
            ("20261003T111500Z", 0),  # a real zero: the source answered
            ("20261003T113000Z", 9),
            ("20261003T114500Z", 3),
            ("20261003T120000Z", 7),  # closes 12:15 > NOW (12:07): still filling
        ]
    )
    rec = Recorder(json_response(body))
    async with rec.client() as client:
        result = await GdeltAdapter(make_settings(), client, sleep=no_sleep).collect(
            [make_subject()], now=NOW
        )
    params = rec.requests[0].url.params
    assert params["mode"] == "timelinevolraw" and params["format"] == "json"
    assert params["query"] == '"Pepe"'  # quoted display name when no gdelt_query
    assert result.status is SourceStatus.AVAILABLE
    obs = result.observations
    assert [o.raw_value for o in obs] == [Decimal(4), Decimal(0), Decimal(9), Decimal(3)]
    first = obs[0]
    assert first.metric is Metric.MENTIONS and first.value_kind is ValueKind.WINDOW_COUNT
    assert first.data_class is DataClass.FORWARD
    assert first.window_start == datetime(2026, 10, 3, 11, 0, tzinfo=UTC)
    assert first.window_end == datetime(2026, 10, 3, 11, 15, tzinfo=UTC)
    assert first.source_timestamp == first.window_start
    assert first.observed_at == first.window_end and first.retrieved_at == NOW
    assert (
        first.query == '"Pepe"' and first.source_url and "gdeltproject.org" in first.source_url
    )
    assert first.raw_payload is not None and first.raw_payload["bucket_seconds"] == 900
    assert first.confidence < Decimal(1)  # keyword news match, not an identity


async def test_gdelt_detects_bucket_size_instead_of_assuming() -> None:
    body = gdelt_body(
        [("20261003T080000Z", 5), ("20261003T090000Z", 6), ("20261003T100000Z", 7)]
    )
    async with Recorder(json_response(body)).client() as client:
        result = await GdeltAdapter(make_settings(), client, sleep=no_sleep).collect(
            [make_subject()], now=NOW
        )
    assert {o.raw_payload["bucket_seconds"] for o in result.observations if o.raw_payload} == {
        3600
    }
    assert result.observations[0].window_end == datetime(2026, 10, 3, 9, tzinfo=UTC)


async def test_gdelt_uses_explicit_query_and_backfill_window() -> None:
    subject = make_subject()
    subject = Subject(
        meme=Meme(
            id="m1",
            slug="pepe",
            display_name="Pepe",
            tracking_started_at=NOW,
            gdelt_query='"pepe frog" sourcelang:eng',
        ),
        aliases=subject.aliases,
    )
    rec = Recorder(
        json_response(gdelt_body([("20260101T000000Z", 2), ("20260101T001500Z", 3)]))
    )
    async with rec.client() as client:
        result = await GdeltAdapter(make_settings(), client, sleep=no_sleep).backfill(
            subject, datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC), NOW
        )
    params = rec.requests[0].url.params
    assert params["query"] == '"pepe frog" sourcelang:eng'
    assert (
        params["startdatetime"] == "20260101000000"
        and params["enddatetime"] == "20260102000000"
    )
    assert all(o.data_class is DataClass.BACKFILL for o in result.observations)
    assert len(result.observations) == 2


@pytest.mark.parametrize(
    ("response", "status", "reason"),
    [
        (
            httpx.Response(200, text="Timespan is too short."),
            SourceStatus.ERROR,
            "unparseable",
        ),
        (httpx.Response(200, json=[1, 2]), SourceStatus.ERROR, "unparseable"),
        (
            httpx.Response(
                200, json={"timeline": [{"data": [{"date": "garbage", "value": 1}]}]}
            ),
            SourceStatus.ERROR,
            "unparseable",
        ),
        (
            httpx.Response(
                200,
                json=gdelt_body(
                    [("20261003T100000Z", 1), ("20261003T101500Z", 1), ("20261003T104500Z", 1)]
                ),
            ),
            SourceStatus.ERROR,
            "irregular_buckets",
        ),
        (httpx.Response(200, json={}), SourceStatus.UNAVAILABLE, "no_data_for_window"),
        (
            httpx.Response(200, json=gdelt_body([("20261003T100000Z", 1)])),
            SourceStatus.UNAVAILABLE,
            "bucket_size_unknown",
        ),
        (httpx.Response(503), SourceStatus.ERROR, "http_503"),
    ],
)
async def test_gdelt_unknown_shapes_never_become_zero(
    response: httpx.Response, status: SourceStatus, reason: str
) -> None:
    async with Recorder(lambda r: response).client() as client:
        result = await GdeltAdapter(make_settings(), client, sleep=no_sleep).collect(
            [make_subject()], now=NOW
        )
    assert (result.status, result.reason) == (status, reason)
    assert result.observations == ()


async def test_gdelt_spaces_requests_by_the_configured_interval() -> None:
    clock = {"t": 100.0}
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["t"] += seconds

    body = gdelt_body([("20261003T100000Z", 1), ("20261003T101500Z", 2)])
    s = make_settings(MLL_GDELT_MIN_INTERVAL_SECONDS=6)
    async with Recorder(json_response(body)).client() as client:
        adapter = GdeltAdapter(s, client, sleep=fake_sleep, clock=lambda: clock["t"])
        await adapter.collect([make_subject(meme_id="a"), make_subject(meme_id="b")], now=NOW)
    assert sleeps == [pytest.approx(6.0)]  # none before the first, 6s before the second


async def test_min_interval_limiter_does_not_wait_when_idle() -> None:
    clock = {"t": 0.0}
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    limiter = MinIntervalLimiter(3.0, sleep=fake_sleep, clock=lambda: clock["t"])
    await limiter.wait()
    clock["t"] = 10.0
    await limiter.wait()
    assert sleeps == []


# ---------------------------------------------------------------- dexscreener


def dex_pair(
    mint: str,
    *,
    pair: str,
    liq: float,
    created_ms: int,
    websites: list[str] | None = None,
    chain: str = "solana",
    name: str = "Pepe",
    symbol: str = "PEPE",
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "chainId": chain,
        "dexId": "pumpswap",
        "pairAddress": pair,
        "baseToken": {"address": mint, "name": name, "symbol": symbol},
        "quoteToken": {"address": "So111", "symbol": "SOL"},
        "pairCreatedAt": created_ms,
        "liquidity": {"usd": liq},
    }
    if websites is not None:
        out["info"] = {
            "websites": [{"label": "Website", "url": u} for u in websites],
            "socials": [{"type": "twitter", "url": "https://x.com/pepe"}],
        }
    return out


async def test_dexscreener_profile_observation_and_missing_mint() -> None:
    other = "MintBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
    created = int(datetime(2026, 9, 1, tzinfo=UTC).timestamp() * 1000)
    older = created - 86_400_000
    body = {
        "pairs": [
            dex_pair(MINT, pair="small", liq=10, created_ms=older),
            dex_pair(
                MINT, pair="big", liq=5000, created_ms=created, websites=["https://pepe.fun"]
            ),
            dex_pair("Other", pair="evm", liq=1, created_ms=created, chain="ethereum"),
        ]
    }
    rec = Recorder(json_response(body))
    async with rec.client() as client:
        result = await DexScreenerAdapter(make_settings(), client, sleep=no_sleep).collect(
            [make_subject(mints=(MINT, other))], now=NOW
        )
    assert str(rec.requests[0].url).endswith(f"/latest/dex/tokens/{MINT},{other}")
    assert result.status is SourceStatus.PARTIAL
    assert result.per_subject[MINT] == (SourceStatus.AVAILABLE, None)
    assert result.per_subject[other] == (SourceStatus.UNAVAILABLE, "not_listed")
    assert len(result.observations) == 1  # nothing fabricated for the missing mint
    obs = result.observations[0]
    assert obs.metric is Metric.PROFILE and obs.value_kind is ValueKind.SNAPSHOT
    assert obs.raw_value == Decimal(1) and obs.mint_address == MINT and obs.meme_id is None
    assert obs.source_timestamp == obs.observed_at == obs.retrieved_at == NOW
    assert obs.raw_payload == {
        "websites": ["https://pepe.fun"],
        "socials": [{"type": "twitter", "url": "https://x.com/pepe"}],
        "pair_created_at": datetime.fromtimestamp(older / 1000, tz=UTC).isoformat(),
        "pair_address": "big",
        "dex_id": "pumpswap",
    }
    assert result.profiles[MINT]["pair_address"] == "big"


async def test_dexscreener_batches_at_30_mints() -> None:
    mints = tuple(f"M{i:03d}" for i in range(65))
    rec = Recorder(json_response({"pairs": []}))
    async with rec.client() as client:
        result = await DexScreenerAdapter(make_settings(), client, sleep=no_sleep).collect(
            [make_subject(mints=mints)], now=NOW
        )
    assert len(rec.requests) == 3
    assert all(len(str(r.url).rsplit("/", 1)[1].split(",")) <= 30 for r in rec.requests)
    assert result.status is SourceStatus.UNAVAILABLE and result.observations == ()


async def test_dexscreener_search_candidates() -> None:
    t1 = int(datetime(2026, 9, 2, tzinfo=UTC).timestamp() * 1000)
    t0 = t1 - 3_600_000
    body = {
        "pairs": [
            dex_pair("Zmint", pair="p1", liq=100, created_ms=t1, name="Pepe Z", symbol="PZ"),
            dex_pair(
                "Amint", pair="p2", liq=900, created_ms=t1, websites=["https://a.example"]
            ),
            dex_pair("Amint", pair="p3", liq=50, created_ms=t0),
            dex_pair("Evm", pair="p4", liq=1, created_ms=t1, chain="base"),
        ]
    }
    rec = Recorder(json_response(body))
    async with rec.client() as client:
        found = await DexScreenerAdapter(
            make_settings(), client, sleep=no_sleep
        ).search_candidates("pepe", now=NOW)
    assert rec.requests[0].url.params["q"] == "pepe"
    assert [t.mint_address for t, _ in found] == ["Amint", "Zmint"]  # solana only, sorted
    token, profile = found[0]
    assert token.created_at == datetime.fromtimestamp(t0 / 1000, tz=UTC)  # oldest pair
    assert token.discovered_at == NOW and token.symbol == "PEPE"
    assert profile["websites"] == ["https://a.example"] and profile["pair_address"] == "p2"


# ---------------------------------------------------------------- geckoterminal


def gecko_handler(
    calls: list[str], *, ohlcv_5m: list[list[float]], ohlcv_1h: list[list[float]]
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append(path)
        if path.endswith("/pools"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "attributes": {
                                "address": "poolSmall",
                                "reserve_in_usd": "100",
                                "volume_usd": {"h24": "5"},
                            }
                        },
                        {
                            "attributes": {
                                "address": "poolTop",
                                "reserve_in_usd": "9000",
                                "volume_usd": {"h24": "1"},
                            }
                        },
                    ]
                },
            )
        rows = ohlcv_5m if path.endswith("/minute") else ohlcv_1h
        return httpx.Response(200, json={"data": {"attributes": {"ohlcv_list": rows}}})

    return handler


async def test_geckoterminal_ohlcv_becomes_backfill_market_points() -> None:
    base = int(datetime(2026, 10, 3, 10, 0, tzinfo=UTC).timestamp())
    calls: list[str] = []
    five = [
        [base + 300, 1, 2, 0.5, 1.5, 10],  # newest first, as the API returns
        [base, 1, 1, 1, 1.25, 7],
        [int(NOW.timestamp()), 1, 1, 1, 9, 9],  # not closed yet -> dropped
    ]
    hour = [[base - 3600, 1, 1, 1, 0.9, 100]]
    rec = Recorder(gecko_handler(calls, ohlcv_5m=five, ohlcv_1h=hour))
    async with rec.client() as client:
        result = await GeckoTerminalAdapter(make_settings(), client, sleep=no_sleep).collect(
            [make_subject(mints=(MINT,))], now=NOW
        )
    assert result.status is SourceStatus.AVAILABLE and result.observations == ()
    assert calls == [
        f"/api/v2/networks/solana/tokens/{MINT}/pools",
        "/api/v2/networks/solana/pools/poolTop/ohlcv/minute",
        "/api/v2/networks/solana/pools/poolTop/ohlcv/hour",
    ]
    minute_req = rec.requests[1].url.params
    assert (minute_req["aggregate"], minute_req["limit"], minute_req["currency"]) == (
        "5",
        "1000",
        "usd",
    )
    assert rec.requests[2].url.params["aggregate"] == "1"
    points = result.market_points
    assert len(points) == 3
    five_min = [p for p in points if p.bar_seconds == 300]
    assert [p.price_usd for p in five_min] == [Decimal("1.25"), Decimal("1.5")]  # ascending
    p = five_min[0]
    assert p.data_class is DataClass.BACKFILL and p.source == "geckoterminal"
    assert p.observed_at == p.available_at == datetime.fromtimestamp(base + 300, tz=UTC)
    assert p.bar_volume == Decimal(7) and p.mint_address == MINT
    assert p.liquidity_usd is None  # OHLCV has no liquidity history
    assert [p.bar_seconds for p in points if p.bar_seconds == 3600] == [3600]


async def test_geckoterminal_no_pools_and_empty_ohlcv_are_unavailable() -> None:
    async with Recorder(json_response({"data": []})).client() as client:
        none = await GeckoTerminalAdapter(make_settings(), client, sleep=no_sleep).collect(
            [make_subject(mints=(MINT,))], now=NOW
        )
    assert none.per_subject[MINT] == (SourceStatus.UNAVAILABLE, "no_pools")
    assert none.market_points == ()

    calls: list[str] = []
    rec = Recorder(gecko_handler(calls, ohlcv_5m=[], ohlcv_1h=[]))
    async with rec.client() as client:
        empty = await GeckoTerminalAdapter(make_settings(), client, sleep=no_sleep).collect(
            [make_subject(mints=(MINT,))], now=NOW
        )
    assert empty.per_subject[MINT] == (SourceStatus.UNAVAILABLE, "no_ohlcv")


async def test_geckoterminal_spacing_and_per_run_bound() -> None:
    clock = {"t": 0.0}
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["t"] += seconds

    mints = tuple(f"M{i}" for i in range(4))
    async with Recorder(json_response({"data": []})).client() as client:
        adapter = GeckoTerminalAdapter(
            make_settings(),
            client,
            sleep=fake_sleep,
            clock=lambda: clock["t"],
            max_mints_per_run=2,
        )
        result = await adapter.collect([make_subject(mints=mints)], now=NOW)
    assert result.per_subject["M2"] == (SourceStatus.UNAVAILABLE, "deferred_budget")
    assert result.per_subject["M3"] == (SourceStatus.UNAVAILABLE, "deferred_budget")
    assert sleeps and all(s == pytest.approx(3.0) for s in sleeps)  # <= 20 calls/minute


# ---------------------------------------------------------------- reddit (enabled path)


def reddit_settings() -> Settings:
    return make_settings(
        MLL_REDDIT_ENABLED=True,
        MLL_REDDIT_CLIENT_ID="cid",
        MLL_REDDIT_CLIENT_SECRET="csecret",
        MLL_REDDIT_USER_AGENT="memescope-lab/0.1 by owner",
    )


def reddit_post(ts: datetime, author: str, score: int, comments: int) -> dict[str, Any]:
    return {
        "kind": "t3",
        "data": {
            "created_utc": ts.timestamp(),
            "author": author,
            "score": score,
            "num_comments": comments,
        },
    }


async def test_reddit_enabled_buckets_mentions_participants_engagement() -> None:
    # NOW 12:07 -> last complete 6h bucket is [06:00, 12:00).
    inside = [
        reddit_post(datetime(2026, 10, 3, 7, 0, tzinfo=UTC), "alice", 10, 2),
        reddit_post(datetime(2026, 10, 3, 8, 0, tzinfo=UTC), "alice", 1, 0),
        reddit_post(datetime(2026, 10, 3, 9, 0, tzinfo=UTC), "bob", 5, 5),
        reddit_post(datetime(2026, 10, 3, 9, 30, tzinfo=UTC), "[deleted]", 0, 1),
    ]
    outside = [reddit_post(datetime(2026, 10, 3, 12, 1, tzinfo=UTC), "carol", 99, 99)]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.reddit.com":
            assert request.headers["authorization"].startswith("Basic ")
            assert request.headers["user-agent"] == "memescope-lab/0.1 by owner"
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 86400})
        assert request.headers["authorization"] == "bearer tok"
        return httpx.Response(200, json={"data": {"children": inside + outside}})

    rec = Recorder(handler)
    async with rec.client() as client:
        result = await RedditAdapter(reddit_settings(), client).collect(
            [make_subject()], now=NOW
        )
    assert result.status is SourceStatus.AVAILABLE
    by_metric = {o.metric: o for o in result.observations}
    assert by_metric[Metric.MENTIONS].raw_value == Decimal(4)
    assert by_metric[Metric.UNIQUE_PARTICIPANTS].raw_value == Decimal(2)
    assert by_metric[Metric.ENGAGEMENT].raw_value == Decimal(10 + 2 + 1 + 10 + 1)
    assert all(o.data_class is DataClass.FORWARD for o in result.observations)
    mentions = by_metric[Metric.MENTIONS]
    assert mentions.window_start == datetime(2026, 10, 3, 6, tzinfo=UTC)
    assert mentions.window_end == datetime(2026, 10, 3, 12, tzinfo=UTC)
    assert mentions.query == '"Pepe" OR "Rare Pepe"'
    assert mentions.source_url and "oauth.reddit.com/search" in mentions.source_url
    assert "csecret" not in mentions.source_url


async def test_reddit_truncated_page_is_partial_not_a_count() -> None:
    full = [
        reddit_post(datetime(2026, 10, 3, 11, 0, tzinfo=UTC) - timedelta(seconds=i), "a", 1, 0)
        for i in range(100)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.reddit.com":
            return httpx.Response(200, json={"access_token": "tok"})
        return httpx.Response(200, json={"data": {"children": full}})

    async with Recorder(handler).client() as client:
        result = await RedditAdapter(reddit_settings(), client).collect(
            [make_subject()], now=NOW
        )
    assert result.per_subject["m1"] == (SourceStatus.PARTIAL, "truncated_page")
    assert result.observations == ()


async def test_reddit_bad_credentials_is_error_unauthorized() -> None:
    async with Recorder(lambda r: httpx.Response(401, json={})).client() as client:
        result = await RedditAdapter(reddit_settings(), client).collect(
            [make_subject()], now=NOW
        )
    assert (result.status, result.reason) == (SourceStatus.ERROR, "unauthorized")
    assert result.observations == ()
