"""GDELT DOC 2.0 news-volume timelines.

This is **news coverage, not social attention**: articles that mention the
query, as ingested by GDELT. It is a different population from pump.fun replies
or Reddit and must not be summed with them as if it were.

VERIFICATION STATUS (2026-10-03). Nothing below has been observed against the
live API from this codebase: the development container's network policy blocks
``api.gdeltproject.org`` (the one attempted request ended ``network_error``).
Every statement about GDELT's behaviour is **UNVERIFIED — from
documentation/memory** unless a test loads the live fixture
``tests/fixtures/lifecycle_lab/gdelt/live_timelinevolraw.json``, which
``scripts/mll_validate_sources.py`` writes when run with network access. The
parser is therefore written to fail loudly (ERROR with a reason) on any shape
it does not recognise, never to guess.

Request (UNVERIFIED — from documentation/memory)::

    GET https://api.gdeltproject.org/api/v2/doc/doc
        ?query=<q>&mode=timelinevolraw&format=json&timespan=<N>h
        (or startdatetime / enddatetime as YYYYMMDDHHMMSS for backfill)

``timelinevolraw`` is raw article counts (``timelinevol`` is a share of all
coverage, which is not a count and is not used).

Query construction (verified by tests, i.e. this is what we SEND):
  * ``meme.gdelt_query`` verbatim when curated (operators may add GDELT
    operators such as ``sourcelang:eng``), else the display name as one quoted
    phrase: ``"<display name>"`` with inner double quotes removed.
  * Aliases are NOT OR'd into the query. A timeline is one series for the whole
    query; GDELT cannot say which OR'd term matched, so OR-ing two memes into
    one request cannot yield per-meme counts. Batching memes is impossible.
  * Identical query strings within one pass ARE shared: one request, the
    timeline fanned out to every meme with that query (each gets its own rows
    with its own ``meme_id``). This is pure request de-duplication.

Response shape relied on (UNVERIFIED — from documentation/memory)::

    {
        "query_details": {...},
        "timeline": [
            {
                "series": "Article Count",
                "data": [{"date": "20240101T001500Z", "value": 12, "norm": 456}],
            }
        ],
    }

Failure shapes (UNVERIFIED — from documentation/memory). GDELT is known to
answer rate limiting and query errors with **HTTP 200 and a plain-text body**
rather than JSON or a 4xx:
  * text mentioning a request limit ("Please limit requests to one every 5
    seconds...")                         -> ERROR ``rate_limited`` (stops the run, like 429)
  * any other non-JSON text (phrase too short, invalid query, HTML)
                                         -> ERROR ``gdelt_query_error``; the first
                                            200 characters go to the run's detail
  * body starting like JSON but not JSON -> ERROR ``unparseable``
  * empty body, ``{}``, or no timeline   -> UNAVAILABLE ``no_data_for_window``
  * HTTP 429                             -> ERROR ``rate_limited``
  * HTTP >= 500 (or any other non-2xx)   -> ERROR ``http_<code>``
  * timeout / transport failure          -> ERROR ``timeout`` / ``network_error``

Timestamp semantics (UNVERIFIED — from documentation/memory): ``date`` is
treated as the bucket's START (``bucket_window``). If it is in fact the end,
every window is labelled one bucket too *late* - conservative for look-ahead,
never early. ``observed_at`` is the bucket end; only closed buckets
(``end <= now``) are emitted.

Bucket size (UNVERIFIED — from documentation/memory: 15 minutes for short
spans, coarser for long ones) is **detected from the timestamps**, never
assumed. Irregular spacing is ``ERROR irregular_buckets``; a single point cannot
reveal its width and is ``UNAVAILABLE bucket_size_unknown``. FORWARD runs
additionally require exactly ``FORWARD_BUCKET`` (15 min): a coarser answer
would put hourly and 15-minute windows into the same series, which the
attention engine would double count, so it is ``ERROR unexpected_bucket_size``
(detail carries the width) rather than stored.

An empty / valueless body is the source returning nothing, which is not a count
of zero. A well-formed timeline containing ``value: 0`` is a real zero.

Recent buckets are revised as GDELT ingests late articles. First write wins:
what we keep is what was known when we asked.

GDELT asks callers to stay under ~1 request / 5 s; requests are spaced by
``MLL_GDELT_MIN_INTERVAL_SECONDS`` and a scheduled pass is bounded by a request
budget and a wall-clock deadline (``set_schedule``).
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from typing import Any

import httpx

from app.lifecycle_lab.adapters.base import (
    REQUEST_TIMEOUT_SECONDS,
    AdapterError,
    AdapterResult,
    ClockFn,
    MinIntervalLimiter,
    SleepFn,
    Subject,
    aggregate_status,
    disabled_result,
    http_get,
    raise_for_status,
    request_url,
)
from app.lifecycle_lab.domain import (
    DataClass,
    Metric,
    Observation,
    Source,
    SourceStatus,
    ValueKind,
)

URL = "https://api.gdeltproject.org/api/v2/doc/doc"
#: Span asked for by an unscheduled forward run (and the pre-scheduler default).
FORWARD_TIMESPAN = timedelta(hours=6)
#: Scheduled runs ask for the gap since the meme's last success plus one
#: bucket of overlap (dedupe makes the overlap free), within these bounds. The
#: upper bound is where 15-minute resolution is assumed to still hold
#: (UNVERIFIED — from documentation/memory; ``FORWARD_BUCKET`` turns a wrong
#: assumption into a loud ERROR, and the validation script asks for exactly
#: this span so an operator can check it).
MIN_FORWARD_TIMESPAN = timedelta(hours=2)
MAX_FORWARD_TIMESPAN = timedelta(hours=24)
FORWARD_BUCKET = timedelta(minutes=15)
BUCKET_OVERLAP = FORWARD_BUCKET
#: News keyword match: the article may be about something else entirely.
CONFIDENCE = Decimal("0.7")
#: How much of a plain-text error body is kept on the run.
ERROR_SNIPPET_CHARS = 200


# --------------------------------------------------------------------------
# Pure helpers (query, window, timestamp and body semantics)
# --------------------------------------------------------------------------


def query_for(subject: Subject) -> str:
    """The exact query string sent for ``subject``. See the module docstring."""
    q = (subject.meme.gdelt_query or "").strip()
    if q:
        return q
    return '"' + subject.meme.display_name.replace('"', "").strip() + '"'


def forward_span(last_success_at: datetime | None, now: datetime) -> timedelta:
    """The span a scheduled forward request must cover: the gap since the last
    success plus one bucket of overlap, clamped. Never collected (or not within
    the scheduler's lookback) asks for the maximum."""
    if last_success_at is None:
        return MAX_FORWARD_TIMESPAN
    span = now - last_success_at + BUCKET_OVERLAP
    return min(max(span, MIN_FORWARD_TIMESPAN), MAX_FORWARD_TIMESPAN)


def timespan_param(span: timedelta) -> str:
    """``timespan`` in whole hours, rounded up so the span is always covered.
    (``<N>h`` syntax: UNVERIFIED — from documentation/memory.)"""
    hours = max(1, math.ceil(span.total_seconds() / 3600))
    return f"{hours}h"


def bucket_window(stamp: datetime, width: timedelta) -> tuple[datetime, datetime]:
    """``date`` labels the bucket START (UNVERIFIED — from documentation/memory).

    Treating it as the start makes ``observed_at = start + width``. Were it the
    end, every row would be visible one bucket later than it could have been:
    a cost in timeliness, never a look-ahead.
    """
    return stamp, stamp + width


def _parse_date(raw: Any) -> datetime | None:
    text = str(raw).strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _fmt(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%d%H%M%S")


def _snippet(text: str) -> dict[str, Any]:
    return {"body_head": text[:ERROR_SNIPPET_CHARS]}


def is_rate_limit_text(text: str) -> bool:
    """A plain-text body asking us to slow down. Both words are required so a
    query error that merely mentions a "limit" (e.g. a length limit) does not
    stop the whole run."""
    t = text.lower()
    return ("limit" in t and "request" in t) or "rate limit" in t or "too many requests" in t


def decode_body(response: httpx.Response) -> dict[str, Any] | None:
    """The JSON object GDELT answered with, or ``None`` for "nothing for this
    window". Raises ``AdapterError`` for every failure shape (module docstring).
    """
    code = response.status_code
    raise_for_status(response)  # 401/403/4xx/5xx -> http_<code> / unauthorized
    if not 200 <= code < 300:
        raise AdapterError(f"http_{code}")
    text = response.text.lstrip("﻿").strip()
    if not text:
        return None
    if text[0] not in "{[":
        if is_rate_limit_text(text):
            raise AdapterError("rate_limited", _snippet(text))
        raise AdapterError("gdelt_query_error", _snippet(text))
    try:
        body = json.loads(text)
    except ValueError:
        raise AdapterError("unparseable", _snippet(text)) from None
    if not isinstance(body, dict):
        raise AdapterError("unparseable")
    return body or None


@dataclass(frozen=True, slots=True)
class Timeline:
    """A parsed, validated timeline: ascending points, one detected width."""

    points: tuple[tuple[datetime, Decimal], ...]
    width: timedelta
    series: Any


def parse_timeline(body: dict[str, Any] | None) -> Timeline | str:
    """A ``Timeline``, or the UNAVAILABLE reason when GDELT had nothing.
    Raises ``AdapterError`` for any shape it does not recognise."""
    if body is None:
        return "no_data_for_window"
    timeline = body.get("timeline")
    if not timeline:
        return "no_data_for_window"
    if not isinstance(timeline, list) or not isinstance(timeline[0], dict):
        raise AdapterError("unparseable")
    series = timeline[0]
    data = series.get("data")
    if not isinstance(data, list):
        raise AdapterError("unparseable")

    points: list[tuple[datetime, Decimal]] = []
    for row in data:
        if not isinstance(row, dict):
            raise AdapterError("unparseable")
        stamp = _parse_date(row.get("date"))
        try:
            value = Decimal(str(row.get("value")))
        except InvalidOperation:
            raise AdapterError("unparseable") from None
        if stamp is None or not value.is_finite() or value < 0:
            raise AdapterError("unparseable")
        points.append((stamp, value))
    if not points:
        return "no_data_for_window"
    points.sort(key=lambda p: p[0])
    if len(points) < 2:
        return "bucket_size_unknown"
    deltas = {b[0] - a[0] for a, b in pairwise(points)}
    if len(deltas) != 1 or next(iter(deltas)) <= timedelta(0):
        raise AdapterError("irregular_buckets")
    return Timeline(tuple(points), next(iter(deltas)), series.get("series"))


# --------------------------------------------------------------------------
# Adapter
# --------------------------------------------------------------------------


class GdeltAdapter:
    source: Source = Source.GDELT
    data_class: DataClass = DataClass.FORWARD

    def __init__(
        self,
        settings: Any,
        client: httpx.AsyncClient,
        *,
        sleep: SleepFn | None = None,
        clock: ClockFn | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._clock: ClockFn = clock or time.monotonic
        self._limiter = MinIntervalLimiter(
            float(settings.MLL_GDELT_MIN_INTERVAL_SECONDS), sleep=sleep, clock=clock
        )
        self._scheduled = False
        self._last_success: dict[str, datetime | None] = {}
        self._deadline: float | None = None

    def enabled(self) -> tuple[bool, str | None]:
        if not self._settings.FEATURE_LIFECYCLE_LAB_ENABLED:
            return False, "lab_disabled"
        if not self._settings.MLL_GDELT_ENABLED:
            return False, "disabled_by_config"
        return True, None

    def set_schedule(
        self,
        *,
        last_success: Mapping[str, datetime | None],
        deadline: float | None = None,
    ) -> None:
        """Scheduled mode for the next ``collect``: each meme's span covers the
        gap since its last success (``forward_span``), and no request starts
        once ``deadline`` (on this adapter's monotonic clock) could be overrun -
        the subjects left are ``UNAVAILABLE deferred_budget``, never dropped."""
        self._scheduled = True
        self._last_success = dict(last_success)
        self._deadline = deadline

    def _past_deadline(self) -> bool:
        if self._deadline is None:
            return False
        spacing = float(self._settings.MLL_GDELT_MIN_INTERVAL_SECONDS)
        return self._clock() + spacing + REQUEST_TIMEOUT_SECONDS > self._deadline

    async def _fetch(self, query: str, window: dict[str, str]) -> tuple[Timeline | str, str]:
        await self._limiter.wait()
        response = await http_get(
            self._client,
            URL,
            params={"query": query, "mode": "timelinevolraw", "format": "json", **window},
        )
        return parse_timeline(decode_body(response)), request_url(response)

    @staticmethod
    def _observations(
        subject: Subject,
        query: str,
        timeline: Timeline,
        url: str,
        *,
        data_class: DataClass,
        now: datetime,
    ) -> list[Observation]:
        out: list[Observation] = []
        for stamp, value in timeline.points:
            start, end = bucket_window(stamp, timeline.width)
            if end > now:
                continue  # bucket still filling
            out.append(
                Observation(
                    source=Source.GDELT,
                    metric=Metric.MENTIONS,
                    value_kind=ValueKind.WINDOW_COUNT,
                    data_class=data_class,
                    source_timestamp=start,
                    observed_at=end,
                    retrieved_at=now,
                    raw_value=value,
                    meme_id=subject.meme.id,
                    window_start=start,
                    window_end=end,
                    query=query,
                    source_url=url,
                    confidence=CONFIDENCE,
                    raw_payload={
                        "bucket_seconds": int(timeline.width.total_seconds()),
                        "series": timeline.series,
                        "coverage": "news",
                    },
                )
            )
        return out

    async def _run(
        self,
        subjects: Sequence[Subject],
        window_for: Callable[[Sequence[Subject]], dict[str, str]],
        *,
        data_class: DataClass,
        now: datetime,
    ) -> AdapterResult:
        # One request per distinct query string, in first-seen order.
        groups: dict[str, list[Subject]] = {}
        for subject in subjects:
            groups.setdefault(query_for(subject), []).append(subject)

        per: dict[str, tuple[SourceStatus, str | None]] = {}
        per_detail: dict[str, dict[str, Any]] = {}
        observations: list[Observation] = []
        blocked: str | None = None
        requests = 0
        for query, members in groups.items():
            keys = [m.meme.id for m in members]
            if blocked is not None:
                per.update(dict.fromkeys(keys, (SourceStatus.ERROR, blocked)))
                continue
            if self._past_deadline():
                per.update(dict.fromkeys(keys, (SourceStatus.UNAVAILABLE, "deferred_budget")))
                continue
            requests += 1
            try:
                parsed, url = await self._fetch(query, window_for(members))
                if (
                    isinstance(parsed, Timeline)
                    and data_class is DataClass.FORWARD
                    and parsed.width != FORWARD_BUCKET
                ):
                    raise AdapterError(
                        "unexpected_bucket_size",
                        {"bucket_seconds": int(parsed.width.total_seconds())},
                    )
            except AdapterError as exc:
                per.update(dict.fromkeys(keys, (SourceStatus.ERROR, exc.reason)))
                if exc.detail:
                    per_detail.update({k: dict(exc.detail) for k in keys})
                if exc.reason == "rate_limited":
                    blocked = exc.reason
                continue
            for member in members:
                if isinstance(parsed, str):
                    per[member.meme.id] = (SourceStatus.UNAVAILABLE, parsed)
                    continue
                rows = self._observations(
                    member, query, parsed, url, data_class=data_class, now=now
                )
                if rows:
                    per[member.meme.id] = (SourceStatus.AVAILABLE, None)
                    observations.extend(rows)
                else:
                    per[member.meme.id] = (SourceStatus.UNAVAILABLE, "no_data_for_window")
        status, reason = aggregate_status(per)
        detail = {
            "requests": requests,
            "subjects": len(subjects),
            "shared_queries": sum(1 for m in groups.values() if len(m) > 1),
        }
        return AdapterResult(
            self.source,
            status,
            reason,
            tuple(observations),
            per,
            detail=detail,
            per_subject_detail=per_detail,
        )

    def _forward_window(self, members: Sequence[Subject], now: datetime) -> dict[str, str]:
        if not self._scheduled:
            return {"timespan": timespan_param(FORWARD_TIMESPAN)}
        span = max(forward_span(self._last_success.get(m.meme.id), now) for m in members)
        return {"timespan": timespan_param(span)}

    async def collect(self, subjects: Sequence[Subject], *, now: datetime) -> AdapterResult:
        ok, why = self.enabled()
        if not ok:
            return disabled_result(self.source, why or "disabled_by_config")
        return await self._run(
            subjects,
            lambda members: self._forward_window(members, now),
            data_class=DataClass.FORWARD,
            now=now,
        )

    async def backfill(
        self, subject: Subject, start: datetime, end: datetime, now: datetime
    ) -> AdapterResult:
        """A past span for one meme, labelled BACKFILL (retrieved_at = now).
        Any detected bucket width is accepted: the span is the operator's."""
        ok, why = self.enabled()
        if not ok:
            return disabled_result(self.source, why or "disabled_by_config")
        window = {"startdatetime": _fmt(start), "enddatetime": _fmt(end)}
        return await self._run(
            [subject], lambda _members: window, data_class=DataClass.BACKFILL, now=now
        )
