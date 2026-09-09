"""The Graduation Hold Lab's spec — the population, the floor, and the pairing.

Every assertion pins one thing that could stop being true silently: the lab
drifting back onto radar's population, the liquidity floor creeping back up to
a level that excludes the cohort, a copied entry that drifts between the arms,
or a ratchet returning.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from app.compound import service as compound_service
from app.compound import spec as compound
from app.fivemin import spec as fivemin
from app.lab import spec as v7
from app.lab.service import LabService
from app.models.lab import LabTournament


class TestItCannotHaltAnotherTournament:
    def test_every_registry_hashes_differently(self) -> None:
        hashes = {fivemin.SPEC_HASH, compound.SPEC_HASH, v7.SPEC_HASH}
        assert len(hashes) == 3

    def test_the_rules_change_bumped_the_version(self) -> None:
        """Each predecessor was a live tournament with different rules —
        5.0.0 ran two graduation arms and no pump.swap arm. Reusing a version
        would attach this book to that record."""
        assert fivemin.SPEC_VERSION == "fivemin-6.0.0"


class TestItTradesTheGraduationCohort:
    def test_candidates_come_from_graduations(self) -> None:
        assert fivemin.CANDIDATE_SOURCE == "graduations"

    def test_radar_is_still_the_default_for_everyone_else(self) -> None:
        """Absent must mean radar, or adding the switch would have silently
        repopulated every registry that predates it."""
        assert getattr(compound, "CANDIDATE_SOURCE", "radar") == "radar"
        assert getattr(v7, "CANDIDATE_SOURCE", "radar") == "radar"
        assert not getattr(compound, "SOURCE_BY_STRATEGY", {})
        assert not getattr(v7, "SOURCE_BY_STRATEGY", {})

    def test_the_service_resolves_a_source_per_arm(self) -> None:
        """Behaviour, not a mapping literal: ask the service what each arm reads."""
        svc = LabService(None, registry=fivemin)
        assert svc._source_for("GRAD-S2") == "graduations"
        assert svc._source_for("PUMP-S2") == "pumpswap"
        assert LabService(None, registry=compound)._source_for("CMP-01") == "radar"

    def test_the_service_actually_queries_graduations(self) -> None:
        """Behaviour, not a flag: compile the statement the service builds and
        read which table it is against."""
        sql_for = {}

        class _Result:
            def all(self):
                return []

        class _Session:
            async def execute(self, q):
                sql_for["last"] = str(q)
                return _Result()

        t = LabTournament(spec_version="x", spec_hash="y",
                          valid_from=datetime(2026, 9, 8, tzinfo=UTC))

        for registry, expected, forbidden in (
            (fivemin, "pumpfun_graduations", "radar_tokens"),
            (compound, "radar_tokens", "pumpfun_graduations"),
        ):
            svc = LabService(_Session(), registry=registry)
            asyncio.run(svc._due_candidates(
                t, minutes=2, ids=[], cutoff=datetime(2026, 9, 9, tzinfo=UTC),
                limit=10,
            ))
            assert expected in sql_for["last"], registry.SPEC_VERSION
            assert forbidden not in sql_for["last"], registry.SPEC_VERSION


class TestTheLiquidityFloorIsExecutionNotSignal:
    def test_the_floor_is_one_hundred_thousand(self) -> None:
        """$300k admitted 11% of graduates; $100k admits 42%. Lower than this
        and 7-8% of SELLS cannot route, which would break the horizon."""
        assert fivemin.LIQUIDITY_FLOOR == Decimal("100000")

    def test_liquidity_is_the_only_entry_condition(self) -> None:
        """The study bought every graduate, and FLOW's two flow features do not
        exist five minutes after a coin completes."""
        for s in fivemin.STRATEGIES:
            assert len(s.entry) == 1
            assert s.entry[0].feature == "liq"


class TestOneVariableAtATime:
    """GRAD-S2 is the reference. Each other arm varies exactly ONE thing
    against it, so a difference has exactly one candidate cause."""

    def test_the_shape_variant_changes_only_the_shape(self) -> None:
        ref = fivemin.BY_ID["GRAD-S2"]
        alt = fivemin.BY_ID["GRAD-S20"]
        assert alt.size_usd != ref.size_usd
        assert alt.entry is ref.entry
        assert alt.exits.time_exit_hours == ref.exits.time_exit_hours
        assert alt.checkpoint_minutes == ref.checkpoint_minutes

    def test_the_population_variant_changes_only_the_population(self) -> None:
        ref = fivemin.BY_ID["GRAD-S2"]
        alt = fivemin.BY_ID["PUMP-S2"]
        assert fivemin.SOURCE_BY_STRATEGY["PUMP-S2"] == "pumpswap"
        assert alt.size_usd == ref.size_usd
        assert alt.max_concurrent == ref.max_concurrent
        assert alt.entry is ref.entry
        assert alt.exits.time_exit_hours == ref.exits.time_exit_hours

    def test_the_pumpswap_arm_needs_no_pricing_delay(self) -> None:
        """It is admitted BY a priced snapshot, so waiting would add drift."""
        assert fivemin.BY_ID["PUMP-S2"].checkpoint_minutes == 0
        assert fivemin.BY_ID["GRAD-S2"].checkpoint_minutes == 2


class TestArmsDifferingOnlyInBookShape:
    def test_both_arms_sell_on_the_same_clock(self) -> None:
        """The axis is SIZE now. A difference in hold would confound it."""
        held = {round(s.exits.time_exit_hours * 60) for s in fivemin.STRATEGIES}
        assert held == {5}
        assert fivemin.HOLD_MINUTES == (5,)

    def test_the_shapes_are_2x50_and_20x5(self) -> None:
        shapes = {(s.size_usd, s.max_concurrent) for s in fivemin.STRATEGIES}
        assert shapes == {(Decimal("2"), 50), (Decimal("20"), 5)}

    def test_every_arm_deploys_the_whole_book(self) -> None:
        """Otherwise the arms differ in capital too, not just in shape."""
        for s in fivemin.STRATEGIES:
            assert s.size_usd * s.max_concurrent == fivemin.STARTING_EQUITY

    def test_the_entry_is_shared_by_identity(self) -> None:
        """So a second arm added later cannot silently drift from this one."""
        assert all(s.entry is fivemin._EXECUTABLE for s in fivemin.STRATEGIES)

    def test_entry_is_as_early_as_the_cohort_can_be_priced(self) -> None:
        """2, not 5. The operator asked to buy within seconds; 2 minutes is
        where 75% of graduates first have BOTH a price and a liquidity (23% at
        the stamp itself), and the measured median drift to +3 is +0.06%."""
        assert fivemin.CHECKPOINT_MINUTES == 2
        # Scoped to the GRADUATION arms: the pump.swap arm is admitted by an
        # already-priced snapshot and enters at 0, which this delay is not about.
        assert {s.checkpoint_minutes for s in fivemin.STRATEGIES
                if s.id.startswith("GRAD")} == {2}

    def test_the_clock_is_the_only_exit(self) -> None:
        for s in fivemin.STRATEGIES:
            assert s.exits.take_profit is None
            assert s.exits.stop_loss is None
            assert s.exits.time_exit_hours


class TestTheOperatorsRuleSet:
    def test_each_arm_fills_its_book_exactly(self) -> None:
        for s in fivemin.STRATEGIES:
            assert s.size_usd * s.max_concurrent == s.max_exposure_usd
            assert s.max_exposure_usd == fivemin.STARTING_EQUITY

    def test_each_arm_starts_with_one_hundred(self) -> None:
        assert fivemin.STARTING_EQUITY == Decimal("100")

    def test_flat_stake_and_no_ratchet(self) -> None:
        assert fivemin.SIZING_SCALES is False
        assert fivemin.CYCLE_ENABLED is False


class TestTheOptOutsAreOptOutsNotDefaults:
    def test_scaling_is_opt_out(self) -> None:
        assert getattr(compound, "SIZING_SCALES", True) is True
        assert getattr(v7, "SIZING_SCALES", True) is True

    def test_the_ratchet_is_opt_out(self) -> None:
        assert getattr(compound, "CYCLE_ENABLED", True) is True
        assert getattr(v7, "CYCLE_ENABLED", True) is True

    def test_the_service_reads_the_ratchet_switch(self) -> None:
        assert compound_service.CompoundService(None, registry=fivemin)._cycles is False
        assert compound_service.CompoundService(None, registry=compound)._cycles is True
