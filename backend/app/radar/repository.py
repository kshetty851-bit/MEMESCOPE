"""Radar database access.

One of the package's two I/O seams. Everything above this line is pure; this
file is the only place the Radar knows SQL exists.

The write path enforces the guarantee the whole track record rests on: **the
first-detection block is written exactly once.** `record_detection` inserts and
does nothing on conflict, so a re-detection — from a restart, a replay, or two
workers racing — can never rewrite the numbers the platform's returns are
measured from.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Select, String, func, literal_column, select
from sqlalchemy.dialects.postgresql import BIT, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.market import TokenMarketSnapshot
from app.models.radar import RadarAchievement, RadarSnapshot, RadarToken
from app.models.token import DiscoveredToken
from app.radar.models import Observation, RadarCandidate, RadarSeries


@dataclass(frozen=True, slots=True)
class PerformanceSummary:
    """Track-record aggregates.

    A dataclass rather than a dict so the API cannot mistake one figure for
    another, and so mypy checks the shape rather than every caller casting.
    """

    total: int
    active: int
    average_peak_multiple: Decimal | None
    median_current_multiple: Decimal | None
    best_peak_multiple: Decimal | None
    worst_current_multiple: Decimal | None
    tier_counts: dict[str, int]

    # --- Track-record additions ---------------------------------------------
    # Every field below is an aggregate over rows that already exist. Nothing
    # here is stored, and nothing is estimated: a figure with no rows behind it
    # is `None`, which the page renders as "—" rather than as zero.
    median_peak_multiple: Decimal | None = None
    #: Mean drawdown from peak, as a fraction: 0.94 means the average entry
    #: gave back 94% of its high. Computed only over entries that have both a
    #: peak and a current reading.
    average_drawdown: Decimal | None = None
    #: Mean days from detection to the first 2x, over entries that reached it.
    #: Read from `radar_achievements`, which records when each tier was hit —
    #: not inferred from the peak, which says nothing about *when*.
    average_days_to_2x: Decimal | None = None
    #: Mean days a detection has been tracked. Survival, not lifetime: nothing
    #: currently marks an entry inactive, so this is age, and the page says so.
    average_days_tracked: Decimal | None = None
    average_detection_market_cap: Decimal | None = None
    average_peak_market_cap: Decimal | None = None
    #: The largest peak market cap any single detection ever reached.
    largest_peak_market_cap: Decimal | None = None
    average_current_multiple: Decimal | None = None
    #: Mean days from detection to the first 5x, over entries that reached it.
    average_days_to_5x: Decimal | None = None
    above_entry: int = 0
    below_entry: int = 0
    #: When the most recent detection was recorded. Distinct from "last
    #: updated": one says when the Radar last found something, the other when
    #: this page was rendered.
    last_detection_at: datetime | None = None


class RadarRepository:
    """All Radar persistence. Holds a session; owns no transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- Reading market history ---------------------------------------------

    def _pumpfun_candidate_statement(
        self,
        *,
        program_id: str,
        min_age_days: int,
        max_age_days: int,
        min_market_cap: Decimal,
        min_liquidity: Decimal,
        now: datetime,
    ) -> Select[tuple[DiscoveredToken, TokenMarketSnapshot]]:
        """Latest enriched snapshot for each eligible Pump.fun discovery.

        The scanner owns creation facts and the enrichment worker owns market
        facts. Selecting them together at read time preserves that ownership
        and avoids a second mutable copy solely for the Radar admission stage.
        """
        latest = select(
            TokenMarketSnapshot.id.label("snapshot_id"),
            func.row_number()
            .over(
                partition_by=TokenMarketSnapshot.mint_address,
                order_by=TokenMarketSnapshot.captured_at.desc(),
            )
            .label("rank"),
        ).subquery()
        oldest_creation = now - timedelta(days=max_age_days)
        newest_creation = now - timedelta(days=min_age_days)

        return (
            select(DiscoveredToken, TokenMarketSnapshot)
            .join(latest, latest.c.snapshot_id == TokenMarketSnapshot.id)
            .join(
                DiscoveredToken,
                DiscoveredToken.mint_address == TokenMarketSnapshot.mint_address,
            )
            .where(
                latest.c.rank == 1,
                DiscoveredToken.source_program == program_id,
                DiscoveredToken.block_time.is_not(None),
                DiscoveredToken.block_time >= oldest_creation,
                DiscoveredToken.block_time <= newest_creation,
                TokenMarketSnapshot.market_cap >= min_market_cap,
                TokenMarketSnapshot.liquidity_usd >= min_liquidity,
            )
            .order_by(TokenMarketSnapshot.captured_at.desc())
        )

    async def pumpfun_candidates(
        self,
        *,
        program_id: str,
        min_age_days: int,
        max_age_days: int,
        min_market_cap: Decimal,
        min_liquidity: Decimal,
        now: datetime,
        limit: int,
        offset: int = 0,
    ) -> list[RadarCandidate]:
        statement = (
            self._pumpfun_candidate_statement(
                program_id=program_id,
                min_age_days=min_age_days,
                max_age_days=max_age_days,
                min_market_cap=min_market_cap,
                min_liquidity=min_liquidity,
                now=now,
            )
            .limit(limit)
            .offset(offset)
        )
        rows = (await self._session.execute(statement)).all()
        return [
            RadarCandidate(
                token_address=token.mint_address,
                name=token.name,
                symbol=token.symbol,
                creation_time=token.block_time,
                age_days=Decimal(max((now - token.block_time).total_seconds(), 0))
                / Decimal(86_400),
                market_cap=snapshot.market_cap,
                liquidity=snapshot.liquidity_usd,
                volume_24h=snapshot.volume_24h,
                # No provider supplies holders yet. The candidate contract is
                # ready for it, but discovery must not invent an estimate.
                holder_count=None,
                last_scan_time=snapshot.captured_at,
            )
            for token, snapshot in rows
            if token.block_time is not None
        ]

    async def count_pumpfun_candidates(
        self,
        *,
        program_id: str,
        min_age_days: int,
        max_age_days: int,
        min_market_cap: Decimal,
        min_liquidity: Decimal,
        now: datetime,
    ) -> int:
        statement = self._pumpfun_candidate_statement(
            program_id=program_id,
            min_age_days=min_age_days,
            max_age_days=max_age_days,
            min_market_cap=min_market_cap,
            min_liquidity=min_liquidity,
            now=now,
        ).order_by(None)
        total = await self._session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        return int(total or 0)

    async def load_series(self, mint_address: str, *, limit: int = 96) -> RadarSeries | None:
        """The observation window the engine scores.

        Ordered oldest-first for the engine, but selected newest-first so the
        index is used and only `limit` rows are read — a token with months of
        history would otherwise pull thousands of rows to use the last few.
        """
        statement = (
            select(TokenMarketSnapshot)
            .where(TokenMarketSnapshot.mint_address == mint_address)
            .order_by(TokenMarketSnapshot.captured_at.desc())
            .limit(limit)
        )
        rows = list((await self._session.scalars(statement)).all())
        if not rows:
            return None

        rows.reverse()
        return RadarSeries(
            mint_address=mint_address,
            observations=[
                Observation(
                    captured_at=row.captured_at,
                    price_usd=row.price_usd,
                    market_cap=row.market_cap,
                    liquidity_usd=row.liquidity_usd,
                    volume_24h=row.volume_24h,
                    volume_1h=row.volume_1h,
                    buy_count_24h=row.buy_count_24h,
                    sell_count_24h=row.sell_count_24h,
                )
                for row in rows
            ],
        )

    async def candidate_mints(self, *, limit: int, min_observations: int = 12) -> list[str]:
        """The hot window: tokens observed most recently.

        Deliberately *not* filtered by age — the Radar's premise is that a
        ninety-day-old project can be the opportunity — but ordered by most
        recent observation so a new launch is assessed while it is still new.

        **This ordering alone cannot cover the universe, and must not be used
        alone.** Measured on live data, 978 mints were snapshotted inside one
        15-minute sweep interval, so the top 500 spans about 1.8 minutes.
        Everything observed earlier sits below the limit forever: position 5,000
        was last seen 32 minutes ago and position 23,355 sixty-two hours ago.
        Those tokens were not evaluated slowly, they were never evaluated at
        all — 22,400 eligible projects could not enter the Radar however good
        they were.

        `rotating_mints` is the other half. Use both.
        """
        statement = (
            select(
                TokenMarketSnapshot.mint_address,
                func.count().label("observations"),
                func.max(TokenMarketSnapshot.captured_at).label("latest"),
            )
            .group_by(TokenMarketSnapshot.mint_address)
            .having(func.count() >= min_observations)
            .order_by(func.max(TokenMarketSnapshot.captured_at).desc())
            .limit(limit)
        )
        return [row.mint_address for row in (await self._session.execute(statement)).all()]

    async def rotating_mints(
        self,
        *,
        limit: int,
        bucket: int,
        buckets: int,
        min_observations: int = 12,
    ) -> list[str]:
        """One deterministic slice of the whole eligible universe.

        Every eligible mint belongs to exactly one bucket, chosen by a stable
        hash of its address. Each sweep processes the next bucket, so the entire
        population is covered in `buckets` sweeps and every project gets a turn
        regardless of when it was last observed.

        **Why a hash rather than a timestamp.** Rotating by "least recently
        evaluated" is the obvious approach and it cannot work here: a candidate
        that is evaluated and *not* detected leaves no record — the Radar
        deliberately stores only what it detected — so there is no per-token
        evaluation timestamp to sort by. Recording every attempt would mean a
        new table written 500 times a sweep purely for scheduling.

        Hashing needs no state at all. It is stable across restarts, identical
        on every replica, and spreads evenly because the input is a base58
        address rather than anything correlated with quality.

        MD5 rather than `hashtext`: the latter is an undocumented internal whose
        value has changed between major versions, which would silently reshuffle
        every bucket during an upgrade and skip a slice of the universe for one
        full rotation.
        """
        if buckets < 1:
            raise ValueError("buckets must be at least 1")
        if not 0 <= bucket < buckets:
            raise ValueError(f"bucket {bucket} outside range 0..{buckets - 1}")

        # ('x' || first 8 hex chars)::bit(32)::bigint gives a stable signed
        # 32-bit integer; abs() before the modulo so negatives cannot fold two
        # buckets onto one.
        bucket_of = func.mod(
            func.abs(
                func.cast(
                    func.cast(
                        literal_column("'x'", String)
                        + func.substr(func.md5(TokenMarketSnapshot.mint_address), 1, 8),
                        BIT(32),
                    ),
                    BigInteger,
                )
            ),
            buckets,
        )

        statement = (
            select(TokenMarketSnapshot.mint_address)
            .group_by(TokenMarketSnapshot.mint_address)
            .having(func.count() >= min_observations)
            .having(bucket_of == bucket)
            # Least recently observed first *within* the bucket, so a slice that
            # overflows the limit still favours the tokens most overdue a look.
            .order_by(func.max(TokenMarketSnapshot.captured_at).asc())
            .limit(limit)
        )
        return list((await self._session.scalars(statement)).all())

    async def token_id_for(self, mint_address: str) -> uuid.UUID | None:
        found: uuid.UUID | None = await self._session.scalar(
            select(DiscoveredToken.id).where(DiscoveredToken.mint_address == mint_address)
        )
        return found

    async def names_for(
        self, mint_addresses: Sequence[str]
    ) -> dict[str, tuple[str | None, str | None]]:
        """Display name and symbol per mint, for the mints on one page.

        `radar_tokens` deliberately stores no name or symbol: identity belongs
        to `discovered_tokens` and duplicating it would let the two disagree.
        The API still has to render a name, so it is resolved here — one query
        per request keyed by the page's mints, rather than a per-entry lookup.

        A mint with no discovery row, or with a null name, is simply absent;
        callers fall back to the mint address.
        """
        if not mint_addresses:
            return {}

        statement = select(
            DiscoveredToken.mint_address, DiscoveredToken.name, DiscoveredToken.symbol
        ).where(DiscoveredToken.mint_address.in_(list(dict.fromkeys(mint_addresses))))

        return {
            row.mint_address: (row.name, row.symbol)
            for row in (await self._session.execute(statement)).all()
        }

    async def tracked_mints(self, *, limit: int) -> list[str]:
        """Mints already on the Radar, stalest first.

        `candidate_mints` ranks by most recent observation, so it surfaces
        whatever enrichment touched last — overwhelmingly brand-new tokens. A
        token that has *already* been detected drops out of that window within
        minutes and would then never be re-evaluated again, freezing its
        `current_*` and `peak_*` values at their detection-time readings.

        Ordering by `last_evaluated_at` ascending gives every tracked entry a
        turn, so the refresh interval degrades predictably as the Radar grows
        instead of leaving an arbitrary subset permanently stale.
        """
        statement = (
            select(RadarToken.mint_address)
            .where(RadarToken.is_active.is_(True))
            .order_by(RadarToken.last_evaluated_at.asc())
            .limit(limit)
        )
        return list((await self._session.scalars(statement)).all())

    # --- Writing ------------------------------------------------------------

    async def record_detection(self, **values: object) -> RadarToken | None:
        """Insert a first detection. Returns `None` if one already existed.

        `ON CONFLICT DO NOTHING` rather than an upsert, deliberately. The
        first-detection numbers are the denominator of every return the platform
        reports; an upsert here would silently reset them and quietly improve
        the track record every time a token was re-detected.
        """
        statement = (
            insert(RadarToken)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[RadarToken.mint_address])
            .returning(RadarToken)
        )
        inserted: RadarToken | None = await self._session.scalar(statement)
        return inserted

    async def get(self, mint_address: str) -> RadarToken | None:
        found: RadarToken | None = await self._session.scalar(
            select(RadarToken).where(RadarToken.mint_address == mint_address)
        )
        return found

    async def update_current(
        self,
        entry: RadarToken,
        *,
        price: Decimal | None,
        market_cap: Decimal | None,
        liquidity: Decimal | None,
        score: Decimal,
        confidence: Decimal,
        category: str,
        current_multiple: Decimal | None,
        evaluated_at: datetime,
        window_high: Decimal | None = None,
    ) -> None:
        """Move the current-state columns, and raise the peak if it has risen.

        The peak is **monotonic**: it is only ever raised. A later crash, a
        provider outage or a bad snapshot cannot erase a high the token
        genuinely reached, which is what lets the track record report peak
        return honestly rather than optimistically.

        `window_high` is the highest price anywhere in the observed window, and
        it is what the peak is actually measured against. Using the latest price
        alone meant a high reached between two sweeps was invisible — the sweep
        cadence is fifteen minutes, enrichment writes every thirty seconds, and
        the snapshot holding the high was already stored. It defaults to `None`
        so existing callers keep their previous behaviour rather than silently
        changing meaning.
        """
        entry.current_price = price
        entry.current_market_cap = market_cap
        entry.current_liquidity = liquidity
        entry.current_opportunity_score = score
        entry.current_confidence = confidence
        entry.current_category = category
        entry.current_multiple = current_multiple
        entry.last_evaluated_at = evaluated_at

        # Take the higher of the window's high and the current price. The
        # current price is still considered because a window that somehow
        # excludes it must not lower the peak.
        candidate = max(
            (value for value in (price, window_high) if value is not None),
            default=None,
        )

        if candidate is not None and (
            entry.peak_price is None or candidate > entry.peak_price
        ):
            entry.peak_price = candidate
            # Market cap is only carried across when the peak is the *current*
            # observation. A historical high has no market cap stored beside it
            # here, and inventing one by reusing today's would be wrong.
            if price is not None and candidate == price:
                entry.peak_market_cap = market_cap
            entry.peak_at = evaluated_at
            if entry.first_price is not None and entry.first_price > 0:
                entry.peak_multiple = candidate / entry.first_price

    async def add_snapshot(self, **values: object) -> None:
        self._session.add(RadarSnapshot(**values))

    async def latest_snapshot(self, radar_token_id: uuid.UUID) -> RadarSnapshot | None:
        found: RadarSnapshot | None = await self._session.scalar(
            select(RadarSnapshot)
            .where(RadarSnapshot.radar_token_id == radar_token_id)
            .order_by(RadarSnapshot.captured_at.desc())
            .limit(1)
        )
        return found

    async def snapshots(
        self, mint_address: str, *, limit: int = 200
    ) -> Sequence[RadarSnapshot]:
        return (
            await self._session.scalars(
                select(RadarSnapshot)
                .where(RadarSnapshot.mint_address == mint_address)
                .order_by(RadarSnapshot.captured_at.desc())
                .limit(limit)
            )
        ).all()

    # --- Achievements --------------------------------------------------------

    async def earned_multiples(self, radar_token_id: uuid.UUID) -> list[Decimal]:
        rows = await self._session.scalars(
            select(RadarAchievement.multiple).where(
                RadarAchievement.radar_token_id == radar_token_id
            )
        )
        return list(rows.all())

    async def record_achievement(self, **values: object) -> None:
        """Insert a milestone, ignoring one already recorded.

        Concurrency-safe rather than check-then-insert: two workers evaluating
        the same token in the same cycle would otherwise both see the tier as
        unearned and both insert it.
        """
        await self._session.execute(
            insert(RadarAchievement)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[RadarAchievement.radar_token_id, RadarAchievement.tier]
            )
        )

    async def achievements(
        self, *, mint_address: str | None = None, limit: int = 100
    ) -> Sequence[RadarAchievement]:
        statement = select(RadarAchievement).order_by(RadarAchievement.achieved_at.desc())
        if mint_address is not None:
            statement = statement.where(RadarAchievement.mint_address == mint_address)
        return (await self._session.scalars(statement.limit(limit))).all()

    # --- Reading the Radar ---------------------------------------------------

    def _base_query(self) -> Select[tuple[RadarToken]]:
        return select(RadarToken)

    async def list_entries(
        self,
        *,
        category: str | None = None,
        active_only: bool = True,
        sort: str = "score",
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[RadarToken]:
        statement = self._base_query()
        if category is not None:
            statement = statement.where(RadarToken.current_category == category)
        if active_only:
            statement = statement.where(RadarToken.is_active.is_(True))

        orders: dict[str, ColumnElement[Any]] = {
            "score": RadarToken.current_opportunity_score.desc(),
            "detected": RadarToken.first_detected_at.desc(),
            "peak": RadarToken.peak_multiple.desc().nullslast(),
            "current": RadarToken.current_multiple.desc().nullslast(),
        }
        # Ordering is made total with the mint, so a page is deterministic even
        # when many rows share a score — the same defect §13 records for
        # `/scores/top` is not worth reproducing here.
        statement = statement.order_by(
            orders.get(sort, orders["score"]), RadarToken.mint_address
        )
        return (await self._session.scalars(statement.offset(offset).limit(limit))).all()

    async def count_entries(
        self, *, category: str | None = None, active_only: bool = True
    ) -> int:
        statement = select(func.count()).select_from(RadarToken)
        if category is not None:
            statement = statement.where(RadarToken.current_category == category)
        if active_only:
            statement = statement.where(RadarToken.is_active.is_(True))
        return await self._session.scalar(statement) or 0

    async def performance_summary(self) -> PerformanceSummary:
        """Aggregates for the track record page.

        Computed in SQL rather than by loading every row: the record is
        append-only and grows without bound, and the page must stay fast when
        it holds a hundred thousand entries.
        """
        totals = (
            await self._session.execute(
                select(
                    func.count().label("total"),
                    func.count().filter(RadarToken.is_active.is_(True)).label("active"),
                    func.avg(RadarToken.peak_multiple).label("avg_peak"),
                    func.percentile_cont(0.5)
                    .within_group(RadarToken.current_multiple.asc())
                    .label("median_current"),
                    func.max(RadarToken.peak_multiple).label("best_peak"),
                    func.min(RadarToken.current_multiple).label("worst_current"),
                    func.percentile_cont(0.5)
                    .within_group(RadarToken.peak_multiple.asc())
                    .label("median_peak"),
                    # Drawdown is derived here rather than stored: it is a pure
                    # function of two columns on the same row, and a stored copy
                    # would drift the moment either is corrected.
                    func.avg(
                        (RadarToken.peak_multiple - RadarToken.current_multiple)
                        / func.nullif(RadarToken.peak_multiple, 0)
                    ).label("avg_drawdown"),
                    func.avg(
                        func.extract(
                            "epoch", func.now() - RadarToken.first_detected_at
                        )
                        / 86400.0
                    ).label("avg_days_tracked"),
                    func.avg(RadarToken.first_market_cap).label("avg_detection_mcap"),
                    func.avg(RadarToken.peak_market_cap).label("avg_peak_mcap"),
                    func.max(RadarToken.peak_market_cap).label("largest_peak_mcap"),
                    func.avg(RadarToken.current_multiple).label("avg_current"),
                    func.count()
                    .filter(RadarToken.current_multiple >= 1)
                    .label("above_entry"),
                    func.count()
                    .filter(RadarToken.current_multiple < 1)
                    .label("below_entry"),
                    func.max(RadarToken.first_detected_at).label("last_detection"),
                )
            )
        ).one()

        # Time-to-2x comes from the achievement row, which records *when* the
        # tier was crossed. Peak multiple cannot answer this: a token that ended
        # at 30x says nothing about how long it took to first double.
        # Both tiers in one grouped pass rather than a query each.
        tier_days = {
            str(tier): value
            for tier, value in (
                await self._session.execute(
                    select(
                        RadarAchievement.tier,
                        func.avg(RadarAchievement.days_to_achieve),
                    )
                    .where(RadarAchievement.tier.in_(["2x", "5x"]))
                    .group_by(RadarAchievement.tier)
                )
            ).all()
        }

        # Tier counts come from the achievement table rather than by comparing
        # peak_multiple, so the two can never disagree about what was reached.
        tiers = (
            await self._session.execute(
                select(RadarAchievement.tier, func.count())
                .group_by(RadarAchievement.tier)
                .order_by(func.count().desc())
            )
        ).all()

        return PerformanceSummary(
            total=int(totals.total or 0),
            active=int(totals.active or 0),
            average_peak_multiple=totals.avg_peak,
            median_current_multiple=totals.median_current,
            best_peak_multiple=totals.best_peak,
            worst_current_multiple=totals.worst_current,
            tier_counts={str(tier): int(count) for tier, count in tiers},
            median_peak_multiple=totals.median_peak,
            average_drawdown=totals.avg_drawdown,
            average_days_to_2x=tier_days.get("2x"),
            average_days_to_5x=tier_days.get("5x"),
            average_days_tracked=totals.avg_days_tracked,
            average_detection_market_cap=totals.avg_detection_mcap,
            average_peak_market_cap=totals.avg_peak_mcap,
            largest_peak_market_cap=totals.largest_peak_mcap,
            average_current_multiple=totals.avg_current,
            above_entry=int(totals.above_entry or 0),
            below_entry=int(totals.below_entry or 0),
            last_detection_at=totals.last_detection,
        )

    async def all_mints(self) -> list[str]:
        """Every mint on the record. Small by construction — admission is
        strict — and needed whole because liveness is a summary over all of
        them, not over a page."""
        rows = await self._session.scalars(select(RadarToken.mint_address))
        return [str(mint) for mint in rows]

    async def observed_within(self, mints: Sequence[str], *, since: datetime) -> set[str]:
        """Mints with a market observation at or after `since`, batched.

        This is the *only* liveness signal the platform can defend. Nothing in
        the system establishes that a token has died — no rule marks one
        inactive, and "the price went to zero" is a price, not a death. What is
        measurable is whether the market was observed recently, so that is what
        is reported: a mint in this set is `alive`, one outside it is `unknown`.

        `inactive` is deliberately never returned. Inventing a death rule would
        put a permanent, wrong verdict on the permanent record.
        """
        unique = list(dict.fromkeys(mints))
        if not unique:
            return set()

        rows = await self._session.scalars(
            select(TokenMarketSnapshot.mint_address)
            .where(
                TokenMarketSnapshot.mint_address.in_(unique),
                TokenMarketSnapshot.captured_at >= since,
            )
            .distinct()
        )
        return {str(mint) for mint in rows}

    async def timeline(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """The Radar's own history, newest first, from stored events only.

        Two kinds of event exist in the record and both carry their own
        timestamp: a detection (`radar_tokens.first_detected_at`) and a tier
        crossing (`radar_achievements.achieved_at`). They are unioned and
        ordered — nothing is synthesised, and no event is written for this feed.

        Deliberately not a table: it is a projection of rows that already exist,
        so it can never disagree with them and needs no backfill.
        """
        detections: Select[Any] = select(
            literal_column("'detection'").label("kind"),
            RadarToken.mint_address.label("mint_address"),
            RadarToken.first_detected_at.label("occurred_at"),
            literal_column("NULL::varchar").label("tier"),
            RadarToken.first_market_cap.label("market_cap"),
            RadarToken.first_opportunity_score.label("value"),
        )
        achievements: Select[Any] = select(
            literal_column("'achievement'").label("kind"),
            RadarAchievement.mint_address.label("mint_address"),
            RadarAchievement.achieved_at.label("occurred_at"),
            RadarAchievement.tier.label("tier"),
            RadarAchievement.market_cap_at_achievement.label("market_cap"),
            RadarAchievement.multiple.label("value"),
        )

        unioned = detections.union_all(achievements).subquery("events")
        rows = (
            await self._session.execute(
                select(unioned)
                .order_by(unioned.c.occurred_at.desc())
                .limit(limit)
            )
        ).all()

        return [
            {
                "kind": row.kind,
                "mint_address": row.mint_address,
                "occurred_at": row.occurred_at,
                "tier": row.tier,
                "market_cap": row.market_cap,
                "value": row.value,
            }
            for row in rows
        ]

    async def benchmark(self) -> dict[str, Decimal | int | None]:
        """What buying every detection equally would have returned.

        The one benchmark the stored history can answer. Each entry's
        `current_multiple` is its return from detection, so the mean across all
        of them *is* an equal-weight portfolio — no simulation, no assumed entry
        or exit, no position sizing.

        Holding SOL is deliberately absent: the platform stores no SOL price
        history, and a comparison against a series it never recorded would be
        fabricated. The page says so rather than showing a number.
        """
        row = (
            await self._session.execute(
                select(
                    func.count().label("entries"),
                    func.avg(RadarToken.current_multiple).label("avg_current"),
                    func.avg(RadarToken.peak_multiple).label("avg_peak"),
                    func.percentile_cont(0.5)
                    .within_group(RadarToken.current_multiple.asc())
                    .label("median_current"),
                    func.count()
                    .filter(RadarToken.current_multiple >= 1)
                    .label("above_entry"),
                    func.count()
                    .filter(RadarToken.current_multiple < 1)
                    .label("below_entry"),
                )
            )
        ).one()
        return {
            "entries": int(row.entries or 0),
            "average_current_multiple": row.avg_current,
            "average_peak_multiple": row.avg_peak,
            "median_current_multiple": row.median_current,
            "above_entry": int(row.above_entry or 0),
            "below_entry": int(row.below_entry or 0),
        }

    async def tiers_for(self, mints: Sequence[str]) -> dict[str, list[str]]:
        """Tiers each mint has ever reached, batched, ordered by multiple.

        One query for a whole page. Read from `radar_achievements` rather than
        recomputed from `peak_multiple` for the same reason the tier counts are:
        an achievement is a permanent fact recorded when it happened, and a
        badge derived from a live column would silently vanish if that column
        were ever corrected downward.
        """
        unique = list(dict.fromkeys(mints))
        if not unique:
            return {}

        rows = (
            await self._session.execute(
                select(RadarAchievement.mint_address, RadarAchievement.tier)
                .where(RadarAchievement.mint_address.in_(unique))
                .order_by(RadarAchievement.mint_address, RadarAchievement.multiple.asc())
            )
        ).all()

        collected: dict[str, list[str]] = {}
        for mint, tier in rows:
            collected.setdefault(str(mint), []).append(str(tier))
        return collected

    async def leaderboard(self, *, limit: int = 25) -> Sequence[RadarToken]:
        return (
            await self._session.scalars(
                select(RadarToken)
                .where(RadarToken.peak_multiple.is_not(None))
                .order_by(RadarToken.peak_multiple.desc(), RadarToken.mint_address)
                .limit(limit)
            )
        ).all()
