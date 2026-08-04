"""The provider framework and the one provider Sprint 4 ships.

Two subjects: the registry's contract (registration, isolation, graceful
failure) and `FreshGraduationProvider`'s single job.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.opportunities.models import (
    MarketObservation,
    ObservationWindow,
    OpportunityStage,
    ProviderMeta,
    ProviderResult,
    SignalType,
)
from app.opportunities.providers import register_default_providers, registry
from app.opportunities.providers.base import SignalProvider
from app.opportunities.providers.fresh_graduation import FreshGraduationProvider
from app.opportunities.providers.registry import (
    DuplicateProviderError,
    ProviderRegistry,
    UnknownProviderError,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
MINT = "HHbRJ9Fw2tPxETGSsaeQhpgdizfVafLvXK7eo5mwpump"


def _window(*venues: str | None, mint: str = MINT) -> ObservationWindow:
    """A window whose observations carry the given venues, oldest first."""
    return ObservationWindow(
        mint_address=mint,
        observations=tuple(
            MarketObservation(
                captured_at=NOW - timedelta(minutes=len(venues) - index),
                price_usd=Decimal("0.001"),
                dex_name=venue,
            )
            for index, venue in enumerate(venues)
        ),
    )


class _Stub(SignalProvider):
    def __init__(self, provider_id: str, *, operational: bool = True) -> None:
        self._id = provider_id
        self._operational = operational
        self.calls = 0

    @property
    def meta(self) -> ProviderMeta:
        return ProviderMeta(
            provider_id=self._id,
            name=self._id,
            question="?",
            emits=(SignalType.BREAKOUT,),
            operational=self._operational,
        )

    def evaluate(self, window: ObservationWindow, *, now: datetime) -> ProviderResult:
        self.calls += 1
        return ProviderResult.nothing(self._id)


class _Exploding(_Stub):
    def evaluate(self, window: ObservationWindow, *, now: datetime) -> ProviderResult:
        self.calls += 1
        raise RuntimeError("provider is broken")


class TestRegistration:
    def test_a_provider_can_be_registered_and_retrieved(self) -> None:
        target = ProviderRegistry()
        provider = target.register(_Stub("alpha"))
        assert target.get("alpha") is provider
        assert "alpha" in target
        assert len(target) == 1

    def test_duplicate_ids_are_rejected(self) -> None:
        """Two providers under one id would make the dedup key
        `(opportunity, signal_type, provider_id)` silently merge them."""
        target = ProviderRegistry()
        target.register(_Stub("alpha"))
        with pytest.raises(DuplicateProviderError):
            target.register(_Stub("alpha"))

    def test_an_unknown_id_raises_rather_than_returning_none(self) -> None:
        """A typo must not quietly fall back to a default nobody chose."""
        with pytest.raises(UnknownProviderError):
            ProviderRegistry().get("nope")

    def test_registration_order_is_preserved(self) -> None:
        """Evaluation order has to be deterministic for replay to be."""
        target = ProviderRegistry()
        for name in ("c", "a", "b"):
            target.register(_Stub(name))
        assert target.ids == ("c", "a", "b")


class TestExecution:
    def test_every_operational_provider_runs(self) -> None:
        target = ProviderRegistry()
        first, second = _Stub("one"), _Stub("two")
        target.register(first)
        target.register(second)

        results = target.evaluate_all(_window("pumpfun"), now=NOW)

        assert len(results) == 2
        assert first.calls == 1
        assert second.calls == 1

    def test_non_operational_providers_are_registered_but_not_run(self) -> None:
        """They stay registered so the gap is discoverable — a missing provider
        is invisible, one that declares why it cannot run is a fact."""
        target = ProviderRegistry()
        target.register(_Stub("live"))
        target.register(_Stub("blocked", operational=False))

        assert len(target.all()) == 2
        assert len(target.operational()) == 1
        assert len(target.evaluate_all(_window("pumpfun"), now=NOW)) == 1


class TestIsolation:
    def test_one_broken_provider_does_not_stop_the_others(self) -> None:
        """The whole point of the registry owning execution.

        Detection for a token must not be all-or-nothing across independent
        sources.
        """
        target = ProviderRegistry()
        target.register(_Exploding("broken"))
        healthy = target.register(_Stub("healthy"))

        results = target.evaluate_all(_window("pumpfun"), now=NOW)

        assert len(results) == 1
        assert results[0].provider_id == "healthy"
        assert healthy.calls == 1

    def test_a_broken_provider_never_propagates(self) -> None:
        target = ProviderRegistry()
        target.register(_Exploding("broken"))
        assert target.evaluate_all(_window("pumpfun"), now=NOW) == ()


class TestFreshGraduation:
    @pytest.fixture
    def provider(self) -> FreshGraduationProvider:
        return FreshGraduationProvider(
            bonding_curve_venues=frozenset({"pumpfun"}),
            graduated_venues=frozenset({"pumpswap"}),
        )

    def test_it_detects_the_transition(self, provider: FreshGraduationProvider) -> None:
        result = provider.evaluate(_window("pumpfun", "pumpswap"), now=NOW)

        assert result.available
        assert len(result.candidates) == 1
        candidate = result.candidates[0]
        assert candidate.signal_type is SignalType.FRESH_GRADUATION
        assert candidate.stage is OpportunityStage.FRESH_GRADUATION
        assert candidate.mint_address == MINT

    def test_it_says_nothing_while_still_on_the_curve(
        self, provider: FreshGraduationProvider
    ) -> None:
        assert provider.evaluate(_window("pumpfun", "pumpfun"), now=NOW).candidates == ()

    def test_it_says_nothing_once_the_transition_is_past(
        self, provider: FreshGraduationProvider
    ) -> None:
        """A token that graduated last week did not graduate *now*.

        The opportunity is new; the token need not be — but the *signal* must
        be, which is the whole premise.
        """
        assert provider.evaluate(_window("pumpswap", "pumpswap"), now=NOW).candidates == ()

    def test_a_first_ever_venue_is_not_a_graduation(
        self, provider: FreshGraduationProvider
    ) -> None:
        """A token discovered after it had already graduated has not just
        graduated. Claiming otherwise would put weeks-old events on a board
        that promises new ones."""
        assert provider.evaluate(_window("pumpswap"), now=NOW).candidates == ()

    def test_a_gap_with_no_venue_is_walked_past(
        self, provider: FreshGraduationProvider
    ) -> None:
        """A snapshot with no indexed pool carries a null venue.

        Treating that as "no previous venue" would miss the graduation entirely.
        """
        result = provider.evaluate(_window("pumpfun", None, None, "pumpswap"), now=NOW)
        assert len(result.candidates) == 1

    def test_a_null_latest_venue_says_nothing(self, provider: FreshGraduationProvider) -> None:
        assert provider.evaluate(_window("pumpfun", None), now=NOW).candidates == ()

    def test_an_empty_window_says_nothing(self, provider: FreshGraduationProvider) -> None:
        """Total on every input, including the degenerate ones."""
        assert (
            provider.evaluate(ObservationWindow(mint_address=MINT), now=NOW).candidates == ()
        )

    def test_an_unrelated_venue_change_is_not_its_subject(
        self, provider: FreshGraduationProvider
    ) -> None:
        """A new pool on an established token is a real change, but not this
        provider's."""
        assert provider.evaluate(_window("meteora", "pumpswap"), now=NOW).candidates == ()

    def test_venue_matching_is_case_insensitive(
        self, provider: FreshGraduationProvider
    ) -> None:
        assert len(provider.evaluate(_window("PumpFun", "PumpSwap"), now=NOW).candidates) == 1

    def test_the_evidence_names_both_venues(self, provider: FreshGraduationProvider) -> None:
        """Enough for a client to render the explanation without inventing it."""
        candidate = provider.evaluate(_window("pumpfun", "pumpswap"), now=NOW).candidates[0]
        labels = {item.label: item.value for item in candidate.evidence}

        assert labels["Previous venue"] == "pumpfun"
        assert labels["Current venue"] == "pumpswap"

    def test_it_carries_reason_codes_not_prose(
        self, provider: FreshGraduationProvider
    ) -> None:
        """Wording changes must never require a migration (AD-07)."""
        candidate = provider.evaluate(_window("pumpfun", "pumpswap"), now=NOW).candidates[0]
        assert "graduated_from_bonding_curve" in candidate.reason_codes

    def test_it_is_pure(self, provider: FreshGraduationProvider) -> None:
        """Same window, same answer — which is what makes replay possible."""
        window = _window("pumpfun", "pumpswap")
        first = provider.evaluate(window, now=NOW)
        second = provider.evaluate(window, now=NOW + timedelta(days=30))
        assert first.candidates == second.candidates

    def test_venues_come_from_configuration(self) -> None:
        """A launchpad renaming its venue must be a config change.

        pump.fun has already renamed an instruction once.
        """
        custom = FreshGraduationProvider(
            bonding_curve_venues=frozenset({"launchpad_v2"}),
            graduated_venues=frozenset({"newswap"}),
        )
        graduated = custom.evaluate(_window("launchpad_v2", "newswap"), now=NOW)
        assert len(graduated.candidates) == 1
        assert custom.evaluate(_window("pumpfun", "pumpswap"), now=NOW).candidates == ()


class TestDefaultRegistry:
    def test_the_shipped_registry_contains_every_provider(self) -> None:
        """Two operational, one declared. Registration order is preserved,
        which is what makes evaluation order deterministic."""
        assert registry.ids == ("fresh_graduation", "near_graduation", "breakout")

    def test_only_the_providers_with_data_actually_run(self) -> None:
        """Near graduation is registered but not operational: `market_cap` on a
        bonding-curve pair does not track curve progress, so a signal built on
        it would be an estimate. It stays visible in the list with the reason
        attached rather than going missing."""
        operational = {provider.meta.provider_id for provider in registry.operational()}
        assert operational == {"fresh_graduation", "breakout"}

        declared = registry.get("near_graduation").meta
        assert declared.operational is False
        assert declared.unavailable_reason

    def test_double_registration_is_a_wiring_error(self) -> None:
        """Catches a double-import at startup rather than at first detection."""
        with pytest.raises(DuplicateProviderError):
            register_default_providers()

    def test_the_shipped_provider_declares_what_it_needs(self) -> None:
        meta = registry.get("fresh_graduation").meta
        assert meta.operational
        assert meta.emits == (SignalType.FRESH_GRADUATION,)
        assert "dex_name" in meta.required_fields
