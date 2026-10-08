"""Reddit mentions - OAuth only.

Official API, application-only OAuth (client credentials). No scraping, no
unauthenticated ``.json`` endpoints. ``enabled()`` is False unless
``MLL_REDDIT_ENABLED`` AND client id, client secret and a descriptive
User-Agent are all configured; when disabled, ``collect`` makes **no network
call** and returns DISABLED.

Flow: ``POST https://www.reddit.com/api/v1/access_token`` (basic auth,
``grant_type=client_credentials``) then ``GET https://oauth.reddit.com/search``
(``sort=new``, ``t=day``, ``limit=100``, one page).

Per meme the query is its display name plus NAME/PHRASE/HASHTAG aliases, OR-ed
and quoted. Posts are bucketed into the last six *complete* UTC hours:
MENTIONS (posts), UNIQUE_PARTICIPANTS (distinct non-deleted authors), and
ENGAGEMENT (score + comments) - FORWARD only, because engagement keeps
accumulating after the window and a later reading describes the present.

Coverage honesty: one page is the 100 newest posts. If the page is full and its
oldest post is newer than a bucket's start, that bucket may be truncated and is
NOT emitted (status PARTIAL ``truncated_page``). A non-full page covers the
whole day, so empty buckets there are genuine zeros of an answered query.
Text search is keyword matching: confidence 0.6.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx

from app.lifecycle_lab.adapters.base import (
    AdapterError,
    AdapterResult,
    Subject,
    aggregate_status,
    disabled_result,
    http_get,
    http_request,
    parse_json,
    raise_for_status,
    request_url,
)
from app.lifecycle_lab.domain import (
    AliasKind,
    DataClass,
    Metric,
    Observation,
    Source,
    SourceStatus,
    ValueKind,
)

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"  # noqa: S105 - an endpoint, not a secret
SEARCH_URL = "https://oauth.reddit.com/search"
PAGE_LIMIT = 100
BUCKET_HOURS = 6
CONFIDENCE = Decimal("0.6")
_QUERY_KINDS = frozenset({AliasKind.NAME, AliasKind.PHRASE, AliasKind.HASHTAG})


def build_query(subject: Subject) -> str:
    terms = [subject.meme.display_name]
    terms += [a.alias for a in subject.aliases if a.kind in _QUERY_KINDS]
    cleaned = sorted({t.replace('"', "").strip() for t in terms if t.strip()}, key=str.lower)
    return " OR ".join(f'"{t}"' for t in cleaned)


class RedditAdapter:
    source: Source = Source.REDDIT
    data_class: DataClass = DataClass.FORWARD

    def __init__(self, settings: Any, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    def enabled(self) -> tuple[bool, str | None]:
        s = self._settings
        if not s.FEATURE_LIFECYCLE_LAB_ENABLED:
            return False, "lab_disabled"
        if not (
            s.MLL_REDDIT_ENABLED
            and s.MLL_REDDIT_CLIENT_ID.get_secret_value()
            and s.MLL_REDDIT_CLIENT_SECRET.get_secret_value()
            and s.MLL_REDDIT_USER_AGENT.strip()
        ):
            return False, "disabled_by_config"
        return True, None

    async def _token(self) -> str:
        s = self._settings
        response = await http_request(
            self._client,
            "POST",
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": s.MLL_REDDIT_USER_AGENT},
            auth=(
                s.MLL_REDDIT_CLIENT_ID.get_secret_value(),
                s.MLL_REDDIT_CLIENT_SECRET.get_secret_value(),
            ),
        )
        raise_for_status(response)
        body = parse_json(response)
        token = body.get("access_token") if isinstance(body, dict) else None
        if not isinstance(token, str) or not token:
            raise AdapterError("unauthorized")
        return token

    async def _subject(
        self, subject: Subject, token: str, now: datetime
    ) -> tuple[SourceStatus, str | None, list[Observation]]:
        query = build_query(subject)
        response = await http_get(
            self._client,
            SEARCH_URL,
            params={
                "q": query,
                "sort": "new",
                "t": "day",
                "limit": PAGE_LIMIT,
                "type": "link",
                "raw_json": 1,
            },
            headers={
                "Authorization": f"bearer {token}",
                "User-Agent": self._settings.MLL_REDDIT_USER_AGENT,
            },
        )
        raise_for_status(response)
        body = parse_json(response)
        data = body.get("data") if isinstance(body, dict) else None
        children = data.get("children") if isinstance(data, dict) else None
        if not isinstance(children, list):
            raise AdapterError("unparseable")
        posts: list[tuple[datetime, str, int]] = []
        for child in children:
            post = child.get("data") if isinstance(child, dict) else None
            if not isinstance(post, dict):
                continue
            try:
                created = datetime.fromtimestamp(float(post["created_utc"]), tz=UTC)
                engagement = int(post.get("score") or 0) + int(post.get("num_comments") or 0)
            except (KeyError, ValueError, TypeError, OverflowError, OSError):
                continue
            author = post.get("author")
            posts.append((created, author if isinstance(author, str) else "", engagement))

        full_page = len(children) >= PAGE_LIMIT
        oldest = min((p[0] for p in posts), default=None)
        floor_hour = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        # Aligned to BUCKET_HOURS so dedupe keys repeat across runs.
        edge = floor_hour - timedelta(hours=floor_hour.hour % BUCKET_HOURS)
        start = edge - timedelta(hours=BUCKET_HOURS)
        end = edge
        url = request_url(response)
        if full_page and (oldest is None or oldest > start):
            return SourceStatus.PARTIAL, "truncated_page", []
        inside = [p for p in posts if start <= p[0] < end]
        authors = {a for _, a, _ in inside if a and a != "[deleted]"}
        common: dict[str, Any] = {
            "source": Source.REDDIT,
            "value_kind": ValueKind.WINDOW_COUNT,
            "data_class": DataClass.FORWARD,
            "source_timestamp": start,
            "observed_at": end,
            "retrieved_at": now,
            "meme_id": subject.meme.id,
            "window_start": start,
            "window_end": end,
            "query": query,
            "source_url": url,
            "confidence": CONFIDENCE,
        }
        observations = [
            Observation(metric=Metric.MENTIONS, raw_value=Decimal(len(inside)), **common),
            Observation(
                metric=Metric.UNIQUE_PARTICIPANTS, raw_value=Decimal(len(authors)), **common
            ),
            Observation(
                metric=Metric.ENGAGEMENT,
                raw_value=Decimal(sum(p[2] for p in inside)),
                raw_payload={"definition": "score+num_comments", "posts": len(inside)},
                **common,
            ),
        ]
        return SourceStatus.AVAILABLE, None, observations

    async def collect(self, subjects: Sequence[Subject], *, now: datetime) -> AdapterResult:
        ok, why = self.enabled()
        if not ok:
            return disabled_result(self.source, why or "disabled_by_config")
        try:
            token = await self._token()
        except AdapterError as exc:
            failed: dict[str, tuple[SourceStatus, str | None]] = {
                s.meme.id: (SourceStatus.ERROR, exc.reason) for s in subjects
            }
            return AdapterResult(
                self.source, SourceStatus.ERROR, exc.reason, per_subject=failed
            )
        per: dict[str, tuple[SourceStatus, str | None]] = {}
        observations: list[Observation] = []
        blocked: str | None = None
        for subject in subjects:
            if blocked is not None:
                per[subject.meme.id] = (SourceStatus.ERROR, blocked)
                continue
            try:
                status, reason, obs = await self._subject(subject, token, now)
            except AdapterError as exc:
                per[subject.meme.id] = (SourceStatus.ERROR, exc.reason)
                if exc.reason == "rate_limited":
                    blocked = exc.reason
                continue
            per[subject.meme.id] = (status, reason)
            observations.extend(obs)
        status, reason = aggregate_status(per)
        return AdapterResult(self.source, status, reason, tuple(observations), per)
