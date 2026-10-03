"""Adapter contract and the HTTP discipline every adapter shares.

An adapter turns one external source into ``Observation`` rows (or
``MarketPoint`` rows) plus an explicit statement of how the attempt went. The
statement is the point: a source that did not answer is ``UNAVAILABLE`` /
``ERROR`` / ``DISABLED`` with a reason, and is **never** converted into a
zero-valued observation. Zero is a measurement ("the source answered and the
count was 0"); absence is a status.

Reason vocabulary (stable codes; prose is rendered elsewhere):

  disabled_by_config, lab_disabled, pumpfun_social_disabled,
  not_implemented_no_api_plan            -> DISABLED
  no_subjects, no_wikipedia_title, no_article, no_data_for_window,
  no_pools, no_ohlcv, not_listed, poller_never_ran,
  bucket_size_unknown, deferred_budget   -> UNAVAILABLE
  poller_stale                           -> STALE
  partial_subjects, truncated_page       -> PARTIAL
  rate_limited, timeout, network_error, unparseable, irregular_buckets,
  unauthorized, http_<code>              -> ERROR

Rate limits are respected, not worked around: a 429 ends the run for that
source (remaining subjects are ``ERROR rate_limited``) and the next scheduled
run tries again. There is no retry loop.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

import httpx

from app.lifecycle_lab.domain import (
    DataClass,
    MarketPoint,
    Meme,
    MemeAlias,
    Observation,
    Source,
    SourceStatus,
)

#: Per-request ceiling. The client is injected, so this travels per call.
REQUEST_TIMEOUT_SECONDS = 20.0

SleepFn = Callable[[float], Awaitable[None]]
ClockFn = Callable[[], float]


@dataclass(frozen=True, slots=True)
class Subject:
    """What an adapter is asked about: a meme, its aliases, its linked mints."""

    meme: Meme
    aliases: tuple[MemeAlias, ...] = ()
    mints: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AdapterResult:
    source: Source
    status: SourceStatus
    reason: str | None
    observations: tuple[Observation, ...] = ()
    #: Key is a meme_id (meme-scoped sources) or a mint (token-scoped sources).
    per_subject: dict[str, tuple[SourceStatus, str | None]] = field(default_factory=dict)
    market_points: tuple[MarketPoint, ...] = ()
    #: mint -> profile facts (DexScreener).
    profiles: dict[str, dict[str, Any]] = field(default_factory=dict)


@runtime_checkable
class SourceAdapter(Protocol):
    source: Source
    #: The class of data this adapter produces when run on a schedule.
    data_class: DataClass

    def enabled(self) -> tuple[bool, str | None]: ...

    async def collect(
        self, subjects: Sequence[Subject], *, now: datetime
    ) -> AdapterResult: ...


class AdapterError(Exception):
    """A failed attempt, carrying the reason code recorded on the run."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class MinIntervalLimiter:
    """Spaces calls at least ``min_interval_seconds`` apart. Never skips a call;
    it waits. Clock and sleep are injected so tests do not sleep."""

    def __init__(
        self,
        min_interval_seconds: float,
        *,
        sleep: SleepFn | None = None,
        clock: ClockFn | None = None,
    ) -> None:
        self._interval = max(0.0, float(min_interval_seconds))
        self._sleep: SleepFn = sleep or asyncio.sleep
        self._clock: ClockFn = clock or time.monotonic
        self._last: float | None = None

    async def wait(self) -> None:
        if self._last is not None:
            remaining = self._last + self._interval - self._clock()
            if remaining > 0:
                await self._sleep(remaining)
        self._last = self._clock()


async def http_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    data: Mapping[str, Any] | None = None,
    auth: tuple[str, str] | None = None,
) -> httpx.Response:
    """One request, no retries. 429 and transport failures raise ``AdapterError``;
    other statuses are returned for the caller to interpret (404 is often data)."""
    try:
        response = await client.request(
            method,
            url,
            params=params,
            headers=headers,
            data=data,
            auth=auth,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException as exc:
        raise AdapterError("timeout") from exc
    except httpx.HTTPError as exc:
        raise AdapterError("network_error") from exc
    if response.status_code == 429:
        raise AdapterError("rate_limited")
    return response


async def http_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> httpx.Response:
    return await http_request(client, "GET", url, params=params, headers=headers)


def raise_for_status(response: httpx.Response) -> None:
    code = response.status_code
    if code in (401, 403):
        raise AdapterError("unauthorized" if code == 401 else f"http_{code}")
    if code >= 400:
        raise AdapterError(f"http_{code}")


def parse_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise AdapterError("unparseable") from exc


def request_url(response: httpx.Response) -> str:
    return str(response.request.url)


def aggregate_status(
    per_subject: Mapping[str, tuple[SourceStatus, str | None]],
) -> tuple[SourceStatus, str | None]:
    """Fold per-subject outcomes into the source-level run status."""
    if not per_subject:
        return SourceStatus.UNAVAILABLE, "no_subjects"
    values = list(per_subject.values())
    statuses = {s for s, _ in values}
    if statuses == {SourceStatus.AVAILABLE}:
        return SourceStatus.AVAILABLE, None
    if SourceStatus.AVAILABLE in statuses or SourceStatus.PARTIAL in statuses:
        return SourceStatus.PARTIAL, "partial_subjects"
    for preferred in (SourceStatus.ERROR, SourceStatus.STALE, SourceStatus.UNAVAILABLE):
        if preferred in statuses:
            return preferred, next(r for s, r in values if s == preferred)
    status, reason = values[0]
    return status, reason


def error_result(
    source: Source, reason: str, subjects: Sequence[Subject], *, by_mint: bool = False
) -> AdapterResult:
    """Every subject failed for one shared reason."""
    keys = [m for s in subjects for m in s.mints] if by_mint else [s.meme.id for s in subjects]
    per: dict[str, tuple[SourceStatus, str | None]] = dict.fromkeys(
        dict.fromkeys(keys), (SourceStatus.ERROR, reason)
    )
    return AdapterResult(source, SourceStatus.ERROR, reason, per_subject=per)


def disabled_result(source: Source, reason: str) -> AdapterResult:
    """No network, no observations: a switched-off source is a status."""
    return AdapterResult(source, SourceStatus.DISABLED, reason)
