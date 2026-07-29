"""Exit Watch detection.

Each signal is checked independently against the observation window and the
Radar's own score history. Severity comes from **how many independent signals
agree**, not from any one being dramatic — a single collapsing metric on a thin
pool is noise, and three unrelated ones deteriorating together is a pattern.

Thresholds are stated priors, published at `GET /api/v1/exit-watch/model` so the
claim is checkable rather than asserted. They are deliberately *lagging*: Exit
Watch is meant to be right, not early. A warning that fires on every wobble
teaches users to ignore it, which is worse than not having one.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from app.exit_signals.models import (
    ExitAssessment,
    ExitSeverity,
    ExitSignal,
    SignalResult,
)
from app.radar.models import Observation, RadarSeries
from app.radar.normalise import mean, sub_series

#: Below this many observations nothing is concluded — a short series has no
#: trend to roll over.
MIN_OBSERVATIONS = 12

#: The window each signal reads, split into halves for comparison.
WINDOW = 48

# --- Thresholds (stated priors) ----------------------------------------------

#: Volume in the recent half below this share of the earlier half.
VOLUME_COLLAPSE_RATIO = Decimal("0.45")
#: Liquidity in the recent half below this share of the earlier half.
LIQUIDITY_EXIT_RATIO = Decimal("0.80")
#: Price below this share of its window high.
TECHNICAL_BREAKDOWN_RATIO = Decimal("0.70")
#: Radar score fallen by at least this many points from its recorded peak.
MOMENTUM_ROLLOVER_DROP = Decimal(12)
#: Confidence fallen by at least this many points.
CONFIDENCE_DROP = Decimal(15)
#: Share of trades that are sells, above which pressure is building.
SELL_PRESSURE_SHARE = Decimal("0.62")

#: Signals agreeing before the assessment escalates.
WATCH_SIGNALS = 1
ELEVATED_SIGNALS = 3


def _halves(
    observations: Sequence[Observation], attribute: str
) -> tuple[Decimal | None, Decimal | None]:
    values = [getattr(o, attribute) for o in observations]
    midpoint = len(values) // 2
    older = mean([v for v in values[:midpoint] if v is not None])
    newer = mean([v for v in values[midpoint:] if v is not None])
    return older, newer


def _ratio(earlier: Decimal | None, later: Decimal | None) -> Decimal | None:
    """Guarded division. `None` rather than infinity when the base is zero."""
    if earlier is None or later is None or earlier <= 0:
        return None
    return later / earlier


def _magnitude(actual: Decimal, threshold: Decimal) -> Decimal:
    """How far past the threshold, 0-1, for ordering signals by severity."""
    if threshold <= 0:
        return Decimal(1)
    overshoot = (threshold - actual) / threshold
    return max(Decimal(0), min(Decimal(1), overshoot))


def _volume(observations: Sequence[Observation]) -> SignalResult:
    older, newer = _halves(observations, "volume_24h")
    ratio = _ratio(older, newer)
    if ratio is None:
        return SignalResult.unavailable(ExitSignal.VOLUME_COLLAPSING)
    if ratio < VOLUME_COLLAPSE_RATIO:
        return SignalResult.fired(
            ExitSignal.VOLUME_COLLAPSING,
            _magnitude(ratio, VOLUME_COLLAPSE_RATIO),
            ratio=ratio,
        )
    return SignalResult.clear(ExitSignal.VOLUME_COLLAPSING, ratio=ratio)


def _liquidity(observations: Sequence[Observation]) -> SignalResult:
    older, newer = _halves(observations, "liquidity_usd")
    ratio = _ratio(older, newer)
    if ratio is None:
        return SignalResult.unavailable(ExitSignal.LIQUIDITY_LEAVING)
    if ratio < LIQUIDITY_EXIT_RATIO:
        # Weighted more heavily than volume in practice because liquidity
        # leaving is a decision somebody made, where volume falling is often
        # just attention moving on.
        return SignalResult.fired(
            ExitSignal.LIQUIDITY_LEAVING,
            _magnitude(ratio, LIQUIDITY_EXIT_RATIO),
            ratio=ratio,
        )
    return SignalResult.clear(ExitSignal.LIQUIDITY_LEAVING, ratio=ratio)


def _technical(observations: Sequence[Observation]) -> SignalResult:
    prices = [o.price_usd for o in observations if o.price_usd is not None and o.price_usd > 0]
    if len(prices) < MIN_OBSERVATIONS:
        return SignalResult.unavailable(ExitSignal.TECHNICAL_BREAKDOWN)

    high = max(prices)
    latest = prices[-1]
    if high <= 0:
        return SignalResult.unavailable(ExitSignal.TECHNICAL_BREAKDOWN)

    ratio = latest / high
    if ratio < TECHNICAL_BREAKDOWN_RATIO:
        return SignalResult.fired(
            ExitSignal.TECHNICAL_BREAKDOWN,
            _magnitude(ratio, TECHNICAL_BREAKDOWN_RATIO),
            from_high=ratio,
        )
    return SignalResult.clear(ExitSignal.TECHNICAL_BREAKDOWN, from_high=ratio)


def _sell_pressure(observations: Sequence[Observation]) -> SignalResult:
    latest = observations[-1]
    buys, sells = latest.buy_count_24h, latest.sell_count_24h
    if buys is None or sells is None or (buys + sells) <= 0:
        return SignalResult.unavailable(ExitSignal.SELL_PRESSURE_BUILDING)

    share = Decimal(sells) / Decimal(buys + sells)
    if share > SELL_PRESSURE_SHARE:
        magnitude = min(
            Decimal(1), (share - SELL_PRESSURE_SHARE) / (Decimal(1) - SELL_PRESSURE_SHARE)
        )
        return SignalResult.fired(
            ExitSignal.SELL_PRESSURE_BUILDING, magnitude, sell_share=share
        )
    return SignalResult.clear(ExitSignal.SELL_PRESSURE_BUILDING, sell_share=share)


def _score_rollover(current_score: Decimal | None, peak_score: Decimal | None) -> SignalResult:
    if current_score is None or peak_score is None:
        return SignalResult.unavailable(ExitSignal.MOMENTUM_ROLLING_OVER)

    drop = peak_score - current_score
    if drop >= MOMENTUM_ROLLOVER_DROP:
        return SignalResult.fired(
            ExitSignal.MOMENTUM_ROLLING_OVER,
            min(Decimal(1), drop / Decimal(40)),
            drop=drop,
        )
    return SignalResult.clear(ExitSignal.MOMENTUM_ROLLING_OVER, drop=drop)


def _confidence_drop(
    current_confidence: Decimal | None, peak_confidence: Decimal | None
) -> SignalResult:
    if current_confidence is None or peak_confidence is None:
        return SignalResult.unavailable(ExitSignal.CONFIDENCE_DROPPING)

    drop = peak_confidence - current_confidence
    if drop >= CONFIDENCE_DROP:
        return SignalResult.fired(
            ExitSignal.CONFIDENCE_DROPPING,
            min(Decimal(1), drop / Decimal(50)),
            drop=drop,
        )
    return SignalResult.clear(ExitSignal.CONFIDENCE_DROPPING, drop=drop)


def _below_detection(
    current_price: Decimal | None, first_price: Decimal | None
) -> SignalResult:
    """Trading below where the Radar found it.

    Included because it is the one signal a user would check first, and leaving
    it implicit would make the platform look like it was avoiding the subject.
    """
    if current_price is None or first_price is None or first_price <= 0:
        return SignalResult.unavailable(ExitSignal.PRICE_BELOW_DETECTION)

    multiple = current_price / first_price
    if multiple < Decimal(1):
        return SignalResult.fired(
            ExitSignal.PRICE_BELOW_DETECTION,
            min(Decimal(1), Decimal(1) - multiple),
            multiple=multiple,
        )
    return SignalResult.clear(ExitSignal.PRICE_BELOW_DETECTION, multiple=multiple)


def assess(
    series: RadarSeries,
    *,
    now: datetime,
    current_score: Decimal | None = None,
    peak_score: Decimal | None = None,
    current_confidence: Decimal | None = None,
    peak_confidence: Decimal | None = None,
    first_price: Decimal | None = None,
) -> ExitAssessment:
    """Assess one token. Pure: a function of its arguments alone."""
    observations = sub_series(series.observations, WINDOW)

    if len(observations) < MIN_OBSERVATIONS:
        # Not enough history to conclude anything. Reported as CLEAR with zero
        # coverage rather than as "nothing wrong" — the API renders the
        # difference, and a user reading "clear" on a token nobody has watched
        # would be misled.
        return ExitAssessment(
            mint_address=series.mint_address,
            severity=ExitSeverity.CLEAR,
            signals=tuple(SignalResult.unavailable(signal) for signal in ExitSignal),
            evaluated_at=now,
            coverage=Decimal(0),
        )

    latest = observations[-1]
    signals: tuple[SignalResult, ...] = (
        _volume(observations),
        _liquidity(observations),
        _technical(observations),
        _sell_pressure(observations),
        _score_rollover(current_score, peak_score),
        _confidence_drop(current_confidence, peak_confidence),
        _below_detection(latest.price_usd, first_price),
        # Declared and permanently unavailable — no wallet or holder data. The
        # gap is visible in coverage rather than silently absent, which is the
        # same mechanism the scoring engine and the Radar both use.
        SignalResult.unavailable(ExitSignal.SMART_MONEY_DISTRIBUTING),
        SignalResult.unavailable(ExitSignal.HOLDER_GROWTH_STALLING),
    )

    checkable = sum(1 for signal in signals if signal.available)
    coverage = Decimal(checkable) / Decimal(len(signals)) * Decimal(100)
    fired = sum(1 for signal in signals if signal.triggered)

    if fired >= ELEVATED_SIGNALS:
        severity = ExitSeverity.ELEVATED
    elif fired >= WATCH_SIGNALS:
        severity = ExitSeverity.WATCH
    else:
        severity = ExitSeverity.CLEAR

    return ExitAssessment(
        mint_address=series.mint_address,
        severity=severity,
        signals=signals,
        evaluated_at=now,
        coverage=coverage,
    )
