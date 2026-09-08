"""The Hold-Horizon Lab's spec — the pairing, and what was removed.

The experiment is only a comparison while the two arms differ in exactly one
thing. Every assertion here pins one way that could stop being true silently:
a copied entry that drifts, a stake that starts scaling again, a ratchet that
comes back, or an arm whose clock quietly matches the other's.
"""

from __future__ import annotations

from decimal import Decimal

from app.compound import service as compound_service
from app.compound import spec as compound
from app.fivemin import spec as fivemin
from app.lab import spec as v7


class TestItCannotHaltAnotherTournament:
    def test_every_registry_hashes_differently(self) -> None:
        """A shared hash would mean one tournament's spec halting another's."""
        hashes = {fivemin.SPEC_HASH, compound.SPEC_HASH, v7.SPEC_HASH}
        assert len(hashes) == 3

    def test_it_has_its_own_version(self) -> None:
        assert fivemin.SPEC_VERSION not in {compound.SPEC_VERSION, v7.SPEC_VERSION}

    def test_the_rules_change_bumped_the_version(self) -> None:
        """fivemin-1.0.0 was a live tournament with different rules. Reusing
        its version would have attached this book to that record."""
        assert fivemin.SPEC_VERSION == "fivemin-2.0.0"


class TestTheTwoArmsDifferOnlyInTheClock:
    def test_both_horizons_are_present(self) -> None:
        held = sorted(round(s.exits.time_exit_hours * 60)
                      for s in fivemin.STRATEGIES)
        assert held == [5, 15]

    def test_they_share_ONE_entry_object_not_a_copy(self) -> None:
        """Identity, not equality. Two equal copies can drift apart on the next
        edit; one shared object cannot, and the pairing depends on that."""
        first = fivemin.STRATEGIES[0].entry
        assert all(s.entry is first for s in fivemin.STRATEGIES)
        assert first is compound.STRATEGIES[0].entry

    def test_everything_except_the_clock_is_identical(self) -> None:
        a, b = fivemin.STRATEGIES
        assert a.size_usd == b.size_usd
        assert a.max_concurrent == b.max_concurrent
        assert a.max_exposure_usd == b.max_exposure_usd
        assert a.checkpoint_minutes == b.checkpoint_minutes
        assert a.exits.time_exit_hours != b.exits.time_exit_hours

    def test_the_clock_is_the_only_exit(self) -> None:
        """A take-profit or a stop would decide some trades before the horizon
        did, and those trades would measure that rule instead of the hold."""
        for s in fivemin.STRATEGIES:
            assert s.exits.take_profit is None
            assert s.exits.stop_loss is None
            assert s.exits.time_exit_hours


class TestTheOperatorsRuleSet:
    def test_ten_trades_of_ten_dollars_fill_the_book(self) -> None:
        for s in fivemin.STRATEGIES:
            assert s.size_usd == Decimal("10")
            assert s.max_concurrent == 10
            assert s.size_usd * s.max_concurrent == s.max_exposure_usd

    def test_each_arm_starts_with_one_hundred(self) -> None:
        assert fivemin.STARTING_EQUITY == Decimal("100")

    def test_the_stake_never_scales(self) -> None:
        assert fivemin.SIZING_SCALES is False

    def test_there_is_no_wallet_ratchet(self) -> None:
        assert fivemin.CYCLE_ENABLED is False
        assert not hasattr(fivemin, "CYCLE_TARGET_MULTIPLE")


class TestTheOptOutsAreOptOutsNotDefaults:
    """Absent must mean "on", or adding either switch would have silently
    changed every registry that predates it."""

    def test_scaling_is_opt_out(self) -> None:
        assert getattr(compound, "SIZING_SCALES", True) is True
        assert getattr(v7, "SIZING_SCALES", True) is True

    def test_the_ratchet_is_opt_out(self) -> None:
        assert getattr(compound, "CYCLE_ENABLED", True) is True
        assert getattr(v7, "CYCLE_ENABLED", True) is True

    def test_the_service_reads_the_switch(self) -> None:
        """Behaviour, not source text: build the service over each registry and
        read what it actually decided about banking."""
        assert compound_service.CompoundService(None, registry=fivemin)._cycles is False
        assert compound_service.CompoundService(None, registry=compound)._cycles is True
