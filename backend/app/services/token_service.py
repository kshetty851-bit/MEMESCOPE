"""Token query use cases.

Read-only today. Ingestion lives in the scanner because it is driven by a
stream rather than a request; this service is what the HTTP layer talks to.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.models.token import DiscoveredToken, MetadataStatus
from app.repositories.token import SortField, SortOrder, TokenRepository

MAX_LATEST = 100


class TokenService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.tokens = TokenRepository(session)

    async def list_tokens(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
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
        if created_after and created_before and created_after > created_before:
            raise ValidationError("created_after must be earlier than created_before.")
        if discovered_after and discovered_before and discovered_after > discovered_before:
            raise ValidationError("discovered_after must be earlier than discovered_before.")

        return await self.tokens.search(
            offset=(page - 1) * page_size,
            limit=page_size,
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

    async def latest_tokens(self, *, limit: int = 20) -> Sequence[DiscoveredToken]:
        return await self.tokens.latest(limit=min(limit, MAX_LATEST))

    async def get_by_mint(self, mint_address: str) -> DiscoveredToken:
        token = await self.tokens.get_by_mint(mint_address.strip())
        if token is None:
            raise NotFoundError(f"No discovered token with mint {mint_address}.")
        return token
