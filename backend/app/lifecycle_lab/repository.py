"""All of the Lab's SQL. Maps rows to and from `app.lifecycle_lab.domain`.

Conventions, each enforced here rather than hoped for upstream:

* ``flush()``, never ``commit()`` — the caller owns the transaction.
* Idempotency is the database's job: every write that could be repeated is an
  ``INSERT ... ON CONFLICT DO NOTHING`` against a unique key, never a "check,
  then insert".
* Write-once columns (``linked_at``, ``retrieved_at``, ``detected_at``) are
  never in an UPDATE. A link re-added by a later matcher run keeps the moment
  it was FIRST made; moving it later would hide what was known, moving it
  earlier would fabricate it.
* Every read that returns rows is totally ordered, with a tiebreak, so a
  replay over the same database reads the same sequence (CLAUDE.md: LIMIT
  without a total ORDER BY livelocked the score sweep).
* Reads deliberately over-fetch around the point-in-time boundary and leave
  the precise cut to ``pit.information_available_at`` — the gate lives in one
  place, and this module only keeps the haul small.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, cast

from sqlalchemy import (
    CursorResult,
    DateTime,
    Select,
    SmallInteger,
    and_,
    func,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.lifecycle_lab.domain import (
    TIMELINESS_HORIZONS,
    AliasKind,
    CollectionRun,
    DataClass,
    LinkMethod,
    MarketPoint,
    Meme,
    MemeAlias,
    MemeEvent,
    MemeTokenLink,
    Metric,
    Observation,
    Source,
    SourceStatus,
    Timeliness,
    TokenInfo,
    Unavailable,
    ValueKind,
)
from app.models.lifecycle_lab import (
    MEME_STATUS_TRACKED,
    MllAttentionObservation,
    MllBacktestRun,
    MllCollectionRun,
    MllExperiment,
    MllMeme,
    MllMemeAlias,
    MllMemeEvent,
    MllMemeToken,
    MllPaperTrade,
    MllPortfolioSnapshot,
)
from app.models.market import (
    LANE_NORMAL,
    EnrichmentStatus,
    TokenEnrichmentState,
    TokenMarketCandle,
    TokenMarketSnapshot,
)
from app.models.social import PumpfunSocialSnapshot
from app.models.token import PUBKEY_MAX_LENGTH, DiscoveredToken

#: Rows per INSERT. asyncpg caps a statement at 32,767 bind parameters and an
#: observation row binds ~20, so 1,000 rows is comfortably inside it.
_CHUNK = 1000

#: `discovered_tokens.source_program` for mints the Lab enrolled. The marker
#: that keeps them distinguishable from scanner discoveries, exactly as
#: `jupiter_verified` does for the universe.
SOURCE_PROGRAM = "lifecycle_lab"

#: The listing the pump.fun poller reads. Recorded as each reply reading's
#: `source_url` — provenance, not a fetch target.
PUMPFUN_COINS_URL = "https://frontend-api-v3.pump.fun/coins?sort={sort}"

#: Timeliness horizon → `mll_meme_events` column. Fixed by the domain.
_RETURN_COLUMNS: dict[timedelta, str] = dict(
    zip(
        TIMELINESS_HORIZONS,
        (
            "return_5m",
            "return_15m",
            "return_30m",
            "return_1h",
            "return_2h",
            "return_6h",
            "return_24h",
        ),
        strict=True,
    )
)

_WS = re.compile(r"\s+")


def normalize_alias(alias: str) -> str:
    """The matcher's key: casefolded, stripped, whitespace collapsed, leading
    ``$``/``#`` removed — so ``$PEPE``, ``#pepe`` and ``Pepe`` are one alias."""
    text = _WS.sub(" ", alias.casefold().strip())
    return text.lstrip("$#").strip()


def _uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _opt_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    return None if value is None else _uuid(value)


def _jsonable(value: Any) -> Any:
    """JSONB goes through `json.dumps`, which refuses Decimal and datetime.
    Money stays a string, as everywhere else in the API."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Unavailable):
        return {"unavailable": value.reason}
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_jsonable(v) for v in value]
    return value


def _chunks[T](rows: Sequence[T], size: int = _CHUNK) -> Iterable[Sequence[T]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def _row_dict(row: Any) -> dict[str, Any]:
    """ORM row → plain dict of its columns (ids as strings)."""
    out: dict[str, Any] = {}
    for column in row.__table__.columns:
        value = getattr(row, column.key)
        out[column.key] = str(value) if isinstance(value, uuid.UUID) else value
    return out


# --------------------------------------------------------------------------
# Row → domain
# --------------------------------------------------------------------------


def _meme(row: MllMeme) -> Meme:
    return Meme(
        id=str(row.id),
        slug=row.slug,
        display_name=row.display_name,
        tracking_started_at=row.tracking_started_at,
        wikipedia_title=row.wikipedia_title,
        gdelt_query=row.gdelt_query,
    )


def _alias(row: MllMemeAlias) -> MemeAlias:
    return MemeAlias(
        meme_id=str(row.meme_id),
        alias=row.alias,
        kind=AliasKind(row.kind),
        added_at=row.added_at,
    )


def _link(row: MllMemeToken) -> MemeTokenLink:
    return MemeTokenLink(
        meme_id=str(row.meme_id),
        mint_address=row.mint_address,
        method=LinkMethod(row.method),
        confidence=row.confidence,
        linked_at=row.linked_at,
        unlinked_at=row.unlinked_at,
    )


def _run(row: MllCollectionRun) -> CollectionRun:
    return CollectionRun(
        id=str(row.id),
        source=Source(row.source),
        status=SourceStatus(row.status),
        started_at=row.started_at,
        finished_at=row.finished_at,
        data_class=DataClass(row.data_class),
        reason=row.reason,
        meme_id=None if row.meme_id is None else str(row.meme_id),
        mint_address=row.mint_address,
        observations_written=row.observations_written,
        detail=row.detail,
    )


def _observation(row: MllAttentionObservation) -> Observation:
    return Observation(
        source=Source(row.source),
        metric=Metric(row.metric),
        value_kind=ValueKind(row.value_kind),
        data_class=DataClass(row.data_class),
        source_timestamp=row.source_timestamp,
        observed_at=row.observed_at,
        retrieved_at=row.retrieved_at,
        raw_value=row.raw_value,
        meme_id=None if row.meme_id is None else str(row.meme_id),
        mint_address=row.mint_address,
        window_start=row.window_start,
        window_end=row.window_end,
        query=row.query,
        source_url=row.source_url,
        normalized_value=row.normalized_value,
        confidence=row.confidence,
        raw_payload=row.raw_payload,
        collection_run_id=(
            None if row.collection_run_id is None else str(row.collection_run_id)
        ),
    )


def _pumpfun_observation(row: PumpfunSocialSnapshot) -> Observation:
    """A pump.fun poll, read in place rather than copied.

    The reply counter is cumulative and was read at `observed_at` by our own
    poller, so all three timestamps are the poll instant and it is FORWARD by
    construction. `query` carries the listing sort, because the sort IS the
    population (see `app/models/social.py`).
    """
    assert row.reply_count is not None  # filtered in SQL
    return Observation(
        source=Source.PUMPFUN_REPLIES,
        metric=Metric.REPLIES_TOTAL,
        value_kind=ValueKind.CUMULATIVE,
        data_class=DataClass.FORWARD,
        source_timestamp=row.observed_at,
        observed_at=row.observed_at,
        retrieved_at=row.observed_at,
        raw_value=Decimal(row.reply_count),
        mint_address=row.mint_address,
        query=row.source_sort,
        source_url=PUMPFUN_COINS_URL.format(sort=row.source_sort),
        raw_payload={"pumpfun_social_snapshot_id": str(row.id)},
    )


def _observation_order(o: Observation) -> tuple[Any, ...]:
    return (
        o.observed_at,
        o.source.value,
        o.metric.value,
        o.meme_id or "",
        o.mint_address or "",
        o.query or "",
        o.retrieved_at,
        o.dedupe_key(),
    )


class LifecycleLabRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Collection
    # ------------------------------------------------------------------

    async def insert_observations(self, rows: Sequence[Observation]) -> int:
        """Insert raw readings. Returns how many were new.

        ``ON CONFLICT (dedupe_key) DO NOTHING``: first write wins. GDELT
        revises recent buckets after the fact, and the revision is a different
        claim made at a different time — the value we had first is what was
        known then, and that record is immutable.
        """
        inserted = 0
        for chunk in _chunks(rows):
            values = [
                {
                    "source": o.source.value,
                    "metric": o.metric.value,
                    "value_kind": o.value_kind.value,
                    "data_class": o.data_class.value,
                    "source_timestamp": o.source_timestamp,
                    "observed_at": o.observed_at,
                    "retrieved_at": o.retrieved_at,
                    "raw_value": o.raw_value,
                    "normalized_value": o.normalized_value,
                    "meme_id": _opt_uuid(o.meme_id),
                    "mint_address": o.mint_address,
                    "window_start": o.window_start,
                    "window_end": o.window_end,
                    "query": o.query,
                    "source_url": o.source_url,
                    "confidence": o.confidence,
                    "raw_payload": _jsonable(o.raw_payload),
                    "collection_run_id": _opt_uuid(o.collection_run_id),
                    "dedupe_key": o.dedupe_key(),
                }
                for o in chunk
            ]
            result = await self.session.execute(
                pg_insert(MllAttentionObservation)
                .values(values)
                .on_conflict_do_nothing(index_elements=["dedupe_key"])
                .returning(MllAttentionObservation.id)
            )
            inserted += len(result.scalars().all())
        await self.session.flush()
        return inserted

    async def record_run(self, run: CollectionRun) -> None:
        """One collection attempt. ``run.id`` must be a UUID string.

        Idempotent on the id: recording the same run twice is a no-op, never
        a rewrite — a run is a record of what happened.
        """
        await self.session.execute(
            pg_insert(MllCollectionRun)
            .values(
                id=_uuid(run.id),
                source=run.source.value,
                status=run.status.value,
                reason=run.reason,
                data_class=run.data_class.value,
                started_at=run.started_at,
                finished_at=run.finished_at,
                meme_id=_opt_uuid(run.meme_id),
                mint_address=run.mint_address,
                observations_written=run.observations_written,
                detail=_jsonable(run.detail),
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await self.session.flush()

    async def upsert_candles(
        self, points: Sequence[MarketPoint], *, source: str, retrieved_at: datetime
    ) -> int:
        """Store BACKFILL bars. Returns how many were new.

        ``bucket = observed_at - bar_seconds``: a MarketPoint is stamped at the
        bar's close, the table at its start. Open/high/low are left NULL — a
        MarketPoint carries the close only, and a NULL is not an estimate.
        ``ON CONFLICT DO NOTHING``: the first fetch of a bar is the record.
        """
        values = []
        for p in points:
            if p.bar_seconds is None or p.bar_seconds <= 0:
                raise ValueError(f"candle without bar_seconds for {p.mint_address}")
            values.append(
                {
                    "mint_address": p.mint_address,
                    "resolution_s": p.bar_seconds,
                    "source": source,
                    "bucket": p.observed_at - timedelta(seconds=p.bar_seconds),
                    "close_price": p.price_usd,
                    "close_market_cap": p.market_cap,
                    "close_liquidity_usd": p.liquidity_usd,
                    "volume": p.bar_volume,
                    "data_class": DataClass.BACKFILL.value,
                    "retrieved_at": retrieved_at,
                }
            )
        inserted = 0
        for chunk in _chunks(values):
            result = cast(
                "CursorResult[Any]",
                await self.session.execute(
                    pg_insert(TokenMarketCandle).values(list(chunk)).on_conflict_do_nothing()
                ),
            )
            inserted += result.rowcount or 0
        await self.session.flush()
        return inserted

    async def pumpfun_social_latest_observed_at(self) -> datetime | None:
        return cast(
            "datetime | None",
            await self.session.scalar(select(func.max(PumpfunSocialSnapshot.observed_at))),
        )

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    async def tracked_memes(self) -> list[Meme]:
        rows = await self.session.scalars(
            select(MllMeme)
            .where(MllMeme.status == MEME_STATUS_TRACKED)
            .order_by(MllMeme.slug, MllMeme.id)
        )
        return [_meme(r) for r in rows.all()]

    async def get_meme_by_slug(self, slug: str) -> Meme | None:
        row = await self.session.scalar(select(MllMeme).where(MllMeme.slug == slug))
        return None if row is None else _meme(row)

    async def meme_record(self, slug: str) -> dict[str, Any] | None:
        """The whole row (description and status included), for display."""
        row = await self.session.scalar(select(MllMeme).where(MllMeme.slug == slug))
        return None if row is None else _row_dict(row)

    async def aliases_for(self, meme_ids: Sequence[str]) -> list[MemeAlias]:
        if not meme_ids:
            return []
        rows = await self.session.scalars(
            select(MllMemeAlias)
            .where(MllMemeAlias.meme_id.in_([_uuid(m) for m in meme_ids]))
            .order_by(
                MllMemeAlias.meme_id,
                MllMemeAlias.added_at,
                MllMemeAlias.alias_normalized,
                MllMemeAlias.kind,
                MllMemeAlias.id,
            )
        )
        return [_alias(r) for r in rows.all()]

    async def links_for(self, meme_ids: Sequence[str]) -> list[MemeTokenLink]:
        """Every link, unlinked ones included: whether a link was visible at T
        is the pure layer's question (`MemeTokenLink.visible_at`)."""
        if not meme_ids:
            return []
        rows = await self.session.scalars(
            select(MllMemeToken)
            .where(MllMemeToken.meme_id.in_([_uuid(m) for m in meme_ids]))
            .order_by(MllMemeToken.meme_id, MllMemeToken.linked_at, MllMemeToken.mint_address)
        )
        return [_link(r) for r in rows.all()]

    async def tokens(self, mints: Sequence[str]) -> list[TokenInfo]:
        """Identity from `discovered_tokens`. A mint not there is absent from
        the result — unknown, not new. `created_at` is the chain's
        `block_time`, which is None when nobody saw the creation."""
        if not mints:
            return []
        rows = await self.session.scalars(
            select(DiscoveredToken)
            .where(DiscoveredToken.mint_address.in_(list(mints)))
            .order_by(DiscoveredToken.mint_address)
        )
        return [
            TokenInfo(
                mint_address=r.mint_address,
                name=r.name,
                symbol=r.symbol,
                created_at=r.block_time,
                discovered_at=r.discovered_at,
                creator_address=r.creator_address,
            )
            for r in rows.all()
        ]

    async def create_meme(
        self,
        *,
        slug: str,
        display_name: str,
        tracking_started_at: datetime,
        wikipedia_title: str | None = None,
        gdelt_query: str | None = None,
        description: str | None = None,
    ) -> Meme:
        """Raises IntegrityError on a duplicate slug — curation is explicit,
        and silently returning someone else's meme would be wrong."""
        row = MllMeme(
            slug=slug,
            display_name=display_name,
            description=description,
            tracking_started_at=tracking_started_at,
            wikipedia_title=wikipedia_title,
            gdelt_query=gdelt_query,
        )
        self.session.add(row)
        await self.session.flush()
        return _meme(row)

    async def add_alias(
        self, meme_id: str, alias: str, kind: AliasKind, added_at: datetime
    ) -> MemeAlias | None:
        """Returns the alias if it was new, None if it already existed (or
        normalises to nothing). An existing alias keeps its original
        `added_at` — it became known when it was first added."""
        normalized = normalize_alias(alias)
        if not normalized:
            return None
        result = await self.session.execute(
            pg_insert(MllMemeAlias)
            .values(
                meme_id=_uuid(meme_id),
                alias=alias.strip(),
                alias_normalized=normalized,
                kind=kind.value,
                added_at=added_at,
            )
            .on_conflict_do_nothing(index_elements=["meme_id", "alias_normalized", "kind"])
            .returning(MllMemeAlias.id)
        )
        if result.scalar_one_or_none() is None:
            return None
        await self.session.flush()
        return MemeAlias(meme_id=meme_id, alias=alias.strip(), kind=kind, added_at=added_at)

    async def add_link(
        self, link: MemeTokenLink, *, evidence: Mapping[str, Any] | None, linked_by: str
    ) -> bool:
        """True if the link is new.

        ``ON CONFLICT DO NOTHING``, never DO UPDATE: `linked_at` is written
        once. A matcher that re-finds an existing link on every pass must not
        drag its `linked_at` forward (hiding it from replays of the period it
        was already known in) — nor can a later, more confident method
        rewrite the method, confidence or evidence of the original claim.

        One row per (meme, mint): a pair that was unlinked stays unlinked;
        re-adding it is a no-op that returns False.
        """
        result = await self.session.execute(
            pg_insert(MllMemeToken)
            .values(
                meme_id=_uuid(link.meme_id),
                mint_address=link.mint_address,
                method=link.method.value,
                confidence=link.confidence,
                linked_at=link.linked_at,
                unlinked_at=link.unlinked_at,
                evidence=_jsonable(evidence) if evidence is not None else None,
                linked_by=linked_by,
            )
            .on_conflict_do_nothing(index_elements=["meme_id", "mint_address"])
            .returning(MllMemeToken.id)
        )
        inserted = result.scalar_one_or_none() is not None
        await self.session.flush()
        return inserted

    async def unlink(self, meme_id: str, mint: str, at: datetime) -> bool:
        """Close a current link at `at`. False if there was no current link —
        an unlink, like a link, is written once."""
        result = cast(
            "CursorResult[Any]",
            await self.session.execute(
                update(MllMemeToken)
                .where(
                    MllMemeToken.meme_id == _uuid(meme_id),
                    MllMemeToken.mint_address == mint,
                    MllMemeToken.unlinked_at.is_(None),
                )
                .values(unlinked_at=at)
            ),
        )
        await self.session.flush()
        return (result.rowcount or 0) > 0

    # ------------------------------------------------------------------
    # Point-in-time reads
    # ------------------------------------------------------------------

    async def observations(
        self,
        *,
        meme_ids: Sequence[str],
        mints: Sequence[str],
        until: datetime,
        since: datetime | None = None,
    ) -> list[Observation]:
        """Raw readings for these subjects that could be visible by `until`.

        Over-fetches on purpose: a FORWARD row is a candidate when
        ``retrieved_at <= until``, a BACKFILL row when ``source_timestamp <=
        until`` (it may be admitted as-if-known in EXPLORATORY mode). The exact
        cut, publication lag included, is `pit`'s. `since` bounds
        ``observed_at`` from below.

        pump.fun replies are read in place from `pumpfun_social_snapshots`
        (rows with a NULL `reply_count` are skipped — a missing counter is not
        zero replies).
        """
        meme_uuids = [_uuid(m) for m in meme_ids]
        mint_list = list(mints)
        if not meme_uuids and not mint_list:
            return []

        subject = []
        if meme_uuids:
            subject.append(MllAttentionObservation.meme_id.in_(meme_uuids))
        if mint_list:
            subject.append(MllAttentionObservation.mint_address.in_(mint_list))
        stmt = select(MllAttentionObservation).where(
            or_(*subject),
            or_(
                MllAttentionObservation.retrieved_at <= until,
                and_(
                    MllAttentionObservation.data_class == DataClass.BACKFILL.value,
                    MllAttentionObservation.source_timestamp <= until,
                ),
            ),
        )
        if since is not None:
            stmt = stmt.where(MllAttentionObservation.observed_at >= since)
        stmt = stmt.order_by(MllAttentionObservation.observed_at, MllAttentionObservation.id)
        out = [_observation(r) for r in (await self.session.scalars(stmt)).all()]

        if mint_list:
            social = select(PumpfunSocialSnapshot).where(
                PumpfunSocialSnapshot.mint_address.in_(mint_list),
                PumpfunSocialSnapshot.observed_at <= until,
                PumpfunSocialSnapshot.reply_count.is_not(None),
            )
            if since is not None:
                social = social.where(PumpfunSocialSnapshot.observed_at >= since)
            social = social.order_by(
                PumpfunSocialSnapshot.mint_address,
                PumpfunSocialSnapshot.observed_at,
                PumpfunSocialSnapshot.id,
            )
            out.extend(
                _pumpfun_observation(r) for r in (await self.session.scalars(social)).all()
            )

        out.sort(key=_observation_order)
        return out

    async def runs(
        self,
        *,
        meme_ids: Sequence[str] | None,
        since: datetime | None,
        until: datetime,
    ) -> list[CollectionRun]:
        """Collection runs finished by `until`.

        With `meme_ids`, the runs about those memes PLUS every run not about
        a meme (global and per-mint runs): source availability is decided from
        both. ``None`` means all runs.
        """
        stmt = select(MllCollectionRun).where(MllCollectionRun.finished_at <= until)
        if since is not None:
            stmt = stmt.where(MllCollectionRun.finished_at >= since)
        if meme_ids is not None:
            stmt = stmt.where(
                or_(
                    MllCollectionRun.meme_id.is_(None),
                    MllCollectionRun.meme_id.in_([_uuid(m) for m in meme_ids]),
                )
            )
        stmt = stmt.order_by(MllCollectionRun.finished_at, MllCollectionRun.id)
        return [_run(r) for r in (await self.session.scalars(stmt)).all()]

    async def latest_runs_by_source(self) -> list[CollectionRun]:
        """Per source: the latest GLOBAL run (no meme, no mint) and the latest
        PER-SUBJECT run (any meme or mint). At most two rows per source,
        global first, sources in name order.

        Two index probes per source on ``(source, finished_at DESC)`` rather
        than one DISTINCT ON, which would read every run ever recorded.
        """
        is_global = and_(
            MllCollectionRun.meme_id.is_(None), MllCollectionRun.mint_address.is_(None)
        )
        out: list[CollectionRun] = []
        for source in sorted(Source, key=lambda s: s.value):
            for scope in (is_global, ~is_global):
                row = await self.session.scalar(
                    select(MllCollectionRun)
                    .where(MllCollectionRun.source == source.value, scope)
                    .order_by(MllCollectionRun.finished_at.desc(), MllCollectionRun.id.desc())
                    .limit(1)
                )
                if row is not None:
                    out.append(_run(row))
        return out

    async def observation_counts(self, *, since: datetime) -> dict[str, int]:
        """Raw readings per source observed since `since`.

        One probe per source on ``(source, observed_at)`` rather than a
        GROUP BY over the whole table. Sources that read in place (pump.fun
        replies) or write candles (GeckoTerminal) have no rows here and
        report 0 — the caller decides whether that 0 means anything.
        """
        out: dict[str, int] = {}
        for source in sorted(Source, key=lambda s: s.value):
            count = await self.session.scalar(
                select(func.count())
                .select_from(MllAttentionObservation)
                .where(
                    MllAttentionObservation.source == source.value,
                    MllAttentionObservation.observed_at >= since,
                )
            )
            out[source.value] = int(count or 0)
        return out

    async def market_points(
        self,
        mints: Sequence[str],
        *,
        since: datetime | None,
        until: datetime,
        include_backfill: bool,
    ) -> list[MarketPoint]:
        """Market readings observed by `until`, ordered by mint then time.

        FORWARD: `token_market_snapshots`, available at `captured_at`.
        Snapshots the ingest firewall flagged `suspect` are excluded, as every
        other feature reader excludes them.

        BACKFILL (only if asked): `token_market_candles` with
        ``data_class='backfill'``; each bar is a point at its close
        (``bucket + resolution_s``), available at that close — `pit` adds the
        source's publication lag.
        """
        mint_list = list(mints)
        if not mint_list:
            return []

        snaps = select(TokenMarketSnapshot).where(
            TokenMarketSnapshot.mint_address.in_(mint_list),
            TokenMarketSnapshot.captured_at <= until,
            TokenMarketSnapshot.suspect.is_(False),
        )
        if since is not None:
            snaps = snaps.where(TokenMarketSnapshot.captured_at >= since)
        snaps = snaps.order_by(
            TokenMarketSnapshot.mint_address,
            TokenMarketSnapshot.captured_at,
            TokenMarketSnapshot.id,
        )
        out = [
            MarketPoint(
                mint_address=s.mint_address,
                observed_at=s.captured_at,
                available_at=s.captured_at,
                data_class=DataClass.FORWARD,
                price_usd=s.price_usd,
                market_cap=s.market_cap,
                liquidity_usd=s.liquidity_usd,
                volume_5m=s.volume_5m,
                volume_1h=s.volume_1h,
                volume_24h=s.volume_24h,
                buy_count_24h=s.buy_count_24h,
                sell_count_24h=s.sell_count_24h,
            )
            for s in (await self.session.scalars(snaps)).all()
        ]

        if include_backfill:
            close = TokenMarketCandle.bucket + func.make_interval(
                0, 0, 0, 0, 0, 0, TokenMarketCandle.resolution_s
            )
            bars = select(TokenMarketCandle).where(
                TokenMarketCandle.mint_address.in_(mint_list),
                TokenMarketCandle.data_class == DataClass.BACKFILL.value,
                close <= until,
            )
            if since is not None:
                bars = bars.where(close >= since)
            bars = bars.order_by(
                TokenMarketCandle.mint_address,
                TokenMarketCandle.bucket,
                TokenMarketCandle.resolution_s,
                TokenMarketCandle.source,
            )
            for c in (await self.session.scalars(bars)).all():
                at = c.bucket + timedelta(seconds=c.resolution_s)
                out.append(
                    MarketPoint(
                        mint_address=c.mint_address,
                        observed_at=at,
                        available_at=at,
                        data_class=DataClass.BACKFILL,
                        price_usd=c.close_price,
                        market_cap=c.close_market_cap,
                        liquidity_usd=c.close_liquidity_usd,
                        bar_volume=c.volume,
                        bar_seconds=c.resolution_s,
                        source=c.source,
                    )
                )

        out.sort(
            key=lambda p: (
                p.mint_address,
                p.observed_at,
                p.data_class.value,
                p.source,
                p.bar_seconds or 0,
            )
        )
        return out

    # ------------------------------------------------------------------
    # Market coverage for linked mints
    # ------------------------------------------------------------------

    def _current_linked_mints(self, limit: int) -> Select[Any]:
        """Currently linked mints of tracked memes, newest link first.

        Newest first so that, when `MLL_MAX_TRACKED_TOKENS` bites, it is the
        longest-standing links that lose fresh coverage — a link made today is
        the one most likely to be about an attention wave happening now.
        """
        return (
            select(MllMemeToken.mint_address)
            .join(MllMeme, MllMeme.id == MllMemeToken.meme_id)
            .where(
                MllMeme.status == MEME_STATUS_TRACKED,
                MllMemeToken.unlinked_at.is_(None),
                func.length(MllMemeToken.mint_address) <= PUBKEY_MAX_LENGTH,
            )
            .group_by(MllMemeToken.mint_address)
            .order_by(func.max(MllMemeToken.linked_at).desc(), MllMemeToken.mint_address)
            .limit(limit)
        )

    async def current_linked_mints(self, *, limit: int | None = None) -> list[str]:
        cap = settings.MLL_MAX_TRACKED_TOKENS if limit is None else limit
        if cap <= 0:
            return []
        rows = await self.session.scalars(self._current_linked_mints(cap))
        return [str(mint) for mint in rows.all()]

    async def enrol_linked_mints(self, *, now: datetime, limit: int | None = None) -> int:
        """Make currently linked mints observable. Returns tokens newly enrolled.

        Discovery is down (Helius 429), so a meme's coin may never have
        reached `discovered_tokens` — and nothing prices a mint that is not
        there. This follows the universe enrolment (`app/universe/enrolment.py`):
        a shallow `discovered_tokens` row marked `source_program =
        'lifecycle_lab'` with an obviously synthetic signature, plus an
        ACTIVE enrichment state on the normal lane. No Radar admission, no
        Track Record entry: a Lab link is something to observe, not an
        opportunity anybody detected.

        Idempotent twice over: an existing token is never re-registered or
        re-dated (`ON CONFLICT DO NOTHING` on the mint), and a token that
        exists without an enrichment state gets one. A dead-lettered or
        paused state is left alone — reviving it is the requeue beat's call.
        """
        mints = await self.current_linked_mints(limit=limit)
        if not mints:
            return 0
        result = await self.session.execute(
            pg_insert(DiscoveredToken)
            .values(
                [
                    {
                        "id": uuid.uuid4(),
                        "mint_address": mint,
                        # Never seen in a transaction: obviously synthetic,
                        # not fabricated-real (same rule as the universe).
                        "signature": f"{SOURCE_PROGRAM}:{mint}",
                        "slot": 0,
                        # Unknown creation time stays unknown; the market
                        # provider's pool age is not the token's age.
                        "block_time": None,
                        "discovered_at": now,
                        "source_program": SOURCE_PROGRAM,
                    }
                    for mint in mints
                ]
            )
            .on_conflict_do_nothing(index_elements=["mint_address"])
            .returning(DiscoveredToken.id)
        )
        enrolled = len(result.scalars().all())

        await self.session.execute(
            pg_insert(TokenEnrichmentState)
            .from_select(
                ["token_id", "mint_address", "status", "next_refresh_at", "priority"],
                select(
                    DiscoveredToken.id,
                    DiscoveredToken.mint_address,
                    literal(EnrichmentStatus.ACTIVE, TokenEnrichmentState.status.type),
                    literal(now, DateTime(timezone=True)),
                    literal(LANE_NORMAL, SmallInteger()),
                ).where(DiscoveredToken.mint_address.in_(mints)),
            )
            .on_conflict_do_nothing()
        )
        await self.session.flush()
        return enrolled

    async def pace_linked_mints(self, *, now: datetime) -> int:
        """Keep linked mints refreshing at least every `MLL_MARKET_INTERVAL_SECONDS`.

        Rides the existing enrichment scheduler rather than adding a market
        system: one predicated UPDATE that pulls `next_refresh_at` forward to
        at most one Lab interval away. Run every minute by the priority beat,
        it caps the gap at roughly interval + one beat (~6 min at 300 s).

        Deliberately NOT the display lane. That lane refreshes every 15 s:
        200 tokens there is ~1.15M snapshots a day, protected from retention,
        on a 38 GB disk. Five minutes is ~58k a day, the design's budget.

        * A clamp, not an assignment — `least`, so a token already due sooner
          (a Radar rank, a nursery slot) keeps its faster cadence.
        * Only rows that would actually move are touched, so an unchanged
          minute writes nothing and leaves no dead tuples.
        * Healthy ACTIVE rows only. A token in failure backoff keeps its
          backoff (the scheduler's rule: hammering a broken endpoint spends
          the budget on the token least able to use it), and dead-lettered or
          retired rows are not revived from here.

        Limit: the rows stay on the normal lane, so with a large overdue
        backlog they queue behind it like any other normal-lane token.
        """
        mints = await self.current_linked_mints()
        if not mints:
            return 0
        clamp_to = now + timedelta(seconds=settings.MLL_MARKET_INTERVAL_SECONDS)
        result = cast(
            "CursorResult[Any]",
            await self.session.execute(
                update(TokenEnrichmentState)
                .where(
                    TokenEnrichmentState.mint_address.in_(mints),
                    TokenEnrichmentState.status == EnrichmentStatus.ACTIVE,
                    TokenEnrichmentState.consecutive_failures == 0,
                    TokenEnrichmentState.next_refresh_at > clamp_to,
                )
                .values(next_refresh_at=clamp_to)
            ),
        )
        await self.session.flush()
        return result.rowcount or 0

    # ------------------------------------------------------------------
    # Research results. Plain-dict in, plain-dict out: the service layer owns
    # the mapping from its own result types, so this module does not have to
    # import them (and their engines) to persist a row.
    # ------------------------------------------------------------------

    async def upsert_experiment(self, values: Mapping[str, Any]) -> str:
        """Register an experiment; returns its id. Keys are `MllExperiment`
        columns (``experiment_key``, ``hypothesis``, ``strategy_spec``,
        ``spec_hash``, ``mode``, ``arm``, ``status`` required).

        Registering an existing key returns the existing id unchanged — the
        registry is append-only. Re-registering a key with a DIFFERENT
        ``spec_hash`` raises ValueError: a changed spec is a new experiment,
        and quietly reusing the key would let a re-tuned strategy inherit an
        old one's place in the multiple-testing count.
        """
        row = {k: _jsonable(v) if k == "strategy_spec" else v for k, v in values.items()}
        await self.session.execute(
            pg_insert(MllExperiment)
            .values(**row)
            .on_conflict_do_nothing(index_elements=["experiment_key"])
        )
        existing = (
            await self.session.execute(
                select(MllExperiment.id, MllExperiment.spec_hash).where(
                    MllExperiment.experiment_key == values["experiment_key"]
                )
            )
        ).one()
        if existing.spec_hash != values["spec_hash"]:
            raise ValueError(
                f"experiment {values['experiment_key']!r} is registered with a different spec"
            )
        await self.session.flush()
        return str(existing.id)

    async def update_experiment(self, experiment_id: str, values: Mapping[str, Any]) -> None:
        """Status, split boundaries and notes only — the spec is immutable."""
        forbidden = {"experiment_key", "strategy_spec", "spec_hash"} & set(values)
        if forbidden:
            raise ValueError(f"immutable experiment fields: {sorted(forbidden)}")
        await self.session.execute(
            update(MllExperiment)
            .where(MllExperiment.id == _uuid(experiment_id))
            .values(**values)
        )
        await self.session.flush()

    async def list_experiments(self) -> list[dict[str, Any]]:
        rows = await self.session.scalars(
            select(MllExperiment).order_by(MllExperiment.created_at, MllExperiment.id)
        )
        return [_row_dict(r) for r in rows.all()]

    async def get_experiment_by_key(self, experiment_key: str) -> dict[str, Any] | None:
        row = await self.session.scalar(
            select(MllExperiment).where(MllExperiment.experiment_key == experiment_key)
        )
        return None if row is None else _row_dict(row)

    async def find_run(
        self, *, experiment_id: str, mode: str, segment: str
    ) -> dict[str, Any] | None:
        """The newest run of an experiment in one mode and segment — the
        forward run that each forward replay re-saves into."""
        row = await self.session.scalar(
            select(MllBacktestRun)
            .where(
                MllBacktestRun.experiment_id == _uuid(experiment_id),
                MllBacktestRun.mode == mode,
                MllBacktestRun.segment == segment,
            )
            .order_by(MllBacktestRun.started_at.desc(), MllBacktestRun.id.desc())
            .limit(1)
        )
        return None if row is None else _row_dict(row)

    async def save_run(self, values: Mapping[str, Any]) -> str:
        """Insert a backtest run; returns its id. Keys are `MllBacktestRun`
        columns; ``id`` is optional (generated when absent)."""
        row = dict(values)
        row["experiment_id"] = _uuid(row["experiment_id"])
        if "id" in row:
            row["id"] = _uuid(row["id"])
        for key in ("config_spec", "summary"):
            if key in row:
                row[key] = _jsonable(row[key])
        entity = MllBacktestRun(**row)
        self.session.add(entity)
        await self.session.flush()
        return str(entity.id)

    async def update_run(self, run_id: str, values: Mapping[str, Any]) -> None:
        """Finish a run: status, finished_at, trades_count, ending_equity,
        summary, contains_backfill, error, input_fingerprint."""
        row = {k: _jsonable(v) if k == "summary" else v for k, v in values.items()}
        await self.session.execute(
            update(MllBacktestRun).where(MllBacktestRun.id == _uuid(run_id)).values(**row)
        )
        await self.session.flush()

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = await self.session.get(MllBacktestRun, _uuid(run_id))
        return None if row is None else _row_dict(row)

    async def latest_run(
        self, *, mode: str, status: str = "completed", experiment_id: str | None = None
    ) -> dict[str, Any] | None:
        stmt = select(MllBacktestRun).where(
            MllBacktestRun.mode == mode, MllBacktestRun.status == status
        )
        if experiment_id is not None:
            stmt = stmt.where(MllBacktestRun.experiment_id == _uuid(experiment_id))
        row = await self.session.scalar(
            stmt.order_by(
                MllBacktestRun.finished_at.desc().nulls_last(), MllBacktestRun.id.desc()
            ).limit(1)
        )
        return None if row is None else _row_dict(row)

    async def save_trades(self, run_id: str, trades: Sequence[Mapping[str, Any]]) -> int:
        """Upsert trades for a run. Returns rows written.

        Keyed on ``(backtest_run_id, mint_address, entry_at)``. On conflict
        ONLY the exit side and status are updated — a forward run re-saves an
        open trade when it closes; the entry, its reason and its evidence are
        the record of a decision and are never rewritten.
        """
        if not trades:
            return 0
        rid = _uuid(run_id)
        values = []
        for t in trades:
            row = dict(t)
            row["backtest_run_id"] = rid
            row["meme_id"] = _uuid(row["meme_id"])
            row["entry_features"] = _jsonable(row.get("entry_features", {}))
            row["evidence_timeline"] = _jsonable(row.get("evidence_timeline", []))
            values.append(row)
        exit_side = (
            "exit_at",
            "exit_price",
            "exit_reason",
            "exit_fees_usd",
            "pnl_usd",
            "return_pct",
            "status",
        )
        written = 0
        for chunk in _chunks(values, 500):
            stmt = pg_insert(MllPaperTrade).values(list(chunk))
            stmt = stmt.on_conflict_do_update(
                index_elements=["backtest_run_id", "mint_address", "entry_at"],
                set_={c: stmt.excluded[c] for c in exit_side} | {"updated_at": func.now()},
            )
            result = cast("CursorResult[Any]", await self.session.execute(stmt))
            written += result.rowcount or 0
        await self.session.flush()
        return written

    async def trades_for_run(self, run_id: str) -> list[dict[str, Any]]:
        rows = await self.session.scalars(
            select(MllPaperTrade)
            .where(MllPaperTrade.backtest_run_id == _uuid(run_id))
            .order_by(MllPaperTrade.entry_at, MllPaperTrade.mint_address, MllPaperTrade.id)
        )
        return [_row_dict(r) for r in rows.all()]

    async def trades_for_meme(
        self, meme_id: str, *, limit: int = 200, backtest_run_id: str | None = None
    ) -> list[dict[str, Any]]:
        stmt = select(MllPaperTrade).where(MllPaperTrade.meme_id == _uuid(meme_id))
        if backtest_run_id is not None:
            stmt = stmt.where(MllPaperTrade.backtest_run_id == _uuid(backtest_run_id))
        rows = await self.session.scalars(
            stmt.order_by(MllPaperTrade.entry_at.desc(), MllPaperTrade.id.desc()).limit(limit)
        )
        return [_row_dict(r) for r in rows.all()]

    async def save_snapshots(self, run_id: str, snapshots: Sequence[Mapping[str, Any]]) -> int:
        """Equity-curve points, keyed ``(backtest_run_id, at)``; first write
        wins. Keys: at, equity, cash, deployed, realized_pnl, unrealized_pnl,
        open_positions, peak_equity, drawdown."""
        if not snapshots:
            return 0
        rid = _uuid(run_id)
        values = [{**s, "backtest_run_id": rid} for s in snapshots]
        written = 0
        for chunk in _chunks(values):
            result = cast(
                "CursorResult[Any]",
                await self.session.execute(
                    pg_insert(MllPortfolioSnapshot)
                    .values(list(chunk))
                    .on_conflict_do_nothing(index_elements=["backtest_run_id", "at"])
                ),
            )
            written += result.rowcount or 0
        await self.session.flush()
        return written

    async def snapshots_for_run(self, run_id: str) -> list[dict[str, Any]]:
        rows = await self.session.scalars(
            select(MllPortfolioSnapshot)
            .where(MllPortfolioSnapshot.backtest_run_id == _uuid(run_id))
            .order_by(MllPortfolioSnapshot.at, MllPortfolioSnapshot.id)
        )
        return [_row_dict(r) for r in rows.all()]

    async def save_events(
        self, events: Sequence[MemeEvent], *, source_run_id: str | None = None
    ) -> int:
        """Detector firings. Returns how many were new.

        Deduped by ``uq_mll_meme_events_identity`` — (meme, type, detected_at,
        detector_version, mode, mint-or-''). Events are reproducible from raw
        observations, so a replay that re-detects one is a no-op: the row
        keeps the run that first produced it.
        """
        if not events:
            return 0
        values = [
            {
                "meme_id": _uuid(e.meme_id),
                "event_type": e.event_type.value,
                "detected_at": e.detected_at,
                "mode": e.mode.value,
                "detector_version": e.detector_version,
                "mint_address": e.mint_address,
                "divergence_case": e.divergence_case.value if e.divergence_case else None,
                "lifecycle_state": e.lifecycle_state.value if e.lifecycle_state else None,
                "features": _jsonable(e.features),
                "contains_backfill": e.contains_backfill,
                "source_run_id": _opt_uuid(source_run_id),
            }
            for e in events
        ]
        inserted = 0
        for chunk in _chunks(values):
            # No conflict target: the identity is an expression index, and
            # the only other unique key is the generated primary key.
            result = await self.session.execute(
                pg_insert(MllMemeEvent)
                .values(list(chunk))
                .on_conflict_do_nothing()
                .returning(MllMemeEvent.id)
            )
            inserted += len(result.scalars().all())
        await self.session.flush()
        return inserted

    async def events_for_meme(
        self, meme_id: str, *, mode: str | None = None, limit: int = 500
    ) -> list[dict[str, Any]]:
        stmt = select(MllMemeEvent).where(MllMemeEvent.meme_id == _uuid(meme_id))
        if mode is not None:
            stmt = stmt.where(MllMemeEvent.mode == mode)
        rows = await self.session.scalars(
            stmt.order_by(MllMemeEvent.detected_at.desc(), MllMemeEvent.id.desc()).limit(limit)
        )
        return [_row_dict(r) for r in rows.all()]

    async def recent_events(
        self, meme_ids: Sequence[str], *, mode: str, since: datetime
    ) -> list[dict[str, Any]]:
        """Events of these memes detected since `since`, oldest first — the
        prior events a forward detection or a state classification needs."""
        if not meme_ids:
            return []
        rows = await self.session.scalars(
            select(MllMemeEvent)
            .where(
                MllMemeEvent.meme_id.in_([_uuid(m) for m in meme_ids]),
                MllMemeEvent.mode == mode,
                MllMemeEvent.detected_at >= since,
            )
            .order_by(MllMemeEvent.meme_id, MllMemeEvent.detected_at, MllMemeEvent.id)
        )
        return [_row_dict(r) for r in rows.all()]

    async def events_awaiting_outcomes(
        self, *, detected_before: datetime, limit: int = 500
    ) -> list[dict[str, Any]]:
        """Events with a mint whose outcomes are not yet complete, oldest first."""
        rows = await self.session.scalars(
            select(MllMemeEvent)
            .where(
                MllMemeEvent.outcomes_complete_at.is_(None),
                MllMemeEvent.mint_address.is_not(None),
                MllMemeEvent.detected_at <= detected_before,
            )
            .order_by(MllMemeEvent.detected_at, MllMemeEvent.id)
            .limit(limit)
        )
        return [_row_dict(r) for r in rows.all()]

    async def record_timeliness(
        self, event_id: str, timeliness: Timeliness, *, complete_at: datetime | None
    ) -> None:
        """Write an event's outcomes. An ``Unavailable`` stays NULL in its
        column with the reason in ``outcome_reasons`` — never a zero.
        `complete_at` marks every horizon as settled."""
        values: dict[str, Any] = {}
        reasons: dict[str, str] = {}

        def put(column: str, measured: Any) -> None:
            if isinstance(measured, Unavailable):
                values[column] = None
                reasons[column] = measured.reason
            else:
                values[column] = measured

        put("price_before_detection", timeliness.price_before_detection)
        put("price_at_detection", timeliness.price_at_detection)
        put("run_up_before_detection", timeliness.run_up_before_detection)
        for horizon, column in _RETURN_COLUMNS.items():
            if horizon in timeliness.returns:
                put(column, timeliness.returns[horizon])
        values["outcome_reasons"] = reasons or None
        values["outcomes_complete_at"] = complete_at
        await self.session.execute(
            update(MllMemeEvent).where(MllMemeEvent.id == _uuid(event_id)).values(**values)
        )
        await self.session.flush()
