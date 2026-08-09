"""Token API contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.models.token import MetadataStatus
from app.schemas.common import BaseSchema

TokenSortField = Literal["discovered_at", "block_time", "slot", "name", "symbol"]
SortOrder = Literal["asc", "desc"]


class TokenRead(BaseSchema):
    id: uuid.UUID
    mint_address: str
    name: str | None
    symbol: str | None
    decimals: int | None
    metadata_uri: str | None
    image_url: str | None = None
    creator_address: str | None
    signature: str
    slot: int
    block_time: datetime | None = Field(default=None, description="On-chain creation time.")
    discovered_at: datetime = Field(description="When this system first saw the token.")
    source_program: str | None
    metadata_status: MetadataStatus


class TokenPage(BaseSchema):
    items: list[TokenRead]
    total: int
    page: int
    page_size: int
    pages: int


class TokenEvent(BaseSchema):
    """Envelope pushed over the WebSocket."""

    type: Literal["token.discovered", "connection.ready", "ping"]
    data: TokenRead | None = None
    message: str | None = None
