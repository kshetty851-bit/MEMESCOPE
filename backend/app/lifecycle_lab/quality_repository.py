"""SQL for the data-quality report and the research-status gate.

Read-only. Every aggregate here is bounded by ``until`` (the report's ``now``):
a quality report must not count a row that did not yet exist at the instant it
claims to describe. This is a low-traffic research report, so plain aggregate
counts are acceptable here in a way they are not on a ranking endpoint
(CLAUDE.md: no unconditional ``count(*)`` on hot paths).

Conventions shared with ``repository.py``: totally ordered reads (a tiebreak on
every ORDER BY), ``flush()``-free because nothing is written, and ids leave as
strings.

Counting rules, chosen once so every figure agrees:

* A raw attention reading is dated by ``retrieved_at`` — the only timestamp
  that proves when MEMESCOPE knew it. (A backfilled Wikipedia day observed in
  2024 and retrieved yesterday is yesterday's *acquisition*.)
* pump.fun replies are read in place from ``pumpfun_social_snapshots``
  (``observed_at`` = ``retrieved_at`` there) and count as FORWARD observations
  for currently-linked mints; a row with a NULL ``reply_count`` is not an
  observation.
* Market snapshots flagged ``suspect`` are excluded, as every other reader
  excludes them.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import exists, func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.lifecycle_lab.domain import DataClass, SourceStatus
from app.lifecycle_lab.research_status import EPISODE_EVENT_TYPES, EpisodeEvent
from app.models.lifecycle_lab import (
    MEME_STATUS_TRACKED,
    MllAttentionObservation,
    MllBacktestRun,
    MllCollectionRun,
    MllExperiment,
    MllMeme,
    MllMemeEvent,
    MllMemeToken,
    MllPaperTrade,
)
from app.models.market import TokenMarketCandle, TokenMarketSnapshot
from app.models.social import PumpfunSocialSnapshot

#: The snapshot columns the report calls "market data". A latest snapshot
#: missing any of them is incomplete.
MARKET_FIELDS: tuple[str, ...] = ("price_usd", "market_cap", "liquidity_usd", "volume_1h")

GECKOTERMINAL = "geckoterminal"
PUMPFUN_REPLIES = "pumpfun_replies"


def _uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


@dataclass(frozen=True, slots=True)
class LinkedToken:
    mint: str
    meme_slug: str


@dataclass(frozen=True, slots=True)
class MarketSummary:
    """One mint's market history: forward snapshots and backfill candles."""

    mint: str
    first_at: datetime | None
    latest_at: datetime | None
    observation_count: int
    #: Whether any FORWARD snapshot exists (the fields below come from the
    #: latest one).
    has_forward: bool
    missing_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceCount:
    source: str
    forward_count: int
    backfill_count: int
    first_at: datetime | None
    latest_at: datetime | None


@dataclass(frozen=True, slots=True)
class TradeRow:
    meme_id: str
    entry_at: datetime
    exit_at: datetime | None
    status: str


class QualityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Identity and links
    # ------------------------------------------------------------------

    async def tracked_meme_refs(self) -> list[dict[str, str]]:
        rows = await self.session.execute(
            select(MllMeme.id, MllMeme.slug, MllMeme.display_name)
            .where(MllMeme.status == MEME_STATUS_TRACKED)
            .order_by(MllMeme.slug, MllMeme.id)
        )
        return [
            {"id": str(r.id), "slug": r.slug, "display_name": r.display_name}
            for r in rows.all()
        ]

    async def current_links(self, until: datetime) -> list[LinkedToken]:
        """Currently linked (mint, meme) pairs of tracked memes, visible by
        ``until``, ordered by meme then mint."""
        rows = await self.session.execute(
            select(MllMemeToken.mint_address, MllMeme.slug)
            .join(MllMeme, MllMeme.id == MllMemeToken.meme_id)
            .where(
                MllMeme.status == MEME_STATUS_TRACKED,
                MllMemeToken.unlinked_at.is_(None),
                MllMemeToken.linked_at <= until,
            )
            .order_by(MllMeme.slug, MllMemeToken.mint_address)
        )
        return [LinkedToken(mint=r.mint_address, meme_slug=r.slug) for r in rows.all()]

    async def link_audit(self, meme_id: str) -> list[dict[str, Any]]:
        """Every link of one meme with its provenance (who, what evidence)."""
        rows = await self.session.scalars(
            select(MllMemeToken)
            .where(MllMemeToken.meme_id == _uuid(meme_id))
            .order_by(MllMemeToken.linked_at, MllMemeToken.mint_address, MllMemeToken.id)
        )
        return [
            {
                "mint": r.mint_address,
                "method": r.method,
                "confidence": r.confidence,
                "linked_at": r.linked_at,
                "unlinked_at": r.unlinked_at,
                "linked_by": r.linked_by,
                "evidence": r.evidence,
            }
            for r in rows.all()
        ]

    # ------------------------------------------------------------------
    # Observations
    # ------------------------------------------------------------------

    async def observation_split(
        self, *, since: datetime, until: datetime, mints: Sequence[str]
    ) -> dict[str, int]:
        """Observations retrieved in ``[since, until]``, FORWARD vs BACKFILL.

        pump.fun replies for ``mints`` are added to FORWARD.
        """
        rows = await self.session.execute(
            select(MllAttentionObservation.data_class, func.count())
            .where(
                MllAttentionObservation.retrieved_at >= since,
                MllAttentionObservation.retrieved_at <= until,
            )
            .group_by(MllAttentionObservation.data_class)
        )
        out = {DataClass.FORWARD.value: 0, DataClass.BACKFILL.value: 0}
        for data_class, n in rows.all():
            out[data_class] = out.get(data_class, 0) + int(n)
        if mints:
            replies = await self.session.scalar(
                select(func.count())
                .select_from(PumpfunSocialSnapshot)
                .where(
                    PumpfunSocialSnapshot.mint_address.in_(list(mints)),
                    PumpfunSocialSnapshot.reply_count.is_not(None),
                    PumpfunSocialSnapshot.observed_at >= since,
                    PumpfunSocialSnapshot.observed_at <= until,
                )
            )
            out[DataClass.FORWARD.value] += int(replies or 0)
        return out

    async def forward_range(
        self, *, until: datetime, mints: Sequence[str]
    ) -> tuple[datetime | None, datetime | None]:
        """Oldest and newest FORWARD observation (``retrieved_at``) by ``until``."""
        lo: datetime | None
        hi: datetime | None
        lo, hi = (
            await self.session.execute(
                select(
                    func.min(MllAttentionObservation.retrieved_at),
                    func.max(MllAttentionObservation.retrieved_at),
                ).where(
                    MllAttentionObservation.data_class == DataClass.FORWARD.value,
                    MllAttentionObservation.retrieved_at <= until,
                )
            )
        ).one()
        if mints:
            rlo, rhi = (
                await self.session.execute(
                    select(
                        func.min(PumpfunSocialSnapshot.observed_at),
                        func.max(PumpfunSocialSnapshot.observed_at),
                    ).where(
                        PumpfunSocialSnapshot.mint_address.in_(list(mints)),
                        PumpfunSocialSnapshot.reply_count.is_not(None),
                        PumpfunSocialSnapshot.observed_at <= until,
                    )
                )
            ).one()
            los = [t for t in (lo, rlo) if t is not None]
            his = [t for t in (hi, rhi) if t is not None]
            lo = min(los) if los else None
            hi = max(his) if his else None
        return lo, hi

    async def memes_without_observations(self, until: datetime) -> list[dict[str, str]]:
        """Tracked memes with no observation of any class: none addressed to
        the meme, none to a mint it is linked to, no pump.fun reply for one."""
        by_meme = exists().where(
            MllAttentionObservation.meme_id == MllMeme.id,
            MllAttentionObservation.retrieved_at <= until,
        )
        by_mint = (
            exists()
            .select_from(
                MllMemeToken.__table__.join(
                    MllAttentionObservation.__table__,
                    MllAttentionObservation.mint_address == MllMemeToken.mint_address,
                )
            )
            .where(
                MllMemeToken.meme_id == MllMeme.id,
                MllAttentionObservation.retrieved_at <= until,
            )
        )
        by_reply = (
            exists()
            .select_from(
                MllMemeToken.__table__.join(
                    PumpfunSocialSnapshot.__table__,
                    PumpfunSocialSnapshot.mint_address == MllMemeToken.mint_address,
                )
            )
            .where(
                MllMemeToken.meme_id == MllMeme.id,
                PumpfunSocialSnapshot.reply_count.is_not(None),
                PumpfunSocialSnapshot.observed_at <= until,
            )
        )
        rows = await self.session.execute(
            select(MllMeme.slug, MllMeme.display_name)
            .where(
                MllMeme.status == MEME_STATUS_TRACKED,
                MllMeme.tracking_started_at <= until,
                ~by_meme,
                ~by_mint,
                ~by_reply,
            )
            .order_by(MllMeme.slug, MllMeme.id)
        )
        return [{"slug": r.slug, "display_name": r.display_name} for r in rows.all()]

    async def source_counts(
        self, *, meme_id: str, mints: Sequence[str], until: datetime
    ) -> list[SourceCount]:
        """Per-source observation counts for one meme (its own readings plus
        those addressed to its mints), split by data class.

        Includes pump.fun replies (forward, read in place) and GeckoTerminal
        candles (backfill): neither lives in ``mll_attention_observations``.
        """
        subject = [MllAttentionObservation.meme_id == _uuid(meme_id)]
        if mints:
            subject.append(MllAttentionObservation.mint_address.in_(list(mints)))
        rows = await self.session.execute(
            select(
                MllAttentionObservation.source,
                MllAttentionObservation.data_class,
                func.count(),
                func.min(MllAttentionObservation.retrieved_at),
                func.max(MllAttentionObservation.retrieved_at),
            )
            .where(or_(*subject), MllAttentionObservation.retrieved_at <= until)
            .group_by(MllAttentionObservation.source, MllAttentionObservation.data_class)
        )
        acc: dict[str, dict[str, Any]] = {}

        def add(source: str, data_class: str, n: int, lo: datetime, hi: datetime) -> None:
            slot = acc.setdefault(
                source, {"forward": 0, "backfill": 0, "first": None, "latest": None}
            )
            slot[data_class] = slot.get(data_class, 0) + n
            slot["first"] = lo if slot["first"] is None else min(slot["first"], lo)
            slot["latest"] = hi if slot["latest"] is None else max(slot["latest"], hi)

        for source, data_class, n, lo, hi in rows.all():
            add(source, data_class, int(n), lo, hi)

        if mints:
            n, lo, hi = (
                await self.session.execute(
                    select(
                        func.count(),
                        func.min(PumpfunSocialSnapshot.observed_at),
                        func.max(PumpfunSocialSnapshot.observed_at),
                    ).where(
                        PumpfunSocialSnapshot.mint_address.in_(list(mints)),
                        PumpfunSocialSnapshot.reply_count.is_not(None),
                        PumpfunSocialSnapshot.observed_at <= until,
                    )
                )
            ).one()
            if n:
                add(PUMPFUN_REPLIES, DataClass.FORWARD.value, int(n), lo, hi)

            gn, glo, ghi = (
                await self.session.execute(
                    select(
                        func.count(),
                        func.min(TokenMarketCandle.retrieved_at),
                        func.max(TokenMarketCandle.retrieved_at),
                    ).where(
                        TokenMarketCandle.mint_address.in_(list(mints)),
                        TokenMarketCandle.data_class == DataClass.BACKFILL.value,
                        TokenMarketCandle.source == GECKOTERMINAL,
                        TokenMarketCandle.retrieved_at.is_not(None),
                        TokenMarketCandle.retrieved_at <= until,
                    )
                )
            ).one()
            if gn and glo is not None and ghi is not None:
                add(GECKOTERMINAL, DataClass.BACKFILL.value, int(gn), glo, ghi)

        return [
            SourceCount(
                source=source,
                forward_count=int(v["forward"]),
                backfill_count=int(v["backfill"]),
                first_at=v["first"],
                latest_at=v["latest"],
            )
            for source, v in sorted(acc.items())
        ]

    # ------------------------------------------------------------------
    # Collection runs
    # ------------------------------------------------------------------

    async def run_status_counts(
        self, *, since: datetime, until: datetime
    ) -> dict[tuple[str, str], int]:
        """Runs finished in ``[since, until]``, by (source, status)."""
        rows = await self.session.execute(
            select(MllCollectionRun.source, MllCollectionRun.status, func.count())
            .where(
                MllCollectionRun.finished_at >= since,
                MllCollectionRun.finished_at <= until,
            )
            .group_by(MllCollectionRun.source, MllCollectionRun.status)
        )
        return {(r[0], r[1]): int(r[2]) for r in rows.all()}

    async def latest_run(
        self, source: str, *, until: datetime, status: SourceStatus | None = None
    ) -> dict[str, Any] | None:
        """The newest run of ``source`` finished by ``until`` (optionally only
        of one status): an index probe on ``(source, finished_at DESC)``."""
        stmt = select(MllCollectionRun).where(
            MllCollectionRun.source == source, MllCollectionRun.finished_at <= until
        )
        if status is not None:
            stmt = stmt.where(MllCollectionRun.status == status.value)
        row = await self.session.scalar(
            stmt.order_by(
                MllCollectionRun.finished_at.desc(), MllCollectionRun.id.desc()
            ).limit(1)
        )
        if row is None:
            return None
        return {"status": row.status, "reason": row.reason, "finished_at": row.finished_at}

    # ------------------------------------------------------------------
    # Market history
    # ------------------------------------------------------------------

    async def market_summaries(
        self, mints: Sequence[str], *, until: datetime
    ) -> dict[str, MarketSummary]:
        """Per mint: first/latest/count over forward snapshots AND backfill
        candles, and the missing fields of the latest FORWARD snapshot.

        A mint with no history at all is absent from the result — unknown,
        not complete.
        """
        mint_list = sorted(set(mints))
        if not mint_list:
            return {}

        snap = TokenMarketSnapshot
        snap_rows = await self.session.execute(
            select(
                snap.mint_address,
                func.count(),
                func.min(snap.captured_at),
                func.max(snap.captured_at),
            )
            .where(
                snap.mint_address.in_(mint_list),
                snap.captured_at <= until,
                snap.suspect.is_(False),
            )
            .group_by(snap.mint_address)
        )
        stats: dict[str, dict[str, Any]] = {
            r[0]: {"n": int(r[1]), "lo": r[2], "hi": r[3], "fwd": True}
            for r in snap_rows.all()
        }

        close = TokenMarketCandle.bucket + func.make_interval(
            0, 0, 0, 0, 0, 0, TokenMarketCandle.resolution_s
        )
        candle_rows = await self.session.execute(
            select(
                TokenMarketCandle.mint_address,
                func.count(),
                func.min(close),
                func.max(close),
            )
            .where(
                TokenMarketCandle.mint_address.in_(mint_list),
                TokenMarketCandle.data_class == DataClass.BACKFILL.value,
                close <= until,
            )
            .group_by(TokenMarketCandle.mint_address)
        )
        for mint, n, lo, hi in candle_rows.all():
            slot = stats.setdefault(mint, {"n": 0, "lo": None, "hi": None, "fwd": False})
            slot["n"] += int(n)
            slot["lo"] = lo if slot["lo"] is None else min(slot["lo"], lo)
            slot["hi"] = hi if slot["hi"] is None else max(slot["hi"], hi)

        latest = await self.session.scalars(
            select(snap)
            .where(
                snap.mint_address.in_(mint_list),
                snap.captured_at <= until,
                snap.suspect.is_(False),
            )
            .ext(distinct_on(snap.mint_address))
            .order_by(snap.mint_address, snap.captured_at.desc(), snap.id.desc())
        )
        missing: dict[str, tuple[str, ...]] = {
            s.mint_address: tuple(f for f in MARKET_FIELDS if getattr(s, f) is None)
            for s in latest.all()
        }
        return {
            mint: MarketSummary(
                mint=mint,
                first_at=v["lo"],
                latest_at=v["hi"],
                observation_count=v["n"],
                has_forward=bool(v["fwd"]),
                missing_fields=missing.get(mint, ()),
            )
            for mint, v in sorted(stats.items())
        }

    # ------------------------------------------------------------------
    # Research gate
    # ------------------------------------------------------------------

    async def episode_events(self, *, since: datetime, until: datetime) -> list[EpisodeEvent]:
        """FORWARD, AUTHORITATIVE wave and revival events detected in
        ``[since, until]`` as (meme, type, detected_at). Backfill-derived
        events never count toward the gate."""
        rows = await self.session.execute(
            select(MllMemeEvent.meme_id, MllMemeEvent.event_type, MllMemeEvent.detected_at)
            .where(
                MllMemeEvent.mode == "authoritative",
                MllMemeEvent.contains_backfill.is_(False),
                MllMemeEvent.event_type.in_(sorted(EPISODE_EVENT_TYPES)),
                MllMemeEvent.detected_at >= since,
                MllMemeEvent.detected_at <= until,
            )
            .order_by(MllMemeEvent.detected_at, MllMemeEvent.id)
        )
        return [(str(r[0]), r[1], r[2]) for r in rows.all()]

    async def experiment_bounds(self, experiment_key: str) -> dict[str, Any] | None:
        row = await self.session.scalar(
            select(MllExperiment).where(MllExperiment.experiment_key == experiment_key)
        )
        if row is None:
            return None
        return {
            "id": str(row.id),
            "experiment_key": row.experiment_key,
            "data_cutoff": row.data_cutoff,
            "test_start": row.test_start,
            "test_end": row.test_end,
        }

    async def forward_run(self, experiment_id: str, *, segment: str) -> dict[str, Any] | None:
        """The newest authoritative run of an experiment in ``segment``."""
        row = await self.session.scalar(
            select(MllBacktestRun)
            .where(
                MllBacktestRun.experiment_id == _uuid(experiment_id),
                MllBacktestRun.mode == "authoritative",
                MllBacktestRun.segment == segment,
            )
            .order_by(MllBacktestRun.started_at.desc(), MllBacktestRun.id.desc())
            .limit(1)
        )
        if row is None:
            return None
        return {
            "id": str(row.id),
            "status": row.status,
            "window_start": row.window_start,
            "window_end": row.window_end,
        }

    async def baseline_trades(self, run_id: str, *, until: datetime) -> list[TradeRow]:
        """Authoritative paper trades of a run entered by ``until`` — no
        backfill-contaminated or hindsight trade, which cannot count."""
        rows = await self.session.execute(
            select(
                MllPaperTrade.meme_id,
                MllPaperTrade.entry_at,
                MllPaperTrade.exit_at,
                MllPaperTrade.status,
            )
            .where(
                MllPaperTrade.backtest_run_id == _uuid(run_id),
                MllPaperTrade.entry_at <= until,
                MllPaperTrade.contains_backfill.is_(False),
                MllPaperTrade.hindsight.is_(False),
            )
            .order_by(MllPaperTrade.entry_at, MllPaperTrade.mint_address, MllPaperTrade.id)
        )
        return [
            TradeRow(meme_id=str(r[0]), entry_at=r[1], exit_at=r[2], status=r[3])
            for r in rows.all()
        ]
