"""Breakout: a token trading above its own recent range, on expanded volume.

ADR §15 step 3, and the first provider that needs a *window* rather than a
transition between two observations. Fresh graduation reads one field changing;
this reads a series and asks whether the latest reading left the range the
series established.

## Why these inputs

`volume_1h`, `volume_24h` and the trade counts are present on **100 %** of
stored snapshots across every venue; `price_usd` on 88.5 % of pump.fun rows and
100 % elsewhere (measured over 1.72 M snapshots, 2026-08-03). Liquidity is not
used at all — it is null for every bonding-curve pair (ADR 0002), and a
component that silently drops out for the majority of the universe is worse
than one that was never claimed.

## The baseline, which ADR §16 left open

**Trailing median of the token's own window**, not a mean. The question was
recorded as empirical and the data answers it: memecoin volume is spiky enough
that one outlying observation drags a mean above every other reading in the
window, and a baseline that the current value helped set cannot detect that the
current value is unusual. The median is unmoved by the spike it is meant to
measure. The current observation is excluded from its own baseline for the same
reason.

## Range, not duration

The claim is about the token's own recent observations, never about a fixed
wall-clock span. Snapshot cadence is tier-dependent — 30 s for a fresh token,
6 h for an old one — so twelve observations is anywhere from six minutes to
three days, and a provider that said "24-hour high" would be wrong for most of
the universe. The window's actual span is measured and published as evidence,
so a reader sees which one they are looking at. This is ADR §16's open
"confirmation window per tier" question answered by disclosure rather than by
picking a number that is wrong for two thirds of tokens.

## What is deliberately not claimed

Nothing about what happens next. A breakout is an observation that the range
broke — not a prediction that it keeps going, and never a recommendation.
Whether the move held is *precision*, which needs the realisation exit path and
is reported unavailable until it exists (see `analytics.py`).
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from app.core.config import settings
from app.opportunities.models import (
    Evidence,
    MarketObservation,
    ObservationWindow,
    ProviderMeta,
    ProviderResult,
    SignalCandidate,
    SignalSeverity,
    SignalType,
)
from app.opportunities.providers.base import SignalProvider

PROVIDER_ID = "breakout"

#: Reason codes. Stable identifiers; the prose lives in `explain.py` so a
#: rewording is a deploy rather than a migration (AD-07).
REASON_PRICE_BROKE_RANGE = "price_broke_trailing_high"
REASON_VOLUME_EXPANDED = "volume_expanded_over_baseline"
REASON_APPROACHING_RANGE = "approaching_trailing_high"
REASON_BUY_PRESSURE = "buy_pressure_dominant"
REASON_THIN_WINDOW = "thin_observation_window"

#: Why the provider cannot answer for a given token. Each names the field, so
#: the gap is attributable rather than a generic shrug.
NO_WINDOW = (
    "Too few observations to establish a range. A breakout is a departure from "
    "a baseline, and there is no baseline yet."
)
NO_PRICE = (
    "This token's market snapshots carry no price, so there is no range to "
    "break. Bonding-curve pairs report a price for 88.5% of observations."
)
NO_VOLUME = (
    "This token's market snapshots carry no hourly volume, so expansion cannot "
    "be measured against a baseline."
)

#: A window this thin still answers, but says so in its own explanation.
_COMFORTABLE_OBSERVATIONS = 10


class BreakoutProvider(SignalProvider):
    """Emits `BREAKOUT`, or `PRE_BREAKOUT` when the range is approached but held.

    The two are mutually exclusive by construction — one requires the price to
    have cleared the trailing high, the other requires it not to have — so a
    single window never produces both. That matters: two live signals on one
    opportunity is corroboration, and a provider corroborating itself would
    inflate confidence with one observation counted twice.
    """

    def __init__(
        self,
        *,
        min_observations: int | None = None,
        price_margin: Decimal | None = None,
        volume_multiple: Decimal | None = None,
        proximity: Decimal | None = None,
    ) -> None:
        # Configured, not hardcoded. Every threshold here is an empirical claim
        # about a market that moves, and the platform publishes its boundaries
        # (AD-07) — a number that can only be changed by a deploy is one nobody
        # revisits when the measurement that justified it goes stale.
        self._min_observations = (
            min_observations
            if min_observations is not None
            else settings.OPPORTUNITY_BREAKOUT_MIN_OBSERVATIONS
        )
        self._price_margin = _decimal(
            price_margin, settings.OPPORTUNITY_BREAKOUT_PRICE_MARGIN
        )
        self._volume_multiple = _decimal(
            volume_multiple, settings.OPPORTUNITY_BREAKOUT_VOLUME_MULTIPLE
        )
        self._proximity = _decimal(proximity, settings.OPPORTUNITY_BREAKOUT_PROXIMITY)

    @property
    def meta(self) -> ProviderMeta:
        return ProviderMeta(
            provider_id=PROVIDER_ID,
            name="Breakout",
            question="Has this token left the price range its own recent history set?",
            emits=(SignalType.BREAKOUT, SignalType.PRE_BREAKOUT),
            operational=True,
            required_fields=("price_usd", "volume_1h"),
        )

    def evaluate(self, window: ObservationWindow, *, now: datetime) -> ProviderResult:
        latest = window.latest
        if latest is None or len(window) < self._min_observations:
            return self._unavailable(NO_WINDOW)

        prior = window.observations[:-1]
        resistance = trailing_high(prior)
        baseline = _trailing_median_volume(prior)

        if latest.price_usd is None or latest.price_usd <= 0 or resistance is None:
            return self._unavailable(NO_PRICE)
        if latest.volume_1h is None or baseline is None or baseline <= 0:
            return self._unavailable(NO_VOLUME)

        break_ratio = latest.price_usd / resistance
        volume_ratio = latest.volume_1h / baseline
        expanded = volume_ratio >= self._volume_multiple

        # Volume expansion is required by both claims. A price that drifts above
        # its range on no extra trading is not a breakout; it is the same
        # thinness that set the range, re-read.
        if not expanded:
            return self._nothing()

        broke = break_ratio >= Decimal(1) + self._price_margin
        approaching = not broke and break_ratio >= self._proximity

        if not broke and not approaching:
            return self._nothing()

        return ProviderResult(
            provider_id=PROVIDER_ID,
            candidates=(
                self._candidate(
                    window,
                    latest=latest,
                    observations=len(window),
                    resistance=resistance,
                    baseline=baseline,
                    break_ratio=break_ratio,
                    volume_ratio=volume_ratio,
                    broke=broke,
                ),
            ),
        )

    # --- Building the claim --------------------------------------------------

    def _candidate(
        self,
        window: ObservationWindow,
        *,
        latest: MarketObservation,
        observations: int,
        resistance: Decimal,
        baseline: Decimal,
        break_ratio: Decimal,
        volume_ratio: Decimal,
        broke: bool,
    ) -> SignalCandidate:
        buys = latest.buy_count_24h
        sells = latest.sell_count_24h
        buy_pressure = buys is not None and sells is not None and buys > sells

        codes = [
            REASON_PRICE_BROKE_RANGE if broke else REASON_APPROACHING_RANGE,
            REASON_VOLUME_EXPANDED,
        ]
        if buy_pressure:
            codes.append(REASON_BUY_PRESSURE)
        if observations < _COMFORTABLE_OBSERVATIONS:
            # Charged to the explanation rather than hidden. The signal is still
            # emitted — refusing outright would lose a real transition — but a
            # reader is told how much history stands behind it.
            codes.append(REASON_THIN_WINDOW)

        return SignalCandidate(
            mint_address=window.mint_address,
            signal_type=SignalType.BREAKOUT if broke else SignalType.PRE_BREAKOUT,
            strength=_strength(
                break_ratio=break_ratio,
                volume_ratio=volume_ratio,
                price_margin=self._price_margin,
                volume_multiple=self._volume_multiple,
                broke=broke,
            ),
            severity=SignalSeverity.MAJOR if broke else SignalSeverity.NOTABLE,
            reason_codes=tuple(codes),
            evidence=_evidence(
                window,
                latest=latest,
                observations=observations,
                resistance=resistance,
                baseline=baseline,
                break_ratio=break_ratio,
                volume_ratio=volume_ratio,
                buys=buys,
                sells=sells,
            ),
            # No stage opinion. Breaking a range says nothing about where the
            # token is in its own life, and `UNKNOWN` is the honest default the
            # stage enum already documents.
            stage=None,
            observed_at=latest.captured_at,
        )


# --- Pure helpers -------------------------------------------------------------


def _decimal(override: Decimal | None, configured: float) -> Decimal:
    """Thresholds as `Decimal`, so a ratio never mixes float and Decimal.

    Configuration arrives as float because that is what env parsing gives; every
    comparison downstream is against `NUMERIC` columns, and mixing the two is
    the arithmetic that makes a replay disagree with production by a rounding
    step.
    """
    return override if override is not None else Decimal(str(configured))


def trailing_high(prior: Sequence[MarketObservation]) -> Decimal | None:
    """The range the token itself set, excluding the observation under test.

    Public because `outcomes.py` decides whether a pre-breakout realised by
    asking the same question of the same window. Two implementations of "the
    range" would let a signal be opened against one boundary and judged against
    another.
    """
    prices = [
        observation.price_usd
        for observation in prior
        if observation.price_usd is not None and observation.price_usd > 0
    ]
    return max(prices) if prices else None


def _trailing_median_volume(prior: Sequence[MarketObservation]) -> Decimal | None:
    """Median hourly volume over the window, excluding the current reading.

    The median rather than the mean, and excluding the current observation:
    a baseline that the value under test helped set cannot report that value as
    unusual. See the module docstring for the measurement behind the choice.
    """
    volumes = [
        observation.volume_1h
        for observation in prior
        if observation.volume_1h is not None and observation.volume_1h >= 0
    ]
    if not volumes:
        return None
    # `statistics.median` on Decimals averages the middle pair for an even
    # count, which stays exact — Decimal division, not float.
    return Decimal(statistics.median(volumes))


def _strength(
    *,
    break_ratio: Decimal,
    volume_ratio: Decimal,
    price_margin: Decimal,
    volume_multiple: Decimal,
    broke: bool,
) -> Decimal:
    """0-100, from how far past its own boundaries the observation is.

    Two normalised components, each saturating at twice its threshold, mixed
    60/40 in favour of price: the price break is the claim, and volume is what
    makes it credible rather than what makes it large. A qualifying signal
    starts at 50 — it already cleared a published boundary, and a strength near
    zero would rank a real transition below noise.

    Saturating rather than unbounded on purpose. A 25 000x ratio appears in the
    stored history (a token whose prior price was effectively zero), and a
    linear scale would let one such row dominate every ranking it appears in.
    """
    price_component = _saturating(break_ratio - Decimal(1), price_margin * 2)
    volume_component = _saturating(
        volume_ratio - Decimal(1), (volume_multiple - Decimal(1)) * 2
    )
    mixed = price_component * Decimal("0.6") + volume_component * Decimal("0.4")
    floor = Decimal(50) if broke else Decimal(40)
    return (floor + (Decimal(100) - floor) * mixed).quantize(Decimal("0.01"))


def _saturating(excess: Decimal, span: Decimal) -> Decimal:
    """`excess / span`, clamped to 0-1. Zero span saturates rather than divides."""
    if span <= 0:
        return Decimal(1)
    return max(Decimal(0), min(Decimal(1), excess / span))


def _evidence(
    window: ObservationWindow,
    *,
    latest: MarketObservation,
    observations: int,
    resistance: Decimal,
    baseline: Decimal,
    break_ratio: Decimal,
    volume_ratio: Decimal,
    buys: int | None,
    sells: int | None,
) -> tuple[Evidence, ...]:
    """The figures behind the claim, in the order a reader needs them.

    Every number here is one the reader could recompute from stored snapshots.
    That is what makes the explanation auditable rather than a summary.
    """
    span_minutes = int(
        (latest.captured_at - window.observations[0].captured_at).total_seconds() // 60
    )
    items = [
        Evidence(
            label="Trailing high",
            value=f"{resistance:f}",
            detail=f"Highest of the previous {observations - 1} observations",
        ),
        Evidence(label="Latest price", value=f"{latest.price_usd:f}"),
        Evidence(
            label="Above range by",
            value=f"{(break_ratio - Decimal(1)) * 100:.1f}%",
        ),
        Evidence(
            label="Volume baseline",
            value=f"{baseline:f}",
            detail="Median hourly volume across the window",
        ),
        Evidence(
            label="Latest hourly volume",
            value=f"{latest.volume_1h:f}",
            detail=f"{volume_ratio:.1f}x the baseline",
        ),
        Evidence(
            label="Window",
            value=f"{observations} observations",
            # Published because cadence is tier-dependent: the same twelve
            # observations are six minutes for a fresh token and three days for
            # an old one, and the reader is entitled to know which.
            detail=f"Spanning {span_minutes} minutes",
        ),
    ]
    if buys is not None and sells is not None:
        items.append(
            Evidence(
                label="Trades (24h)",
                value=f"{buys} buys / {sells} sells",
            )
        )
    return tuple(items)
