"""The Five-Minute Lab's spec — the two things that differ from CMP-01.

Both are the variable under test, so both are pinned. A silent revert of
either would leave a tournament that looks like this one and measures the
Compound Lab's question instead.
"""

from __future__ import annotations

from decimal import Decimal

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


class TestTheTwoVariables:
    def test_the_hold_is_five_minutes(self) -> None:
        held_hours = fivemin.STRATEGIES[0].exits.time_exit_hours
        assert round(held_hours * 60) == 5
        assert fivemin.TIME_EXIT_MINUTES == 5

    def test_the_stake_never_scales(self) -> None:
        """Flat by instruction. The wallet ratchet is already a compounding
        effect; a scaling stake would be a second one and the result could not
        be attributed to either."""
        assert fivemin.SIZING_SCALES is False

    def test_everything_else_matches_cmp01(self) -> None:
        """So a difference between the two is the two variables, not a redesign."""
        fm, cmp = fivemin.STRATEGIES[0], compound.STRATEGIES[0]
        assert fm.entry == cmp.entry
        assert fm.size_usd == cmp.size_usd
        assert fm.max_concurrent == cmp.max_concurrent
        assert fm.max_exposure_usd == cmp.max_exposure_usd
        assert fm.checkpoint_minutes == cmp.checkpoint_minutes
        assert fm.exits.take_profit is cmp.exits.take_profit is None
        assert fivemin.STARTING_EQUITY == compound.STARTING_EQUITY
        assert fivemin.CYCLE_TARGET_MULTIPLE == compound.CYCLE_TARGET_MULTIPLE


class TestTheOtherRegistriesKeepTheLadder:
    def test_scaling_is_opt_out_not_opt_in(self) -> None:
        """Absent means True, so no existing registry changed behaviour."""
        assert getattr(compound, "SIZING_SCALES", True) is True
        assert getattr(v7, "SIZING_SCALES", True) is True
