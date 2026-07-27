"""Market enrichment routes.

Two mounts, one router file:
  * `/tokens/{mint}/market` and `/tokens/{mint}/history` — per-token views.
  * `/market/trending` — cross-token ranking.

Public, matching the rest of the token API: this is public chain data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.api.deps import DbSession
from app.schemas.market import (
    MarketHistoryPage,
    MarketSnapshotRead,
    TokenMarketRead,
    TrendingEntry,
    TrendingPage,
    TrendingSort,
)
from app.schemas.token import TokenRead
from app.services.market.query_service import MarketQueryService

# Base58 pubkeys are 32-44 chars; reject junk before it reaches the database.
MINT_PATTERN = r"^[1-9A-HJ-NP-Za-km-z]{32,44}$"

MintPath = Annotated[str, Path(pattern=MINT_PATTERN, description="Base58 mint address.")]


def get_market_service(session: DbSession) -> MarketQueryService:
    return MarketQueryService(session)


MarketServiceDep = Annotated[MarketQueryService, Depends(get_market_service)]

# Mounted under /tokens so the per-token market views sit beside the token itself.
token_market_router = APIRouter(prefix="/tokens", tags=["market"])
# Mounted under /market for cross-token views.
market_router = APIRouter(prefix="/market", tags=["market"])


@token_market_router.get(
    "/{mint}/market",
    response_model=TokenMarketRead,
    summary="Current market state for a token",
)
async def get_token_market(service: MarketServiceDep, mint: MintPath) -> TokenMarketRead:
    token, snapshot, state, count = await service.current_market(mint)
    return TokenMarketRead(
        mint_address=token.mint_address,
        market=MarketSnapshotRead.model_validate(snapshot) if snapshot else None,
        snapshot_count=count,
        last_refreshed_at=state.last_success_at if state else None,
        next_refresh_at=state.next_refresh_at if state else None,
        enrichment_status=str(state.status) if state else None,
        tier=state.tier if state else None,
    )


@token_market_router.get(
    "/{mint}/history",
    response_model=MarketHistoryPage,
    summary="Historical market snapshots for a token, newest first",
)
async def get_token_history(
    service: MarketServiceDep,
    mint: MintPath,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
    since: Annotated[datetime | None, Query(description="Lower bound on captured_at.")] = None,
    until: Annotated[datetime | None, Query(description="Upper bound on captured_at.")] = None,
) -> MarketHistoryPage:
    token, rows, total = await service.history(
        mint, page=page, page_size=page_size, since=since, until=until
    )
    return MarketHistoryPage(
        mint_address=token.mint_address,
        items=[MarketSnapshotRead.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size if page_size else 0,
    )


@market_router.get(
    "/trending",
    response_model=TrendingPage,
    summary="Tokens ranked by their most recent market snapshot",
)
async def get_trending(
    service: MarketServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort_by: TrendingSort = "volume_24h",
    min_liquidity: Annotated[
        float | None, Query(ge=0, description="Filter out pools below this USD liquidity.")
    ] = None,
    since: Annotated[
        datetime | None, Query(description="Only consider snapshots captured after this time.")
    ] = None,
) -> TrendingPage:
    rows, total = await service.trending(
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        min_liquidity=min_liquidity,
        since=since,
    )
    return TrendingPage(
        items=[
            TrendingEntry(
                token=TokenRead.model_validate(token),
                market=MarketSnapshotRead.model_validate(snapshot),
            )
            for snapshot, token in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size if page_size else 0,
        sort_by=sort_by,
    )
