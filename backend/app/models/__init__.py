"""Model registry.

Import every model here. Alembic's autogenerate walks `Base.metadata`, and a
model that is never imported is invisible to it.
"""

from app.db.base import Base
from app.models.alpha_session import AlphaSession
from app.models.curve import TokenCurveSnapshot  # noqa: F401
from app.models.discovery import (
    DiscoveryObservationSource,
    DiscoverySourceObservation,
    YellowstoneStreamCheckpoint,
)
from app.models.market import (
    EnrichmentStatus,
    TokenEnrichmentState,
    TokenMarketSnapshot,
    TradingStatus,
)
from app.models.paper import (
    PaperPosition,
    PaperTradeAudit,
    PaperWallet,
)
from app.models.paper_research import (
    PaperDecisionEnrichment,
    PaperDecisionOutcome,
    PaperDecisionSnapshot,
)
from app.models.hq_ops import HqAction, HqIncident  # noqa: F401
from app.models.karthik import (  # noqa: F401
    KarthikOpportunity,
    KarthikPosition,
    KarthikWallet,
)
from app.models.radar import RadarAchievement, RadarSnapshot, RadarToken
from app.models.radar_quality import (
    RadarDecisionOutcome,
    RadarDecisionSnapshot,
    RadarRankEvent,
)
from app.models.real_wallet_execution import (
    RealWalletDevnetEvent,
    RealWalletDevnetIntent,
    RealWalletDevnetQuote,
    RealWalletExecutionEvent,
    RealWalletExecutionHealth,
    RealWalletExecutionIntent,
    RealWalletKillSwitch,
    RealWalletLiveIntent,
    RealWalletPosition,
    RealWalletAutotradeEvent,
    RealWalletAutotradeSwitch,
)
from app.models.real_wallet_safety import RealWalletSafetyEvaluation
from app.models.token_security import TokenSecurityEvaluationRow
from app.models.refresh_token import RefreshToken
from app.models.report_delivery import (  # noqa: F401
    DeliveryStatus,
    ReportDelivery,
    ReportKind,
)
from app.models.score import (
    ScoreGrade,
    ScoreTrigger,
    TokenScore,
    TokenScoreHistory,
)
from app.models.arena import (  # noqa: F401
    ArenaCandidate,
    ArenaDecision,
    ArenaPosition,
)
from app.models.password_reset import PasswordResetToken  # noqa: F401
from app.models.compound import CompoundCycle  # noqa: F401
from app.models.lab import (  # noqa: F401
    LabDecision,
    LabEquityPoint,
    LabPosition,
    LabSnapshot,
    LabStrategy,
    LabTournament,
)
from app.models.research_data import (  # noqa: F401
    HolderSnapshot,
    JupiterUniverseSnapshot,
    NurseryAdmission,
    RadarExecutableOutcome,
    RegimeSnapshot,
    ResearchQuote,
    WalletFlowSnapshot,
)
from app.models.token import DiscoveredToken, MetadataStatus
from app.models.user import User, UserRole

__all__ = [
    "AlphaSession",
    "Base",
    "DiscoveredToken",
    "DiscoveryObservationSource",
    "DiscoverySourceObservation",
    "EnrichmentStatus",
    "HqAction",
    "HqIncident",
    "KarthikOpportunity",
    "KarthikPosition",
    "KarthikWallet",
    "MetadataStatus",
    "PaperDecisionEnrichment",
    "PaperDecisionOutcome",
    "PaperDecisionSnapshot",
    "PaperPosition",
    "PaperTradeAudit",
    "PaperWallet",
    "RadarAchievement",
    "RadarDecisionOutcome",
    "RadarDecisionSnapshot",
    "RadarRankEvent",
    "RadarSnapshot",
    "RadarToken",
    "RealWalletDevnetEvent",
    "RealWalletDevnetIntent",
    "RealWalletDevnetQuote",
    "RealWalletExecutionEvent",
    "RealWalletExecutionHealth",
    "RealWalletExecutionIntent",
    "RealWalletKillSwitch",
    "RealWalletLiveIntent",
    "RealWalletPosition",
    "RealWalletSafetyEvaluation",
    "TokenSecurityEvaluationRow",
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
    "YellowstoneStreamCheckpoint",
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
