"""Bonding curve persistence. Append-only, like the market history it sits beside."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.curve import TokenCurveSnapshot
from app.models.token import DiscoveredToken
from app.services.curve.state import CurveReading, CurveState


def progress_of(snapshot: TokenCurveSnapshot) -> Decimal | None:
    """Curve position for a stored observation, or `None` if unmeasurable.

    Rebuilds the domain state and asks it, rather than re-deriving the ratio
    here: the table stores raw account fields precisely so the derivation has
    exactly one home (`services/curve/state.py`). Two copies of it would drift
    the moment the layout is corrected against a live account.
    """
    return CurveState(
        virtual_token_reserves=int(snapshot.virtual_token_reserves),
        virtual_sol_reserves=int(snapshot.virtual_sol_reserves),
        real_token_reserves=int(snapshot.real_token_reserves),
        real_sol_reserves=int(snapshot.real_sol_reserves),
        token_total_supply=int(snapshot.token_total_supply),
        complete=snapshot.complete,
    ).progress


class CurveSnapshotRepository:
    """All curve persistence. Holds a session; owns no transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self, readings: Sequence[CurveReading], *, captured_at: datetime
    ) -> int:
        """Append one observation per reading. Returns how many landed.

        `ON CONFLICT DO NOTHING` against `(mint_address, captured_at)`: a cycle
        that runs twice — a retry, a restart, two workers racing — records each
        state once. The database is the guarantee, as it is for discovery.

        Readings for tokens absent from `discovered_tokens` are dropped rather
        than raising: the foreign key would reject them anyway, and one unknown
        mint must not cost the batch.
        """
        if not readings:
            return 0

        token_ids = await self._token_ids([reading.mint_address for reading in readings])
        rows = [
            {
                "token_id": token_ids[reading.mint_address],
                "mint_address": reading.mint_address,
                "captured_at": captured_at,
                "virtual_token_reserves": Decimal(reading.state.virtual_token_reserves),
                "virtual_sol_reserves": Decimal(reading.state.virtual_sol_reserves),
                "real_token_reserves": Decimal(reading.state.real_token_reserves),
                "real_sol_reserves": Decimal(reading.state.real_sol_reserves),
                "token_total_supply": Decimal(reading.state.token_total_supply),
                "complete": reading.state.complete,
            }
            for reading in readings
            if reading.mint_address in token_ids
        ]
        if not rows:
            return 0

        statement = (
            insert(TokenCurveSnapshot)
            .values(rows)
            .on_conflict_do_nothing(
                index_elements=[
                    TokenCurveSnapshot.mint_address,
                    TokenCurveSnapshot.captured_at,
                ]
            )
            .returning(TokenCurveSnapshot.id)
        )
        return len((await self._session.scalars(statement)).all())

    async def _token_ids(self, mints: Sequence[str]) -> dict[str, uuid.UUID]:
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

    async def latest_for(
        self, mints: Sequence[str]
    ) -> dict[str, TokenCurveSnapshot]:
        """The newest curve observation per mint, in one query."""
        unique = list(dict.fromkeys(mints))
        if not unique:
            return {}

        ranked = (
            select(
                TokenCurveSnapshot,
                func.row_number()
                .over(
                    partition_by=TokenCurveSnapshot.mint_address,
                    order_by=TokenCurveSnapshot.captured_at.desc(),
                )
                .label("rank"),
            )
            .where(TokenCurveSnapshot.mint_address.in_(unique))
            .subquery()
        )
        aliased = select(TokenCurveSnapshot).from_statement(
            select(ranked).where(ranked.c.rank == 1)
        )
        rows = (await self._session.scalars(aliased)).all()
        return {row.mint_address: row for row in rows}

    async def windows_for(
        self, mints: Sequence[str], *, limit_per_mint: int
    ) -> dict[str, list[TokenCurveSnapshot]]:
        """Recent curve observations for each mint, oldest first, in one query.

        The batch equivalent of `history_for`, and for the same reason
        `OpportunityRepository.windows_for` exists: detection runs over a whole
        enrichment batch, and a query per token turns an enrichment-paced cycle
        back into a scan.
        """
        unique = list(dict.fromkeys(mints))
        if not unique or limit_per_mint <= 0:
            return {}

        ranked = (
            select(
                TokenCurveSnapshot,
                func.row_number()
                .over(
                    partition_by=TokenCurveSnapshot.mint_address,
                    order_by=TokenCurveSnapshot.captured_at.desc(),
                )
                .label("rank"),
            )
            .where(TokenCurveSnapshot.mint_address.in_(unique))
            .subquery()
        )
        aliased = select(TokenCurveSnapshot).from_statement(
            select(ranked).where(ranked.c.rank <= limit_per_mint)
        )
        rows = (await self._session.scalars(aliased)).all()

        collected: dict[str, list[TokenCurveSnapshot]] = {}
        for row in rows:
            collected.setdefault(row.mint_address, []).append(row)
        for series in collected.values():
            series.sort(key=lambda snapshot: snapshot.captured_at)
        return collected

    async def history_for(
        self, mint_address: str, *, limit: int = 24
    ) -> Sequence[TokenCurveSnapshot]:
        """A token's curve observations, oldest first.

        Oldest-first because every consumer reads it as a series, and a series
        that arrives backwards is one every caller has to reverse.
        """
        statement = (
            select(TokenCurveSnapshot)
            .where(TokenCurveSnapshot.mint_address == mint_address)
            .order_by(TokenCurveSnapshot.captured_at.desc())
            .limit(limit)
        )
        rows = list((await self._session.scalars(statement)).all())
        return list(reversed(rows))
