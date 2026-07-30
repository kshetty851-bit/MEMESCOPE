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
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.market import TokenMarketSnapshot
from app.models.radar import RadarAchievement, RadarSnapshot, RadarToken
from app.models.token import DiscoveredToken
from app.radar.models import Observation, RadarSeries


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


class RadarRepository:
    """All Radar persistence. Holds a session; owns no transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- Reading market history ---------------------------------------------

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
        """Tokens with enough history for the Radar to have an opinion.

        Deliberately *not* filtered by age: the Radar's premise is that a
        ninety-day-old project can be the opportunity. Ordered by most recently
        observed so an evaluation cycle spends its budget on live tokens.
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
                )
            )
        ).one()

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
        )

    async def leaderboard(self, *, limit: int = 25) -> Sequence[RadarToken]:
        return (
            await self._session.scalars(
                select(RadarToken)
                .where(RadarToken.peak_multiple.is_not(None))
                .order_by(RadarToken.peak_multiple.desc(), RadarToken.mint_address)
                .limit(limit)
            )
        ).all()
