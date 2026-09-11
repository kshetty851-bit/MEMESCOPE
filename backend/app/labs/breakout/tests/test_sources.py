"""The HTTP layer: pacing, the `Retry-After` floor, the per-tick call cap.

Every test drives the REAL `BreakoutSource` over a fake transport, so the
budget, the backoff and the retry loop are the ones that run in production.
"""

from __future__ import annotations

import httpx
import pytest

from app.labs.breakout import config
from app.labs.breakout.sources import (
    DEX,
    GECKO,
    BreakoutSource,
    BudgetExhaustedError,
    _retry_after,
)


class Clock:
    """A monotonic clock the test advances, so the token bucket refills
    without anything sleeping for real."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.t += seconds


def transport(*statuses: int, headers: dict[str, str] | None = None) -> httpx.MockTransport:
    """Answers with each status in turn, then 200 forever."""
    queue = list(statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        status = queue.pop(0) if queue else 200
        if status == 200:
            return httpx.Response(200, json={"data": {"attributes": {"ohlcv_list": []}}})
        return httpx.Response(status, headers=headers or {}, json={"errors": []})

    return httpx.MockTransport(handler)


def source(clock: Clock, *statuses: int, headers=None, **kw) -> BreakoutSource:
    return BreakoutSource(
        client=httpx.AsyncClient(transport=transport(*statuses, headers=headers)),
        gecko_budget=_budget(clock, config.GECKOTERMINAL_CALLS_PER_MINUTE),
        dex_budget=_budget(clock, config.DEXSCREENER_CALLS_PER_MINUTE),
        sleep=clock.sleep, **kw)


def _budget(clock: Clock, rate: int):
    from app.services.market.providers.rate_budget import CallBudget

    return CallBudget(1, window_seconds=config.call_spacing_seconds(rate), clock=clock)


# --- the Retry-After floor ----------------------------------------------------

def test_retry_after_reads_the_header_and_refuses_nonsense() -> None:
    def response(headers):
        return httpx.Response(429, headers=headers)

    assert _retry_after(response({"Retry-After": "12"})) == 12.0
    assert _retry_after(response({})) == 0.0
    assert _retry_after(response({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})) == 0.0
    assert _retry_after(response({"Retry-After": "-5"})) == 0.0, "never shortens a backoff"


async def test_retry_after_zero_does_not_defeat_the_backoff() -> None:
    """GeckoTerminal answers a 429 with `Retry-After: 0` and then refuses for
    about 35 seconds. Honouring that literally burned every attempt inside a
    millisecond — the header is a FLOOR, not a ceiling."""
    clock = Clock()
    async with source(clock, 429, 429, headers={"retry-after": "0"}) as src:
        await src.gecko_ohlcv("Pool", "day")
    assert clock.t > 0.0, "a 429 must cost real waiting even at Retry-After: 0"


async def test_a_longer_retry_after_wins_over_the_backoff() -> None:
    clock = Clock()
    async with source(clock, 429, headers={"retry-after": "45"}) as src:
        await src.gecko_ohlcv("Pool", "day")
    # 45 is capped at 60 by the sleep guard and dwarfs a 2-second base backoff.
    assert clock.t >= 45.0


async def test_a_call_gives_up_after_max_attempts_rather_than_forever() -> None:
    clock = Clock()
    async with source(clock, *([429] * 20)) as src:
        with pytest.raises(RuntimeError, match="gave up"):
            await src.gecko_ohlcv("Pool", "day")
    assert src.requests[GECKO] == config.MAX_ATTEMPTS


async def test_a_server_error_is_retried_like_a_429() -> None:
    clock = Clock()
    async with source(clock, 503) as src:
        await src.gecko_ohlcv("Pool", "day")
    assert src.requests[GECKO] == 2


async def test_a_client_error_is_not_retried() -> None:
    """A 404 is a dead pool, not a busy host. Retrying it four times spends
    the budget on a wrong answer."""
    clock = Clock()
    async with source(clock, 404) as src:
        with pytest.raises(httpx.HTTPStatusError):
            await src.gecko_ohlcv("Pool", "day")
    assert src.requests[GECKO] == 1


# --- pacing -------------------------------------------------------------------

async def test_calls_to_one_host_are_spaced_not_bursted() -> None:
    """Measured: a client inside GeckoTerminal's 30/min allowance was refused
    on its seventh call 0.7 seconds in. Capacity-one buckets make a burst
    impossible."""
    clock = Clock()
    spacing = config.call_spacing_seconds(config.GECKOTERMINAL_CALLS_PER_MINUTE)
    async with source(clock) as src:
        for _ in range(6):
            await src.gecko_ohlcv("Pool", "day")
    assert src.requests[GECKO] == 6
    assert clock.t >= 5 * spacing, f"six calls took {clock.t}s, under {5 * spacing}s"


async def test_the_two_hosts_do_not_spend_each_others_allowance() -> None:
    clock = Clock()
    async with source(clock) as src:
        await src.gecko_ohlcv("Pool", "day")
        await src.dex_boosts()
    assert src.requests == {GECKO: 1, DEX: 1}
    assert clock.t == 0.0, "the second host's first call waits on nobody"


# --- the per-tick cap ---------------------------------------------------------

async def test_the_tick_cap_stops_before_sending_rather_than_after() -> None:
    clock = Clock()
    async with source(clock, max_calls=3) as src:
        for _ in range(3):
            await src.gecko_ohlcv("Pool", "day")
        with pytest.raises(BudgetExhaustedError):
            await src.gecko_ohlcv("Pool", "day")
    assert src.requests[GECKO] == 3, "the refused call was never sent"


async def test_the_cap_counts_retries_too() -> None:
    """A 429 storm spends the tick's allowance on retries. That is the point:
    the tick stops and carries its queue instead of hammering."""
    clock = Clock()
    async with source(clock, 429, 429, max_calls=3) as src:
        await src.gecko_ohlcv("Pool", "day")   # 3 requests: 429, 429, 200
        assert src.total_requests == 3, "one logical call, three requests"
        with pytest.raises(BudgetExhaustedError):
            await src.gecko_ohlcv("Pool", "day")
    assert src.total_requests == 3


async def test_used_outside_its_context_manager_it_refuses_rather_than_crashes() -> None:
    with pytest.raises(RuntimeError, match="outside `async with`"):
        await BreakoutSource().gecko_ohlcv("Pool", "day")


# --- payload handling ---------------------------------------------------------

async def test_an_ohlcv_body_without_the_expected_shape_reads_as_no_bars() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"data": None})))
    async with BreakoutSource(client=client) as src:
        assert await src.gecko_ohlcv("Pool", "day") == []


async def test_a_dex_list_that_is_not_a_list_reads_as_empty() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"error": "nope"})))
    async with BreakoutSource(client=client) as src:
        assert await src.dex_boosts() == []
        assert await src.dex_profiles() == []


async def test_no_mints_means_no_request_at_all() -> None:
    async with BreakoutSource(client=httpx.AsyncClient()) as src:
        assert await src.dex_pairs([]) == []
    assert src.total_requests == 0


async def test_the_ohlcv_limit_is_clamped_to_the_apis_cap() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(200, json={"data": {"attributes": {"ohlcv_list": []}}})

    async with BreakoutSource(client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler))) as src:
        await src.gecko_ohlcv("Pool", "day", limit=5_000, before=123)
    assert seen["limit"] == str(config.OHLCV_LIMIT)
    assert seen["before_timestamp"] == "123"
