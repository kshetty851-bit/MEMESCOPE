"""Exit Watch and record API contracts.

Decimals serialise as strings, matching every other surface.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.schemas.common import BaseSchema


class ExitSignalOut(BaseSchema):
    code: str
    label: str
    agent: str
    #: Rendered by the backend. The client never composes these.
    message: str
    triggered: bool
    #: False when the signal could not be checked — never conflated with a pass.
    available: bool
    magnitude: Decimal | None = None


class ExitAssessmentOut(BaseSchema):
    mint_address: str
    severity: str
    #: Share of declared signals that could be checked. Never 100 while
    #: wallet-level data is missing.
    coverage: Decimal
    summary: str
    signals: list[ExitSignalOut]
    current_multiple: Decimal | None
    peak_multiple: Decimal | None
    evaluated_at: datetime


class ExitWatchPage(BaseSchema):
    items: list[ExitAssessmentOut]
    total: int
    #: Carried on every response so no client can render the list without it.
    disclaimer: str


class ExitModelOut(BaseSchema):
    signals: list[dict[str, object]]
    thresholds: dict[str, str]
    signals_for_watch: int
    signals_for_elevated: int
    disclaimer: str


class SmartMoneyBlock(BaseSchema):
    """Wallet intelligence for one token.

    Every figure is `None` rather than zero. "No smart wallets detected" and
    "wallets cannot be seen" are different claims, and a zero would be read as
    the first.
    """

    mint_address: str
    smart_wallet_count: int | None
    average_wallet_quality: Decimal | None
    net_accumulation: Decimal | None
    accumulation_trend: str | None
    distribution_trend: str | None
    largest_recent_buyer: str | None
    largest_recent_seller: str | None
    unavailable_reason: str


class HallEntryOut(BaseSchema):
    """One entry in the permanent record.

    The same shape serves the Hall of Fame and the Hall of Lessons — they are
    the same table ordered two ways, which is the point.
    """

    mint_address: str
    category: str
    original_category: str

    first_detected_at: datetime
    first_market_cap: Decimal | None
    first_price: Decimal | None

    peak_market_cap: Decimal | None
    peak_price: Decimal | None
    peak_multiple: Decimal | None
    peak_at: datetime | None

    current_market_cap: Decimal | None
    current_price: Decimal | None
    current_multiple: Decimal | None

    days_since_detection: Decimal
    days_to_peak: Decimal | None

    opportunity_score: Decimal
    confidence: Decimal
    is_active: bool


class LeaderboardBoard(BaseSchema):
    id: str
    label: str
    description: str
    entries: list[HallEntryOut]


class LeaderboardOut(BaseSchema):
    boards: list[LeaderboardBoard]
    smart_money_available: bool
    smart_money_note: str
