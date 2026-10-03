"""GDELT DOC 2.0 news-volume timelines.

This is **news coverage, not social attention**: articles that mention the
query, as ingested by GDELT. It is a different population from pump.fun replies
or Reddit and must not be summed with them as if it were.

Endpoint: ``GET https://api.gdeltproject.org/api/v2/doc/doc`` with
``mode=timelinevolraw`` (raw article counts; ``timelinevol`` is a percentage of
all coverage), ``format=json`` and either ``timespan`` (``6h``, ``3d``) or
``startdatetime``/``enddatetime`` (``YYYYMMDDHHMMSS``).

Response shape relied on (parsed defensively - anything else is ``ERROR
unparseable``)::

    {
        "query_details": {...},
        "timeline": [
            {
                "series": "Article Count",
                "data": [{"date": "20240101T001500Z", "value": 12, "norm": 456}, ...],
            }
        ],
    }

Uncertainties, stated rather than hidden:
  * Whether ``date`` is a bucket's start or its end is not documented. It is
    treated as the START. If it is the end, every window is labelled one bucket
    too late - conservative for look-ahead, never early.
  * Bucket size depends on the span (15 min for recent short spans, hourly or
    daily for longer). It is **detected from the timestamps**, never assumed;
    irregular spacing is ``ERROR irregular_buckets``; a single point cannot
    reveal its width and is ``UNAVAILABLE bucket_size_unknown``.
  * An empty / valueless body is ``UNAVAILABLE no_data_for_window``: the source
    returned nothing, which is not a count of zero. A well-formed timeline that
    contains ``value: 0`` is a real zero.

Recent buckets are revised as GDELT ingests late articles. First write wins:
what we keep is what was known when we asked. Only buckets that have fully
closed (``window_end <= now``) are emitted.

GDELT asks callers to stay under ~1 request / 5 s; requests are spaced by
``MLL_GDELT_MIN_INTERVAL_SECONDS``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from typing import Any

import httpx

from app.lifecycle_lab.adapters.base import (
    AdapterError,
    AdapterResult,
    ClockFn,
    MinIntervalLimiter,
    SleepFn,
    Subject,
    aggregate_status,
    disabled_result,
    http_get,
    parse_json,
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
#: Forward runs ask for a span longer than the cadence so a missed run is healed.
FORWARD_TIMESPAN = "6h"
#: News keyword match: the article may be about something else entirely.
CONFIDENCE = Decimal("0.7")


def _parse_date(raw: Any) -> datetime | None:
    text = str(raw).strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _query_for(subject: Subject) -> str:
    q = (subject.meme.gdelt_query or "").strip()
    if q:
        return q
    return '"' + subject.meme.display_name.replace('"', "").strip() + '"'


def _fmt(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%d%H%M%S")


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
        self._limiter = MinIntervalLimiter(
            float(settings.MLL_GDELT_MIN_INTERVAL_SECONDS), sleep=sleep, clock=clock
        )

    def enabled(self) -> tuple[bool, str | None]:
        if not self._settings.FEATURE_LIFECYCLE_LAB_ENABLED:
            return False, "lab_disabled"
        if not self._settings.MLL_GDELT_ENABLED:
            return False, "disabled_by_config"
        return True, None

    async def _fetch(
        self,
        subject: Subject,
        window: dict[str, str],
        *,
        data_class: DataClass,
        now: datetime,
    ) -> tuple[SourceStatus, str | None, list[Observation]]:
        query = _query_for(subject)
        await self._limiter.wait()
        response = await http_get(
            self._client,
            URL,
            params={"query": query, "mode": "timelinevolraw", "format": "json", **window},
        )
        raise_for_status(response)
        body = parse_json(response)
        if not isinstance(body, dict):
            raise AdapterError("unparseable")
        timeline = body.get("timeline")
        if not timeline:
            return SourceStatus.UNAVAILABLE, "no_data_for_window", []
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
            return SourceStatus.UNAVAILABLE, "no_data_for_window", []
        points.sort(key=lambda p: p[0])

        if len(points) < 2:
            return SourceStatus.UNAVAILABLE, "bucket_size_unknown", []
        deltas = {b[0] - a[0] for a, b in pairwise(points)}
        if len(deltas) != 1 or next(iter(deltas)) <= timedelta(0):
            raise AdapterError("irregular_buckets")
        width = next(iter(deltas))

        url = request_url(response)
        observations: list[Observation] = []
        for start, value in points:
            end = start + width
            if end > now:
                continue  # bucket still filling
            observations.append(
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
                        "bucket_seconds": int(width.total_seconds()),
                        "series": series.get("series"),
                        "coverage": "news",
                    },
                )
            )
        if not observations:
            return SourceStatus.UNAVAILABLE, "no_data_for_window", []
        return SourceStatus.AVAILABLE, None, observations

    async def _run(
        self,
        subjects: Sequence[Subject],
        window: dict[str, str],
        *,
        data_class: DataClass,
        now: datetime,
    ) -> AdapterResult:
        per: dict[str, tuple[SourceStatus, str | None]] = {}
        observations: list[Observation] = []
        blocked: str | None = None
        for subject in subjects:
            if blocked is not None:
                per[subject.meme.id] = (SourceStatus.ERROR, blocked)
                continue
            try:
                status, reason, obs = await self._fetch(
                    subject, window, data_class=data_class, now=now
                )
            except AdapterError as exc:
                per[subject.meme.id] = (SourceStatus.ERROR, exc.reason)
                if exc.reason == "rate_limited":
                    blocked = exc.reason
                continue
            per[subject.meme.id] = (status, reason)
            observations.extend(obs)
        status, reason = aggregate_status(per)
        return AdapterResult(self.source, status, reason, tuple(observations), per)

    async def collect(self, subjects: Sequence[Subject], *, now: datetime) -> AdapterResult:
        ok, why = self.enabled()
        if not ok:
            return disabled_result(self.source, why or "disabled_by_config")
        return await self._run(
            subjects, {"timespan": FORWARD_TIMESPAN}, data_class=DataClass.FORWARD, now=now
        )

    async def backfill(
        self, subject: Subject, start: datetime, end: datetime, now: datetime
    ) -> AdapterResult:
        """A past span for one meme, labelled BACKFILL (retrieved_at = now)."""
        ok, why = self.enabled()
        if not ok:
            return disabled_result(self.source, why or "disabled_by_config")
        return await self._run(
            [subject],
            {"startdatetime": _fmt(start), "enddatetime": _fmt(end)},
            data_class=DataClass.BACKFILL,
            now=now,
        )
