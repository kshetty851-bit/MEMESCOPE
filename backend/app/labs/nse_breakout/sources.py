"""The exchange archive, over one httpx client. Keyless.

NSE serves these as static files, but it refuses a default client agent
outright, so every request carries a browser user-agent and a referer. There
is no API key anywhere in this lab and no broker integration: Kite Connect's
token expires daily and an unattended run must not depend on it.

**yfinance is deliberately absent.** The brief asked for it, but Yahoo
answered 429 to every request from this host — including with a cookie-seeded
session and backoff — so both the historical backfill and the Nifty series
come from the exchange's own archive instead. One source, so there is no
cross-source adjustment mismatch, and no new dependency: `httpx` is what every
other lab here uses.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date
from types import TracebackType
from typing import Self

import httpx

from app.core.backoff import BackoffPolicy
from app.core.logging import get_logger
from app.labs.nse_breakout import config
from app.services.market.providers.rate_budget import CallBudget

logger = get_logger(__name__)

_RETRY_STATUSES = frozenset({429, 502, 503, 504})


class NotPublished(Exception):  # noqa: N818
    """The archive has no file for this date — a holiday, a weekend, or a day
    the exchange has not published yet. A FACT about the calendar, not a
    failure: it is recorded and never retried into the ground.

    Named without the `Error` suffix on purpose: it is control flow, and
    `except NotPublished` reads as the question it is asking.
    """


class NseArchive:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        budget: CallBudget | None = None,
        backoff: BackoffPolicy | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client
        self._owns_client = client is None
        # Capacity one, so the budget is a minimum SPACING rather than an
        # allowance that can be spent in a burst. A backfill walks ~620 files
        # and the archive is a static host; there is nothing to gain from
        # hammering it.
        self._budget = budget or CallBudget(
            1, window_seconds=60.0 / config.REQUESTS_PER_MINUTE)
        self._backoff = backoff or BackoffPolicy(
            initial_seconds=config.BACKOFF_INITIAL_SECONDS,
            max_seconds=config.BACKOFF_MAX_SECONDS)
        self._sleep = sleep
        self.requests = 0

    async def __aenter__(self) -> Self:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(config.HTTP_TIMEOUT_SECONDS),
                follow_redirects=True,
                headers={"user-agent": config.HTTP_USER_AGENT,
                         "referer": config.HTTP_REFERER,
                         "accept": "*/*"},
            )
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None,
                        exc: BaseException | None, tb: TracebackType | None) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get(self, url: str) -> bytes:
        if self._client is None:
            raise RuntimeError("NseArchive used outside `async with`")
        for attempt in range(1, config.MAX_ATTEMPTS + 1):
            while not self._budget.try_acquire(1):
                await self._sleep(0.25)
            response = await self._client.get(url)
            self.requests += 1
            # 404 is the calendar answering, not an error to retry.
            if response.status_code == 404:
                raise NotPublished(url)
            if response.status_code in _RETRY_STATUSES:
                retry_after = response.headers.get("Retry-After")
                floor = 0.0
                if retry_after:
                    try:
                        floor = max(0.0, float(retry_after))
                    except ValueError:
                        floor = 0.0
                # `Retry-After` is a FLOOR, never a ceiling: a host that says
                # "retry immediately" on a 429 is not telling you anything
                # actionable, and honouring it burns every attempt at once.
                delay = max(floor, self._backoff.delay_for(attempt))
                logger.warning("nse_http_retry", url=url, status=response.status_code,
                               attempt=attempt, delay_seconds=round(delay, 2))
                await self._sleep(min(delay, config.BACKOFF_MAX_SECONDS))
                continue
            response.raise_for_status()
            return response.content
        raise RuntimeError(f"nse: gave up on {url} after {config.MAX_ATTEMPTS} attempts")

    async def bhavcopy(self, day: date) -> bytes:
        """One trading day's ZIP. Raises `NotPublished` on a non-trading day."""
        return await self._get(
            config.BHAVCOPY_URL.format(yyyymmdd=day.strftime("%Y%m%d")))

    async def index_closes(self, day: date) -> str:
        """One trading day's index close file, as text."""
        payload = await self._get(
            config.INDEX_CLOSE_URL.format(ddmmyyyy=day.strftime("%d%m%Y")))
        return payload.decode("utf-8", "replace")
