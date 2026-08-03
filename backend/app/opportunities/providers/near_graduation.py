"""Near graduation: a bonding-curve token approaching its migration.

The first *predictive* provider. Fresh graduation reports a fact that already
happened; this one reports a trajectory, which is a weaker claim and has to be
built more carefully.

## Why it ships switched off

Measured against the live database on 2026-08-03, `market_cap` on a pump.fun
bonding-curve pair does not track curve progress:

  * Of **386** tokens observed graduating, only **5** ever showed a pump.fun
    market cap at or above $50k. The median peak was $4,159 against a ~$69k
    graduation threshold.
  * Of **48** tokens that did reach $50k on the curve, only those same **5**
    graduated — 10% precision, 1.3% recall.
  * The fallbacks are no better: at the last observation before graduation,
    volume ran a median **1.11x** the token's own earlier baseline and
    transaction count **1.26x**. That is noise, not a surge.

This is the same class of gap that leaves `liquidity_usd` 100% null for these
pairs: DexScreener does not model the bonding curve (ADR 0002). Building a
threshold on `market_cap` anyway would produce a confident-looking signal that
is wrong nine times in ten, which the platform's rules forbid — missing data is
declared, never estimated.

So the model below is complete, deterministic and tested, and the provider
registers as **non-operational** with that reason attached. It becomes
operational by configuration the moment a real progress source exists —
on-chain reserves via Helius is the route ADR 0002 names — with no code change
and no engine change.

## The model

Six components, each 0-100 and each declaring its own availability. Weights are
published and redistribute across whatever is available, so a component with no
data lowers the evidence rather than silently counting as zero — the same
discipline `services/scoring` holds.

    progress          0.40   how far along the curve
    progress_velocity 0.20   is it still moving, or stalled
    volume_trend      0.15   recent volume against its own earlier baseline
    buy_pressure      0.10   buys against total, from deltas
    transaction_rate  0.10   trades per hour, from deltas
    consistency       0.05   how much observation supports the reading

`progress` is mandatory: "near graduation" without knowing distance to
graduation is not a claim this platform can make. If it is unavailable the
provider reports nothing at all rather than scoring the remainder.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.core.config import settings
from app.opportunities.models import (
    Evidence,
    MarketObservation,
    ObservationWindow,
    OpportunityStage,
    ProviderMeta,
    ProviderResult,
    SignalCandidate,
    SignalSeverity,
    SignalType,
)
from app.opportunities.providers.base import SignalProvider

PROVIDER_ID = "near_graduation"

ZERO = Decimal(0)
HUNDRED = Decimal(100)

# --- Reason codes ------------------------------------------------------------
# Stable identifiers. Prose lives in `explain.py` and is rendered at read time,
# so rewording is a deploy rather than a migration.
REASON_APPROACHING = "approaching_graduation"
REASON_PROGRESS_RISING = "curve_progress_rising"
REASON_PROGRESS_STALLED = "curve_progress_stalled"
REASON_VOLUME_EXPANDING = "volume_expanding_into_graduation"
REASON_BUY_PRESSURE = "buy_pressure_dominant"
REASON_TRADE_RATE_RISING = "trade_rate_rising"
REASON_THIN_OBSERVATION = "thin_observation_window"


@dataclass(frozen=True, slots=True)
class Component:
    """One axis's contribution. `score` is None exactly when it has no data."""

    id: str
    weight: Decimal
    score: Decimal | None

    @property
    def available(self) -> bool:
        return self.score is not None


#: Published weights. They sum to 1.0 and are redistributed over whatever is
#: available, never silently treated as zero.
WEIGHTS: dict[str, Decimal] = {
    "progress": Decimal("0.40"),
    "progress_velocity": Decimal("0.20"),
    "volume_trend": Decimal("0.15"),
    "buy_pressure": Decimal("0.10"),
    "transaction_rate": Decimal("0.10"),
    "consistency": Decimal("0.05"),
}

#: Below this share of declared weight there is too little to say anything
#: honest, and the provider declines rather than reporting a thin score.
MIN_AVAILABLE_WEIGHT = Decimal("0.55")


class NearGraduationProvider(SignalProvider):
    """Emits `NEAR_GRADUATION` for a bonding-curve token approaching migration."""

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        graduation_market_cap: Decimal | None = None,
        min_progress: Decimal | None = None,
        min_observations: int | None = None,
        bonding_curve_venues: frozenset[str] | None = None,
    ) -> None:
        self._enabled = (
            settings.OPPORTUNITY_NEAR_GRADUATION_ENABLED if enabled is None else enabled
        )
        self._threshold = graduation_market_cap or Decimal(
            str(settings.OPPORTUNITY_GRADUATION_MARKET_CAP)
        )
        self._min_progress = min_progress or Decimal(
            str(settings.OPPORTUNITY_NEAR_GRADUATION_MIN_PROGRESS)
        )
        self._min_observations = (
            min_observations or settings.OPPORTUNITY_NEAR_GRADUATION_MIN_OBSERVATIONS
        )
        self._bonding = bonding_curve_venues or frozenset(
            venue.lower() for venue in settings.OPPORTUNITY_BONDING_CURVE_VENUES
        )

    @property
    def meta(self) -> ProviderMeta:
        return ProviderMeta(
            provider_id=PROVIDER_ID,
            name="Near Graduation",
            question="Is this token approaching its bonding-curve graduation?",
            emits=(SignalType.NEAR_GRADUATION,),
            operational=self._enabled,
            unavailable_reason=None
            if self._enabled
            else (
                "Bonding-curve progress is not collected. `market_cap` on a "
                "pump.fun pair does not track it — measured across 386 observed "
                "graduations it identified 5, and of 48 tokens that reached $50k "
                "only those same 5 graduated. Reporting a signal from it would "
                "be an estimate, not an observation."
            ),
            required_fields=("market_cap", "volume_24h", "buy_count_24h"),
        )

    def evaluate(self, window: ObservationWindow, *, now: datetime) -> ProviderResult:
        if not self._enabled:
            # Belt and braces: the registry already skips non-operational
            # providers, but a caller holding an instance directly must get the
            # declaration rather than a score built on data we do not trust.
            reason = self.meta.unavailable_reason
            assert reason is not None
            return self._unavailable(reason)

        latest = window.latest
        if latest is None:
            return self._nothing()

        venue = (latest.dex_name or "").strip().lower()
        if venue not in self._bonding:
            # Already graduated, or on a venue with no curve. Not this
            # provider's subject, and not an error.
            return self._nothing()

        progress = _progress(latest, threshold=self._threshold)
        if progress is None:
            # The mandatory anchor. Without a distance to graduation there is no
            # such thing as "near" it.
            return self._nothing()
        if progress < self._min_progress:
            return self._nothing()

        observations = [
            item for item in window.observations if _venue_of(item) in self._bonding
        ]
        components = self._components(observations, progress=progress)

        available = [component for component in components if component.available]
        available_weight = sum((component.weight for component in available), start=ZERO)
        if available_weight < MIN_AVAILABLE_WEIGHT:
            return self._nothing()

        # Redistribute across what is available, so an absent component lowers
        # the evidence rather than dragging the score toward zero.
        strength = sum(
            (
                (component.weight / available_weight) * (component.score or ZERO)
                for component in available
            ),
            start=ZERO,
        )
        strength = _clamp(strength)

        return ProviderResult(
            provider_id=PROVIDER_ID,
            candidates=(
                SignalCandidate(
                    mint_address=window.mint_address,
                    signal_type=SignalType.NEAR_GRADUATION,
                    strength=_quantize(strength),
                    severity=_severity(progress),
                    reason_codes=_reason_codes(components, progress, len(observations)),
                    evidence=_evidence(
                        components,
                        progress=progress,
                        threshold=self._threshold,
                        latest=latest,
                        observations=len(observations),
                    ),
                    stage=OpportunityStage.NEAR_GRADUATION,
                    observed_at=latest.captured_at,
                ),
            ),
        )

    # --- Components ----------------------------------------------------------

    def _components(
        self, observations: list[MarketObservation], *, progress: Decimal
    ) -> list[Component]:
        enough = len(observations) >= self._min_observations
        return [
            Component(
                "progress",
                WEIGHTS["progress"],
                _progress_score(progress, self._min_progress),
            ),
            Component(
                "progress_velocity",
                WEIGHTS["progress_velocity"],
                _progress_velocity(observations, threshold=self._threshold)
                if enough
                else None,
            ),
            Component(
                "volume_trend",
                WEIGHTS["volume_trend"],
                _volume_trend(observations) if enough else None,
            ),
            Component(
                "buy_pressure", WEIGHTS["buy_pressure"], _buy_pressure(observations)
            ),
            Component(
                "transaction_rate",
                WEIGHTS["transaction_rate"],
                _transaction_rate(observations) if enough else None,
            ),
            Component(
                "consistency",
                WEIGHTS["consistency"],
                _consistency(len(observations), self._min_observations),
            ),
        ]


# --- Pure helpers ------------------------------------------------------------


def _venue_of(observation: MarketObservation) -> str:
    return (observation.dex_name or "").strip().lower()


def _clamp(value: Decimal, low: Decimal = ZERO, high: Decimal = HUNDRED) -> Decimal:
    return max(low, min(high, value))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _progress(observation: MarketObservation, *, threshold: Decimal) -> Decimal | None:
    """Fraction of the way to graduation, 0 to 1, or None when unmeasurable.

    Read **only** from `curve_progress`, which comes from the bonding curve
    account itself. The market-cap route this used to take is gone: §14a
    measured it identifying 5 of 386 observed graduations, and leaving it as a
    fallback would quietly reintroduce a signal already disproven.

    `None` and `0` are different claims: one says the curve position is unknown,
    the other says nobody has bought yet. Only the second is a reading.

    `threshold` is retained for callers and tests that still address it, and is
    deliberately unused — curve progress arrives already normalised.
    """
    del threshold
    if observation.curve_progress is None:
        return None
    return max(Decimal(0), min(Decimal(1), observation.curve_progress))


def _progress_score(progress: Decimal, floor: Decimal) -> Decimal:
    """Position on the curve, rescaled so the reportable band spans the range.

    Without the rescale every token in the band would score high purely for
    qualifying, and the component could not tell 60% along from 95%.
    """
    if progress >= Decimal(1):
        return HUNDRED
    span = Decimal(1) - floor
    if span <= 0:
        return HUNDRED
    return _clamp((progress - floor) / span * HUNDRED)


def _progress_velocity(
    observations: list[MarketObservation], *, threshold: Decimal
) -> Decimal | None:
    """Is the curve still filling, or has it stalled?

    A token parked at 80% for a day is a weaker claim than one that arrived
    there in an hour, and this is the component that separates them.
    """
    points = [
        (item.captured_at, _progress(item, threshold=threshold))
        for item in observations
        if _progress(item, threshold=threshold) is not None
    ]
    if len(points) < 2:
        return None

    first_at, first = points[0]
    last_at, last = points[-1]
    assert first is not None and last is not None

    hours = Decimal(str(max((last_at - first_at).total_seconds(), 1) / 3600))
    per_hour = (last - first) / hours

    # 5 percentage points an hour saturates. Chosen as the rate that closes a
    # half-full curve inside a working day; it is a published constant, not a
    # fitted one, because there is no data to fit it against.
    saturation = Decimal("0.05")
    if per_hour <= 0:
        return ZERO
    return _clamp(per_hour / saturation * HUNDRED)


def _volume_trend(observations: list[MarketObservation]) -> Decimal | None:
    """Recent volume against this token's own earlier baseline.

    Its own baseline, never a cross-token one: comparing a token's volume to
    another token's says more about their sizes than about either's trend.
    """
    values = [
        item.volume_24h for item in observations if item.volume_24h is not None
    ]
    if len(values) < 4:
        return None

    half = len(values) // 2
    earlier = sum(values[:half], start=ZERO) / Decimal(half)
    recent = sum(values[half:], start=ZERO) / Decimal(len(values) - half)

    if earlier <= 0:
        # No baseline to compare against. Unknown, not zero.
        return None
    ratio = recent / earlier
    # 1x is flat and scores 50; 3x or better saturates.
    return _clamp((ratio - Decimal(1)) / Decimal(2) * Decimal(50) + Decimal(50))


def _buy_pressure(observations: list[MarketObservation]) -> Decimal | None:
    """Share of trades that were buys, from the change across the window.

    Deltas rather than the raw counters: `buy_count_24h` is a trailing total, so
    its level says what happened over a day while its change says what happened
    since the last observation.
    """
    points = [
        item
        for item in observations
        if item.buy_count_24h is not None and item.sell_count_24h is not None
    ]
    if len(points) < 2:
        return None

    buys = points[-1].buy_count_24h - points[0].buy_count_24h  # type: ignore[operator]
    sells = points[-1].sell_count_24h - points[0].sell_count_24h  # type: ignore[operator]
    total = buys + sells
    if total <= 0:
        # No trades in the window, or a counter that reset. Neither is pressure.
        return None
    return _clamp(Decimal(buys) / Decimal(total) * HUNDRED)


def _transaction_rate(observations: list[MarketObservation]) -> Decimal | None:
    """Trades per hour across the window, from the same deltas."""
    points = [
        item
        for item in observations
        if item.buy_count_24h is not None and item.sell_count_24h is not None
    ]
    if len(points) < 2:
        return None

    trades = (points[-1].buy_count_24h + points[-1].sell_count_24h) - (  # type: ignore[operator]
        points[0].buy_count_24h + points[0].sell_count_24h  # type: ignore[operator]
    )
    if trades <= 0:
        return ZERO

    hours = Decimal(
        str(max((points[-1].captured_at - points[0].captured_at).total_seconds(), 1) / 3600)
    )
    per_hour = Decimal(trades) / hours
    # 60 trades an hour saturates — one a minute. Published, not fitted.
    return _clamp(per_hour / Decimal(60) * HUNDRED)


def _consistency(observations: int, minimum: int) -> Decimal:
    """How much observation stands behind the reading.

    Always available: counting observations needs no market data, and a window
    of two is itself a fact worth reporting.
    """
    if minimum <= 0:
        return HUNDRED
    # Saturates at three times the minimum, so a dense window is rewarded but a
    # very long one does not dominate.
    return _clamp(Decimal(observations) / Decimal(minimum * 3) * HUNDRED)


def _severity(progress: Decimal) -> SignalSeverity:
    """How loudly the signal reads. A property of the type and its position,
    never of how sure we are — that is confidence, which the engine derives."""
    if progress >= Decimal("0.90"):
        return SignalSeverity.MAJOR
    if progress >= Decimal("0.75"):
        return SignalSeverity.NOTABLE
    return SignalSeverity.INFO


def _reason_codes(
    components: list[Component], progress: Decimal, observations: int
) -> tuple[str, ...]:
    by_id = {component.id: component for component in components}
    codes = [REASON_APPROACHING]

    velocity = by_id["progress_velocity"]
    if velocity.available:
        codes.append(
            REASON_PROGRESS_RISING
            if (velocity.score or ZERO) > ZERO
            else REASON_PROGRESS_STALLED
        )

    volume = by_id["volume_trend"]
    if volume.available and (volume.score or ZERO) > Decimal(50):
        codes.append(REASON_VOLUME_EXPANDING)

    buys = by_id["buy_pressure"]
    if buys.available and (buys.score or ZERO) > Decimal(50):
        codes.append(REASON_BUY_PRESSURE)

    rate = by_id["transaction_rate"]
    if rate.available and (rate.score or ZERO) > Decimal(50):
        codes.append(REASON_TRADE_RATE_RISING)

    if observations < 6:
        # Said out loud rather than folded silently into a lower score.
        codes.append(REASON_THIN_OBSERVATION)

    return tuple(codes)


def _evidence(
    components: list[Component],
    *,
    progress: Decimal,
    threshold: Decimal,
    latest: MarketObservation,
    observations: int,
) -> tuple[Evidence, ...]:
    """The named figures behind the score, including what could not be read.

    Unavailable components are listed explicitly. A component omitted from the
    evidence is invisible; one that says "not available" is a fact the reader
    can weigh.
    """
    items = [
        Evidence(
            label="Curve progress",
            value=f"{(progress * HUNDRED).quantize(Decimal('0.1'))}%",
            detail=f"of a {threshold:,.0f} USD graduation threshold",
        ),
        Evidence(
            label="Market cap",
            value=f"{latest.market_cap:,.0f}" if latest.market_cap is not None else "—",
        ),
        Evidence(label="Observations", value=str(observations)),
    ]
    for component in components:
        items.append(
            Evidence(
                label=component.id.replace("_", " ").capitalize(),
                value=(
                    f"{(component.score or ZERO).quantize(Decimal('0.1'))}"
                    if component.available
                    else "not available"
                ),
                detail=f"weight {component.weight}",
            )
        )
    return tuple(items)
