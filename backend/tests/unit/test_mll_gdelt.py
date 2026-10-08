"""GDELT adapter hardening: failure shapes, timestamp and query semantics.

GDELT's live behaviour has NOT been observed from this repository (the dev
container's network policy blocks it - see the fixtures README). The failure
fixtures are SYNTHETIC and pin our *classification*; the success shape is only
checked against a live capture, and that test skips until one exists. What
these tests protect is the Lab's first rule: whatever GDELT answers, absence
never becomes a zero and a failure is never mistaken for data.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.lifecycle_lab.adapters import GdeltAdapter, Subject
from app.lifecycle_lab.adapters.gdelt import (
    ERROR_SNIPPET_CHARS,
    FORWARD_BUCKET,
    MAX_FORWARD_TIMESPAN,
    MIN_FORWARD_TIMESPAN,
    bucket_window,
    forward_span,
    is_rate_limit_text,
    query_for,
    timespan_param,
)
from app.lifecycle_lab.domain import (
    AliasKind,
    DataClass,
    Meme,
    MemeAlias,
    SourceStatus,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 3, 12, 7, tzinfo=UTC)
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "lifecycle_lab" / "gdelt"
LIVE_FIXTURE = FIXTURES / "live_timelinevolraw.json"
LIVE_SKIP = (
    "live GDELT fixture not captured: network blocked in CI container; "
    "run scripts/mll_validate_sources.py"
)


def settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "FEATURE_LIFECYCLE_LAB_ENABLED": True,
        "MLL_GDELT_MIN_INTERVAL_SECONDS": 0,
    }
    base.update(overrides)
    return Settings(**base)


def subject(meme_id: str = "m1", *, name: str = "Pepe", query: str | None = None) -> Subject:
    meme = Meme(
        id=meme_id,
        slug=meme_id,
        display_name=name,
        tracking_started_at=NOW - timedelta(days=3),
        gdelt_query=query,
    )
    alias = MemeAlias(meme_id, "Rare Pepe", AliasKind.PHRASE, NOW - timedelta(days=3))
    return Subject(meme=meme, aliases=(alias,))


def body(points: list[tuple[str, int]]) -> dict[str, Any]:
    return {
        "query_details": {"title": "x"},
        "timeline": [
            {
                "series": "Article Count",
                "data": [{"date": d, "value": v, "norm": 1000} for d, v in points],
            }
        ],
    }


GOOD = body([("20261003T110000Z", 4), ("20261003T111500Z", 0), ("20261003T113000Z", 9)])


class Recorder:
    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._handler = handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))


async def no_sleep(_: float) -> None:
    return None


def load_fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text())
    return data


def fixture_response(fx: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        int(fx["status"]), headers=fx.get("headers") or {}, content=str(fx["body"]).encode()
    )


# ---------------------------------------------------------------- failure shapes


@pytest.mark.parametrize(
    ("name", "status", "reason"),
    [
        ("synthetic_empty_body.json", SourceStatus.UNAVAILABLE, "no_data_for_window"),
        ("synthetic_empty_object.json", SourceStatus.UNAVAILABLE, "no_data_for_window"),
        ("synthetic_text_rate_limit.json", SourceStatus.ERROR, "rate_limited"),
        ("synthetic_text_query_error.json", SourceStatus.ERROR, "gdelt_query_error"),
        ("synthetic_malformed_json.json", SourceStatus.ERROR, "unparseable"),
        ("synthetic_http_503.json", SourceStatus.ERROR, "http_503"),
        ("synthetic_http_429.json", SourceStatus.ERROR, "rate_limited"),
    ],
)
async def test_synthetic_failure_shapes_are_statuses_never_zero(
    name: str, status: SourceStatus, reason: str
) -> None:
    fx = load_fixture(name)
    assert fx["synthetic"] is True  # never confuse these with a live capture
    async with Recorder(lambda r: fixture_response(fx)).client() as client:
        result = await GdeltAdapter(settings(), client, sleep=no_sleep).collect(
            [subject()], now=NOW
        )
    assert (result.status, result.reason) == (status, reason)
    assert result.per_subject == {"m1": (status, reason)}
    assert result.observations == ()


@pytest.mark.parametrize("name", ["synthetic_text_rate_limit.json", "synthetic_http_429.json"])
async def test_any_rate_limit_stops_the_run_without_further_requests(name: str) -> None:
    """GDELT answers throttling with HTTP 200 + text as well as 429; both must
    stop the loop - continuing would only dig the hole deeper."""
    fx = load_fixture(name)
    rec = Recorder(lambda r: fixture_response(fx))
    async with rec.client() as client:
        result = await GdeltAdapter(settings(), client, sleep=no_sleep).collect(
            [subject("a", name="A"), subject("b", name="B"), subject("c", name="C")], now=NOW
        )
    assert len(rec.requests) == 1
    assert result.per_subject == dict.fromkeys(
        ["a", "b", "c"], (SourceStatus.ERROR, "rate_limited")
    )


async def test_query_error_keeps_the_first_200_characters_for_the_operator() -> None:
    text = "Your search contained an invalid operator: " + "x" * 400
    async with Recorder(lambda r: httpx.Response(200, text=text)).client() as client:
        result = await GdeltAdapter(settings(), client, sleep=no_sleep).collect(
            [subject()], now=NOW
        )
    assert result.reason == "gdelt_query_error"
    head = result.per_subject_detail["m1"]["body_head"]
    assert head == text[:ERROR_SNIPPET_CHARS] and len(head) == 200


async def test_query_error_does_not_stop_other_queries() -> None:
    """A bad query is that meme's problem, not GDELT's: the run continues."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["query"] == '"A"':
            return httpx.Response(200, text="The specified phrase is too short.")
        return httpx.Response(200, json=GOOD)

    rec = Recorder(handler)
    async with rec.client() as client:
        result = await GdeltAdapter(settings(), client, sleep=no_sleep).collect(
            [subject("a", name="A"), subject("b", name="B")], now=NOW
        )
    assert len(rec.requests) == 2
    assert result.per_subject["a"] == (SourceStatus.ERROR, "gdelt_query_error")
    assert result.per_subject["b"] == (SourceStatus.AVAILABLE, None)
    assert (result.status, result.reason) == (SourceStatus.PARTIAL, "partial_subjects")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Please limit requests to one every 5 seconds", True),
        ("Too Many Requests", True),
        ("rate limit exceeded", True),
        ("Your query exceeded the maximum length limit.", False),  # no "request"
        ("The specified phrase is too short.", False),
    ],
)
def test_rate_limit_text_needs_more_than_the_word_limit(text: str, expected: bool) -> None:
    assert is_rate_limit_text(text) is expected


@pytest.mark.parametrize(
    ("make", "reason"),
    [
        (lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=r)), "timeout"),
        (
            lambda r: (_ for _ in ()).throw(httpx.ConnectError("down", request=r)),
            "network_error",
        ),
        (lambda r: httpx.Response(500), "http_500"),
        (lambda r: httpx.Response(502, text="Bad Gateway"), "http_502"),
        (lambda r: httpx.Response(301, headers={"location": "https://x"}), "http_301"),
    ],
)
async def test_transport_and_http_failures(
    make: Callable[[httpx.Request], httpx.Response], reason: str
) -> None:
    async with Recorder(make).client() as client:
        result = await GdeltAdapter(settings(), client, sleep=no_sleep).collect(
            [subject()], now=NOW
        )
    assert (result.status, result.reason) == (SourceStatus.ERROR, reason)
    assert result.observations == ()


async def test_a_real_zero_is_kept_and_a_bom_does_not_break_parsing() -> None:
    raw = "﻿" + json.dumps(GOOD)
    async with Recorder(lambda r: httpx.Response(200, content=raw.encode())).client() as c:
        result = await GdeltAdapter(settings(), c, sleep=no_sleep).collect(
            [subject()], now=NOW
        )
    assert result.status is SourceStatus.AVAILABLE
    assert [o.raw_value for o in result.observations] == [Decimal(4), Decimal(0), Decimal(9)]


# ---------------------------------------------------------------- timestamps


def test_date_labels_the_bucket_start_unverified() -> None:
    """UNVERIFIED - from documentation/memory: ``date`` is the bucket START.
    Pinned so a change of interpretation is a deliberate, reviewed edit."""
    stamp = datetime(2026, 10, 3, 11, 0, tzinfo=UTC)
    assert bucket_window(stamp, FORWARD_BUCKET) == (stamp, stamp + timedelta(minutes=15))


async def test_observed_at_is_bucket_end_and_open_buckets_are_withheld() -> None:
    """A bucket is visible only once it has closed: observed_at = start +
    width <= now. The bucket starting 12:00 closes 12:15 > NOW (12:07)."""
    data = body([("20261003T113000Z", 1), ("20261003T114500Z", 2), ("20261003T120000Z", 3)])
    async with Recorder(lambda r: httpx.Response(200, json=data)).client() as client:
        result = await GdeltAdapter(settings(), client, sleep=no_sleep).collect(
            [subject()], now=NOW
        )
    assert [
        (o.source_timestamp, o.window_start, o.observed_at) for o in result.observations
    ] == [
        (
            datetime(2026, 10, 3, 11, 30, tzinfo=UTC),
            datetime(2026, 10, 3, 11, 30, tzinfo=UTC),
            datetime(2026, 10, 3, 11, 45, tzinfo=UTC),
        ),
        (
            datetime(2026, 10, 3, 11, 45, tzinfo=UTC),
            datetime(2026, 10, 3, 11, 45, tzinfo=UTC),
            datetime(2026, 10, 3, 12, 0, tzinfo=UTC),
        ),
    ]
    assert all(o.observed_at <= NOW and o.retrieved_at == NOW for o in result.observations)


# ---------------------------------------------------------------- query semantics


def test_query_is_the_curated_query_or_the_quoted_display_name() -> None:
    assert query_for(subject(name='Pe"pe')) == '"Pepe"'
    assert query_for(subject(query=' "pepe frog" sourcelang:eng ')) == (
        '"pepe frog" sourcelang:eng'
    )


async def test_aliases_are_not_ored_into_the_query() -> None:
    """A timeline cannot attribute OR'd terms, so an alias in the query would
    silently merge two populations into one count."""
    rec = Recorder(lambda r: httpx.Response(200, json=GOOD))
    async with rec.client() as client:
        await GdeltAdapter(settings(), client, sleep=no_sleep).collect([subject()], now=NOW)
    assert rec.requests[0].url.params["query"] == '"Pepe"'
    assert " OR " not in rec.requests[0].url.params["query"]


async def test_identical_queries_share_one_request_and_each_meme_gets_its_rows() -> None:
    rec = Recorder(lambda r: httpx.Response(200, json=GOOD))
    a, b = subject("a", name="Pepe"), subject("b", name="Pepe")
    c = subject("c", name="Doge")
    async with rec.client() as client:
        result = await GdeltAdapter(settings(), client, sleep=no_sleep).collect(
            [a, b, c], now=NOW
        )
    assert [r.url.params["query"] for r in rec.requests] == ['"Pepe"', '"Doge"']
    assert result.detail == {"requests": 2, "subjects": 3, "shared_queries": 1}
    by_meme: dict[str | None, list[Decimal]] = {}
    for o in result.observations:
        by_meme.setdefault(o.meme_id, []).append(o.raw_value)
    assert by_meme["a"] == by_meme["b"] == by_meme["c"] == [Decimal(4), Decimal(0), Decimal(9)]
    assert {o.dedupe_key() for o in result.observations if o.meme_id == "a"}.isdisjoint(
        {o.dedupe_key() for o in result.observations if o.meme_id == "b"}
    )


async def test_a_shared_query_failure_is_recorded_for_every_meme_sharing_it() -> None:
    rec = Recorder(lambda r: httpx.Response(200, text="The specified phrase is too short."))
    async with rec.client() as client:
        result = await GdeltAdapter(settings(), client, sleep=no_sleep).collect(
            [subject("a"), subject("b")], now=NOW
        )
    assert len(rec.requests) == 1
    assert result.per_subject == dict.fromkeys(
        ["a", "b"], (SourceStatus.ERROR, "gdelt_query_error")
    )
    assert set(result.per_subject_detail) == {"a", "b"}


# ---------------------------------------------------------------- scheduled spans


def test_forward_span_covers_the_gap_plus_one_bucket_clamped() -> None:
    assert forward_span(None, NOW) == MAX_FORWARD_TIMESPAN
    assert forward_span(NOW - timedelta(minutes=15), NOW) == MIN_FORWARD_TIMESPAN
    assert forward_span(NOW - timedelta(hours=6), NOW) == timedelta(hours=6, minutes=15)
    assert forward_span(NOW - timedelta(days=5), NOW) == MAX_FORWARD_TIMESPAN


@pytest.mark.parametrize(
    ("span", "param"),
    [
        (timedelta(hours=2), "2h"),
        (timedelta(hours=6, minutes=15), "7h"),  # rounded UP: the gap stays covered
        (timedelta(hours=24), "24h"),
        (timedelta(minutes=1), "1h"),
    ],
)
def test_timespan_param_rounds_up_to_whole_hours(span: timedelta, param: str) -> None:
    assert timespan_param(span) == param


async def test_unscheduled_runs_keep_the_fixed_six_hour_span() -> None:
    rec = Recorder(lambda r: httpx.Response(200, json=GOOD))
    async with rec.client() as client:
        await GdeltAdapter(settings(), client, sleep=no_sleep).collect([subject()], now=NOW)
    assert rec.requests[0].url.params["timespan"] == "6h"


async def test_scheduled_span_is_the_largest_gap_in_a_shared_query() -> None:
    rec = Recorder(lambda r: httpx.Response(200, json=GOOD))
    async with rec.client() as client:
        adapter = GdeltAdapter(settings(), client, sleep=no_sleep)
        adapter.set_schedule(
            last_success={
                "a": NOW - timedelta(minutes=20),
                "b": NOW - timedelta(hours=3),
                "c": NOW - timedelta(minutes=30),
            }
        )
        await adapter.collect([subject("a"), subject("b"), subject("c", name="Doge")], now=NOW)
    spans = {r.url.params["query"]: r.url.params["timespan"] for r in rec.requests}
    assert spans == {'"Pepe"': "4h", '"Doge"': "2h"}  # 3h15m -> 4h; 45m -> floor 2h


async def test_never_collected_meme_asks_for_the_cap() -> None:
    rec = Recorder(lambda r: httpx.Response(200, json=GOOD))
    async with rec.client() as client:
        adapter = GdeltAdapter(settings(), client, sleep=no_sleep)
        adapter.set_schedule(last_success={})
        await adapter.collect([subject()], now=NOW)
    assert rec.requests[0].url.params["timespan"] == "24h"


async def test_deadline_defers_instead_of_starting_a_request_that_could_overrun() -> None:
    clock = {"t": 0.0}

    def slow(request: httpx.Request) -> httpx.Response:
        clock["t"] += 10.0  # the first answer takes 10 s
        return httpx.Response(200, json=GOOD)

    rec = Recorder(slow)
    async with rec.client() as client:
        adapter = GdeltAdapter(
            settings(MLL_GDELT_MIN_INTERVAL_SECONDS=6),
            client,
            sleep=no_sleep,
            clock=lambda: clock["t"],
        )
        # A request may start only if spacing (6 s) + timeout (20 s) fits:
        # at t=0 it does (26 <= 30); at t=10 it does not (36 > 30).
        adapter.set_schedule(last_success={}, deadline=30.0)
        result = await adapter.collect(
            [subject("a", name="A"), subject("b", name="B")], now=NOW
        )
    assert len(rec.requests) == 1
    assert result.per_subject["a"] == (SourceStatus.AVAILABLE, None)
    assert result.per_subject["b"] == (SourceStatus.UNAVAILABLE, "deferred_budget")
    assert not any(o.meme_id == "b" for o in result.observations)


# ---------------------------------------------------------------- live shape


def _live() -> dict[str, Any]:
    if not LIVE_FIXTURE.exists():
        pytest.skip(LIVE_SKIP)
    data: dict[str, Any] = json.loads(LIVE_FIXTURE.read_text())
    return data


async def test_live_fixture_parses_into_closed_15_minute_buckets() -> None:
    """The one test that speaks for GDELT's REAL shape. If it fails after a
    capture, the adapter's documented assumptions were wrong: fix the adapter
    (and the UNVERIFIED notes), never the fixture."""
    fx = _live()
    assert fx.get("synthetic") is not True
    now = datetime.fromisoformat(fx["retrieved_at"])
    live = replace(subject(), meme=replace(subject().meme, gdelt_query=fx["query"]))
    async with Recorder(lambda r: fixture_response(fx)).client() as client:
        result = await GdeltAdapter(settings(), client, sleep=no_sleep).collect(
            [live], now=now
        )
    assert result.status in (SourceStatus.AVAILABLE, SourceStatus.UNAVAILABLE), result.reason
    if result.status is SourceStatus.UNAVAILABLE:
        assert result.reason == "no_data_for_window"
        return
    obs = sorted(result.observations, key=lambda o: o.observed_at)
    assert obs and all(o.data_class is DataClass.FORWARD for o in obs)
    assert all(o.window_end - o.window_start == FORWARD_BUCKET for o in obs if o.window_start)
    assert all(o.observed_at <= now and o.raw_value >= 0 for o in obs)
    assert all(b.window_start == a.window_end for a, b in pairwise(obs))


def test_live_fixture_is_raw_and_attributable() -> None:
    fx = _live()
    assert fx["status"] == 200 and "gdeltproject.org" in fx["url"]
    assert isinstance(json.loads(fx["body"]), dict)
    datetime.fromisoformat(fx["retrieved_at"])
