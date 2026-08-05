"""The Opportunity Engine.

Receives candidate signals, merges them into opportunities, drives the
lifecycle, and appends an immutable event for every transition.

It knows nothing about Pump.fun, graduation, or any other subject matter. It
receives `SignalCandidate`s from a registry it does not populate and treats them
identically — which is the property that lets a future sprint add whale or
community intelligence without editing this file
(ARCHITECTURE_DECISIONS.md AD-04).

## Transaction shape

The engine mutates through its repository and never commits. The caller owns the
boundary, matching `get_db` and the enrichment worker's TX-2/TX-3 split. Events
are appended in the same transaction as the state they describe, so a rolled
back cycle leaves no event claiming something that did not happen.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.events.detector import DetectedEvent
from app.events.repository import EventRepository
from app.models.intelligence import EventKind, EventSeverity
from app.models.opportunity import Opportunity, OpportunitySignal
from app.opportunities.lifecycle import (
    ConfidenceInputs,
    ConfidencePolicy,
    ExpiryPolicy,
    SignalView,
    assert_transition,
    confidence_for,
    priority_band,
    priority_for,
    resolve_status,
    should_archive,
)
from app.opportunities.models import (
    LIVE_SIGNAL_STATUSES,
    ObservationWindow,
    OpportunityStage,
    OpportunityStatus,
    SignalCandidate,
    SignalSeverity,
    SignalStatus,
    SignalType,
)
from app.opportunities.outcomes import Outcome, OutcomeRules, assess
from app.opportunities.providers.registry import ProviderRegistry
from app.opportunities.providers.registry import registry as default_registry
from app.opportunities.repository import OpportunityRepository

logger = get_logger(__name__)

#: Signal statuses that still count as live, as stored values.
_LIVE_SIGNAL_VALUES = frozenset(status.value for status in LIVE_SIGNAL_STATUSES)


@dataclass
class EngineOutcome:
    """What one pass did. Every field is a count, so it logs cleanly."""

    evaluated: int = 0
    candidates: int = 0
    opportunities_opened: int = 0
    signals_added: int = 0
    signals_confirmed: int = 0
    signals_expired: int = 0
    signals_realised: int = 0
    signals_invalidated: int = 0
    activated: int = 0
    closed: int = 0
    archived: int = 0
    events_recorded: int = 0
    providers_unavailable: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "evaluated": self.evaluated,
            "candidates": self.candidates,
            "opportunities_opened": self.opportunities_opened,
            "signals_added": self.signals_added,
            "signals_confirmed": self.signals_confirmed,
            "signals_expired": self.signals_expired,
            "signals_realised": self.signals_realised,
            "signals_invalidated": self.signals_invalidated,
            "activated": self.activated,
            "closed": self.closed,
            "archived": self.archived,
            "events_recorded": self.events_recorded,
            "providers_unavailable": self.providers_unavailable,
        }


@dataclass
class _Pending:
    """Events collected during a pass, appended once at the end.

    Batched rather than written per transition: `EventRepository.record` takes a
    sequence and deduplicates in one statement, and a pass that touches sixty
    tokens should not issue sixty inserts.
    """

    events: list[DetectedEvent] = field(default_factory=list)

    def add(
        self,
        *,
        mint: str,
        kind: EventKind,
        severity: EventSeverity,
        summary: str,
        previous: str | None = None,
        current: str | None = None,
        provider: str | None = None,
    ) -> None:
        self.events.append(
            DetectedEvent(
                mint_address=mint,
                kind=kind,
                severity=severity,
                summary=summary,
                previous_value=previous,
                current_value=current,
                # `analyst` is String(16); a provider id longer than that would
                # be silently rejected by Postgres, so it is truncated here
                # where the reason is visible.
                analyst=provider[:16] if provider else None,
            )
        )


def expiry_policy_from_settings() -> ExpiryPolicy:
    """The configured TTLs. One place, so tests can substitute a whole policy."""
    return ExpiryPolicy(
        ttl_seconds={
            SignalType.FRESH_GRADUATION: settings.OPPORTUNITY_TTL_FRESH_GRADUATION_SECONDS,
            SignalType.BREAKOUT: settings.OPPORTUNITY_TTL_BREAKOUT_SECONDS,
            SignalType.PRE_BREAKOUT: settings.OPPORTUNITY_TTL_PRE_BREAKOUT_SECONDS,
        },
        default_ttl_seconds=settings.OPPORTUNITY_TTL_DEFAULT_SECONDS,
        grace_seconds=settings.OPPORTUNITY_GRACE_SECONDS,
        archive_after_seconds=settings.OPPORTUNITY_ARCHIVE_AFTER_SECONDS,
    )


def outcome_rules_from_settings() -> OutcomeRules:
    """The thresholds an outcome is judged against.

    The same boundaries the providers published when they opened the signal. A
    claim opened against one number and judged against another would make the
    record unreadable — and un-replayable, which is worse.
    """
    return OutcomeRules(
        price_margin=Decimal(str(settings.OPPORTUNITY_BREAKOUT_PRICE_MARGIN)),
        proximity=Decimal(str(settings.OPPORTUNITY_BREAKOUT_PROXIMITY)),
        bonding_curve_venues=frozenset(
            venue.lower() for venue in settings.OPPORTUNITY_BONDING_CURVE_VENUES
        ),
        graduated_venues=frozenset(
            venue.lower() for venue in settings.OPPORTUNITY_GRADUATED_VENUES
        ),
        min_curve_progress=Decimal(str(settings.OPPORTUNITY_NEAR_GRADUATION_MIN_PROGRESS)),
    )


def confidence_policy_from_settings() -> ConfidencePolicy:
    return ConfidencePolicy(required_confirmations=settings.OPPORTUNITY_REQUIRED_CONFIRMATIONS)


class OpportunityEngine:
    """Merges candidates into opportunities and drives their lifecycle."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        registry: ProviderRegistry | None = None,
        expiry: ExpiryPolicy | None = None,
        confidence: ConfidencePolicy | None = None,
        outcome_rules: OutcomeRules | None = None,
    ) -> None:
        self._session = session
        self._repository = OpportunityRepository(session)
        self._events = EventRepository(session)
        self._registry = registry or default_registry
        self._expiry = expiry or expiry_policy_from_settings()
        self._confidence = confidence or confidence_policy_from_settings()
        self._outcomes = outcome_rules or outcome_rules_from_settings()

    # --- Entry points --------------------------------------------------------

    async def detect(
        self, mints: Sequence[str], *, now: datetime | None = None
    ) -> EngineOutcome:
        """Run every provider over these tokens and merge what they emit.

        Called after enrichment commits a batch, so the engine evaluates exactly
        the tokens whose data just changed. There is no scan.
        """
        moment = now or datetime.now(UTC)
        outcome = EngineOutcome()
        unique = list(dict.fromkeys(mints))
        if not unique:
            return outcome

        windows = await self._repository.windows_for(
            unique,
            limit_per_mint=settings.OPPORTUNITY_WINDOW_SIZE,
            # Curve position is read only while it is being collected. With
            # collection off the newest snapshot is however old the flag is, and
            # attaching it to today's observations would report a stalled curve
            # rather than an absent one — see `windows_for`.
            curve_limit_per_mint=(
                settings.CURVE_WINDOW_SIZE if settings.FEATURE_CURVE_COLLECTION_ENABLED else 0
            ),
        )
        pending = _Pending()

        for mint in unique:
            window = windows.get(mint)
            if window is None or not len(window):
                continue
            outcome.evaluated += 1
            emitted = self._collect(window, now=moment, outcome=outcome)
            if emitted:
                await self._merge(
                    mint, window, emitted, now=moment, outcome=outcome, pending=pending
                )

        # Tokens that were evaluated may also have signals that just lapsed, or
        # that the same windows have now resolved one way or the other.
        await self._review(
            unique, windows=windows, now=moment, outcome=outcome, pending=pending
        )
        outcome.events_recorded = await self._events.record(pending.events, occurred_at=moment)

        logger.info("opportunity_detection_completed", **outcome.as_dict())
        return outcome

    async def review_expired(self, *, now: datetime | None = None) -> EngineOutcome:
        """Advance lifecycle for opportunities whose signals may have lapsed.

        Deliberately not a scan of the token universe: it walks only
        opportunities that already exist, oldest-confirmed first and bounded, so
        its cost tracks the board rather than the table.
        """
        moment = now or datetime.now(UTC)
        outcome = EngineOutcome()
        pending = _Pending()

        due = await self._repository.due_for_review(
            now=moment, limit=settings.OPPORTUNITY_EXPIRY_BATCH_LIMIT
        )
        if due:
            await self._advance(due, now=moment, outcome=outcome, pending=pending)
            outcome.events_recorded = await self._events.record(
                pending.events, occurred_at=moment
            )

        logger.info("opportunity_review_completed", **outcome.as_dict())
        return outcome

    # --- Detection -----------------------------------------------------------

    def _collect(
        self, window: ObservationWindow, *, now: datetime, outcome: EngineOutcome
    ) -> list[tuple[str, SignalCandidate]]:
        """Every provider's candidates for one window, paired with its id.

        The pairing matters: `provider_id` is half of a signal's dedup key, and
        deriving it from the signal type instead would break the moment two
        providers emit the same type — which is exactly what corroboration
        means.

        Provider isolation lives in the registry: one that raises is logged and
        skipped, and the others still contribute.
        """
        collected: list[tuple[str, SignalCandidate]] = []
        for result in self._registry.evaluate_all(window, now=now):
            if not result.available:
                outcome.providers_unavailable += 1
                continue
            collected.extend(
                (result.provider_id, candidate) for candidate in result.candidates
            )
        outcome.candidates += len(collected)
        return collected

    async def _merge(
        self,
        mint: str,
        window: ObservationWindow,
        emitted: Sequence[tuple[str, SignalCandidate]],
        *,
        now: datetime,
        outcome: EngineOutcome,
        pending: _Pending,
    ) -> None:
        """Attach candidates to this token's live opportunity, opening one if
        it has none.

        This is the deduplication seam. Several candidates on one token become
        several signals on **one** opportunity — never several opportunities.
        """
        candidates = [candidate for _, candidate in emitted]
        live = (await self._repository.live_for([mint])).get(mint)
        opened = False

        if live is None:
            token_ids = await self._repository.token_ids_for([mint])
            token_id = token_ids.get(mint)
            if token_id is None:
                # A signal for a token that is not in `discovered_tokens`. The
                # foreign key would reject it; skipping is the honest outcome
                # and matches how enrichment handles an unknown mint.
                logger.warning("opportunity_unknown_token", mint=mint)
                return
            stage = _stage_of(candidates)
            live, opened = await self._repository.open_or_get(
                token_id=token_id,
                mint_address=mint,
                generation=await self._repository.next_generation(mint),
                detected_at=now,
                stage=stage.value,
            )
            if opened:
                outcome.opportunities_opened += 1
                pending.add(
                    mint=mint,
                    kind=EventKind.OPPORTUNITY_OPENED,
                    severity=EventSeverity.NOTABLE,
                    summary=(
                        f"An opportunity opened on {mint[:8]} (generation {live.generation})."
                    ),
                    current=stage.value,
                )

        observations = len(window)
        for provider_id, candidate in emitted:
            signal, created = await self._repository.upsert_signal(
                opportunity_id=live.id,
                mint_address=mint,
                signal_type=candidate.signal_type.value,
                provider_id=provider_id,
                severity=candidate.severity.value,
                strength=candidate.strength,
                observations=observations,
                detected_at=now,
                expires_at=self._expiry.expires_at(candidate.signal_type, detected_at=now),
                observed_at=candidate.observed_at,
                reason_codes=candidate.reason_codes,
                evidence=[
                    {
                        "label": item.label,
                        "value": item.value,
                        "detail": item.detail,
                    }
                    for item in candidate.evidence
                ],
            )
            if created:
                outcome.signals_added += 1
                pending.add(
                    mint=mint,
                    kind=EventKind.SIGNAL_ADDED,
                    severity=EventSeverity.NOTABLE,
                    summary=f"{_label(candidate.signal_type)} detected on {mint[:8]}.",
                    current=candidate.signal_type.value,
                    provider=provider_id,
                )
            else:
                outcome.signals_confirmed += 1
                pending.add(
                    mint=mint,
                    kind=EventKind.SIGNAL_CONFIRMED,
                    severity=EventSeverity.INFO,
                    summary=(
                        f"{_label(candidate.signal_type)} confirmed on {mint[:8]} "
                        f"({signal.confirmations} observations)."
                    ),
                    current=str(signal.confirmations),
                    provider=provider_id,
                )

            self._score_signal(signal, now=now)

        # Only overwrite the stage when a provider actually had an opinion.
        # UNKNOWN is "no opinion", not a verdict, and letting it win would erase
        # a stage an earlier provider established.
        stage_opinion = _stage_of(candidates)
        if stage_opinion is not OpportunityStage.UNKNOWN:
            live.stage = stage_opinion.value

        await self._advance([live], now=now, outcome=outcome, pending=pending, confirmed=True)

    # --- Lifecycle -----------------------------------------------------------

    async def _review(
        self,
        mints: Sequence[str],
        *,
        windows: dict[str, ObservationWindow],
        now: datetime,
        outcome: EngineOutcome,
        pending: _Pending,
    ) -> None:
        """Advance any live opportunity on these mints that gained no candidate.

        Without this a signal that stopped firing would keep its opportunity
        ACTIVE until an unrelated sweep noticed. Absence of fresh detection is
        itself the exit condition (AD-10).
        """
        live = await self._repository.live_for(mints)
        if not live:
            return

        # Outcomes are settled first, against the windows already in hand. A
        # signal that realised or reversed is no longer live, so `_advance`
        # then reads the truthful set — the ordering is what stops an
        # opportunity being held ACTIVE by a signal that has already resolved.
        await self._settle_outcomes(
            list(live.values()), windows=windows, outcome=outcome, pending=pending
        )
        await self._advance(list(live.values()), now=now, outcome=outcome, pending=pending)

    async def _settle_outcomes(
        self,
        opportunities: Sequence[Opportunity],
        *,
        windows: dict[str, ObservationWindow],
        outcome: EngineOutcome,
        pending: _Pending,
    ) -> None:
        """Apply AD-10's realisation and invalidation exits to live signals.

        No query and no clock: the rules read the window detection already
        loaded, which is what makes an outcome replayable over history exactly
        as it was decided live. A signal with no rule, or an open question,
        simply stays live and exits on its TTL like before.
        """
        signals = await self._repository.signals_for([item.id for item in opportunities])
        for opportunity in opportunities:
            window = windows.get(opportunity.mint_address)
            if window is None or not len(window):
                continue
            for signal in signals.get(opportunity.id, []):
                if signal.status not in _LIVE_SIGNAL_VALUES:
                    continue
                verdict = assess(
                    SignalType(signal.signal_type),
                    window,
                    observed_at=signal.observed_at,
                    rules=self._outcomes,
                )
                if verdict is not None:
                    self._apply_outcome(signal, verdict, outcome=outcome, pending=pending)

    def _apply_outcome(
        self,
        signal: OpportunitySignal,
        verdict: Outcome,
        *,
        outcome: EngineOutcome,
        pending: _Pending,
    ) -> None:
        """Record one terminal verdict, on the signal and in the event log.

        The status column carries the outcome; nothing else stores it. The event
        is what makes it a moment in the timeline rather than a value that
        silently changed.
        """
        signal.status = verdict.status.value
        signal.reason_codes = [*signal.reason_codes, verdict.reason_code]
        label = _label(SignalType(signal.signal_type))

        if verdict.realised:
            outcome.signals_realised += 1
            kind, severity = EventKind.SIGNAL_REALISED, EventSeverity.NOTABLE
            summary = f"{label} realised on {signal.mint_address[:8]}."
        else:
            outcome.signals_invalidated += 1
            kind, severity = EventKind.SIGNAL_INVALIDATED, EventSeverity.INFO
            summary = f"{label} no longer holds on {signal.mint_address[:8]}."

        pending.add(
            mint=signal.mint_address,
            kind=kind,
            severity=severity,
            summary=summary,
            previous=SignalStatus.ACTIVE.value,
            current=verdict.status.value,
            provider=signal.provider_id,
        )

    async def _advance(
        self,
        opportunities: Sequence[Opportunity],
        *,
        now: datetime,
        outcome: EngineOutcome,
        pending: _Pending,
        confirmed: bool = False,
    ) -> None:
        """Resolve and apply the lifecycle state for each opportunity."""
        ids = [item.id for item in opportunities]
        expired = await self._repository.expire_signals(now=now, opportunity_ids=ids)
        outcome.signals_expired += expired
        signals = await self._repository.signals_for(ids)

        for opportunity in opportunities:
            attached = signals.get(opportunity.id, [])
            current = OpportunityStatus(opportunity.status)

            if current is OpportunityStatus.CLOSED:
                if should_archive(
                    closed_at=opportunity.closed_at, now=now, policy=self._expiry
                ):
                    await self._transition(
                        opportunity,
                        target=OpportunityStatus.ARCHIVED,
                        now=now,
                        outcome=outcome,
                        pending=pending,
                    )
                continue

            for signal in attached:
                self._score_signal(signal, now=now)

            target = resolve_status(
                current=current,
                signals=tuple(_view(signal) for signal in attached),
                now=now,
                policy=self._expiry,
                confidence_policy=self._confidence,
                expiring_since=opportunity.expiring_since,
            )

            live_signals = [
                signal
                for signal in attached
                if signal.status in {status.value for status in LIVE_SIGNAL_STATUSES}
            ]
            best_confidence = max(
                (signal.confidence for signal in live_signals), default=Decimal(0)
            )
            best_priority, band = _rank(live_signals, policy=self._confidence)

            await self._repository.apply_state(
                opportunity,
                status=target,
                now=now,
                priority=best_priority,
                priority_band=band,
                confidence=best_confidence,
                confirmed=confirmed,
            )

            if target is not current:
                self._record_transition(
                    opportunity,
                    previous=current,
                    target=target,
                    outcome=outcome,
                    pending=pending,
                )

    async def _transition(
        self,
        opportunity: Opportunity,
        *,
        target: OpportunityStatus,
        now: datetime,
        outcome: EngineOutcome,
        pending: _Pending,
    ) -> None:
        previous = OpportunityStatus(opportunity.status)
        assert_transition(previous, target)
        await self._repository.apply_state(opportunity, status=target, now=now)
        self._record_transition(
            opportunity, previous=previous, target=target, outcome=outcome, pending=pending
        )

    def _record_transition(
        self,
        opportunity: Opportunity,
        *,
        previous: OpportunityStatus,
        target: OpportunityStatus,
        outcome: EngineOutcome,
        pending: _Pending,
    ) -> None:
        """Append the event for a status change, and count it.

        Every transition emits. A lifecycle the log cannot reconstruct is a
        lifecycle nobody can audit, and the log is the source of truth the board
        projects from (AD-11).
        """
        assert_transition(previous, target)

        kind, severity, sentence = _TRANSITION_EVENTS.get(
            target,
            (EventKind.OPPORTUNITY_CONFIRMED, EventSeverity.INFO, "changed state"),
        )
        if target is OpportunityStatus.ACTIVE:
            outcome.activated += 1
        elif target is OpportunityStatus.CLOSED:
            outcome.closed += 1
        elif target is OpportunityStatus.ARCHIVED:
            outcome.archived += 1

        pending.add(
            mint=opportunity.mint_address,
            kind=kind,
            severity=severity,
            summary=f"Opportunity on {opportunity.mint_address[:8]} {sentence}.",
            previous=previous.value,
            current=target.value,
        )

    # --- Scoring -------------------------------------------------------------

    def _score_signal(self, signal: OpportunitySignal, *, now: datetime) -> None:
        """Recompute a signal's confidence and promote it once confirmed.

        Confidence is derived here and never supplied by a provider: a provider
        reports how strong a transition was, the engine decides how much to
        trust it.
        """
        signal_type = SignalType(signal.signal_type)
        ttl = int(self._expiry.ttl_for(signal_type).total_seconds())
        age = (now - (signal.observed_at or signal.detected_at)).total_seconds()

        signal.confidence = confidence_for(
            ConfidenceInputs(
                strength=signal.strength,
                confirmations=signal.confirmations,
                # One provider per signal type today. Corroboration becomes real
                # when a second provider emits the same type; the term is here
                # so that does not require a schema or formula change.
                corroborating_providers=1,
                observations=signal.observations,
                age_seconds=max(0.0, age),
                ttl_seconds=ttl,
            ),
            policy=self._confidence,
        )

        if signal.status == SignalStatus.PENDING.value and (
            signal.confirmations >= self._confidence.required_confirmations
        ):
            signal.status = SignalStatus.ACTIVE.value


# --- Helpers -----------------------------------------------------------------

_TRANSITION_EVENTS: dict[OpportunityStatus, tuple[EventKind, EventSeverity, str]] = {
    OpportunityStatus.PENDING_CONFIRMATION: (
        EventKind.OPPORTUNITY_OPENED,
        EventSeverity.INFO,
        "is awaiting confirmation",
    ),
    OpportunityStatus.ACTIVE: (
        EventKind.OPPORTUNITY_CONFIRMED,
        EventSeverity.NOTABLE,
        "is confirmed and active",
    ),
    OpportunityStatus.EXPIRING: (
        EventKind.OPPORTUNITY_EXPIRING,
        EventSeverity.INFO,
        "has no live signals and is expiring",
    ),
    OpportunityStatus.CLOSED: (
        EventKind.OPPORTUNITY_CLOSED,
        EventSeverity.INFO,
        "closed",
    ),
    OpportunityStatus.ARCHIVED: (
        EventKind.OPPORTUNITY_ARCHIVED,
        EventSeverity.INFO,
        "was archived",
    ),
}

_SIGNAL_LABELS: dict[SignalType, str] = {
    SignalType.FRESH_GRADUATION: "Fresh graduation",
}


def _label(signal_type: SignalType) -> str:
    """A display name for a signal type.

    Falls back to the enum value rather than raising: a provider added without a
    label should produce a plain-looking event, not a failed cycle.
    """
    return _SIGNAL_LABELS.get(signal_type, signal_type.value.replace("_", " ").capitalize())


def _stage_of(candidates: Sequence[SignalCandidate]) -> OpportunityStage:
    """The stage the candidates imply, or UNKNOWN when none has an opinion.

    Stage is exclusive, so the last opinion wins deterministically by taking the
    candidates in order. With one provider this is trivially its own answer.
    """
    stage = OpportunityStage.UNKNOWN
    for candidate in candidates:
        if candidate.stage is not None:
            stage = candidate.stage
    return stage


def _view(signal: OpportunitySignal) -> SignalView:
    return SignalView(
        signal_type=SignalType(signal.signal_type),
        status=SignalStatus(signal.status),
        confirmations=signal.confirmations,
        expires_at=signal.expires_at,
    )


def _rank(
    signals: Sequence[OpportunitySignal], *, policy: ConfidencePolicy
) -> tuple[Decimal, str]:
    """An opportunity's priority: its strongest live signal.

    Max rather than a sum. Three weak signals are not one strong opportunity,
    and summing would let a token accumulate its way onto the board.
    """
    best = Decimal(0)
    for signal in signals:
        best = max(
            best,
            priority_for(
                severity=SignalSeverity(signal.severity),
                confidence=signal.confidence,
                observations=signal.observations,
                policy=policy,
            ),
        )
    return best, priority_band(best).value
