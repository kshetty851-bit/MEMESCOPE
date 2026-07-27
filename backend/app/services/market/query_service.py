"""Read-side market use cases used by the REST API.

Kept separate from `MarketEnrichmentService`, which is the write path owned by
the worker. The API never needs a provider, and giving it one would invite a
request to trigger an outbound call.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.models.market import TokenEnrichmentState, TokenMarketSnapshot
from app.models.token import DiscoveredToken
from app.repositories.market import EnrichmentStateRepository, MarketSnapshotRepository
from app.repositories.token import TokenRepository


class MarketQueryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.snapshots = MarketSnapshotRepository(session)
        self.states = EnrichmentStateRepository(session)
        self.tokens = TokenRepository(session)

    async def _require_token(self, mint_address: str) -> DiscoveredToken:
        token = await self.tokens.get_by_mint(mint_address.strip())
        if token is None:
            raise NotFoundError(f"No discovered token with mint {mint_address}.")
        return token

    async def current_market(
        self, mint_address: str
    ) -> tuple[DiscoveredToken, TokenMarketSnapshot | None, TokenEnrichmentState | None, int]:
        """Latest snapshot for a token.

        A token with no snapshot yet is not an error — the provider may simply
        not have indexed a pool. The caller renders `market: null`.
        """
        token = await self._require_token(mint_address)
        snapshot = await self.snapshots.latest_for_mint(token.mint_address)
        state = await self.states.get_by_mint(token.mint_address)
        count = await self.snapshots.count_for_mint(token.mint_address)
        return token, snapshot, state, count

    async def history(
        self,
        mint_address: str,
        *,
        page: int = 1,
        page_size: int = 50,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[DiscoveredToken, Sequence[TokenMarketSnapshot], int]:
        if since and until and since > until:
            raise ValidationError("`since` must be earlier than `until`.")

        token = await self._require_token(mint_address)
        rows, total = await self.snapshots.history_for_mint(
            token.mint_address,
            offset=(page - 1) * page_size,
            limit=page_size,
            since=since,
            until=until,
        )
        return token, rows, total

    async def trending(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "volume_24h",
        min_liquidity: float | None = None,
        since: datetime | None = None,
    ) -> tuple[Sequence[tuple[TokenMarketSnapshot, DiscoveredToken]], int]:
        return await self.snapshots.latest_per_token(
            offset=(page - 1) * page_size,
            limit=page_size,
            order_by=sort_by,
            min_liquidity=min_liquidity,
            since=since,
        )
