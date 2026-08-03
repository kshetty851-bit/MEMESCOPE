"""What became of a signal. AD-10's exit paths 2 and 3, and nothing else.

Expiry (path 1) was already built: a signal that stops being re-detected lapses
on its TTL. That is an exit, but it is not an *outcome* — "nobody confirmed this
again" says nothing about whether the claim was right. This module adds the two
exits that do:

  * **Realisation** — the thing the signal predicted happened.
  * **Invalidation** — the transition the signal reported reversed.

Pure. The rules read the same `ObservationWindow` the engine already loaded for
detection, so an outcome costs no query and can be replayed over history exactly
as it was decided live.

## Not every signal can realise, and this is the crux

A signal is either **predictive** — it claims something is about to happen — or
**factual**: it reports a change that has already completed. Only a predictive
claim can come true, so only a predictive claim has a *precision*.

Fresh graduation and breakout are factual. A token that left its bonding curve
left it; a price that broke its range broke it. Neither can be "wrong later",
and a price that retraces afterwards does not un-make the move that was
observed. Scoring them for precision would compute `realised / (realised +
invalidated)` over a numerator that is structurally always zero and publish
0.00 against providers that never made a prediction to miss. That number would
be arithmetically correct and completely false, which is the worst kind this
platform can produce.

So precision is defined over `PREDICTIVE_SIGNALS` only, and a provider that
emits none of them reports precision unavailable — with that as the reason,
rather than a zero.

Invalidation still applies to factual signals, and still means something: it
says the observation was **contradicted** — a venue that went back to the
bonding curve was an indexing artefact, not a graduation. That is a data
correction and it is counted separately, never as a failed prediction.

## What has no rule, and why

**Breakout has no invalidation rule.** A completed price move cannot reverse
into never having happened; a retracement is a later fact, not a correction of
an earlier one. It exits on TTL like the factual observation it is. Inventing a
"broke back below" rule would quietly convert every ordinary retracement into a
recorded failure and make the board's history read as though the platform were
usually wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.opportunities.models import (
    MarketObservation,
    ObservationWindow,
    SignalStatus,
    SignalType,
)
from app.opportunities.providers.breakout import trailing_high

#: Signal types that make a forward-looking claim, and therefore have a
#: precision. Everything else is an observation of a completed change.
PREDICTIVE_SIGNALS: frozenset[SignalType] = frozenset(
    {SignalType.NEAR_GRADUATION, SignalType.PRE_BREAKOUT}
)

#: Reason codes for the outcome itself, rendered in `explain.py` like every
#: other code. Stored on the event, never as prose.
REASON_BREAKOUT_REALISED = "pre_breakout_became_breakout"
REASON_PRESSURE_FADED = "pre_breakout_pressure_faded"
REASON_GRADUATION_REALISED = "near_graduation_became_graduation"
REASON_CURVE_RETREATED = "curve_progress_retreated"
REASON_VENUE_REVERTED = "graduation_venue_reverted"


@dataclass(frozen=True, slots=True)
class Outcome:
    """A terminal verdict on one signal, with the code that explains it."""

    status: SignalStatus
    reason_code: str

    @property
    def realised(self) -> bool:
        return self.status is SignalStatus.REALISED


@dataclass(frozen=True, slots=True)
class OutcomeRules:
    """The thresholds an assessment reads.

    The same numbers the breakout provider published as its boundaries. Passed
    in rather than read from settings here, so the rules stay pure and a replay
    can re-decide history under the policy that was actually in force.
    """

    price_margin: Decimal
    proximity: Decimal
    bonding_curve_venues: frozenset[str]
    graduated_venues: frozenset[str]
    min_curve_progress: Decimal


def assess(
    signal_type: SignalType,
    window: ObservationWindow,
    *,
    observed_at: datetime | None,
    rules: OutcomeRules,
) -> Outcome | None:
    """The signal's outcome, or `None` while it is still an open question.

    `None` is the overwhelmingly common answer and is not a failure: most
    signals neither realise nor reverse before their TTL runs out, and forcing a
    verdict on them would be the estimate this platform refuses to make.

    A signal is never judged by the observation that created it. `observed_at`
    is the snapshot the claim was derived from, and an outcome read from that
    same snapshot would be the claim marking its own homework — the window has
    to have moved on first.
    """
    latest = window.latest
    if latest is None:
        return None
    if observed_at is not None and latest.captured_at <= observed_at:
        return None

    if signal_type is SignalType.PRE_BREAKOUT:
        return _assess_pre_breakout(window, latest=latest, rules=rules)
    if signal_type is SignalType.NEAR_GRADUATION:
        return _assess_near_graduation(window, latest=latest, rules=rules)
    if signal_type is SignalType.FRESH_GRADUATION:
        return _assess_fresh_graduation(latest=latest, rules=rules)
    # Breakout, and every signal type whose provider has not shipped. No rule is
    # the honest answer for both: see the module docstring.
    return None


# --- Per-type rules -----------------------------------------------------------


def _assess_pre_breakout(
    window: ObservationWindow, *, latest: MarketObservation, rules: OutcomeRules
) -> Outcome | None:
    """Did the pressure resolve into a break, or drain away?

    This is the realisation path ADR §15 names for step 3: the signal exits, and
    the same window re-enters through the provider as a breakout on the next
    cycle. Two records of one story, in the right order, rather than one signal
    quietly changing what it claimed.
    """
    resistance = trailing_high(window.observations[:-1])
    if resistance is None or latest.price_usd is None or latest.price_usd <= 0:
        # No range to compare against. Unknown, not unrealised — the same
        # refusal the provider makes on the same missing field.
        return None

    ratio = latest.price_usd / resistance
    if ratio >= Decimal(1) + rules.price_margin:
        return Outcome(SignalStatus.REALISED, REASON_BREAKOUT_REALISED)
    if ratio < rules.proximity:
        # Out of the band it was detected in. The claim was that price was
        # pressing against its range; it no longer is.
        return Outcome(SignalStatus.INVALIDATED, REASON_PRESSURE_FADED)
    return None


def _assess_near_graduation(
    window: ObservationWindow, *, latest: MarketObservation, rules: OutcomeRules
) -> Outcome | None:
    """Did it graduate, or did the curve drain back?

    Graduation is read from the venue, which is stored for every token. The
    retreat arm reads `curve_progress`, which is collected only while curve
    collection runs — absent, it returns `None` rather than inferring a retreat
    from market cap, which §14a measured as unusable.
    """
    venue = _venue(latest.dex_name)
    if venue is not None and venue in rules.graduated_venues:
        return Outcome(SignalStatus.REALISED, REASON_GRADUATION_REALISED)

    progress = latest.curve_progress
    if progress is not None and progress < rules.min_curve_progress:
        return Outcome(SignalStatus.INVALIDATED, REASON_CURVE_RETREATED)
    return None


def _assess_fresh_graduation(
    *, latest: MarketObservation, rules: OutcomeRules
) -> Outcome | None:
    """A graduated token seen back on a bonding curve contradicts the reading.

    Factual, so this is a correction rather than a failed prediction: the venue
    change that was reported did not hold, which means the platform saw an
    indexing artefact. Counted as a contradiction, never against precision.
    """
    venue = _venue(latest.dex_name)
    if venue is not None and venue in rules.bonding_curve_venues:
        return Outcome(SignalStatus.INVALIDATED, REASON_VENUE_REVERTED)
    return None


def _venue(dex_name: str | None) -> str | None:
    if dex_name is None:
        return None
    normalised = dex_name.strip().lower()
    return normalised or None
