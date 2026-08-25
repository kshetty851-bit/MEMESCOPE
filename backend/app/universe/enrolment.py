"""Enrol tradeable market tokens into the observation pipeline.

MEMESCOPE's pipeline was built around one program: the scanner subscribes to
pump.fun, and everything downstream keys off `discovered_tokens`. The market
universe this wallet trades is not discovered that way — it comes from
Jupiter's verified list — so those mints have to be registered before anything
can price them.

Registration is deliberately shallow. A universe token gets a
`discovered_tokens` row and an enrichment state row, nothing else: no Radar
admission, no Track Record entry, no nursery lifecycle. It is a thing to
observe, not an opportunity anybody detected, and conflating the two would put
tokens into a permanent record that never detected them.

`source_program = 'jupiter_verified'` is the marker every downstream query
uses to tell the two populations apart.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.market import LANE_NORMAL, EnrichmentStatus, TokenEnrichmentState
from app.models.research_data import JupiterUniverseSnapshot
from app.models.token import DiscoveredToken
from app.universe import rules
from app.universe.rules import UniverseRow

logger = get_logger(__name__)

#: The marker that separates market tokens from scanner discoveries.
SOURCE_PROGRAM = "jupiter_verified"

#: `discovered_tokens.signature` and `.slot` are NOT NULL because a scanner
#: discovery always has both. A universe token has neither — it was never
#: discovered in a transaction we saw. A synthetic, obviously-synthetic
#: signature is honest about that; a fabricated real-looking one would not be.
_SYNTHETIC_SLOT = 0


def _synthetic_signature(mint: str) -> str:
    return f"universe:{mint}"


async def enrol(session: AsyncSession, *, now: datetime | None = None,
                limit: int = 500) -> dict[str, Any]:
    """Register today's qualifying universe tokens for observation."""
    moment = now or datetime.now(UTC)

    latest_date = await session.scalar(
        select(func.max(JupiterUniverseSnapshot.snapshot_date))
    )
    if latest_date is None:
        return {"skipped": "no_universe_snapshot"}

    rows = list(
        (
            await session.execute(
                select(JupiterUniverseSnapshot).where(
                    JupiterUniverseSnapshot.snapshot_date == latest_date
                )
            )
        ).scalars()
    )

    admitted: list[JupiterUniverseSnapshot] = []
    refusals: dict[str, int] = {}
    for row in rows:
        age_days = (
            (moment - row.provider_created_at).total_seconds() / 86400
            if row.provider_created_at is not None
            else None
        )
        verdict = rules.judge(
            UniverseRow(
                mint_address=row.mint_address,
                symbol=row.symbol,
                age_days=age_days,
                liquidity_usd=row.liquidity_usd,
                market_cap=row.market_cap,
                holder_count=row.holder_count,
            )
        )
        if verdict.admit:
            admitted.append(row)
        else:
            refusals[verdict.reason or "unknown"] = (
                refusals.get(verdict.reason or "unknown", 0) + 1
            )

    admitted = admitted[:limit]
    enrolled = 0
    for row in admitted:
        result = await session.execute(
            pg_insert(DiscoveredToken)
            .values(
                mint_address=row.mint_address,
                symbol=(row.symbol or None),
                signature=_synthetic_signature(row.mint_address),
                slot=_SYNTHETIC_SLOT,
                # The provider's own creation time is the token's real age and
                # the basis of the seven-day rule; `discovered_at` is only when
                # THIS platform first looked at it.
                block_time=row.provider_created_at,
                discovered_at=moment,
                source_program=SOURCE_PROGRAM,
            )
            .on_conflict_do_nothing(index_elements=[DiscoveredToken.mint_address])
            .returning(DiscoveredToken.id)
        )
        token_id = result.scalar_one_or_none()
        if token_id is None:
            continue  # already known — never re-registered, never re-dated
        await session.execute(
            pg_insert(TokenEnrichmentState)
            .values(
                token_id=token_id,
                mint_address=row.mint_address,
                status=EnrichmentStatus.ACTIVE,
                next_refresh_at=moment,
                priority=LANE_NORMAL,
            )
            .on_conflict_do_nothing()
        )
        enrolled += 1

    logger.info(
        "universe_enrolled",
        snapshot_date=str(latest_date),
        considered=len(rows),
        admitted=len(admitted),
        newly_enrolled=enrolled,
        refusals=refusals,
    )
    return {
        "considered": len(rows),
        "admitted": len(admitted),
        "enrolled": enrolled,
        "refusals": refusals,
    }
