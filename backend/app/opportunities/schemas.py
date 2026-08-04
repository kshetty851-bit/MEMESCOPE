"""Response models for the Opportunity board.

Shapes follow the conventions the rest of the API already holds: money as
strings via `Decimal`, server-rendered explanations, applied filters echoed so
an empty page caused by a strict filter is distinguishable from an empty board.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import Field

from app.schemas.common import BaseSchema


class ExplanationOut(BaseSchema):
    """Why this appeared *now*, in the five parts of AD-07.

    Rendered from stored reason codes at read time. `limits` is not optional
    padding — it is where the card says what could not be checked, which is the
    difference between honest coverage and a card that quietly looks complete.
    """

    headline: str
    trigger: str
    boundary: str | None = None
    delta: list[str] = Field(default_factory=list)
    corroboration: list[str] = Field(default_factory=list)
    limits: list[str] = Field(default_factory=list)


class EvidenceOut(BaseSchema):
    label: str
    value: str
    detail: str | None = None


class SignalOut(BaseSchema):
    """One live signal on an opportunity."""

    signal_type: str
    provider: str
    status: str
    severity: str
    #: The provider's claim about the transition, 0-100.
    strength: Decimal
    #: What the engine derived from it. Always <= strength on a young signal.
    confidence: Decimal
    confirmations: int
    observations: int
    detected_at: datetime
    last_confirmed_at: datetime
    expires_at: datetime
    #: Seconds until this signal lapses. Negative is impossible on the board:
    #: the read filters lapsed signals out rather than trusting the sweep.
    expires_in_seconds: int
    reason_codes: list[str]
    evidence: list[EvidenceOut]
    explanation: ExplanationOut


class MarketOut(BaseSchema):
    """The market figures a trader needs before acting on a card.

    Every field is optional and the whole object is nullable, because a token
    the market has not priced yet is a real state — and rendering a missing
    price as `$0` would be the estimate this platform does not make. A client
    that gets `market: null` must say "no market data", never zero.

    Money stays a string end to end (`NUMERIC` in Postgres, string in JSON) so
    no float rounding sits between the snapshot and the screen.
    """

    price_usd: Decimal | None = None
    market_cap: Decimal | None = None
    liquidity_usd: Decimal | None = None
    volume_24h: Decimal | None = None
    #: Percent change over 24h, when both ends of the window were observed.
    change_24h_pct: Decimal | None = None
    #: When this reading was taken. Surfaced so a stale price is visibly stale
    #: rather than silently presented as current.
    captured_at: datetime | None = None
    dex_name: str | None = None


class OpportunityOut(BaseSchema):
    """One card. One token, one generation, many live signals."""

    mint_address: str
    name: str | None = None
    symbol: str | None = None
    #: Null when the token has never been priced. Not an error, and not zero.
    market: MarketOut | None = None
    #: Seconds since the token was first seen on-chain. The card shows age
    #: because a four-minute-old token and a four-day-old one are different
    #: risks even when every other figure matches.
    age_seconds: int | None = None
    generation: int
    status: str
    stage: str
    priority: Decimal
    priority_band: str
    confidence: Decimal
    detected_at: datetime
    last_confirmed_at: datetime
    #: How long ago the ranking was last recomputed. Surfaced rather than
    #: hidden: `priority` is as of the last evaluation, and a reader is entitled
    #: to see that it is nine minutes old rather than be shown a silently
    #: re-sorted board.
    confirmed_age_seconds: int
    signals: list[SignalOut]


class OpportunityBoard(BaseSchema):
    """The live board.

    No `total`. An unconditional `count(*)` alongside the page is a measured
    mistake — on `/scores/top` two of them cost 7.1 ms against a 0.4 ms ranking
    query — and "how many exactly" is not a question anyone asks of a live
    board. `has_more` answers the one that matters.
    """

    items: list[OpportunityOut]
    page: int
    page_size: int
    has_more: bool
    applied_filters: dict[str, object]
    observed_at: datetime


class ProviderAnalyticsOut(BaseSchema):
    """One provider's measured record.

    Ratios are nullable and that is the contract: a provider with no signals has
    no hit rate, and `null` says so where `0.00` would claim it tried and
    failed. `precision_unavailable_reason` carries the gap in the payload rather
    than leaving a reader to infer it — the same shape `/smart-money/{mint}`
    holds for data the platform does not collect.
    """

    provider_id: str
    name: str
    operational: bool
    unavailable_reason: str | None = None
    signals: int
    opportunities: int
    confirmed: int
    expired: int
    closed: int
    #: Invalidations on factual signals — corrections to an observation, kept
    #: out of every ratio so a re-indexing artefact never reads as a bad call.
    contradicted: int = 0
    average_confidence: Decimal | None = None
    average_lifetime_seconds: int | None = None
    hit_rate: Decimal | None = None
    precision: Decimal | None = None
    precision_unavailable_reason: str | None = None


class ProviderAnalyticsReport(BaseSchema):
    """Every registered provider, measured. Internal surface.

    Registered rather than active: a provider that has never emitted is listed
    with zeroes and its reason, because "this signal has produced nothing" and
    "this signal does not exist here" are different facts and the second is the
    one an operator needs.
    """

    providers: list[ProviderAnalyticsOut]
    engine_enabled: bool
    observed_at: datetime
