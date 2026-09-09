"""Model registry.

Import every model here. Alembic's autogenerate walks `Base.metadata`, and a
model that is never imported is invisible to it.
"""

from app.db.base import Base

# Rafiq Lab's three `rafiq_lab_*` tables. Imported here for one reason: without
# it they exist in the database and not in this metadata, and autogenerate
# emits `drop_table` for each of them. Additive — it declares tables, it does
# not change any.
from app.labs.rafiq.models import (  # noqa: F401
    RafiqLabDailyState,
    RafiqLabPosition,
    RafiqLabStrategy,
)
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
from app.models.paper_v2 import (  # noqa: F401
    PaperV2Fill,
    PaperV2Position,
    PaperV2Wallet,
)
from app.models.strategy_lab_discovery import (  # noqa: F401
    StrategyLabDiscoveryCandidate,
    StrategyLabDiscoveryResult,
    StrategyLabDiscoveryRun,
)
from app.models.strategy_lab import (  # noqa: F401
    StrategyLabFill,
    StrategyLabOpportunity,
    StrategyLabPosition,
    StrategyLabRefusal,
    StrategyLabRun,
    StrategyLabStrategy,
    StrategyLabWallet,
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
    RealWalletAllocation,
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
    "PaperV2Wallet",
    "PaperV2Position",
    "PaperV2Fill",
    "StrategyLabRun",
    "StrategyLabStrategy",
    "StrategyLabOpportunity",
    "StrategyLabWallet",
    "StrategyLabPosition",
    "StrategyLabFill",
    "StrategyLabRefusal",
    "StrategyLabDiscoveryRun",
    "StrategyLabDiscoveryCandidate",
    "StrategyLabDiscoveryResult",
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
