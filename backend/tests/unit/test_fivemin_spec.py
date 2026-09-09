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
        3.1.0 ran $10 x 10 across two horizons. Reusing a version would attach
        this book to that record."""
        assert fivemin.SPEC_VERSION == "fivemin-4.0.0"


class TestItTradesTheGraduationCohort:
    def test_candidates_come_from_graduations(self) -> None:
        assert fivemin.CANDIDATE_SOURCE == "graduations"

    def test_radar_is_still_the_default_for_everyone_else(self) -> None:
        """Absent must mean radar, or adding the switch would have silently
        repopulated every registry that predates it."""
        assert getattr(compound, "CANDIDATE_SOURCE", "radar") == "radar"
        assert getattr(v7, "CANDIDATE_SOURCE", "radar") == "radar"

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


class TestOneArmAtFiveMinutes:
    def test_only_the_five_minute_horizon_remains(self) -> None:
        """Fifteen was retired on measurement, not preference: same medians
        (1.0308 vs 1.0282) but the share going to zero tripled, 4.3% to 14.6%."""
        held = sorted(round(s.exits.time_exit_hours * 60)
                      for s in fivemin.STRATEGIES)
        assert held == [5]
        assert fivemin.HOLD_MINUTES == (5,)

    def test_the_entry_is_shared_by_identity(self) -> None:
        """So a second arm added later cannot silently drift from this one."""
        assert all(s.entry is fivemin._EXECUTABLE for s in fivemin.STRATEGIES)

    def test_entry_is_as_early_as_the_cohort_can_be_priced(self) -> None:
        """2, not 5. The operator asked to buy within seconds; 2 minutes is
        where 75% of graduates first have BOTH a price and a liquidity (23% at
        the stamp itself), and the measured median drift to +3 is +0.06%."""
        assert fivemin.CHECKPOINT_MINUTES == 2
        assert {s.checkpoint_minutes for s in fivemin.STRATEGIES} == {2}

    def test_the_clock_is_the_only_exit(self) -> None:
        for s in fivemin.STRATEGIES:
            assert s.exits.take_profit is None
            assert s.exits.stop_loss is None
            assert s.exits.time_exit_hours


class TestTheOperatorsRuleSet:
    def test_fifty_trades_of_two_dollars_fill_the_book(self) -> None:
        """$2 x 50, chosen on a sweep of 48 combinations: every loss here is
        TOTAL, so bet size is the only lever, and minus its best trade $2x50
        finished at $93.57 against $86.18 for $10x10 and $1.68 for $25x4."""
        for s in fivemin.STRATEGIES:
            assert s.size_usd == Decimal("2")
            assert s.max_concurrent == 50
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
