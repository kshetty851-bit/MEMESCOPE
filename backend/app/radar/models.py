"""Radar domain types.

The Opportunity Radar asks a different question from the launch scanner. The
scanner asks "what appeared?"; the Radar asks "what is getting stronger?" — of
any project, at any age. A ninety-day-old token with growing liquidity, rising
volume and a clean technical structure is a better opportunity than a fresh
launch with none of those, and market cap is deliberately not a qualification.

Everything here is a plain dataclass or enum. No I/O, no clock, no randomness —
the same discipline as `services/scoring`, enforced by `test_radar_purity.py`.
Time enters as an explicit `now`.
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


class RadarCategory(enum.StrEnum):
    """What kind of opportunity the engine believes it has found.

    Persisted on `radar_tokens.category`, so append-only.

    This replaces the single Elite Gem verdict with a shape that can describe
    several different reasons a project is interesting. A breakout and a quietly
    accumulating undervalued project are both opportunities and look nothing
    alike; collapsing them into one score threw that away.
    """

    EARLY_MOMENTUM = "early_momentum"
    BREAKOUT = "breakout"
    STRONG_COMMUNITY = "strong_community"
    UNDERVALUED = "undervalued"
    ELITE = "elite"


class RadarDimension(enum.StrEnum):
    """The independent axes an opportunity is measured on.

    Persisted inside `radar_snapshots.dimensions`, so append-only.
    """

    ONCHAIN_HEALTH = "onchain_health"
    MOMENTUM = "momentum"
    TECHNICAL = "technical"
    LIQUIDITY_QUALITY = "liquidity_quality"
    COMMUNITY = "community"
    RISK = "risk"


class RadarReason(enum.StrEnum):
    """Why the engine concluded what it did.

    Rendered into English by `explain.py` and never composed on the client, for
    the same reason the scoring engine renders its own reasons: a second opinion
    about the same token is worse than no opinion.
    """

    # --- Momentum ----------------------------------------------------------
    LIQUIDITY_GROWING = "liquidity_growing"
    LIQUIDITY_SHRINKING = "liquidity_shrinking"
    VOLUME_EXPANDING = "volume_expanding"
    VOLUME_FADING = "volume_fading"
    PRICE_TRENDING_UP = "price_trending_up"
    PRICE_TRENDING_DOWN = "price_trending_down"
    BUY_PRESSURE_DOMINANT = "buy_pressure_dominant"
    SELL_PRESSURE_DOMINANT = "sell_pressure_dominant"

    # --- Technical ---------------------------------------------------------
    HIGHER_HIGHS_AND_LOWS = "higher_highs_and_lows"
    RESISTANCE_BROKEN = "resistance_broken"
    TREND_ALIGNED = "trend_aligned"
    VOLATILITY_COMPRESSED = "volatility_compressed"
    STRUCTURE_BREAKING_DOWN = "structure_breaking_down"

    # --- Liquidity / health ------------------------------------------------
    LIQUIDITY_DEEP_FOR_SIZE = "liquidity_deep_for_size"
    LIQUIDITY_THIN_FOR_SIZE = "liquidity_thin_for_size"
    TURNOVER_HEALTHY = "turnover_healthy"

    # --- Risk --------------------------------------------------------------
    LIQUIDITY_CRITICALLY_THIN = "liquidity_critically_thin"
    VOLUME_WITHOUT_LIQUIDITY = "volume_without_liquidity"

    # --- Availability ------------------------------------------------------
    INSUFFICIENT_HISTORY = "insufficient_history"
    SIGNAL_NOT_AVAILABLE = "signal_not_available"
    COMMUNITY_DATA_UNAVAILABLE = "community_data_unavailable"


@dataclass(frozen=True, slots=True)
class Observation:
    """One market snapshot, reduced to what the Radar reads.

    A projection of `token_market_snapshots` rather than the ORM row, so the
    engine stays free of SQLAlchemy and can be tested with literals.
    """

    captured_at: datetime
    price_usd: Decimal | None
    market_cap: Decimal | None
    liquidity_usd: Decimal | None
    volume_24h: Decimal | None
    volume_1h: Decimal | None
    buy_count_24h: int | None
    sell_count_24h: int | None


@dataclass(frozen=True, slots=True)
class RadarSeries:
    """A token's observation history, oldest first.

    The Radar's entire input. Holder counts, wallet clustering and social
    activity are absent because the platform does not collect them — the
    dimensions that need them report unavailable rather than guessing, which is
    what keeps confidence honest.
    """

    mint_address: str
    observations: Sequence[Observation]
    #: When the token was first discovered on-chain. Distinct from Radar
    #: detection, which is when *this* engine first found it interesting.
    discovered_at: datetime | None = None

    @property
    def latest(self) -> Observation | None:
        return self.observations[-1] if self.observations else None

    def __len__(self) -> int:
        return len(self.observations)


@dataclass(frozen=True, slots=True)
class DimensionResult:
    """One axis's verdict.

    `score` is `None` exactly when `available` is `False`. The scorer asserts
    that rather than trusting it — an available `None` would poison the weighted
    sum silently.
    """

    id: RadarDimension
    available: bool
    score: Decimal | None
    reasons: tuple[RadarReason, ...] = ()
    raw: dict[str, Decimal | None] = field(default_factory=dict)

    @classmethod
    def unavailable(
        cls,
        dimension: RadarDimension,
        *,
        reason: RadarReason,
        raw: dict[str, Decimal | None] | None = None,
    ) -> DimensionResult:
        return cls(
            id=dimension,
            available=False,
            score=None,
            reasons=(reason,),
            raw=raw or {},
        )


@dataclass(frozen=True, slots=True)
class OpportunityResult:
    """The engine's complete verdict on one token at one moment.

    Reproducible: a pure function of `(series, model version, now)`.
    """

    mint_address: str
    #: 0-100. The combined MEMESCOPE Opportunity Score.
    score: Decimal
    #: Share of declared weight that could actually be applied, 0-100.
    coverage: Decimal
    #: Coverage tempered by how much history stood behind it, 0-100.
    confidence: Decimal
    category: RadarCategory | None
    dimensions: tuple[DimensionResult, ...]
    reasons: tuple[RadarReason, ...]
    model_version: str
    evaluated_at: datetime
    observations: int

    def dimension(self, dimension: RadarDimension) -> DimensionResult | None:
        for result in self.dimensions:
            if result.id is dimension:
                return result
        return None


@dataclass(frozen=True, slots=True)
class AchievementTier:
    """A return multiple worth recording permanently."""

    multiple: Decimal
    label: str


@dataclass(frozen=True, slots=True)
class Performance:
    """How a Radar opportunity has actually done since detection.

    Every figure is measured from **MEMESCOPE's first detection**, never from
    the token's launch. Measuring from launch would flatter the platform with
    gains it did not call, which is the opposite of what the track record is
    for.
    """

    first_price: Decimal | None
    current_price: Decimal | None
    peak_price: Decimal | None
    #: Multiples, not percentages: 1.0 means unchanged, 2.0 means a double.
    current_multiple: Decimal | None
    peak_multiple: Decimal | None
    days_since_detection: Decimal
