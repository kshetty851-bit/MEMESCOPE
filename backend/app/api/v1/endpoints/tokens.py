"""Discovered-token routes: REST queries plus the multiplexed live feed."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, WebSocket, WebSocketDisconnect

from app.api.deps import DbSession
from app.core.events import broadcaster
from app.core.logging import get_logger
from app.models.token import MetadataStatus
from app.schemas.token import SortOrder, TokenPage, TokenRead, TokenSortField
from app.services.token_service import TokenService

logger = get_logger(__name__)

router = APIRouter(prefix="/tokens", tags=["tokens"])

# Base58 pubkeys are 32-44 chars; reject junk before it reaches the database.
MINT_PATTERN = r"^[1-9A-HJ-NP-Za-km-z]{32,44}$"

# How long to wait for an event before sending a keepalive frame. Without this,
# an idle proxy will silently close a quiet connection.
WS_IDLE_PING_SECONDS = 25.0


def get_token_service(session: DbSession) -> TokenService:
    return TokenService(session)


TokenServiceDep = Annotated[TokenService, Depends(get_token_service)]


@router.get(
    "",
    response_model=TokenPage,
    summary="List discovered tokens with pagination, sorting and time filters",
)
async def list_tokens(
    service: TokenServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort_by: TokenSortField = "discovered_at",
    order: SortOrder = "desc",
    created_after: Annotated[
        datetime | None, Query(description="On-chain creation time lower bound (inclusive).")
    ] = None,
    created_before: Annotated[
        datetime | None, Query(description="On-chain creation time upper bound (inclusive).")
    ] = None,
    discovered_after: Annotated[
        datetime | None, Query(description="Discovery time lower bound (inclusive).")
    ] = None,
    discovered_before: Annotated[
        datetime | None, Query(description="Discovery time upper bound (inclusive).")
    ] = None,
    symbol: Annotated[str | None, Query(max_length=64)] = None,
    creator_address: Annotated[str | None, Query(max_length=44)] = None,
    metadata_status: MetadataStatus | None = None,
) -> TokenPage:
    items, total = await service.list_tokens(
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        order=order,
        created_after=created_after,
        created_before=created_before,
        discovered_after=discovered_after,
        discovered_before=discovered_before,
        symbol=symbol,
        creator_address=creator_address,
        metadata_status=metadata_status,
    )
    return TokenPage(
        items=[TokenRead.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size if page_size else 0,
    )


@router.get(
    "/latest",
    response_model=list[TokenRead],
    summary="Most recently discovered tokens, newest first",
)
async def latest_tokens(
    service: TokenServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[TokenRead]:
    tokens = await service.latest_tokens(limit=limit)
    return [TokenRead.model_validate(token) for token in tokens]


@router.get(
    "/{mint}",
    response_model=TokenRead,
    summary="Fetch a single discovered token by mint address",
)
async def get_token(
    service: TokenServiceDep,
    mint: Annotated[str, Path(pattern=MINT_PATTERN, description="Base58 mint address.")],
) -> TokenRead:
    return TokenRead.model_validate(await service.get_by_mint(mint))


@router.websocket("/stream")
async def token_stream(websocket: WebSocket) -> None:
    """Push committed discovery and read-model invalidations to the client.

    The stream carries identifiers and event kinds, not independently computed
    values. Clients refetch server-owned read models after an event, so no
    browser-side score, ranking, or paper-wallet calculation can drift.
    """
    await websocket.accept()
    client = websocket.client.host if websocket.client else "unknown"

    async with broadcaster.subscribe() as queue:
        logger.info(
            "ws_client_connected", client=client, subscribers=broadcaster.subscriber_count
        )
        await websocket.send_json(
            {"type": "connection.ready", "message": "Streaming committed updates."}
        )

        # Drains client frames so a disconnect surfaces promptly rather than
        # waiting for the next discovery.
        async def _drain() -> None:
            while True:
                await websocket.receive_text()

        drain_task = asyncio.create_task(_drain())
        try:
            while True:
                get_event = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait(
                    {get_event, drain_task},
                    timeout=WS_IDLE_PING_SECONDS,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if drain_task in done:
                    get_event.cancel()
                    break

                if get_event in done:
                    await websocket.send_json(get_event.result())
                else:
                    get_event.cancel()
                    await websocket.send_json({"type": "ping"})

        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            drain_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await drain_task
            logger.info("ws_client_disconnected", client=client)
