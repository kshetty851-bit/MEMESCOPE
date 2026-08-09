"""Model registry.

Import every model here. Alembic's autogenerate walks `Base.metadata`, and a
model that is never imported is invisible to it.
"""

from app.db.base import Base
from app.models.alpha_session import AlphaSession
from app.models.curve import TokenCurveSnapshot  # noqa: F401
from app.models.market import (
    EnrichmentStatus,
    TokenEnrichmentState,
    TokenMarketSnapshot,
    TradingStatus,
)
from app.models.paper import (
    PaperPosition,
    PaperShadowDecision,
    PaperShadowPosition,
    PaperShadowTradeAudit,
    PaperShadowWallet,
    PaperTradeAudit,
    PaperWallet,
)
from app.models.radar import RadarAchievement, RadarSnapshot, RadarToken
from app.models.real_wallet_execution import RealWalletExecutionIntent, RealWalletPosition
from app.models.real_wallet_safety import RealWalletSafetyEvaluation
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
    "AlphaSession",
    "Base",
    "DiscoveredToken",
    "EnrichmentStatus",
    "MetadataStatus",
    "PaperPosition",
    "PaperShadowDecision",
    "PaperShadowPosition",
    "PaperShadowTradeAudit",
    "PaperShadowWallet",
    "PaperTradeAudit",
    "PaperWallet",
    "RadarAchievement",
    "RadarSnapshot",
    "RadarToken",
    "RealWalletExecutionIntent",
    "RealWalletPosition",
    "RealWalletSafetyEvaluation",
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
from app.models.intelligence import (  # noqa: F401
    AnalystReadingCache,
    EventKind,
    EventSeverity,
    IntelligenceEvent,
    Watchlist,
    WatchlistItem,
)
from app.models.opportunity import (  # noqa: F401
    Opportunity,
    OpportunitySignal,
)
