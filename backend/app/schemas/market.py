"""Market API contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from app.models.market import TradingStatus
from app.schemas.common import BaseSchema
from app.schemas.token import TokenRead

TrendingSort = Literal[
    "volume_24h",
    "volume_1h",
    "volume_5m",
    "liquidity_usd",
    "market_cap",
    "price_usd",
    # Ranks by recency of the observation rather than by size. The live feed
    # uses it to pick up market data for tokens that are new and low-volume.
    "captured_at",
]


class MarketSnapshotRead(BaseSchema):
    id: uuid.UUID
    mint_address: str
    captured_at: datetime = Field(description="Last updated timestamp for this observation.")

    price_usd: Decimal | None
    price_native: Decimal | None
    liquidity_usd: Decimal | None
    fully_diluted_valuation: Decimal | None
    market_cap: Decimal | None

    volume_24h: Decimal | None
    volume_1h: Decimal | None
    volume_5m: Decimal | None

    buy_count_24h: int | None
    sell_count_24h: int | None

    dex_name: str | None
    trading_pair: str | None
    pool_address: str | None

    trading_status: TradingStatus
    is_verified: bool

    provider: str
    provider_latency_ms: int | None


class TokenMarketRead(BaseSchema):
    """Current market state for a token, plus enrichment bookkeeping."""

    mint_address: str
    market: MarketSnapshotRead | None = Field(
        default=None, description="Null until the provider has indexed a pool."
    )
    snapshot_count: int = 0
    last_refreshed_at: datetime | None = None
    next_refresh_at: datetime | None = None
    enrichment_status: str | None = None
    tier: str | None = None


class MarketHistoryPage(BaseSchema):
    mint_address: str
    items: list[MarketSnapshotRead]
    total: int
    page: int
    page_size: int
    pages: int


class TrendingEntry(BaseSchema):
    token: TokenRead
    market: MarketSnapshotRead


class TrendingPage(BaseSchema):
    items: list[TrendingEntry]
    total: int
    page: int
    page_size: int
    pages: int
    sort_by: TrendingSort
