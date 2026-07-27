"""Model registry.

Import every model here. Alembic's autogenerate walks `Base.metadata`, and a
model that is never imported is invisible to it.
"""

from app.db.base import Base
from app.models.market import (
    EnrichmentStatus,
    TokenEnrichmentState,
    TokenMarketSnapshot,
    TradingStatus,
)
from app.models.refresh_token import RefreshToken
from app.models.score import (
    ScoreGrade,
    ScoreTrigger,
    TokenScore,
    TokenScoreHistory,
)
from app.models.token import DiscoveredToken, MetadataStatus
from app.models.user import User, UserRole

__all__ = [
    "Base",
    "DiscoveredToken",
    "EnrichmentStatus",
    "MetadataStatus",
    "RefreshToken",
    "ScoreGrade",
    "ScoreTrigger",
    "TokenEnrichmentState",
    "TokenMarketSnapshot",
    "TokenScore",
    "TokenScoreHistory",
    "TradingStatus",
    "User",
    "UserRole",
]
