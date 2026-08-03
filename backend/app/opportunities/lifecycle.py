"""The lifecycle state machine, TTL policy, confidence and priority.

Every function here is pure: same inputs, same answer, no I/O and no clock.
`now` is always a parameter. That is what makes a past board reconstructible
exactly (AD-08) and lets the whole state machine be tested without a database.

    NEW → PENDING_CONFIRMATION → ACTIVE → EXPIRING → CLOSED → ARCHIVED
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.opportunities.models import (
    LIVE_SIGNAL_STATUSES,
    OpportunityPriority,
    OpportunityStatus,
    SignalSeverity,
    SignalStatus,
    SignalType,
)

ZERO = Decimal(0)
HUNDRED = Decimal(100)


def clamp(value: Decimal, low: Decimal = ZERO, high: Decimal = HUNDRED) -> Decimal:
    return max(low, min(high, value))


# --- Transitions -------------------------------------------------------------

#: Which moves are legal. An illegal transition is a bug in the engine, not a
#: state the data can reach, so it raises rather than being silently coerced.
#:
#: EXPIRING → ACTIVE is deliberate: a signal re-detected during the grace window
#: revives the opportunity rather than closing it and opening a new generation.
#: Without it a flapping signal would mint a new generation every few minutes
#: and the permanent record would be unreadable.
_ALLOWED: dict[OpportunityStatus, frozenset[OpportunityStatus]] = {
    OpportunityStatus.NEW: frozenset(
        {OpportunityStatus.PENDING_CONFIRMATION, OpportunityStatus.ACTIVE}
    ),
    OpportunityStatus.PENDING_CONFIRMATION: frozenset(
        {OpportunityStatus.ACTIVE, OpportunityStatus.EXPIRING, OpportunityStatus.CLOSED}
    ),
    OpportunityStatus.ACTIVE: frozenset(
        {OpportunityStatus.EXPIRING, OpportunityStatus.CLOSED}
    ),
    OpportunityStatus.EXPIRING: frozenset(
        {OpportunityStatus.ACTIVE, OpportunityStatus.CLOSED}
    ),
    OpportunityStatus.CLOSED: frozenset({OpportunityStatus.ARCHIVED}),
    OpportunityStatus.ARCHIVED: frozenset(),
}


class IllegalTransitionError(RuntimeError):
    """A move the state machine does not permit."""


def can_transition(current: OpportunityStatus, target: OpportunityStatus) -> bool:
    return target in _ALLOWED[current]


def assert_transition(current: OpportunityStatus, target: OpportunityStatus) -> None:
    if not can_transition(current, target):
        raise IllegalTransitionError(
            f"{current.value} -> {target.value} is not a legal transition"
        )


# --- Expiry policy -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExpiryPolicy:
    """Per-signal-type TTLs, plus the two opportunity-level windows.

    TTL is a property of the signal type and never global (AD-10): "fresh
    graduation" is meaningless after two days while a community surge is still
    young. Types with no entry fall back to `default_ttl_seconds` so a provider
    added in a future sprint cannot produce an immortal signal by omission.
    """

    ttl_seconds: dict[SignalType, int]
    default_ttl_seconds: int
    #: How long an opportunity stays EXPIRING before closing. A re-detection
    #: inside this window revives it in place.
    grace_seconds: int
    #: How long a CLOSED opportunity waits before it is archived and its token
    #: may open a new generation.
    archive_after_seconds: int

    def ttl_for(self, signal_type: SignalType) -> timedelta:
        return timedelta(
            seconds=self.ttl_seconds.get(signal_type, self.default_ttl_seconds)
        )

    def expires_at(self, signal_type: SignalType, *, detected_at: datetime) -> datetime:
        return detected_at + self.ttl_for(signal_type)


# --- Confidence --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConfidenceInputs:
    """The four terms of AD-06, gathered so the maths is inspectable."""

    #: The provider's own 0-100 reading of how strong the transition was.
    strength: Decimal
    #: How many times this signal has been observed. 1 is a first sighting.
    confirmations: int
    #: How many *independent* providers reported the same signal type.
    corroborating_providers: int
    #: Observations available in the window the signal was derived from.
    observations: int
    #: Seconds since the observation the signal was derived from.
    age_seconds: float
    #: The TTL of this signal type, as the yardstick age is measured against.
    ttl_seconds: int


@dataclass(frozen=True, slots=True)
class ConfidencePolicy:
    """Weights and shapes. Published, so the number is checkable."""

    #: Confirmations needed before a signal may become ACTIVE. Below this the
    #: opportunity sits in PENDING_CONFIRMATION and is not on any board — one
    #: snapshot is noise (AD-03).
    required_confirmations: int = 2
    #: Observations at which the data-quality term saturates.
    full_evidence_observations: int = 6
    #: Confirmations at which the persistence term saturates. Bounded on
    #: purpose: repetition alone must not reach high confidence.
    persistence_ceiling: int = 4
    #: The most persistence can contribute, as a fraction.
    persistence_weight: Decimal = Decimal("0.25")
    #: The most corroboration can contribute, as a fraction.
    corroboration_weight: Decimal = Decimal("0.20")
    #: The most data quality can contribute, as a fraction.
    evidence_weight: Decimal = Decimal("0.25")
    #: Floor the freshness multiplier cannot fall below while a signal is live,
    #: so an ageing signal decays rather than collapsing to zero.
    freshness_floor: Decimal = Decimal("0.40")
    #: Below this, an opportunity is not ranked at all — a gate, never a
    #: multiplier, so a thinly-evidenced signal cannot climb the board (AD-08).
    evidence_gate_observations: int = 2


def freshness(age_seconds: float, ttl_seconds: int, *, floor: Decimal) -> Decimal:
    """1.0 at the moment of observation, decaying linearly to `floor` at TTL.

    Linear rather than exponential because the reader has to be able to predict
    it. A signal half way through its life is worth half of the decayable part,
    which is a sentence anyone can check against the number.
    """
    if ttl_seconds <= 0:
        return floor
    elapsed = max(Decimal(0), Decimal(str(age_seconds)))
    fraction = min(Decimal(1), elapsed / Decimal(ttl_seconds))
    return clamp(Decimal(1) - (Decimal(1) - floor) * fraction, floor, Decimal(1))


def confidence_for(
    inputs: ConfidenceInputs, *, policy: ConfidencePolicy | None = None
) -> Decimal:
    """0-100. Deterministic, and derived from the four terms of AD-06.

    Rises with confirmation, corroboration and widening evidence; falls with
    freshness decay. The provider's `strength` sets the ceiling — no amount of
    repetition turns a weak transition into a strong one, it only makes us
    surer about how weak it is.
    """
    resolved = policy or ConfidencePolicy()

    persistence = min(
        Decimal(1),
        Decimal(max(0, inputs.confirmations - 1)) / Decimal(resolved.persistence_ceiling),
    )
    corroboration = min(
        Decimal(1),
        Decimal(max(0, inputs.corroborating_providers - 1)) / Decimal(2),
    )
    evidence = min(
        Decimal(1),
        Decimal(max(0, inputs.observations)) / Decimal(resolved.full_evidence_observations),
    )

    # The base is what the provider claimed, scaled down when the supporting
    # terms are absent and back up to its full value when they are all present.
    supported = (
        Decimal(1)
        - resolved.persistence_weight
        - resolved.corroboration_weight
        - resolved.evidence_weight
        + resolved.persistence_weight * persistence
        + resolved.corroboration_weight * corroboration
        + resolved.evidence_weight * evidence
    )
    decayed = freshness(
        inputs.age_seconds, inputs.ttl_seconds, floor=resolved.freshness_floor
    )

    return clamp(clamp(inputs.strength) * supported * decayed)


# --- Priority ----------------------------------------------------------------

#: Severity as a multiplier. Published constants, per AD-08.
_SEVERITY_WEIGHT: dict[SignalSeverity, Decimal] = {
    SignalSeverity.INFO: Decimal("0.40"),
    SignalSeverity.NOTABLE: Decimal("0.65"),
    SignalSeverity.MAJOR: Decimal("0.85"),
    SignalSeverity.CRITICAL: Decimal("1.00"),
}


def priority_for(
    *,
    severity: SignalSeverity,
    confidence: Decimal,
    observations: int,
    policy: ConfidencePolicy | None = None,
) -> Decimal:
    """`severity x confidence`, gated on evidence.

    Evidence is a gate rather than a multiplier: below the floor the result is
    zero and the opportunity is not ranked at all. A multiplier would let a
    confident-looking, thinly-evidenced signal climb; a gate cannot.

    Freshness is already inside `confidence`, so it is not applied twice here.
    """
    resolved = policy or ConfidencePolicy()
    if observations < resolved.evidence_gate_observations:
        return ZERO
    return clamp(_SEVERITY_WEIGHT[severity] * clamp(confidence))


def priority_band(priority: Decimal) -> OpportunityPriority:
    """The coarse band a numeric priority falls into."""
    if priority >= Decimal(75):
        return OpportunityPriority.CRITICAL
    if priority >= Decimal(50):
        return OpportunityPriority.HIGH
    if priority >= Decimal(25):
        return OpportunityPriority.MEDIUM
    return OpportunityPriority.LOW


# --- Resolving an opportunity's status ---------------------------------------


@dataclass(frozen=True, slots=True)
class SignalView:
    """The minimum of a signal the state machine needs. Storage-agnostic."""

    signal_type: SignalType
    status: SignalStatus
    confirmations: int
    expires_at: datetime


def resolve_status(
    *,
    current: OpportunityStatus,
    signals: tuple[SignalView, ...],
    now: datetime,
    policy: ExpiryPolicy,
    confidence_policy: ConfidencePolicy | None = None,
    expiring_since: datetime | None = None,
) -> OpportunityStatus:
    """What an opportunity's status should be, given its signals.

    The single place the lifecycle is decided. The engine applies the answer;
    it never reasons about states itself, so there is one implementation of
    "when is this active" rather than one per call site.
    """
    resolved_confidence = confidence_policy or ConfidencePolicy()

    if current is OpportunityStatus.ARCHIVED:
        return current

    if current is OpportunityStatus.CLOSED:
        # Archival is purely elapsed time. It has no signal input, because a
        # closed opportunity cannot gain one.
        return current

    live = tuple(signal for signal in signals if signal.status in LIVE_SIGNAL_STATUSES)
    unexpired = tuple(signal for signal in live if signal.expires_at > now)

    if not unexpired:
        # Nothing live left. Enter the grace window, and close once it elapses.
        if current is OpportunityStatus.EXPIRING and expiring_since is not None:
            if (now - expiring_since).total_seconds() >= policy.grace_seconds:
                return OpportunityStatus.CLOSED
            return OpportunityStatus.EXPIRING
        return OpportunityStatus.EXPIRING

    confirmed = tuple(
        signal
        for signal in unexpired
        if signal.confirmations >= resolved_confidence.required_confirmations
    )
    if confirmed:
        return OpportunityStatus.ACTIVE
    return OpportunityStatus.PENDING_CONFIRMATION


def should_archive(
    *, closed_at: datetime | None, now: datetime, policy: ExpiryPolicy
) -> bool:
    """Whether a closed opportunity has settled long enough to be archived.

    Archival is what frees a token to open a new generation, so it is a real
    decision rather than housekeeping: too eager and a flapping signal mints
    generations, too slow and a genuinely new opportunity is suppressed.
    """
    if closed_at is None:
        return False
    return (now - closed_at).total_seconds() >= policy.archive_after_seconds
