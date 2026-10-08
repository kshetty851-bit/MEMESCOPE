"""Wikipedia per-article pageviews (Wikimedia REST API).

## Granularity

Daily only. The REST per-article endpoint offers ``daily`` and ``monthly``;
hourly per-article views exist only as bulk dump files, which are not used. A
Wikipedia reading is therefore a footprint / baseline signal, not a fast one.
Each observation is one complete UTC day: ``window = [00:00, 24:00)``,
``source_timestamp = window_start``, ``observed_at = window_end``.

## Provenance

``retrieved_at`` is when we fetched, which for a day published late is well
after ``window_end``. Forward mode fetches the last three complete days each
run so a day that was not yet published last time is picked up; dedupe is
first-write-wins per (meme, day).

Wikimedia asks for a descriptive User-Agent with contact information; it is
sent on every request from ``MLL_WIKIPEDIA_USER_AGENT``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import quote

import httpx

from app.lifecycle_lab.adapters.base import (
    AdapterError,
    AdapterResult,
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

BASE = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
PROJECT = "en.wikipedia"
FORWARD_DAYS = 3


def _day(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


class WikipediaAdapter:
    source: Source = Source.WIKIPEDIA
    data_class: DataClass = DataClass.FORWARD

    def __init__(self, settings: Any, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    def enabled(self) -> tuple[bool, str | None]:
        if not self._settings.FEATURE_LIFECYCLE_LAB_ENABLED:
            return False, "lab_disabled"
        if not self._settings.MLL_WIKIPEDIA_ENABLED:
            return False, "disabled_by_config"
        return True, None

    def _url(self, title: str, start: date, end: date) -> str:
        article = quote(title.strip().replace(" ", "_"), safe="")
        return f"{BASE}/{PROJECT}/all-access/user/{article}/daily/{start:%Y%m%d}/{end:%Y%m%d}"

    async def _fetch_subject(
        self,
        subject: Subject,
        start: date,
        end: date,
        *,
        data_class: DataClass,
        now: datetime,
    ) -> tuple[SourceStatus, str | None, list[Observation]]:
        title = subject.meme.wikipedia_title
        if not title:
            return SourceStatus.UNAVAILABLE, "no_wikipedia_title", []
        response = await http_get(
            self._client,
            self._url(title, start, end),
            headers={
                "User-Agent": str(self._settings.MLL_WIKIPEDIA_USER_AGENT),
                "Accept": "application/json",
            },
        )
        # 404 means "no article or no data for these dates" - the API does not
        # distinguish. Either way the source has nothing; it is not a zero.
        if response.status_code == 404:
            return SourceStatus.UNAVAILABLE, "no_article", []
        raise_for_status(response)
        body = parse_json(response)
        items = body.get("items") if isinstance(body, dict) else None
        if not isinstance(items, list):
            raise AdapterError("unparseable")
        url = request_url(response)
        observations: list[Observation] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                stamp = datetime.strptime(str(item["timestamp"])[:8], "%Y%m%d").replace(
                    tzinfo=UTC
                )
                views = Decimal(int(item["views"]))
            except (KeyError, ValueError, TypeError):
                continue
            window_end = stamp + timedelta(days=1)
            if window_end > now:
                continue  # an incomplete day is not a measurement yet
            observations.append(
                Observation(
                    source=Source.WIKIPEDIA,
                    metric=Metric.PAGEVIEWS,
                    value_kind=ValueKind.WINDOW_COUNT,
                    data_class=data_class,
                    source_timestamp=stamp,
                    observed_at=window_end,
                    retrieved_at=now,
                    raw_value=views,
                    meme_id=subject.meme.id,
                    window_start=stamp,
                    window_end=window_end,
                    query=title,
                    source_url=url,
                    confidence=Decimal("1"),
                    raw_payload={
                        "article": item.get("article"),
                        "granularity": "daily",
                        "access": "all-access",
                        "agent": "user",
                    },
                )
            )
        if not observations:
            return SourceStatus.UNAVAILABLE, "no_data_for_window", []
        observations.sort(key=lambda o: o.window_start or o.observed_at)
        return SourceStatus.AVAILABLE, None, observations

    async def _run(
        self,
        subjects: Sequence[Subject],
        start: date,
        end: date,
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
                status, reason, obs = await self._fetch_subject(
                    subject, start, end, data_class=data_class, now=now
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
        today = now.astimezone(UTC).date()
        return await self._run(
            subjects,
            today - timedelta(days=FORWARD_DAYS),
            today - timedelta(days=1),
            data_class=DataClass.FORWARD,
            now=now,
        )

    async def backfill(
        self, subject: Subject, start: datetime, end: datetime, now: datetime
    ) -> AdapterResult:
        """Past days for one meme, labelled BACKFILL (retrieved_at = now)."""
        ok, why = self.enabled()
        if not ok:
            return disabled_result(self.source, why or "disabled_by_config")
        return await self._run(
            [subject],
            start.astimezone(UTC).date(),
            end.astimezone(UTC).date(),
            data_class=DataClass.BACKFILL,
            now=now,
        )
