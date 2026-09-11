"""Model registry.

Import every model here. Alembic's autogenerate walks `Base.metadata`, and a
model that is never imported is invisible to it.
"""

from app.db.base import Base
from app.models.early_buyer import TokenEarlyBuyer
from app.models.kol import KolWalletRank

# Rafiq Lab's three `rafiq_lab_*` tables. Imported here for one reason: without
# it they exist in the database and not in this metadata, and autogenerate
# emits `drop_table` for each of them. Additive — it declares tables, it does
# not change any.
from app.labs.rafiq.models import (  # noqa: F401
    RafiqLabDailyState,
    RafiqLabPosition,
    RafiqLabStrategy,
)
# Breakout Lab's ten `bo_*` tables, for the same reason: `alembic/env.py`
# imports only `app.models`, so a model this package never imports is invisible
# to autogenerate and the next revision would emit `drop_table` for each.
from app.labs.breakout.models import (  # noqa: F401
    BoAccount,
    BoCandle,
    BoEpisode,
    BoEquity,
    BoLevels,
    BoPosition,
    BoRun,
    BoSetupSnapshot,
    BoTrade,
    BoUniverseMember,
)
from app.models.alpha_session import AlphaSession
from app.models.curve import TokenCurveSnapshot  # noqa: F401
from app.models.basechain import EvmLaunch  # noqa: F401
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
# Retired experiment. Imported so the metadata still describes the tables it
# left behind — without this, autogenerate proposes dropping them.
from app.models.arena import (  # noqa: F401
    ArenaCandidate,
    ArenaDecision,
    ArenaPosition,
)
from app.models.password_reset import PasswordResetToken  # noqa: F401
from app.models.compound import CompoundCycle  # noqa: F401
from app.models.pumpfun import PumpfunSignal  # noqa: F401
from app.models.graduation import (  # noqa: F401
    PumpfunGraduation,
    PumpfunGraduationMark,
)
from app.models.social import PumpfunSocialSnapshot  # noqa: F401
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
    "KolWalletRank",
    "TokenEarlyBuyer",
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
