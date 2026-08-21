"""Discovered-token persistence."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Select, select
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.token import DiscoveredToken, MetadataStatus
from app.repositories.base import BaseRepository

SortField = Literal["discovered_at", "block_time", "slot", "name", "symbol"]
SortOrder = Literal["asc", "desc"]

_SORTABLE = {
    "discovered_at": DiscoveredToken.discovered_at,
    "block_time": DiscoveredToken.block_time,
    "slot": DiscoveredToken.slot,
    "name": DiscoveredToken.name,
    "symbol": DiscoveredToken.symbol,
}


class TokenRepository(BaseRepository[DiscoveredToken]):
    model = DiscoveredToken

    async def get_by_mint(self, mint_address: str) -> DiscoveredToken | None:
        stmt = select(DiscoveredToken).where(DiscoveredToken.mint_address == mint_address)
        return (await self.session.execute(stmt)).scalars().first()

    async def name_collisions(
        self, mint_addresses: Sequence[str]
    ) -> dict[str, tuple[int, int]]:
        """Per mint: how many tokens share its name, and how many predate it.

        Returns `{mint: (sharing_name, discovered_before)}`, counting the token
        itself in `sharing_name`. A mint whose name is null or blank is absent —
        an unnamed token cannot impersonate anything by name.

        Both halves matter and neither is sufficient alone. The cluster size
        says how contested a name is; the "discovered before" count says where
        in that queue this particular mint sits. The 1st token called *Puffins*
        and the 149th are very different propositions, and only the second
        number separates them.

        Two window functions over one scan rather than a correlated subquery
        per mint, which at 24k tokens and 333 clusters of ten-or-more would be
        the difference between one query and thousands.
        """
        if not mint_addresses:
            return {}

        named = (
            select(
                DiscoveredToken.mint_address,
                DiscoveredToken.name,
                sa_func.count().over(partition_by=DiscoveredToken.name).label("sharing_name"),
                sa_func.rank()
                .over(
                    partition_by=DiscoveredToken.name,
                    order_by=(
                        DiscoveredToken.discovered_at.asc(),
                        DiscoveredToken.mint_address.asc(),
                    ),
                )
                .label("arrival_rank"),
            )
            .where(DiscoveredToken.name.is_not(None))
            .where(DiscoveredToken.name != "")
            .subquery()
        )

        stmt = select(named.c.mint_address, named.c.sharing_name, named.c.arrival_rank).where(
            named.c.mint_address.in_(list(dict.fromkeys(mint_addresses)))
        )

        return {
            row.mint_address: (int(row.sharing_name), int(row.arrival_rank) - 1)
            for row in (await self.session.execute(stmt)).all()
        }

    async def get_many_by_mints(
        self, mint_addresses: Sequence[str]
    ) -> dict[str, DiscoveredToken]:
        """Fetch several tokens at once, keyed by mint.

        Used by the enrichment worker, which processes tokens in batches and
        would otherwise issue one query per token.
        """
        if not mint_addresses:
            return {}
        stmt = select(DiscoveredToken).where(
            DiscoveredToken.mint_address.in_(list(mint_addresses))
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return {row.mint_address: row for row in rows}

    async def discovered_after(
        self, *, watermark: datetime, limit: int, as_of: datetime | None = None
    ) -> Sequence[DiscoveredToken]:
        """Raw scanner discoveries after an experiment watermark, oldest first.

        This intentionally does not join Radar/scoring state.  It is the raw
        scanner stream used by the all-scanned paper experiment.
        """
        predicates = [DiscoveredToken.discovered_at > watermark]
        if as_of is not None:
            predicates.append(DiscoveredToken.discovered_at <= as_of)
        stmt = (
            select(DiscoveredToken)
            .where(*predicates)
            .order_by(DiscoveredToken.discovered_at.asc(), DiscoveredToken.mint_address.asc())
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def max_recent_slot(self, *, since: datetime) -> int | None:
        """The highest slot among recent discoveries — the durable gap marker
        for scanner recovery after a cold start.

        Bounded by `discovered_at` so the scan stays on the timestamp index; a
        gap older than the bound is past recovering anyway.
        """
        value = await self.session.scalar(
            select(sa_func.max(DiscoveredToken.slot)).where(
                DiscoveredToken.discovered_at >= since
            )
        )
        return int(value) if value is not None else None

    async def insert_if_absent(self, values: dict[str, Any]) -> DiscoveredToken | None:
        """Insert a token, ignoring it if the mint is already known.

        `ON CONFLICT DO NOTHING` makes this idempotent at the database level
        rather than in application code: two scanner workers racing on the same
        mint cannot both win, and no exception is raised for the loser. Returns
        the inserted row, or None when the mint already existed — which is
        precisely the signal for "should we broadcast this?".
        """
        stmt = (
            pg_insert(DiscoveredToken)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[DiscoveredToken.mint_address])
            .returning(DiscoveredToken)
        )
        result = await self.session.execute(stmt)
        row = result.scalars().first()
        if row is not None:
            await self.session.flush()
        return row

    async def update_metadata(
        self,
        token: DiscoveredToken,
        *,
        name: str | None,
        symbol: str | None,
        metadata_uri: str | None,
        image_url: str | None = None,
        decimals: int | None,
        status: MetadataStatus,
    ) -> DiscoveredToken:
        token.name = name or token.name
        token.symbol = symbol or token.symbol
        token.metadata_uri = metadata_uri or token.metadata_uri
        token.image_url = image_url or token.image_url
        if decimals is not None:
            token.decimals = decimals
        token.metadata_status = status
        token.metadata_attempts += 1
        await self.session.flush()
        await self.session.refresh(token)
        return token

    async def update_image_url(
        self, token: DiscoveredToken, *, image_url: str
    ) -> DiscoveredToken:
        """Persist a mint-owned token image without rewriting identity metadata."""
        token.image_url = image_url
        await self.session.flush()
        await self.session.refresh(token)
        return token

    async def list_missing_images(self, *, limit: int = 50) -> Sequence[DiscoveredToken]:
        """Tokens with metadata JSON available but no resolved token image."""
        stmt = (
            select(DiscoveredToken)
            .where(DiscoveredToken.metadata_uri.is_not(None))
            .where(DiscoveredToken.image_url.is_(None))
            .order_by(DiscoveredToken.discovered_at.desc(), DiscoveredToken.id.desc())
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def list_pending_metadata(self, *, limit: int = 50) -> Sequence[DiscoveredToken]:
        """Tokens whose metadata has not resolved yet, oldest first."""
        stmt = (
            select(DiscoveredToken)
            .where(DiscoveredToken.metadata_status == MetadataStatus.PENDING)
            .order_by(DiscoveredToken.discovered_at.asc())
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()

    def _apply_filters(
        self,
        stmt: Select[Any],
        *,
        created_after: datetime | None,
        created_before: datetime | None,
        discovered_after: datetime | None,
        discovered_before: datetime | None,
        symbol: str | None,
        creator_address: str | None,
        metadata_status: MetadataStatus | None,
    ) -> Select[Any]:
        # `created_*` filters on-chain creation time; `discovered_*` filters when
        # this system saw it. They answer different questions, so both exist.
        if created_after is not None:
            stmt = stmt.where(DiscoveredToken.block_time >= created_after)
        if created_before is not None:
            stmt = stmt.where(DiscoveredToken.block_time <= created_before)
        if discovered_after is not None:
            stmt = stmt.where(DiscoveredToken.discovered_at >= discovered_after)
        if discovered_before is not None:
            stmt = stmt.where(DiscoveredToken.discovered_at <= discovered_before)
        if symbol:
            stmt = stmt.where(DiscoveredToken.symbol.ilike(symbol))
        if creator_address:
            stmt = stmt.where(DiscoveredToken.creator_address == creator_address)
        if metadata_status is not None:
            stmt = stmt.where(DiscoveredToken.metadata_status == metadata_status)
        return stmt

    async def search(
        self,
        *,
        offset: int = 0,
        limit: int = 20,
        sort_by: SortField = "discovered_at",
        order: SortOrder = "desc",
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        discovered_after: datetime | None = None,
        discovered_before: datetime | None = None,
        symbol: str | None = None,
        creator_address: str | None = None,
        metadata_status: MetadataStatus | None = None,
    ) -> tuple[Sequence[DiscoveredToken], int]:
        """Return one page of tokens plus the total matching count."""
        filters: dict[str, Any] = {
            "created_after": created_after,
            "created_before": created_before,
            "discovered_after": discovered_after,
            "discovered_before": discovered_before,
            "symbol": symbol,
            "creator_address": creator_address,
            "metadata_status": metadata_status,
        }

        column = _SORTABLE[sort_by]
        ordering = column.desc() if order == "desc" else column.asc()

        stmt = self._apply_filters(select(DiscoveredToken), **filters)
        # id is a stable tiebreaker: without it, rows sharing a timestamp can
        # reappear on page 2 or vanish entirely.
        stmt = stmt.order_by(ordering, DiscoveredToken.id.desc()).offset(offset).limit(limit)

        count_stmt = self._apply_filters(
            select(sa_func.count()).select_from(DiscoveredToken), **filters
        )

        rows = (await self.session.execute(stmt)).scalars().all()
        total = int((await self.session.execute(count_stmt)).scalar_one())
        return rows, total

    async def latest(self, *, limit: int = 20) -> Sequence[DiscoveredToken]:
        stmt = (
            select(DiscoveredToken)
            .order_by(DiscoveredToken.discovered_at.desc(), DiscoveredToken.id.desc())
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()
