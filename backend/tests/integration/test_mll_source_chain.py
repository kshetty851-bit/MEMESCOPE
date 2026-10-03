"""Source health, end to end: from an HTTP answer to what the page shows.

For pump.fun, Wikipedia, GDELT and DexScreener, each test drives the REAL
adapter through the REAL collector into Postgres (``httpx.MockTransport``; no
network), then reads back through every layer a reader depends on:

    adapter -> collector -> mll_collection_runs -> observation timestamps
    -> pit gate -> attention features -> event detector -> API (/health,
    /memes, /memes/{slug}) -> status values

All six collection states are covered end to end - AVAILABLE, DISABLED,
UNAVAILABLE, ERROR, STALE, PARTIAL - and the property asserted at the end of
every chain is the Lab's first rule: a source that did not answer is a status
with a reason (``Measured`` null + ``unavailable_reason``), never a zero.

The second half pins the collection scheduler through the real store: who is
asked, who waits, who is deferred and recorded.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.lifecycle_lab import api as lab_api
from app.lifecycle_lab import attention as attention_engine
from app.lifecycle_lab.adapters import (
    DexScreenerAdapter,
    GdeltAdapter,
    PumpfunRepliesAdapter,
    WikipediaAdapter,
)
from app.lifecycle_lab.domain import (
    CollectionRun,
    DataClass,
    Meme,
    Metric,
    ResearchMode,
    Source,
    SourceStatus,
    Unavailable,
)
from app.lifecycle_lab.service import LifecycleLabService, partition
from app.models.social import PumpfunSocialSnapshot

pytestmark = pytest.mark.integration

API = f"{settings.API_V1_PREFIX}/lifecycle-lab"
#: When the API is read and events are detected (on the 5-minute grid).
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
#: When collection ran: just before NOW, so everything it wrote is visible.
T = NOW - timedelta(minutes=2)
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
ATTENTION_KEYS = (
    "mentions_1h",
    "mentions_24h",
    "velocity",
    "acceleration",
    "baseline_multiple",
)


def mint() -> str:
    return "".join(random.choice(B58) for _ in range(44))


@pytest.fixture
def svc(db_session: AsyncSession) -> LifecycleLabService:
    return LifecycleLabService(db_session)


@pytest.fixture
def lab_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "FEATURE_LIFECYCLE_LAB_ENABLED", True)
    monkeypatch.setattr(settings, "FEATURE_PUMPFUN_SOCIAL_ENABLED", True)
    monkeypatch.setattr(settings, "MLL_PUMPFUN_REPLIES_ENABLED", True)
    monkeypatch.setattr(settings, "MLL_GDELT_ENABLED", True)
    monkeypatch.setattr(settings, "MLL_WIKIPEDIA_ENABLED", True)
    monkeypatch.setattr(settings, "MLL_DEXSCREENER_ENABLED", True)
    monkeypatch.setattr(settings, "MLL_REDDIT_ENABLED", False)
    monkeypatch.setattr(settings, "MLL_X_ENABLED", False)
    monkeypatch.setattr(settings, "MLL_GDELT_MIN_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(lab_api, "_now", lambda: NOW)


def ticking(start: datetime) -> Callable[[], datetime]:
    """A finish clock that advances 1 ms per run, so a per-subject run is
    always later than its global run and the gate's choice is deterministic."""
    steps: Iterator[int] = iter(range(1_000_000))
    return lambda: start + timedelta(milliseconds=next(steps))


class Transport:
    """MockTransport handler for one host; any other host fails the test."""

    def __init__(self, host: str, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self.host = host
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == self.host, f"unexpected host {request.url.host}"
        self.requests.append(request)
        return self.handler(request)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))


async def make_meme(
    svc: LifecycleLabService,
    name: str,
    *,
    wikipedia_title: str | None = None,
    gdelt_query: str | None = None,
) -> Meme:
    slug = f"mll-{uuid.uuid4().hex[:10]}"
    await svc.create_meme(
        slug=slug,
        display_name=name,
        now=T - timedelta(days=1),
        wikipedia_title=wikipedia_title,
        gdelt_query=gdelt_query,
    )
    meme = await svc.get_meme(slug)
    assert meme is not None
    return meme


async def collect(
    svc: LifecycleLabService, adapter: Any, *, at: datetime = T
) -> dict[str | None, CollectionRun]:
    """One real collection pass; runs keyed by meme id / mint (None: global)."""
    runs = await svc.collect(at, [adapter], clock=ticking(at))
    return {r.meme_id or r.mint_address: r for r in runs}


async def health(client: AsyncClient) -> dict[str, dict[str, Any]]:
    response = await client.get(f"{API}/health")
    assert response.status_code == 200, response.text
    return {s["source"]: s for s in response.json()["sources"]}


async def radar_row(client: AsyncClient, slug: str) -> dict[str, Any]:
    response = await client.get(f"{API}/memes")
    assert response.status_code == 200, response.text
    rows = [r for r in response.json()["items"] if r["slug"] == slug]
    assert len(rows) == 1
    row: dict[str, Any] = rows[0]
    return row


def assert_unavailable_not_zero(row: dict[str, Any], expected_reason: str) -> None:
    """Every attention figure is null with a reason naming the source state."""
    for key in ATTENTION_KEYS:
        measured = row["attention"][key]
        assert measured["value"] is None, (key, measured)
        assert measured["unavailable_reason"], key
    assert expected_reason in row["attention"]["mentions_1h"]["unavailable_reason"]


async def features(svc: LifecycleLabService, meme: Meme, as_of: datetime) -> Any:
    inputs = await svc.load_inputs(
        meme_ids=[meme.id],
        until=as_of,
        since=as_of - timedelta(days=8),
        include_backfill=False,
    )
    (mi,) = partition(inputs)
    state = mi.state(as_of, ResearchMode.AUTHORITATIVE, svc.cfg)
    return state, attention_engine.attention_features(state, svc.cfg.attention)


# ======================================================================== GDELT


def gdelt_timeline(values: dict[datetime, int]) -> dict[str, Any]:
    return {
        "query_details": {"title": "x"},
        "timeline": [
            {
                "series": "Article Count",
                "data": [
                    {"date": t.strftime("%Y%m%dT%H%M%SZ"), "value": v, "norm": 1000}
                    for t, v in sorted(values.items())
                ],
            }
        ],
    }


def surge() -> dict[datetime, int]:
    """06:00-11:45 in 15-minute buckets: 1 per bucket, then 10 from 11:00.
    The 11:45 bucket closes at 12:00 > T and must be withheld."""
    out: dict[datetime, int] = {}
    t = datetime(2026, 9, 20, 6, 0, tzinfo=UTC)
    while t <= datetime(2026, 9, 20, 11, 45, tzinfo=UTC):
        out[t] = 10 if t.hour >= 11 else 1
        t += timedelta(minutes=15)
    return out


def gdelt(svc_handler: Callable[[httpx.Request], httpx.Response]) -> Transport:
    return Transport("api.gdeltproject.org", svc_handler)


async def test_gdelt_available_reaches_features_events_and_the_page(
    svc: LifecycleLabService, client: AsyncClient, lab_on: None
) -> None:
    meme = await make_meme(svc, "Frog CEO")
    transport = gdelt(lambda r: httpx.Response(200, json=gdelt_timeline(surge())))
    async with transport.client() as http:
        runs = await collect(svc, GdeltAdapter(settings, http))

    # runs: one global, one per meme, both AVAILABLE; 23 closed buckets written.
    assert transport.requests[0].url.params["query"] == '"Frog CEO"'
    assert runs[None].status is SourceStatus.AVAILABLE
    assert runs[meme.id].status is SourceStatus.AVAILABLE
    assert runs[meme.id].observations_written == 23

    # observation timestamps: start / end / retrieval, nothing still filling.
    rows = await svc.repo.observations(meme_ids=[meme.id], mints=[], until=NOW)
    assert len(rows) == 23
    assert all(o.retrieved_at == T and o.data_class is DataClass.FORWARD for o in rows)
    assert all(o.source_timestamp == o.window_start for o in rows)
    assert all(o.observed_at == o.window_end <= T for o in rows)

    # pit: invisible before retrieval, visible after.
    before, _ = await features(svc, meme, T - timedelta(seconds=1))
    assert before.observations == ()
    state, attn = await features(svc, meme, NOW)
    assert len(state.observations) == 23
    assert attn.mentions_1h == Decimal(31)  # (10:45, 11:45]: 1 + 10 + 10 + 10

    # event detector fires on the surge.
    detected = await svc.detect_and_store_events(NOW)
    assert detected["new"] >= 1
    events = await svc.repo.events_for_meme(meme.id, mode="authoritative", limit=50)
    assert "attention_increase" in {e["event_type"] for e in events}

    # API.
    by = await health(client)
    assert (by["gdelt"]["status"], by["gdelt"]["reason"]) == ("available", None)
    assert by["gdelt"]["observations_24h"] == 23
    row = await radar_row(client, meme.slug)
    assert row["attention"]["mentions_1h"] == {"value": "31", "unavailable_reason": None}
    detail = (await client.get(f"{API}/memes/{meme.slug}")).json()
    assert "gdelt" in detail["series"]["per_source"]
    assert {s["source"]: s["status"] for s in detail["sources"]}["gdelt"] == "available"


@pytest.mark.parametrize(
    ("respond", "status", "reason"),
    [
        (lambda r: httpx.Response(200, text=""), "unavailable", "no_data_for_window"),
        (lambda r: httpx.Response(200, json={}), "unavailable", "no_data_for_window"),
        (
            lambda r: httpx.Response(
                200, text="Please limit requests to one every 5 seconds."
            ),
            "error",
            "rate_limited",
        ),
        (
            lambda r: httpx.Response(200, text="The specified phrase is too short."),
            "error",
            "gdelt_query_error",
        ),
        (lambda r: httpx.Response(200, text='{"timeline": ['), "error", "unparseable"),
        (lambda r: httpx.Response(503), "error", "http_503"),
        (lambda r: httpx.Response(429), "error", "rate_limited"),
    ],
)
async def test_gdelt_failures_are_statuses_all_the_way_up(
    svc: LifecycleLabService,
    client: AsyncClient,
    lab_on: None,
    respond: Callable[[httpx.Request], httpx.Response],
    status: str,
    reason: str,
) -> None:
    meme = await make_meme(svc, "Frog CEO")
    async with gdelt(respond).client() as http:
        runs = await collect(svc, GdeltAdapter(settings, http))
    assert (runs[meme.id].status.value, runs[meme.id].reason) == (status, reason)
    assert runs[meme.id].observations_written == 0
    if reason == "gdelt_query_error":
        assert runs[meme.id].detail == {"body_head": "The specified phrase is too short."}
    assert await svc.repo.observations(meme_ids=[meme.id], mints=[], until=NOW) == []

    _, attn = await features(svc, meme, NOW)
    assert attn.per_source["gdelt"]["mentions_1h"] == Unavailable(reason)
    assert (await svc.detect_and_store_events(NOW))["detected"] == 0

    by = await health(client)
    assert (by["gdelt"]["status"], by["gdelt"]["reason"]) == (status, reason)
    assert_unavailable_not_zero(await radar_row(client, meme.slug), f"gdelt={reason}")


async def test_gdelt_disabled_asks_nobody_and_says_so(
    svc: LifecycleLabService,
    client: AsyncClient,
    lab_on: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MLL_GDELT_ENABLED", False)
    meme = await make_meme(svc, "Frog CEO")
    transport = gdelt(lambda r: httpx.Response(200, json=gdelt_timeline(surge())))
    async with transport.client() as http:
        runs = await collect(svc, GdeltAdapter(settings, http))
    assert transport.requests == []
    assert set(runs) == {None}
    assert (runs[None].status, runs[None].reason) == (
        SourceStatus.DISABLED,
        "disabled_by_config",
    )
    by = await health(client)
    assert by["gdelt"]["status"] == "disabled" and by["gdelt"]["observations_24h"] is None
    assert_unavailable_not_zero(await radar_row(client, meme.slug), "gdelt=disabled_by_config")


async def test_gdelt_goes_stale_when_nothing_new_arrives(
    svc: LifecycleLabService,
    client: AsyncClient,
    lab_on: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Past GDELT's freshness budget (7h: the LOW-priority 6h cadence plus a
    margin) the old counts are not "now": the source is STALE and every figure
    is null - not the last value, not 0."""
    meme = await make_meme(svc, "Frog CEO")
    async with gdelt(
        lambda r: httpx.Response(200, json=gdelt_timeline(surge()))
    ).client() as h:
        await collect(svc, GdeltAdapter(settings, h))
    later = NOW + timedelta(hours=8)
    monkeypatch.setattr(lab_api, "_now", lambda: later)

    _, attn = await features(svc, meme, later)
    assert attn.per_source["gdelt"]["mentions_1h"] == Unavailable(
        "no_available_run_within_max_age"
    )
    by = await health(client)
    assert (by["gdelt"]["status"], by["gdelt"]["reason"]) == (
        "stale",
        "no_available_run_within_max_age",
    )
    assert_unavailable_not_zero(
        await radar_row(client, meme.slug), "gdelt=no_available_run_within_max_age"
    )


async def test_gdelt_partial_keeps_each_memes_own_truth(
    svc: LifecycleLabService, client: AsyncClient, lab_on: None
) -> None:
    ok = await make_meme(svc, "Alpha")
    bad = await make_meme(svc, "Beta")

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.params["query"] == '"Beta"':
            return httpx.Response(200, text="The specified phrase is too short.")
        return httpx.Response(200, json=gdelt_timeline(surge()))

    async with gdelt(respond).client() as http:
        runs = await collect(svc, GdeltAdapter(settings, http))
    assert (runs[None].status, runs[None].reason) == (SourceStatus.PARTIAL, "partial_subjects")
    assert runs[ok.id].status is SourceStatus.AVAILABLE
    assert runs[bad.id].reason == "gdelt_query_error"

    by = await health(client)
    assert (by["gdelt"]["status"], by["gdelt"]["reason"]) == ("partial", "partial_subjects")
    good_row = await radar_row(client, ok.slug)
    assert good_row["attention"]["mentions_1h"]["value"] == "31"
    assert_unavailable_not_zero(await radar_row(client, bad.slug), "gdelt=gdelt_query_error")


# ===================================================================== pump.fun


async def linked(svc: LifecycleLabService, meme: Meme, *mints: str) -> None:
    for m in mints:
        await svc.add_manual_link(
            meme.slug, m, Decimal("0.9"), "tester", T - timedelta(hours=20)
        )


async def add_replies(
    session: AsyncSession, mint_address: str, *, last: datetime, hours: int = 3
) -> None:
    """A poll every 10 minutes for ``hours``, the counter climbing 2 per poll."""
    t, n = last - timedelta(hours=hours), 0
    while t <= last:
        session.add(
            PumpfunSocialSnapshot(
                mint_address=mint_address,
                observed_at=t,
                reply_count=n,
                source_sort="last_reply",
            )
        )
        t += timedelta(minutes=10)
        n += 2
    await session.flush()


@pytest.mark.parametrize(
    ("last_poll", "status", "reason"),
    [
        (T - timedelta(minutes=5), "available", None),
        (T - timedelta(hours=1), "stale", "poller_stale"),
        (None, "unavailable", "poller_never_ran"),
    ],
)
async def test_pumpfun_probe_states_reach_the_page(
    svc: LifecycleLabService,
    db_session: AsyncSession,
    client: AsyncClient,
    lab_on: None,
    last_poll: datetime | None,
    status: str,
    reason: str | None,
) -> None:
    meme = await make_meme(svc, "Frog CEO")
    m = mint()
    await linked(svc, meme, m)
    if last_poll is not None:
        await add_replies(db_session, m, last=last_poll)
    runs = await collect(svc, PumpfunRepliesAdapter(settings))
    assert set(runs) == {None}  # a probe: one global run, no network, no rows written
    assert (runs[None].status.value, runs[None].reason) == (status, reason)

    _, attn = await features(svc, meme, NOW)
    by = await health(client)
    assert (by["pumpfun_replies"]["status"], by["pumpfun_replies"]["reason"]) == (
        status,
        reason,
    )
    assert by["pumpfun_replies"]["observations_24h"] is None  # read in place, not counted
    row = await radar_row(client, meme.slug)
    if status == "available":
        # Replies are read in place: deltas of the cumulative counter.
        assert isinstance(attn.per_source["pumpfun_replies"]["mentions_1h"], Decimal)
        assert row["attention"]["mentions_1h"]["value"] is not None
    else:
        assert attn.per_source["pumpfun_replies"]["mentions_1h"] == (Unavailable(reason or ""))
        assert_unavailable_not_zero(row, f"pumpfun_replies={reason}")


async def test_pumpfun_disabled_when_the_poller_is_off(
    svc: LifecycleLabService,
    client: AsyncClient,
    lab_on: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "FEATURE_PUMPFUN_SOCIAL_ENABLED", False)
    meme = await make_meme(svc, "Frog CEO")
    runs = await collect(svc, PumpfunRepliesAdapter(settings))
    assert (runs[None].status, runs[None].reason) == (
        SourceStatus.DISABLED,
        "pumpfun_social_disabled",
    )
    by = await health(client)
    assert by["pumpfun_replies"]["status"] == "disabled"
    assert_unavailable_not_zero(
        await radar_row(client, meme.slug), "pumpfun_replies=pumpfun_social_disabled"
    )


# ==================================================================== Wikipedia


def wiki(handler: Callable[[httpx.Request], httpx.Response]) -> Transport:
    return Transport("wikimedia.org", handler)


def wiki_items(views: list[int]) -> dict[str, Any]:
    days = [T.date() - timedelta(days=len(views) - i) for i in range(len(views))]
    return {
        "items": [
            {"article": "Pepe_the_Frog", "timestamp": f"{d:%Y%m%d}00", "views": v}
            for d, v in zip(days, views, strict=True)
        ]
    }


async def test_wikipedia_available_daily_windows_reach_features(
    svc: LifecycleLabService, client: AsyncClient, lab_on: None
) -> None:
    meme = await make_meme(svc, "Pepe", wikipedia_title="Pepe_the_Frog")
    transport = wiki(lambda r: httpx.Response(200, json=wiki_items([100, 120, 600])))
    async with transport.client() as http:
        runs = await collect(svc, WikipediaAdapter(settings, http))
    assert "user-agent" in transport.requests[0].headers
    assert runs[meme.id].status is SourceStatus.AVAILABLE
    assert runs[meme.id].observations_written == 3

    rows = await svc.repo.observations(meme_ids=[meme.id], mints=[], until=NOW)
    assert {o.metric for o in rows} == {Metric.PAGEVIEWS}
    for o in rows:  # one complete UTC day per row, retrieved after it closed
        assert o.window_end - o.window_start == timedelta(days=1)  # type: ignore[operator]
        assert o.observed_at == o.window_end and o.window_end <= T and o.retrieved_at == T

    _, attn = await features(svc, meme, NOW)
    assert attn.per_source["wikipedia"]["daily_views"] == Decimal(600)
    assert attn.per_source["wikipedia"]["views_baseline_multiple"] == Decimal(600) / Decimal(
        110
    )
    by = await health(client)
    assert (by["wikipedia"]["status"], by["wikipedia"]["reason"]) == ("available", None)


@pytest.mark.parametrize(
    ("respond", "status", "reason"),
    [
        (
            lambda r: httpx.Response(404, json={"title": "Not found."}),
            "unavailable",
            "no_article",
        ),
        (lambda r: httpx.Response(503), "error", "http_503"),
        (lambda r: httpx.Response(200, text="<html>"), "error", "unparseable"),
    ],
)
async def test_wikipedia_failures_are_statuses_all_the_way_up(
    svc: LifecycleLabService,
    client: AsyncClient,
    lab_on: None,
    respond: Callable[[httpx.Request], httpx.Response],
    status: str,
    reason: str,
) -> None:
    meme = await make_meme(svc, "Pepe", wikipedia_title="Pepe_the_Frog")
    async with wiki(respond).client() as http:
        runs = await collect(svc, WikipediaAdapter(settings, http))
    assert (runs[meme.id].status.value, runs[meme.id].reason) == (status, reason)
    _, attn = await features(svc, meme, NOW)
    assert attn.per_source["wikipedia"]["daily_views"] == Unavailable(reason)
    by = await health(client)
    assert (by["wikipedia"]["status"], by["wikipedia"]["reason"]) == (status, reason)
    assert_unavailable_not_zero(await radar_row(client, meme.slug), f"wikipedia={reason}")


# ================================================================== DexScreener


def dex_pair(mint_address: str) -> dict[str, Any]:
    return {
        "chainId": "solana",
        "dexId": "pumpswap",
        "pairAddress": f"pair-{mint_address[:6]}",
        "baseToken": {"address": mint_address, "name": "Frog CEO", "symbol": "FROGCEO"},
        "liquidity": {"usd": 12345.6},
        "pairCreatedAt": int((T - timedelta(days=3)).timestamp() * 1000),
        "info": {"websites": [{"url": "https://frog.example"}], "socials": []},
    }


async def test_dexscreener_partial_and_profile_visibility(
    svc: LifecycleLabService, client: AsyncClient, lab_on: None
) -> None:
    """Identity, not attention: a listed mint gets a profile snapshot dated
    when we asked; an unlisted one is UNAVAILABLE not_listed - not an empty
    profile - and the source as a whole is PARTIAL."""
    meme = await make_meme(svc, "Frog CEO")
    listed, unlisted = mint(), mint()
    await linked(svc, meme, listed, unlisted)
    transport = Transport(
        "api.dexscreener.com",
        lambda r: httpx.Response(200, json={"pairs": [dex_pair(listed)]}),
    )
    async with transport.client() as http:
        runs = await collect(svc, DexScreenerAdapter(settings, http, sleep=_no_sleep))
    assert len(transport.requests) == 1  # both mints in one batch
    assert (runs[None].status, runs[None].reason) == (SourceStatus.PARTIAL, "partial_subjects")
    assert runs[listed].status is SourceStatus.AVAILABLE and runs[listed].meme_id is None
    assert (runs[unlisted].status, runs[unlisted].reason) == (
        SourceStatus.UNAVAILABLE,
        "not_listed",
    )

    before, _ = await features(svc, meme, T - timedelta(seconds=1))
    assert not [o for o in before.observations if o.source is Source.DEXSCREENER]
    state, attn = await features(svc, meme, NOW)
    profiles = [o for o in state.observations if o.source is Source.DEXSCREENER]
    assert [(o.mint_address, o.retrieved_at, o.metric) for o in profiles] == [
        (listed, T, Metric.PROFILE)
    ]
    assert "dexscreener" not in attn.per_source  # never counted as attention

    by = await health(client)
    assert (by["dexscreener"]["status"], by["dexscreener"]["reason"]) == (
        "partial",
        "partial_subjects",
    )


async def test_dexscreener_rate_limit_is_error_everywhere(
    svc: LifecycleLabService, client: AsyncClient, lab_on: None
) -> None:
    meme = await make_meme(svc, "Frog CEO")
    m = mint()
    await linked(svc, meme, m)
    async with Transport(
        "api.dexscreener.com", lambda r: httpx.Response(429)
    ).client() as http:
        runs = await collect(svc, DexScreenerAdapter(settings, http, sleep=_no_sleep))
    assert (runs[m].status, runs[m].reason) == (SourceStatus.ERROR, "rate_limited")
    assert await svc.repo.observations(meme_ids=[], mints=[m], until=NOW) == []
    by = await health(client)
    assert (by["dexscreener"]["status"], by["dexscreener"]["reason"]) == (
        "error",
        "rate_limited",
    )


async def _no_sleep(_: float) -> None:
    return None


async def test_every_state_appears_and_none_reads_as_zero(
    svc: LifecycleLabService,
    db_session: AsyncSession,
    client: AsyncClient,
    lab_on: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One board, every status at once: the health payload carries the six
    states, and wherever a source is not AVAILABLE its count is null or the
    rows it really stored - never a fabricated 0 standing in for "unknown"."""
    meme = await make_meme(svc, "Frog CEO", wikipedia_title="Pepe_the_Frog")
    other = await make_meme(svc, "Beta")
    m = mint()
    await linked(svc, meme, m)
    await add_replies(db_session, m, last=T - timedelta(hours=1))  # STALE

    def gdelt_partial(request: httpx.Request) -> httpx.Response:
        if request.url.params["query"] == '"Beta"':
            return httpx.Response(200, text="The specified phrase is too short.")
        return httpx.Response(200, json=gdelt_timeline(surge()))

    async with (
        Transport("api.gdeltproject.org", gdelt_partial).client() as g,
        wiki(lambda r: httpx.Response(404)).client() as w,
        Transport("api.dexscreener.com", lambda r: httpx.Response(503)).client() as d,
    ):
        for adapter in (
            GdeltAdapter(settings, g),  # PARTIAL
            WikipediaAdapter(settings, w),  # UNAVAILABLE (no_article / no title)
            DexScreenerAdapter(settings, d, sleep=_no_sleep),  # ERROR
            PumpfunRepliesAdapter(settings),  # STALE
        ):
            await collect(svc, adapter)
    monkeypatch.setattr(settings, "MLL_REDDIT_ENABLED", False)  # DISABLED

    by = await health(client)
    states = {name: s["status"] for name, s in by.items()}
    assert states["gdelt"] == "partial"
    assert states["wikipedia"] == "unavailable"
    assert states["dexscreener"] == "error"
    assert states["pumpfun_replies"] == "stale"
    assert states["reddit"] == "disabled"
    assert states["gdelt"] != "available"
    # AVAILABLE end to end, on the same board, via the meme GDELT answered for.
    row = await radar_row(client, meme.slug)
    assert row["attention"]["mentions_1h"]["value"] == "31"
    for name, s in by.items():
        if s["status"] != "available":
            assert s["reason"], name
        if s["status"] in ("disabled", "never_collected"):
            assert s["observations_24h"] is None, name
    assert_unavailable_not_zero(await radar_row(client, other.slug), "gdelt=gdelt_query_error")
    detail = (await client.get(f"{API}/memes/{other.slug}")).json()
    assert detail["series"]["per_source"] == {}
    assert {p["value"] for p in detail["series"]["attention"]} <= {None}


# ============================================================ scheduling, real store


async def record(
    svc: LifecycleLabService,
    source: Source,
    status: SourceStatus,
    at: datetime,
    *,
    meme_id: str | None = None,
    mint_address: str | None = None,
    reason: str | None = None,
) -> None:
    await svc.repo.record_run(
        CollectionRun(
            id=str(uuid.uuid4()),
            source=source,
            status=status,
            started_at=at,
            finished_at=at,
            data_class=DataClass.FORWARD,
            reason=reason,
            meme_id=meme_id,
            mint_address=mint_address,
        )
    )


async def test_scheduled_pass_asks_the_due_defers_over_budget_and_skips_the_rest(
    svc: LifecycleLabService, lab_on: None
) -> None:
    """Three memes with no attention data (UNKNOWN, no recent data: LOW, 6h).
    'fresh' succeeded 1h ago (not due); 'stale' 7h ago and 'new' never (both
    due). With a budget of one request, 'new' goes first (never collected
    sorts first), 'stale' is deferred AND recorded, 'fresh' is not touched.
    The deferral is not a success, so 'stale' is first in line next pass."""
    fresh = await make_meme(svc, "Fresh")
    stale = await make_meme(svc, "Stale")
    new = await make_meme(svc, "New")
    await record(
        svc, Source.GDELT, SourceStatus.AVAILABLE, T - timedelta(hours=1), meme_id=fresh.id
    )
    await record(
        svc, Source.GDELT, SourceStatus.AVAILABLE, T - timedelta(hours=7), meme_id=stale.id
    )

    transport = gdelt(lambda r: httpx.Response(200, json=gdelt_timeline(surge())))
    async with transport.client() as http:
        adapter = GdeltAdapter(settings, http)
        priorities = await svc.collection_priorities(T)
        assert {p.level.value for p in priorities.values()} == {"low"}
        assert {p.reason for p in priorities.values()} == {"unknown_no_recent_data"}

        plan = await svc.plan_collection(T, [adapter], gdelt_budget=1)
        assert plan[Source.GDELT].summary == {
            "due": 1,
            "not_due": 1,
            "deferred": 1,
            "planned_requests": 1,
        }
        runs = await svc.collect(T, [adapter], clock=ticking(T), schedule=plan)

    assert [r.url.params["query"] for r in transport.requests] == ['"New"']
    assert transport.requests[0].url.params["timespan"] == "24h"  # never collected: the cap
    by = {r.meme_id: r for r in runs}
    assert by[new.id].status is SourceStatus.AVAILABLE
    assert (by[stale.id].status, by[stale.id].reason) == (
        SourceStatus.UNAVAILABLE,
        "deferred_budget",
    )
    assert fresh.id not in by
    assert by[None].detail is not None and by[None].detail["schedule"]["deferred"] == 1

    later = T + timedelta(minutes=14)
    transport.requests.clear()
    async with transport.client() as http:
        adapter = GdeltAdapter(settings, http)
        plan = await svc.plan_collection(later, [adapter], gdelt_budget=1)
        await svc.collect(later, [adapter], clock=ticking(later), schedule=plan)
    assert [r.url.params["query"] for r in transport.requests] == ['"Stale"']
    # The gap since its last success (7h14m) plus one bucket, rounded up.
    assert transport.requests[0].url.params["timespan"] == "8h"


async def test_daily_sources_are_asked_once_per_utc_day(
    svc: LifecycleLabService, lab_on: None
) -> None:
    today = await make_meme(svc, "Today", wikipedia_title="A")
    yesterday = await make_meme(svc, "Yesterday", wikipedia_title="B")
    m_known, m_new = mint(), mint()
    await linked(svc, today, m_known)
    await linked(svc, yesterday, m_new)  # newly linked: never profiled
    midnight = datetime(2026, 9, 20, tzinfo=UTC)
    await record(
        svc,
        Source.WIKIPEDIA,
        SourceStatus.AVAILABLE,
        midnight + timedelta(minutes=5),
        meme_id=today.id,
    )
    await record(
        svc,
        Source.WIKIPEDIA,
        SourceStatus.AVAILABLE,
        midnight - timedelta(minutes=5),
        meme_id=yesterday.id,
    )
    await record(
        svc,
        Source.DEXSCREENER,
        SourceStatus.AVAILABLE,
        midnight + timedelta(hours=1),
        mint_address=m_known,
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(500))
    ) as http:
        plan = await svc.plan_collection(
            T, [WikipediaAdapter(settings, http), DexScreenerAdapter(settings, http)]
        )
    assert [s.meme.id for s in plan[Source.WIKIPEDIA].subjects] == [yesterday.id]
    dex_subjects = plan[Source.DEXSCREENER].subjects
    assert [(s.meme.id, s.mints) for s in dex_subjects] == [(yesterday.id, (m_new,))]
