"""The lifecycle state machine, confidence and priority.

Pure functions, so these need no database. The persisted half is covered in
`tests/integration/test_opportunity_engine.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.opportunities.lifecycle import (
    ConfidenceInputs,
    ConfidencePolicy,
    ExpiryPolicy,
    IllegalTransitionError,
    SignalView,
    assert_transition,
    can_transition,
    confidence_for,
    freshness,
    priority_band,
    priority_for,
    resolve_status,
    should_archive,
)
from app.opportunities.models import (
    OpportunityPriority,
    OpportunityStatus,
    SignalSeverity,
    SignalStatus,
    SignalType,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)

POLICY = ExpiryPolicy(
    ttl_seconds={SignalType.FRESH_GRADUATION: 3600},
    default_ttl_seconds=1800,
    grace_seconds=600,
    archive_after_seconds=86_400,
)


def _signal(
    *,
    status: SignalStatus = SignalStatus.ACTIVE,
    confirmations: int = 2,
    expires_in: int = 3600,
) -> SignalView:
    return SignalView(
        signal_type=SignalType.FRESH_GRADUATION,
        status=status,
        confirmations=confirmations,
        expires_at=NOW + timedelta(seconds=expires_in),
    )


class TestTransitions:
    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (OpportunityStatus.NEW, OpportunityStatus.PENDING_CONFIRMATION),
            (OpportunityStatus.NEW, OpportunityStatus.ACTIVE),
            (OpportunityStatus.PENDING_CONFIRMATION, OpportunityStatus.ACTIVE),
            (OpportunityStatus.ACTIVE, OpportunityStatus.EXPIRING),
            (OpportunityStatus.EXPIRING, OpportunityStatus.CLOSED),
            (OpportunityStatus.CLOSED, OpportunityStatus.ARCHIVED),
        ],
    )
    def test_the_approved_path_is_legal(
        self, current: OpportunityStatus, target: OpportunityStatus
    ) -> None:
        assert can_transition(current, target)

    def test_a_lapsed_signal_can_revive_during_grace(self) -> None:
        """EXPIRING → ACTIVE, deliberately.

        Without it a signal that flickers would close its opportunity and open a
        new generation every few minutes, and the permanent record would be
        unreadable.
        """
        assert can_transition(OpportunityStatus.EXPIRING, OpportunityStatus.ACTIVE)

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (OpportunityStatus.ARCHIVED, OpportunityStatus.ACTIVE),
            (OpportunityStatus.CLOSED, OpportunityStatus.ACTIVE),
            (OpportunityStatus.ACTIVE, OpportunityStatus.NEW),
            (OpportunityStatus.ACTIVE, OpportunityStatus.ARCHIVED),
            (OpportunityStatus.NEW, OpportunityStatus.CLOSED),
        ],
    )
    def test_illegal_moves_raise(
        self, current: OpportunityStatus, target: OpportunityStatus
    ) -> None:
        """An illegal transition is an engine bug, not a reachable state.

        Raising beats silently coercing: a resurrection would let a closed
        opportunity re-enter the board without a new generation, and the record
        of the first call would be quietly rewritten.
        """
        assert not can_transition(current, target)
        with pytest.raises(IllegalTransitionError):
            assert_transition(current, target)

    def test_archived_is_terminal(self) -> None:
        for target in OpportunityStatus:
            assert not can_transition(OpportunityStatus.ARCHIVED, target)


class TestResolveStatus:
    def test_an_unconfirmed_signal_stays_pending(self) -> None:
        """One snapshot is noise. A first sighting reaches no board."""
        status = resolve_status(
            current=OpportunityStatus.NEW,
            signals=(_signal(status=SignalStatus.PENDING, confirmations=1),),
            now=NOW,
            policy=POLICY,
        )
        assert status is OpportunityStatus.PENDING_CONFIRMATION

    def test_a_confirmed_signal_activates(self) -> None:
        status = resolve_status(
            current=OpportunityStatus.PENDING_CONFIRMATION,
            signals=(_signal(confirmations=2),),
            now=NOW,
            policy=POLICY,
        )
        assert status is OpportunityStatus.ACTIVE

    def test_no_live_signal_enters_expiring(self) -> None:
        status = resolve_status(
            current=OpportunityStatus.ACTIVE,
            signals=(_signal(expires_in=-1),),
            now=NOW,
            policy=POLICY,
        )
        assert status is OpportunityStatus.EXPIRING

    def test_no_signals_at_all_enters_expiring(self) -> None:
        status = resolve_status(
            current=OpportunityStatus.ACTIVE, signals=(), now=NOW, policy=POLICY
        )
        assert status is OpportunityStatus.EXPIRING

    def test_grace_holds_before_closing(self) -> None:
        status = resolve_status(
            current=OpportunityStatus.EXPIRING,
            signals=(_signal(expires_in=-1),),
            now=NOW,
            policy=POLICY,
            expiring_since=NOW - timedelta(seconds=POLICY.grace_seconds - 1),
        )
        assert status is OpportunityStatus.EXPIRING

    def test_grace_elapsed_closes(self) -> None:
        status = resolve_status(
            current=OpportunityStatus.EXPIRING,
            signals=(_signal(expires_in=-1),),
            now=NOW,
            policy=POLICY,
            expiring_since=NOW - timedelta(seconds=POLICY.grace_seconds),
        )
        assert status is OpportunityStatus.CLOSED

    def test_a_revived_signal_reactivates_within_grace(self) -> None:
        """The reason the grace window exists."""
        status = resolve_status(
            current=OpportunityStatus.EXPIRING,
            signals=(_signal(expires_in=3600, confirmations=3),),
            now=NOW,
            policy=POLICY,
            expiring_since=NOW - timedelta(seconds=60),
        )
        assert status is OpportunityStatus.ACTIVE

    def test_closed_and_archived_are_not_recomputed(self) -> None:
        """Signals cannot revive a closed opportunity — only a new generation can."""
        for terminal in (OpportunityStatus.CLOSED, OpportunityStatus.ARCHIVED):
            assert (
                resolve_status(
                    current=terminal,
                    signals=(_signal(),),
                    now=NOW,
                    policy=POLICY,
                )
                is terminal
            )

    def test_active_with_only_unconfirmed_evidence_expires_rather_than_demotes(
        self,
    ) -> None:
        """The ladder has no way back down. When an ACTIVE opportunity's
        confirmed signal expires while an unconfirmed one lives on, the answer
        must be a legal state — this exact case returned PENDING_CONFIRMATION
        and aborted the whole detection cycle for every mint in the batch."""
        status = resolve_status(
            current=OpportunityStatus.ACTIVE,
            signals=(
                _signal(confirmations=3, expires_in=-1),
                _signal(status=SignalStatus.PENDING, confirmations=1, expires_in=3600),
            ),
            now=NOW,
            policy=POLICY,
        )
        assert status is OpportunityStatus.EXPIRING
        assert can_transition(OpportunityStatus.ACTIVE, status)

    def test_expiring_with_only_unconfirmed_evidence_still_closes_after_grace(
        self,
    ) -> None:
        """An unconfirmed straggler must not hold the grace window open
        forever."""
        status = resolve_status(
            current=OpportunityStatus.EXPIRING,
            signals=(_signal(status=SignalStatus.PENDING, confirmations=1),),
            now=NOW,
            policy=POLICY,
            expiring_since=NOW - timedelta(seconds=POLICY.grace_seconds),
        )
        assert status is OpportunityStatus.CLOSED

    def test_a_new_opportunity_with_no_evidence_stands_still(self) -> None:
        """NEW may only become PENDING_CONFIRMATION or ACTIVE. With no live
        signal it has nowhere legal to go, so it must stay put rather than
        propose EXPIRING and abort the batch."""
        for signals in ((), (_signal(expires_in=-1),)):
            assert (
                resolve_status(
                    current=OpportunityStatus.NEW,
                    signals=signals,
                    now=NOW,
                    policy=POLICY,
                )
                is OpportunityStatus.NEW
            )

    def test_every_resolved_status_is_reachable_from_its_current(self) -> None:
        """resolve_status must never propose a move assert_transition rejects,
        whatever the status and signal mix — the engine applies its answer
        unconditionally, and an illegal answer raises inside the detection
        cycle, losing every other mint in the batch with it.

        Exhaustive over both axes on purpose: the two illegal transitions this
        pins (ACTIVE -> PENDING_CONFIRMATION, NEW -> EXPIRING) were each found
        in production rather than by a targeted test."""
        signal_variants = (
            (),
            (_signal(confirmations=3),),
            (_signal(status=SignalStatus.PENDING, confirmations=1),),
            (_signal(expires_in=-1),),
            (_signal(status=SignalStatus.EXPIRED, expires_in=3600),),
            (
                _signal(confirmations=3, expires_in=-1),
                _signal(status=SignalStatus.PENDING, confirmations=1),
            ),
        )
        for current in OpportunityStatus:
            for signals in signal_variants:
                for expiring_since in (None, NOW - timedelta(seconds=1), NOW):
                    resolved = resolve_status(
                        current=current,
                        signals=signals,
                        now=NOW,
                        policy=POLICY,
                        expiring_since=expiring_since,
                    )
                    assert resolved is current or can_transition(current, resolved), (
                        f"{current} -> {resolved} for {signals!r}"
                    )

    def test_an_expired_signal_status_does_not_count_as_live(self) -> None:
        status = resolve_status(
            current=OpportunityStatus.ACTIVE,
            signals=(_signal(status=SignalStatus.EXPIRED, expires_in=3600),),
            now=NOW,
            policy=POLICY,
        )
        assert status is OpportunityStatus.EXPIRING


class TestArchival:
    def test_archives_after_the_settling_window(self) -> None:
        assert should_archive(
            closed_at=NOW - timedelta(seconds=POLICY.archive_after_seconds),
            now=NOW,
            policy=POLICY,
        )

    def test_does_not_archive_early(self) -> None:
        assert not should_archive(
            closed_at=NOW - timedelta(seconds=POLICY.archive_after_seconds - 1),
            now=NOW,
            policy=POLICY,
        )

    def test_an_opportunity_that_never_closed_is_never_archived(self) -> None:
        assert not should_archive(closed_at=None, now=NOW, policy=POLICY)


class TestExpiryPolicy:
    def test_a_type_with_its_own_ttl_uses_it(self) -> None:
        assert POLICY.ttl_for(SignalType.FRESH_GRADUATION) == timedelta(seconds=3600)

    def test_an_unconfigured_type_falls_back(self) -> None:
        """A provider added in a future sprint must not produce an immortal
        signal by forgetting to configure a TTL."""
        assert POLICY.ttl_for(SignalType.BREAKOUT) == timedelta(seconds=1800)

    def test_expiry_is_measured_from_detection(self) -> None:
        assert POLICY.expires_at(
            SignalType.FRESH_GRADUATION, detected_at=NOW
        ) == NOW + timedelta(seconds=3600)


class TestFreshness:
    def test_full_at_the_moment_of_observation(self) -> None:
        assert freshness(0, 3600, floor=Decimal("0.4")) == Decimal(1)

    def test_at_the_floor_once_the_ttl_elapses(self) -> None:
        assert freshness(3600, 3600, floor=Decimal("0.4")) == Decimal("0.4")

    def test_decays_linearly_in_between(self) -> None:
        """Predictable on purpose: half the life, half the decayable part."""
        assert freshness(1800, 3600, floor=Decimal("0.4")) == pytest.approx(Decimal("0.7"))

    def test_never_below_the_floor(self) -> None:
        assert freshness(999_999, 3600, floor=Decimal("0.4")) == Decimal("0.4")


class TestConfidence:
    def _inputs(self, **overrides: object) -> ConfidenceInputs:
        values: dict[str, object] = {
            "strength": Decimal(100),
            "confirmations": 1,
            "corroborating_providers": 1,
            "observations": 1,
            "age_seconds": 0.0,
            "ttl_seconds": 3600,
        }
        values.update(overrides)
        return ConfidenceInputs(**values)  # type: ignore[arg-type]

    def test_confirmation_raises_it(self) -> None:
        first = confidence_for(self._inputs(confirmations=1))
        second = confidence_for(self._inputs(confirmations=3))
        assert second > first

    def test_corroboration_raises_it(self) -> None:
        """Two providers agreeing is worth more than one shouting."""
        alone = confidence_for(self._inputs(corroborating_providers=1))
        supported = confidence_for(self._inputs(corroborating_providers=3))
        assert supported > alone

    def test_more_evidence_raises_it(self) -> None:
        thin = confidence_for(self._inputs(observations=1))
        thick = confidence_for(self._inputs(observations=12))
        assert thick > thin

    def test_age_lowers_it(self) -> None:
        fresh = confidence_for(self._inputs(age_seconds=0))
        stale = confidence_for(self._inputs(age_seconds=3600))
        assert stale < fresh

    def test_repetition_alone_cannot_reach_certainty(self) -> None:
        """The persistence term is bounded on purpose.

        A signal observed a thousand times over one thin window is still built
        on one thin window.
        """
        many = confidence_for(self._inputs(confirmations=1000, observations=1))
        assert many < Decimal(90)

    def test_strength_is_the_ceiling(self) -> None:
        """No amount of confirmation turns a weak transition into a strong one.

        It only makes us surer about how weak it is.
        """
        weak = confidence_for(
            self._inputs(
                strength=Decimal(20),
                confirmations=50,
                corroborating_providers=5,
                observations=50,
            )
        )
        assert weak <= Decimal(20)

    def test_it_is_deterministic(self) -> None:
        assert confidence_for(self._inputs()) == confidence_for(self._inputs())

    def test_it_stays_in_range(self) -> None:
        extreme = confidence_for(
            self._inputs(
                strength=Decimal(100),
                confirmations=999,
                corroborating_providers=999,
                observations=999,
            )
        )
        assert Decimal(0) <= extreme <= Decimal(100)


class TestPriority:
    def test_severity_scales_it(self) -> None:
        major = priority_for(
            severity=SignalSeverity.MAJOR, confidence=Decimal(80), observations=6
        )
        info = priority_for(
            severity=SignalSeverity.INFO, confidence=Decimal(80), observations=6
        )
        assert major > info

    def test_evidence_is_a_gate_not_a_multiplier(self) -> None:
        """Below the floor the answer is zero, not merely smaller.

        A multiplier would let a confident-looking, thinly-evidenced signal
        climb the board. A gate cannot.
        """
        assert priority_for(
            severity=SignalSeverity.CRITICAL,
            confidence=Decimal(100),
            observations=1,
        ) == Decimal(0)

    def test_just_above_the_gate_ranks(self) -> None:
        assert priority_for(
            severity=SignalSeverity.CRITICAL,
            confidence=Decimal(100),
            observations=2,
        ) > Decimal(0)

    @pytest.mark.parametrize(
        ("value", "band"),
        [
            (Decimal(0), OpportunityPriority.LOW),
            (Decimal(30), OpportunityPriority.MEDIUM),
            (Decimal(60), OpportunityPriority.HIGH),
            (Decimal(90), OpportunityPriority.CRITICAL),
        ],
    )
    def test_bands(self, value: Decimal, band: OpportunityPriority) -> None:
        assert priority_band(value) is band


class TestPolicyWiring:
    def test_required_confirmations_is_honoured(self) -> None:
        """The confirmation bar is configuration, not a constant.

        A fresh-tier token is observed every 30 s and an old-tier one every 6 h,
        so what "two observations" costs differs by orders of magnitude.
        """
        strict = ConfidencePolicy(required_confirmations=3)
        assert (
            resolve_status(
                current=OpportunityStatus.PENDING_CONFIRMATION,
                signals=(_signal(confirmations=2),),
                now=NOW,
                policy=POLICY,
                confidence_policy=strict,
            )
            is OpportunityStatus.PENDING_CONFIRMATION
        )
        assert (
            resolve_status(
                current=OpportunityStatus.PENDING_CONFIRMATION,
                signals=(_signal(confirmations=3),),
                now=NOW,
                policy=POLICY,
                confidence_policy=strict,
            )
            is OpportunityStatus.ACTIVE
        )
