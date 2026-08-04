"""Market snapshot and enrichment-state persistence.

Database access only — no provider calls, no scheduling decisions. The worker
and service pass in already-computed values.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import CursorResult, Select, and_, func, select, true, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased

from app.models.market import (
    EnrichmentStatus,
    TokenEnrichmentState,
    TokenMarketSnapshot,
)
from app.models.token import DiscoveredToken
from app.repositories.base import BaseRepository


class MarketSnapshotRepository(BaseRepository[TokenMarketSnapshot]):
    """Append-only history. Nothing here ever updates a snapshot."""

    model = TokenMarketSnapshot

    async def add_snapshot(self, values: dict[str, Any]) -> TokenMarketSnapshot:
        snapshot = TokenMarketSnapshot(**values)
        self.session.add(snapshot)
        await self.session.flush()
        await self.session.refresh(snapshot)
        return snapshot

    async def add_many(self, rows: Sequence[dict[str, Any]]) -> int:
        """Bulk insert. Used by the worker to write a whole batch in one round trip."""
        if not rows:
            return 0
        await self.session.execute(pg_insert(TokenMarketSnapshot).values(list(rows)))
        return len(rows)

    async def latest_for_mint(self, mint_address: str) -> TokenMarketSnapshot | None:
        stmt = (
            select(TokenMarketSnapshot)
            .where(TokenMarketSnapshot.mint_address == mint_address)
            .order_by(TokenMarketSnapshot.captured_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def latest_for_mints(
        self, mints: Sequence[str]
    ) -> dict[str, TokenMarketSnapshot]:
        """Newest snapshot per mint, for a batch, in one query.

        The board renders market data for a whole page of cards, and a query per
        card is what turns one page load into twenty-five round trips. `DISTINCT
        ON` rides the `(mint_address, captured_at DESC)` index for the same
        reason `latest_per_token` uses it.

        A mint with no snapshot is simply absent from the result. That is the
        honest shape: the caller must render "no market data" rather than a
        zero, because a token nobody has priced yet is not a token worth $0.
        """
        unique = list(dict.fromkeys(mints))
        if not unique:
            return {}

        stmt = (
            select(TokenMarketSnapshot)
            .distinct(TokenMarketSnapshot.mint_address)
            .where(TokenMarketSnapshot.mint_address.in_(unique))
            .order_by(
                TokenMarketSnapshot.mint_address,
                TokenMarketSnapshot.captured_at.desc(),
            )
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return {row.mint_address: row for row in rows}

    async def price_as_of_for_mints(
        self, mints: Sequence[str], *, as_of: datetime
    ) -> dict[str, Decimal]:
        """Each mint's last observed price at or before `as_of`, batched.

        The platform stores no `price_change_24h` column, and it should not
        start: a stored delta is a second copy of what the history already says
        and drifts the moment a snapshot is corrected or pruned. The change is
        derived at read time from the two readings that actually exist.

        A mint absent from the result had no observation that far back — it is
        newer than the window. The caller must render no change rather than
        0%, because "unchanged" and "we were not watching yet" are different
        claims and only one of them is true.
        """
        unique = list(dict.fromkeys(mints))
        if not unique:
            return {}

        stmt = (
            select(TokenMarketSnapshot)
            .distinct(TokenMarketSnapshot.mint_address)
            .where(
                TokenMarketSnapshot.mint_address.in_(unique),
                TokenMarketSnapshot.captured_at <= as_of,
                TokenMarketSnapshot.price_usd.is_not(None),
            )
            .order_by(
                TokenMarketSnapshot.mint_address,
                TokenMarketSnapshot.captured_at.desc(),
            )
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return {
            row.mint_address: row.price_usd
            for row in rows
            if row.price_usd is not None and row.price_usd > 0
        }

    async def history_for_mint(
        self,
        mint_address: str,
        *,
        offset: int = 0,
        limit: int = 50,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[Sequence[TokenMarketSnapshot], int]:
        def _filtered(stmt: Select[Any]) -> Select[Any]:
            stmt = stmt.where(TokenMarketSnapshot.mint_address == mint_address)
            if since is not None:
                stmt = stmt.where(TokenMarketSnapshot.captured_at >= since)
            if until is not None:
                stmt = stmt.where(TokenMarketSnapshot.captured_at <= until)
            return stmt

        rows_stmt = (
            _filtered(select(TokenMarketSnapshot))
            .order_by(TokenMarketSnapshot.captured_at.desc())
            .offset(offset)
            .limit(limit)
        )
        count_stmt = _filtered(select(func.count()).select_from(TokenMarketSnapshot))

        rows = (await self.session.execute(rows_stmt)).scalars().all()
        total = int((await self.session.execute(count_stmt)).scalar_one())
        return rows, total

    async def window_for_mints(
        self,
        mint_addresses: Sequence[str],
        *,
        since: datetime,
        limit_per_mint: int,
    ) -> dict[str, list[TokenMarketSnapshot]]:
        """Up to N recent snapshots for each of several mints, newest first.

        One round trip for a whole scoring batch. `ROW_NUMBER() OVER (PARTITION
        BY mint_address ORDER BY captured_at DESC)` takes the head of each
        token's history in a single pass over
        `ix_snapshots_mint_captured_desc`, where the obvious alternative - a
        query per mint - would be one round trip per token per cycle.

        `since` is the widest window in the batch. Tokens whose own tier implies
        a narrower window are trimmed in memory by the caller, because the
        window is a per-token property and this is a single statement.
        """
        if not mint_addresses:
            return {}

        ranked = (
            select(
                TokenMarketSnapshot,
                func.row_number()
                .over(
                    partition_by=TokenMarketSnapshot.mint_address,
                    order_by=TokenMarketSnapshot.captured_at.desc(),
                )
                .label("rn"),
            )
            .where(
                TokenMarketSnapshot.mint_address.in_(mint_addresses),
                TokenMarketSnapshot.captured_at >= since,
            )
            .subquery("ranked")
        )
        Ranked = aliased(TokenMarketSnapshot, ranked)  # noqa: N806 - an ORM alias is a class

        stmt = (
            select(Ranked)
            .where(ranked.c.rn <= limit_per_mint)
            .order_by(Ranked.mint_address, Ranked.captured_at.desc())
        )

        window: dict[str, list[TokenMarketSnapshot]] = {}
        for snapshot in (await self.session.execute(stmt)).scalars().all():
            window.setdefault(snapshot.mint_address, []).append(snapshot)
        return window

    async def latest_per_token(
        self,
        *,
        offset: int = 0,
        limit: int = 20,
        order_by: str = "volume_24h",
        min_liquidity: float | None = None,
        since: datetime | None = None,
    ) -> tuple[Sequence[tuple[TokenMarketSnapshot, DiscoveredToken]], int]:
        """Latest snapshot per token, joined to the token, ranked for trending.

        `DISTINCT ON (mint_address) ... ORDER BY mint_address, captured_at DESC`
        is the Postgres-native way to take one row per group; it rides the
        `(mint_address, captured_at DESC)` index instead of sorting the whole
        table like a window-function or correlated-subquery formulation would.
        """
        newest = (
            select(TokenMarketSnapshot)
            .distinct(TokenMarketSnapshot.mint_address)
            .order_by(
                TokenMarketSnapshot.mint_address,
                TokenMarketSnapshot.captured_at.desc(),
            )
        )
        if since is not None:
            newest = newest.where(TokenMarketSnapshot.captured_at >= since)

        latest = newest.subquery("latest")
        # Map the subquery back onto the ORM class so callers get real
        # TokenMarketSnapshot instances rather than raw rows.
        Latest = aliased(TokenMarketSnapshot, latest)  # noqa: N806 — an ORM alias is a class

        sortable = {
            "volume_24h": Latest.volume_24h,
            "volume_1h": Latest.volume_1h,
            "volume_5m": Latest.volume_5m,
            "liquidity_usd": Latest.liquidity_usd,
            "market_cap": Latest.market_cap,
            "price_usd": Latest.price_usd,
            "captured_at": Latest.captured_at,
        }
        sort_column = sortable.get(order_by, Latest.volume_24h)

        conditions = []
        if min_liquidity is not None:
            conditions.append(Latest.liquidity_usd >= min_liquidity)
        where = and_(*conditions) if conditions else true()

        rows_stmt = (
            select(Latest, DiscoveredToken)
            .join(DiscoveredToken, DiscoveredToken.id == Latest.token_id)
            .where(where)
            # NULLS LAST: a token with no recorded volume must not outrank one
            # that has volume, and NULL sorts first in Postgres DESC ordering.
            .order_by(sort_column.desc().nullslast(), Latest.mint_address)
            .offset(offset)
            .limit(limit)
        )
        count_stmt = select(func.count()).select_from(latest).where(where)

        rows = (await self.session.execute(rows_stmt)).all()
        total = int((await self.session.execute(count_stmt)).scalar_one())
        return [(row[0], row[1]) for row in rows], total

    async def count_for_mint(self, mint_address: str) -> int:
        stmt = (
            select(func.count())
            .select_from(TokenMarketSnapshot)
            .where(TokenMarketSnapshot.mint_address == mint_address)
        )
        return int((await self.session.execute(stmt)).scalar_one())


class EnrichmentStateRepository(BaseRepository[TokenEnrichmentState]):
    model = TokenEnrichmentState

    async def get_by_mint(self, mint_address: str) -> TokenEnrichmentState | None:
        stmt = select(TokenEnrichmentState).where(
            TokenEnrichmentState.mint_address == mint_address
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def ensure_state(
        self, *, token_id: uuid.UUID, mint_address: str, next_refresh_at: datetime
    ) -> TokenEnrichmentState | None:
        """Create the scheduling row for a token if it has none.

        `ON CONFLICT DO NOTHING` so the discovery listener and the backfill
        sweep can both call it without racing.
        """
        stmt = (
            pg_insert(TokenEnrichmentState)
            .values(
                token_id=token_id,
                mint_address=mint_address,
                next_refresh_at=next_refresh_at,
                status=EnrichmentStatus.ACTIVE,
            )
            .on_conflict_do_nothing(index_elements=[TokenEnrichmentState.mint_address])
            .returning(TokenEnrichmentState)
        )
        row = (await self.session.execute(stmt)).scalars().first()
        if row is not None:
            await self.session.flush()
        return row

    async def backfill_missing(self, *, limit: int = 500) -> int:
        """Create state rows for tokens discovered before enrichment existed."""
        missing = (
            select(DiscoveredToken.id, DiscoveredToken.mint_address)
            .outerjoin(
                TokenEnrichmentState,
                TokenEnrichmentState.token_id == DiscoveredToken.id,
            )
            .where(TokenEnrichmentState.id.is_(None))
            .limit(limit)
        )
        rows = (await self.session.execute(missing)).all()
        if not rows:
            return 0

        await self.session.execute(
            pg_insert(TokenEnrichmentState)
            .values(
                [
                    {
                        "token_id": token_id,
                        "mint_address": mint_address,
                        "status": EnrichmentStatus.ACTIVE,
                    }
                    for token_id, mint_address in rows
                ]
            )
            .on_conflict_do_nothing(index_elements=[TokenEnrichmentState.mint_address])
        )
        return len(rows)

    async def claim_due(
        self, *, now: datetime, limit: int, lease_seconds: int = 120
    ) -> Sequence[TokenEnrichmentState]:
        """Atomically claim tokens that are due for refresh.

        `FOR UPDATE SKIP LOCKED` inside a CTE is what makes this safe to run
        from multiple worker replicas: each claims a disjoint set instead of
        every worker fetching the same head of the queue. Claimed rows are
        pushed forward by `lease_seconds` so a worker that dies mid-batch
        releases its tokens automatically rather than stranding them.
        """
        due = (
            select(TokenEnrichmentState.id)
            .where(
                TokenEnrichmentState.status == EnrichmentStatus.ACTIVE,
                TokenEnrichmentState.next_refresh_at <= now,
            )
            .order_by(TokenEnrichmentState.next_refresh_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )

        claimed = (
            update(TokenEnrichmentState)
            .where(TokenEnrichmentState.id.in_(due))
            .values(
                last_attempt_at=now,
                next_refresh_at=now + timedelta(seconds=lease_seconds),
            )
            .returning(TokenEnrichmentState)
        )
        return (await self.session.execute(claimed)).scalars().all()

    async def record_result(
        self,
        state: TokenEnrichmentState,
        *,
        now: datetime,
        next_refresh_at: datetime,
        tier: str,
        succeeded: bool,
        had_data: bool,
        error: str | None = None,
        dead_letter: bool = False,
    ) -> TokenEnrichmentState:
        state.total_refreshes += 1
        state.next_refresh_at = next_refresh_at
        state.tier = tier
        state.last_attempt_at = now

        if succeeded:
            state.last_success_at = now
            state.consecutive_failures = 0
            state.last_error = None
            if had_data:
                state.total_snapshots += 1
                state.consecutive_empty = 0
            else:
                state.consecutive_empty += 1
        else:
            state.consecutive_failures += 1
            state.last_error = (error or "")[:500] or None

        if dead_letter:
            state.status = EnrichmentStatus.DEAD_LETTER

        await self.session.flush()
        return state

    async def counts_by_status(self) -> dict[str, int]:
        stmt = select(TokenEnrichmentState.status, func.count()).group_by(
            TokenEnrichmentState.status
        )
        return {
            str(status): int(count) for status, count in (await self.session.execute(stmt))
        }

    async def requeue_dead_letters(self, *, now: datetime, limit: int = 100) -> int:
        """Return dead-lettered tokens to the active queue (operator action)."""
        ids = (
            select(TokenEnrichmentState.id)
            .where(TokenEnrichmentState.status == EnrichmentStatus.DEAD_LETTER)
            .limit(limit)
            .scalar_subquery()
        )
        result = cast(
            "CursorResult[Any]",
            await self.session.execute(
                update(TokenEnrichmentState)
                .where(TokenEnrichmentState.id.in_(ids))
                .values(
                    status=EnrichmentStatus.ACTIVE,
                    consecutive_failures=0,
                    next_refresh_at=now,
                    last_error=None,
                )
            ),
        )
        return int(result.rowcount or 0)
