"""Fresh graduation: a token that has left its bonding curve.

The first provider, chosen deliberately as the first because it is the cleanest
honest signal the platform can produce today. `dex_name` moving from a
bonding-curve venue to a graduated one is a factual, already-stored, unambiguous
transition — no threshold to tune, no missing data to work around, and no
dependency on the liquidity gap that caps almost everything else
(ARCHITECTURE_DECISIONS.md §14, §15).

It detects that transition and nothing else. No scoring, no ranking, no opinion
about whether graduating was good.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.core.config import settings
from app.opportunities.models import (
    Evidence,
    ObservationWindow,
    OpportunityStage,
    ProviderMeta,
    ProviderResult,
    SignalCandidate,
    SignalSeverity,
    SignalType,
)
from app.opportunities.providers.base import SignalProvider

PROVIDER_ID = "fresh_graduation"

#: Reason codes, rendered into prose at read time and never stored as text.
REASON_GRADUATED = "graduated_from_bonding_curve"
REASON_VENUE_CHANGED = "trading_venue_changed"


class FreshGraduationProvider(SignalProvider):
    """Emits `FRESH_GRADUATION` on a bonding-curve → graduated venue change."""

    def __init__(
        self,
        *,
        bonding_curve_venues: frozenset[str] | None = None,
        graduated_venues: frozenset[str] | None = None,
    ) -> None:
        # Read from configuration rather than hardcoded. A launchpad renaming
        # its venue is a config change, not a code change — the same reasoning
        # that keeps `SCANNER_WATCH_PROGRAMS` configurable, and pump.fun has
        # already renamed an instruction once.
        self._bonding = bonding_curve_venues or frozenset(
            venue.lower() for venue in settings.OPPORTUNITY_BONDING_CURVE_VENUES
        )
        self._graduated = graduated_venues or frozenset(
            venue.lower() for venue in settings.OPPORTUNITY_GRADUATED_VENUES
        )

    @property
    def meta(self) -> ProviderMeta:
        return ProviderMeta(
            provider_id=PROVIDER_ID,
            name="Fresh Graduation",
            question="Has this token just left its bonding curve?",
            emits=(SignalType.FRESH_GRADUATION,),
            operational=True,
            required_fields=("dex_name",),
        )

    def evaluate(self, window: ObservationWindow, *, now: datetime) -> ProviderResult:
        latest = window.latest
        if latest is None:
            return self._nothing()

        current_venue = _venue(latest.dex_name)
        if current_venue is None or current_venue not in self._graduated:
            return self._nothing()

        # The most recent *earlier* observation that named a venue. Not simply
        # the previous row: a snapshot with no pool indexed yet carries a null
        # `dex_name`, and treating that as "no previous venue" would report a
        # graduation every time a gap happened to precede a graduated reading.
        previous_venue = _previous_venue(window)
        if previous_venue is None:
            # First venue ever seen. A token discovered after it had already
            # graduated has not graduated *now*, and claiming otherwise would
            # put weeks-old events on a board that promises new ones.
            return self._nothing()

        if previous_venue not in self._bonding:
            # Some other venue change — a new pool on an established token, say.
            # Real, but not this provider's subject.
            return self._nothing()

        return ProviderResult(
            provider_id=PROVIDER_ID,
            candidates=(
                SignalCandidate(
                    mint_address=window.mint_address,
                    signal_type=SignalType.FRESH_GRADUATION,
                    # A completed graduation is a binary fact, not a matter of
                    # degree. Strength is the provider's claim about the
                    # transition; how much to trust it is confidence, which the
                    # engine derives from confirmation and evidence.
                    strength=Decimal(100),
                    severity=SignalSeverity.MAJOR,
                    reason_codes=(REASON_GRADUATED, REASON_VENUE_CHANGED),
                    evidence=(
                        Evidence(
                            label="Previous venue",
                            value=previous_venue,
                            detail="Bonding curve",
                        ),
                        Evidence(
                            label="Current venue",
                            value=current_venue,
                            detail="Graduated pool",
                        ),
                        Evidence(
                            label="Observed at",
                            value=latest.captured_at.isoformat(),
                        ),
                    ),
                    stage=OpportunityStage.FRESH_GRADUATION,
                    observed_at=latest.captured_at,
                ),
            ),
        )


def _venue(dex_name: str | None) -> str | None:
    """Normalised venue name, or None when the observation names no venue."""
    if dex_name is None:
        return None
    normalised = dex_name.strip().lower()
    return normalised or None


def _previous_venue(window: ObservationWindow) -> str | None:
    """The venue of the most recent observation before the latest one.

    Walks backwards past observations with no venue, which are the normal state
    for a token whose pool is not indexed yet rather than an error.
    """
    for observation in reversed(window.observations[:-1]):
        venue = _venue(observation.dex_name)
        if venue is not None:
            return venue
    return None
