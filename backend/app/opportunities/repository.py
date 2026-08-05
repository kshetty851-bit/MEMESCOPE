"""Opportunity persistence. The engine's only I/O seam.

Holds a session, owns no transaction — the caller's `get_db` or worker session
decides when anything commits, matching every other repository here.

Two guarantees are enforced by the schema rather than trusted:

  * **One live opportunity per token**, via the partial unique index over live
    statuses. `open_or_get` races safely: the loser of a concurrent insert
    reads the winner's row rather than raising.
  * **No duplicate active signal**, via
    `uq_opportunity_signals_dedupe`. Re-detection collides and updates.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Numeric, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.curve import TokenCurveSnapshot
from app.models.market import TokenMarketSnapshot
from app.models.opportunity import Opportunity, OpportunitySignal
from app.models.token import DiscoveredToken
from app.opportunities.analytics import ProviderTotals
from app.opportunities.models import (
    LIVE_SIGNAL_STATUSES,
    LIVE_STATUSES,
    MarketObservation,
    ObservationWindow,
    OpportunityStatus,
    SignalStatus,
)
from app.opportunities.outcomes import PREDICTIVE_SIGNALS
from app.repositories.curve import CurveSnapshotRepository, progress_of

_LIVE_STATUS_VALUES = sorted(status.value for status in LIVE_STATUSES)
#: Signal types that carry a forecast, as stored values. Sorted so the emitted
#: SQL is stable and two runs of the same query plan identically.
_PREDICTIVE_VALUES = sorted(signal.value for signal in PREDICTIVE_SIGNALS)
_LIVE_SIGNAL_VALUES = sorted(status.value for status in LIVE_SIGNAL_STATUSES)


def as_of_progress(
    moments: Sequence[datetime], snapshots: Sequence[TokenCurveSnapshot]
) -> list[Decimal | None]:
    """Curve position as it stood at each moment. Pure, both series oldest-first.

    An as-of join, not a nearest match: an observation carries the newest curve
    reading taken **at or before** it, and `None` when no reading covers it yet.
    The two series come from different sources on different clocks — the chain
    and DexScreener — so their timestamps never line up exactly, and pairing by
    index would silently mis-date the whole window.

    Nothing is carried backwards. A curve read after an observation describes a
    curve that observation never saw; using it would let a signal be justified
    by data that did not exist when the market state it explains was recorded,
    which is exactly the leak that makes a replay disagree with production.
    """
    if not snapshots:
        return [None] * len(moments)

    values: list[Decimal | None] = []
    index = 0
    carried: Decimal | None = None
    for moment in moments:
        while index < len(snapshots) and snapshots[index].captured_at <= moment:
            # Advance to the newest reading this moment can see. Each one
            # replaces the carried value outright, including when it derives to
            # `None`: "unmeasurable now" is a reading, and letting an older
            # number outlive it would report a curve position nobody observed.
            carried = progress_of(snapshots[index])
            index += 1
        values.append(carried)
    return values


class OpportunityRepository:
    """All Opportunity Engine persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- Provider input ------------------------------------------------------

    async def windows_for(
        self,
        mints: Sequence[str],
        *,
        limit_per_mint: int,
        curve_limit_per_mint: int = 0,
        curve_repository: CurveSnapshotRepository | None = None,
    ) -> dict[str, ObservationWindow]:
        """Recent observations for each mint, oldest first, in one query.

        One round trip for the batch. A query per token is what turns an
        enrichment-paced cycle back into a scan, which is the mistake the
        scoring service's `_load_windows` already documents.

        `curve_limit_per_mint` adds a second round trip — never per token — that
        attaches bonding-curve position to each observation. It defaults to
        **off**, and the caller passes a size only while curve collection is
        actually running: attaching progress from a series that stopped being
        written would hold the last value against every newer observation, which
        the near-graduation provider reads as a stalled curve. A stale reading
        presented as a current one is the estimate this platform does not make.
        """
        unique = list(dict.fromkeys(mints))
        if not unique:
            return {}

        ranked = (
            select(
                TokenMarketSnapshot.mint_address,
                TokenMarketSnapshot.captured_at,
                TokenMarketSnapshot.price_usd,
                TokenMarketSnapshot.market_cap,
                TokenMarketSnapshot.liquidity_usd,
                TokenMarketSnapshot.volume_24h,
                TokenMarketSnapshot.volume_1h,
                TokenMarketSnapshot.buy_count_24h,
                TokenMarketSnapshot.sell_count_24h,
                TokenMarketSnapshot.dex_name,
                TokenMarketSnapshot.pool_address,
                func.row_number()
                .over(
                    partition_by=TokenMarketSnapshot.mint_address,
                    order_by=TokenMarketSnapshot.captured_at.desc(),
                )
                .label("rank"),
            )
            .where(TokenMarketSnapshot.mint_address.in_(unique))
            .subquery()
        )
        rows = (
            await self._session.execute(select(ranked).where(ranked.c.rank <= limit_per_mint))
        ).all()

        collected: dict[str, list[Any]] = {mint: [] for mint in unique}
        for row in rows:
            collected[row.mint_address].append(row)

        curves: dict[str, list[TokenCurveSnapshot]] = {}
        if curve_limit_per_mint > 0:
            repository = curve_repository or CurveSnapshotRepository(self._session)
            curves = await repository.windows_for(unique, limit_per_mint=curve_limit_per_mint)

        # The window function returns newest-first; providers read oldest-first.
        windows: dict[str, ObservationWindow] = {}
        for mint, mint_rows in collected.items():
            ordered = sorted(mint_rows, key=lambda row: row.captured_at)
            progress = as_of_progress(
                [row.captured_at for row in ordered], curves.get(mint, ())
            )
            windows[mint] = ObservationWindow(
                mint_address=mint,
                observations=tuple(
                    MarketObservation(
                        captured_at=row.captured_at,
                        price_usd=row.price_usd,
                        market_cap=row.market_cap,
                        liquidity_usd=row.liquidity_usd,
                        volume_24h=row.volume_24h,
                        volume_1h=row.volume_1h,
                        buy_count_24h=row.buy_count_24h,
                        sell_count_24h=row.sell_count_24h,
                        dex_name=row.dex_name,
                        pool_address=row.pool_address,
                        curve_progress=value,
                    )
                    for row, value in zip(ordered, progress, strict=True)
                ),
            )
        return windows

    async def token_ids_for(self, mints: Sequence[str]) -> dict[str, uuid.UUID]:
        """Mint to token id, for the foreign key on a new opportunity."""
        unique = list(dict.fromkeys(mints))
        if not unique:
            return {}
        rows = (
            await self._session.execute(
                select(DiscoveredToken.mint_address, DiscoveredToken.id).where(
                    DiscoveredToken.mint_address.in_(unique)
                )
            )
        ).all()
        return {row.mint_address: row.id for row in rows}

    # --- Opportunities -------------------------------------------------------

    async def live_for(self, mints: Sequence[str]) -> dict[str, Opportunity]:
        """The live opportunity per mint, if any. At most one by construction."""
        unique = list(dict.fromkeys(mints))
        if not unique:
            return {}
        rows = (
            await self._session.scalars(
                select(Opportunity).where(
                    Opportunity.mint_address.in_(unique),
                    Opportunity.status.in_(_LIVE_STATUS_VALUES),
                )
            )
        ).all()
        return {row.mint_address: row for row in rows}

    async def live_board(
        self,
        *,
        now: datetime,
        limit: int,
        offset: int = 0,
        signal_type: str | None = None,
        stage: str | None = None,
    ) -> Sequence[Opportunity]:
        """The board: live opportunities with at least one unexpired signal.

        **Correct even if the expiry sweep has never run.** `expires_at` passes
        without anything writing a row, so filtering on `status` alone would
        show lapsed opportunities for as long as it took a background job to
        notice — and "a background job is trusted to have run" is precisely the
        assumption that let discovery die unnoticed for four days
        (MEMESCOPE_AUDIT.md R1). The freshness predicate makes the read
        authoritative and demotes the sweep to housekeeping.

        It also handles the case nothing else does: an opportunity whose token
        stopped being enriched leaves the board on its own as its signals age
        out, with no gap detection required.

        Ordered `priority DESC, detected_at DESC, mint_address` — a total order.
        A partial one means an item appearing twice, or not at all, between
        pages, and an unordered `LIMIT` is what caused the score-sweep livelock.
        """
        statement = (
            select(Opportunity)
            .where(
                Opportunity.status.in_(_LIVE_STATUS_VALUES),
                self._has_live_signal(now=now, signal_type=signal_type),
            )
            .order_by(
                Opportunity.priority.desc(),
                Opportunity.detected_at.desc(),
                Opportunity.mint_address.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        if stage is not None:
            statement = statement.where(Opportunity.stage == stage)
        return (await self._session.scalars(statement)).all()

    def _has_live_signal(
        self, *, now: datetime, signal_type: str | None = None
    ) -> ColumnElement[bool]:
        """`EXISTS` a signal that is live *and* has not lapsed.

        Both halves are needed. `status` is what the engine maintains;
        `expires_at` is what is true regardless of whether it has run yet.
        """
        condition = (
            select(OpportunitySignal.id)
            .where(
                OpportunitySignal.opportunity_id == Opportunity.id,
                OpportunitySignal.status.in_(_LIVE_SIGNAL_VALUES),
                OpportunitySignal.expires_at > now,
            )
            .exists()
        )
        if signal_type is not None:
            condition = (
                select(OpportunitySignal.id)
                .where(
                    OpportunitySignal.opportunity_id == Opportunity.id,
                    OpportunitySignal.status.in_(_LIVE_SIGNAL_VALUES),
                    OpportunitySignal.expires_at > now,
                    OpportunitySignal.signal_type == signal_type,
                )
                .exists()
            )
        return condition

    async def board_has_more(
        self,
        *,
        now: datetime,
        offset: int,
        page_size: int,
        signal_type: str | None = None,
        stage: str | None = None,
    ) -> bool:
        """Whether a further page exists, without counting the whole board.

        A `count(*)` here would repeat a measured mistake: on `/scores/top` two
        unconditional counts cost 7.1 ms against a 0.4 ms ranking query and
        dominated the endpoint once the index was fixed (Sprint 2). Fetching one
        row past the page answers the only question a reader actually asks.
        """
        statement = (
            select(Opportunity.id)
            .where(
                Opportunity.status.in_(_LIVE_STATUS_VALUES),
                self._has_live_signal(now=now, signal_type=signal_type),
            )
            .order_by(
                Opportunity.priority.desc(),
                Opportunity.detected_at.desc(),
                Opportunity.mint_address.asc(),
            )
            .limit(1)
            .offset(offset + page_size)
        )
        if stage is not None:
            statement = statement.where(Opportunity.stage == stage)
        return await self._session.scalar(statement) is not None

    async def live_signals_for(
        self, opportunity_ids: Sequence[uuid.UUID], *, now: datetime
    ) -> dict[uuid.UUID, list[OpportunitySignal]]:
        """Unexpired signals for the page's opportunities, in one query.

        Batched for exactly the ids on the page — never a query per card. The
        same freshness predicate as the header query, so a card cannot show a
        badge the board no longer counts.
        """
        unique = list(dict.fromkeys(opportunity_ids))
        if not unique:
            return {}
        rows = (
            await self._session.scalars(
                select(OpportunitySignal)
                .where(
                    OpportunitySignal.opportunity_id.in_(unique),
                    OpportunitySignal.status.in_(_LIVE_SIGNAL_VALUES),
                    OpportunitySignal.expires_at > now,
                )
                .order_by(
                    OpportunitySignal.confidence.desc(),
                    OpportunitySignal.signal_type.asc(),
                )
            )
        ).all()
        grouped: dict[uuid.UUID, list[OpportunitySignal]] = {key: [] for key in unique}
        for row in rows:
            grouped[row.opportunity_id].append(row)
        return grouped

    async def by_mint(
        self, mint_address: str, *, generation: int | None = None
    ) -> Opportunity | None:
        """One opportunity: the live one by default, or a named generation.

        Addressing a past generation is what makes the permanent record
        readable — a closed call must stay retrievable after a token opens a
        new one.
        """
        statement = select(Opportunity).where(Opportunity.mint_address == mint_address)
        if generation is not None:
            statement = statement.where(Opportunity.generation == generation)
        else:
            statement = statement.where(Opportunity.status.in_(_LIVE_STATUS_VALUES))
        found: Opportunity | None = await self._session.scalar(statement)
        return found

    async def next_generation(self, mint_address: str) -> int:
        """One past the highest generation this token has ever held.

        Generations are never reused: two separate calls on the same token must
        stay separately measurable, so a closed generation's number is retired
        with it.
        """
        highest = await self._session.scalar(
            select(func.max(Opportunity.generation)).where(
                Opportunity.mint_address == mint_address
            )
        )
        return int(highest or 0) + 1

    async def open_or_get(
        self,
        *,
        token_id: uuid.UUID,
        mint_address: str,
        generation: int,
        detected_at: datetime,
        stage: str,
    ) -> tuple[Opportunity, bool]:
        """Open a new opportunity, or return the live one that already exists.

        Returns `(opportunity, created)`. The insert is `ON CONFLICT DO NOTHING`
        against the live partial index, so two workers racing on the same mint
        cannot both open one — the loser reads the winner's row. The database is
        the guarantee; the read below is how the loser finds out.
        """
        statement = (
            insert(Opportunity)
            .values(
                token_id=token_id,
                mint_address=mint_address,
                generation=generation,
                status=OpportunityStatus.NEW.value,
                stage=stage,
                detected_at=detected_at,
                last_confirmed_at=detected_at,
            )
            .on_conflict_do_nothing()
            .returning(Opportunity)
        )
        created = await self._session.scalar(statement)
        if created is not None:
            return created, True

        existing = await self._session.scalar(
            select(Opportunity).where(
                Opportunity.mint_address == mint_address,
                Opportunity.status.in_(_LIVE_STATUS_VALUES),
            )
        )
        if existing is None:  # pragma: no cover - see below
            # Unreachable in practice: the insert only conflicts against the
            # live partial index or the (mint, generation) constraint, and both
            # imply a row this select finds. Raising beats returning None and
            # letting a NoneType surface three frames away.
            raise RuntimeError(
                f"opportunity insert for {mint_address} conflicted but no live row exists"
            )
        return existing, False

    async def apply_state(
        self,
        opportunity: Opportunity,
        *,
        status: OpportunityStatus,
        now: datetime,
        priority: Decimal | None = None,
        priority_band: str | None = None,
        confidence: Decimal | None = None,
        stage: str | None = None,
        confirmed: bool = False,
    ) -> None:
        """Write a resolved lifecycle state onto an opportunity.

        `detected_at` and `generation` are deliberately not parameters. They are
        written once at open and there is no path here that can revise them.
        """
        opportunity.status = status.value
        if priority is not None:
            opportunity.priority = priority
        if priority_band is not None:
            opportunity.priority_band = priority_band
        if confidence is not None:
            opportunity.confidence = confidence
        if stage is not None:
            opportunity.stage = stage
        if confirmed:
            opportunity.last_confirmed_at = now

        if status is OpportunityStatus.EXPIRING:
            # Stamped only on entry, so the grace window is measured from when
            # the last signal actually lapsed rather than from the most recent
            # sweep that happened to notice.
            if opportunity.expiring_since is None:
                opportunity.expiring_since = now
        else:
            opportunity.expiring_since = None

        if status is OpportunityStatus.CLOSED and opportunity.closed_at is None:
            opportunity.closed_at = now
        if status is OpportunityStatus.ARCHIVED and opportunity.archived_at is None:
            opportunity.archived_at = now

        await self._session.flush()

    async def due_for_review(self, *, now: datetime, limit: int) -> Sequence[Opportunity]:
        """Live opportunities whose signals may have lapsed, plus closed ones
        waiting to be archived.

        Ordered oldest-confirmed first so every opportunity gets a turn as the
        table grows, the same rotation `stale_before` uses — an unordered LIMIT
        is what starved the score sweep (MEMESCOPE_AUDIT.md §3.5).
        """
        statement = (
            select(Opportunity)
            .where(
                Opportunity.status.in_([*_LIVE_STATUS_VALUES, OpportunityStatus.CLOSED.value])
            )
            .order_by(Opportunity.last_confirmed_at.asc(), Opportunity.mint_address.asc())
            .limit(limit)
        )
        return (await self._session.scalars(statement)).all()

    # --- Signals -------------------------------------------------------------

    async def signals_for(
        self, opportunity_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, list[OpportunitySignal]]:
        unique = list(dict.fromkeys(opportunity_ids))
        if not unique:
            return {}
        rows = (
            await self._session.scalars(
                select(OpportunitySignal).where(OpportunitySignal.opportunity_id.in_(unique))
            )
        ).all()
        grouped: dict[uuid.UUID, list[OpportunitySignal]] = {key: [] for key in unique}
        for row in rows:
            grouped[row.opportunity_id].append(row)
        return grouped

    # --- Analytics -----------------------------------------------------------

    async def provider_totals(
        self, *, required_confirmations: int
    ) -> dict[str, ProviderTotals]:
        """Raw per-provider counts over the whole history, in two grouped passes.

        Counts only. Every ratio is derived in `analytics.py`, so nothing here
        decides what a number means — and nothing is stored: a maintained
        counter would be a second copy of what these tables already say, and the
        copy is what goes wrong during a replay or a failed transaction.

        Archived generations are included deliberately. The permanent record is
        the point: a provider's history must not improve because its worst calls
        settled out of the board.
        """
        closed = Opportunity.closed_at.is_not(None)

        aggregate = (
            select(
                OpportunitySignal.provider_id.label("provider_id"),
                func.count().label("signals"),
                func.count(func.distinct(OpportunitySignal.opportunity_id)).label(
                    "opportunities"
                ),
                func.count()
                .filter(OpportunitySignal.confirmations >= required_confirmations)
                .label("confirmed"),
                func.count()
                .filter(OpportunitySignal.status == SignalStatus.EXPIRED.value)
                .label("expired"),
                func.count(func.distinct(OpportunitySignal.opportunity_id))
                .filter(closed)
                .label("closed"),
                # Outcomes are split by whether the signal type was a forecast
                # at all. A factual signal cannot be right or wrong, so its
                # invalidation is a correction and must not reach precision's
                # denominator — see `outcomes.PREDICTIVE_SIGNALS`.
                func.count()
                .filter(
                    OpportunitySignal.status == SignalStatus.REALISED.value,
                    OpportunitySignal.signal_type.in_(_PREDICTIVE_VALUES),
                )
                .label("realised"),
                func.count()
                .filter(
                    OpportunitySignal.status == SignalStatus.INVALIDATED.value,
                    OpportunitySignal.signal_type.in_(_PREDICTIVE_VALUES),
                )
                .label("invalidated"),
                func.count()
                .filter(
                    OpportunitySignal.status == SignalStatus.INVALIDATED.value,
                    OpportunitySignal.signal_type.not_in(_PREDICTIVE_VALUES),
                )
                .label("contradicted"),
                func.coalesce(func.sum(OpportunitySignal.confidence), 0).label(
                    "confidence_total"
                ),
            )
            .join(Opportunity, Opportunity.id == OpportunitySignal.opportunity_id)
            .group_by(OpportunitySignal.provider_id)
        )

        # Lifetime is a property of the *opportunity*, so it is summed over
        # distinct (provider, opportunity) pairs rather than over signals. A
        # provider holding two signal types on one closed opportunity would
        # otherwise count that single lifetime twice and report an average no
        # opportunity ever had.
        pairs = (
            select(
                OpportunitySignal.provider_id.label("provider_id"),
                OpportunitySignal.opportunity_id.label("opportunity_id"),
                func.extract("epoch", Opportunity.closed_at - Opportunity.detected_at)
                .cast(Numeric)
                .label("lifetime"),
            )
            .join(Opportunity, Opportunity.id == OpportunitySignal.opportunity_id)
            .where(closed)
            .distinct()
            .subquery()
        )
        lifetimes = select(
            pairs.c.provider_id,
            func.coalesce(func.sum(pairs.c.lifetime), 0).label("lifetime_total"),
            func.count().label("lifetime_samples"),
        ).group_by(pairs.c.provider_id)

        measured = {
            row.provider_id: (row.lifetime_total, row.lifetime_samples)
            for row in (await self._session.execute(lifetimes)).all()
        }
        collected: dict[str, ProviderTotals] = {}
        for row in (await self._session.execute(aggregate)).all():
            lifetime_total, lifetime_samples = measured.get(row.provider_id, (0, 0))
            collected[row.provider_id] = ProviderTotals(
                provider_id=row.provider_id,
                signals=row.signals,
                opportunities=row.opportunities,
                confirmed=row.confirmed,
                expired=row.expired,
                closed=row.closed,
                realised=row.realised,
                invalidated=row.invalidated,
                contradicted=row.contradicted,
                confidence_total=Decimal(row.confidence_total),
                lifetime_seconds_total=Decimal(lifetime_total),
                lifetime_samples=lifetime_samples,
            )
        return collected

    async def upsert_signal(
        self,
        *,
        opportunity_id: uuid.UUID,
        mint_address: str,
        signal_type: str,
        provider_id: str,
        severity: str,
        strength: Decimal,
        observations: int,
        detected_at: datetime,
        expires_at: datetime,
        observed_at: datetime | None,
        reason_codes: Sequence[str],
        evidence: Sequence[dict[str, str | None]],
    ) -> tuple[OpportunitySignal, bool]:
        """Insert a signal, or confirm the one that already exists.

        Returns `(signal, created)`. The unique key is
        `(opportunity_id, signal_type, provider_id)`, so a re-detection of the
        same transition collides and is treated as a confirmation — never a
        second row. This is the whole of AD-09's signal half.

        A collision on the *same observation* is not a confirmation: it means
        detection ran twice over one snapshot, and counting it would let a
        replay manufacture confidence. `confirmations` only advances when the
        observation is new.
        """
        insert_statement = (
            insert(OpportunitySignal)
            .values(
                opportunity_id=opportunity_id,
                mint_address=mint_address,
                signal_type=signal_type,
                provider_id=provider_id,
                status=SignalStatus.PENDING.value,
                severity=severity,
                strength=strength,
                confirmations=1,
                observations=observations,
                detected_at=detected_at,
                last_confirmed_at=detected_at,
                expires_at=expires_at,
                observed_at=observed_at,
                reason_codes=list(reason_codes),
                evidence=list(evidence),
            )
            .on_conflict_do_nothing(
                index_elements=[
                    OpportunitySignal.opportunity_id,
                    OpportunitySignal.signal_type,
                    OpportunitySignal.provider_id,
                ]
            )
            .returning(OpportunitySignal)
        )
        created = await self._session.scalar(insert_statement)
        if created is not None:
            return created, True

        existing = await self._session.scalar(
            select(OpportunitySignal).where(
                OpportunitySignal.opportunity_id == opportunity_id,
                OpportunitySignal.signal_type == signal_type,
                OpportunitySignal.provider_id == provider_id,
            )
        )
        if existing is None:  # pragma: no cover - the unique key guarantees it
            raise RuntimeError(
                f"signal insert for {mint_address}/{signal_type} conflicted but no row exists"
            )

        repeat = existing.observed_at is not None and existing.observed_at == observed_at
        if not repeat:
            existing.confirmations += 1
            existing.last_confirmed_at = detected_at
            existing.observed_at = observed_at
            existing.observations = observations
            existing.strength = strength
            # Re-detection restarts the TTL: the transition is still true now.
            existing.expires_at = expires_at
            existing.reason_codes = list(reason_codes)
            existing.evidence = list(evidence)
        if existing.status in {SignalStatus.EXPIRED.value, SignalStatus.INVALIDATED.value}:
            # A re-detected signal is live again. Its opportunity's own status
            # is resolved separately, by the state machine.
            existing.status = SignalStatus.PENDING.value

        await self._session.flush()
        return existing, False

    async def set_signal_confidence(
        self, signal: OpportunitySignal, *, confidence: Decimal, status: SignalStatus
    ) -> None:
        signal.confidence = confidence
        signal.status = status.value
        await self._session.flush()

    async def expire_signals(
        self, *, now: datetime, opportunity_ids: Sequence[uuid.UUID] | None = None
    ) -> int:
        """Mark every live signal past its TTL as expired. Returns how many.

        A set-based update rather than a row-by-row pass: expiry is a pure
        function of `expires_at` and the clock, so there is nothing per-row to
        decide.
        """
        statement = (
            update(OpportunitySignal)
            .where(
                OpportunitySignal.status.in_(_LIVE_SIGNAL_VALUES),
                OpportunitySignal.expires_at <= now,
            )
            .values(status=SignalStatus.EXPIRED.value)
        )
        if opportunity_ids is not None:
            unique = list(dict.fromkeys(opportunity_ids))
            if not unique:
                return 0
            statement = statement.where(OpportunitySignal.opportunity_id.in_(unique))

        result = await self._session.execute(statement)
        await self._session.flush()
        # CursorResult carries rowcount; the generic Result protocol does not.
        return int(getattr(result, "rowcount", 0) or 0)
