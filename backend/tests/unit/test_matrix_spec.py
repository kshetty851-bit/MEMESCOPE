"""The Matrix Lab's grid: twenty-four arms, each differing in ONE dimension.

The point of these tests is not that the numbers are right. It is that the
board stays a FACTORIAL. Twenty-four books where arms differ in two things at
once is not an experiment — it is twenty-four guesses, and the best line out of
twenty-four guesses is noise. V6 ran twenty wallets here and eighteen finished
below the failure floor.
"""

from __future__ import annotations

from decimal import Decimal

from app.matrix import spec


class TestTheGridIsComplete:
    def test_two_populations_four_clocks_three_shapes(self) -> None:
        assert len(spec.STRATEGIES) == 24
        assert len(spec.BY_ID) == 24, "ids must be unique"
        assert len(spec.POPULATIONS) == 2
        assert len(spec.CLOCKS) == 4
        assert len(spec.SHAPES) == 3

    def test_every_cell_of_the_grid_exists_exactly_once(self) -> None:
        cells = {(s.id.split("-")[0], s.exits.time_exit_hours,
                  s.size_usd) for s in spec.STRATEGIES}
        assert len(cells) == 24

    def test_ids_fit_the_column(self) -> None:
        """`lab_decisions.strategy_id` is varchar(8); a longer id fails on
        insert, which halts the tick rather than the arm."""
        for s in spec.STRATEGIES:
            assert len(s.id) <= 8, s.id


class TestOneVariableAtATime:
    def test_a_row_shares_its_entry_and_spans_every_clock(self) -> None:
        """Otherwise the clock axis measures the entry as well."""
        for pop in spec.POPULATIONS:
            for stake, _slots in spec.SHAPES:
                row = [s for s in spec.STRATEGIES
                       if s.id.startswith(pop) and s.size_usd == stake]
                assert len(row) == 4
                assert len({s.entry for s in row}) == 1
                assert len({s.exits.time_exit_hours for s in row}) == 4

    def test_a_column_shares_its_clock_and_spans_every_shape(self) -> None:
        for pop in spec.POPULATIONS:
            for _cid, clock in spec.CLOCKS:
                col = [s for s in spec.STRATEGIES
                       if s.id.startswith(pop) and s.exits.time_exit_hours == clock]
                assert len(col) == 3
                assert len({(s.size_usd, s.max_concurrent) for s in col}) == 3

    def test_the_two_populations_differ_in_entry_and_source(self) -> None:
        fresh = [s for s in spec.STRATEGIES if s.id.startswith("F")]
        aged = [s for s in spec.STRATEGIES if s.id.startswith("A")]
        assert len(fresh) == len(aged) == 12
        assert {spec.SOURCE_BY_STRATEGY[s.id] for s in fresh} == {"radar"}
        assert {spec.SOURCE_BY_STRATEGY[s.id] for s in aged} == {"deepamm"}


class TestTheRulesAsInstructed:
    def test_fresh_requires_the_launchpad_suffix(self) -> None:
        feats = {c.feature for c in spec.ENTRY_BY_POPULATION["F"]}
        assert "mint_suffix_pump" in feats

    def test_aged_requires_twenty_four_hours(self) -> None:
        cond = [c for c in spec.ENTRY_BY_POPULATION["A"]
                if c.feature == "age_hours"]
        assert len(cond) == 1
        assert cond[0].value == Decimal("24")
        assert cond[0].op == "gte"

    def test_the_populations_are_mutually_exclusive_by_design(self) -> None:
        """Measured: across 148 coins the movers labs judged, the median age at
        checkpoint was 1.26 hours and the oldest 18.5 — none reached 24. An age
        filter on the fresh stream rejects everything, which is why the two
        sections need different sources rather than one arm with both rules."""
        fresh = {c.feature for c in spec.ENTRY_BY_POPULATION["F"]}
        aged = {c.feature for c in spec.ENTRY_BY_POPULATION["A"]}
        assert "age_hours" not in fresh
        assert "mint_suffix_pump" not in aged

    def test_every_arm_banks_the_wallet_at_ten_percent(self) -> None:
        assert spec.CYCLE_TARGET_MULTIPLE == Decimal("1.10")

    def test_no_arm_carries_a_position_target(self) -> None:
        """A per-position take-profit would decide trades before the clock did
        and make the clock axis measure itself."""
        assert all(s.exits.take_profit is None for s in spec.STRATEGIES)

    def test_one_clock_is_the_ratchet_alone(self) -> None:
        no_clock = [s for s in spec.STRATEGIES if s.exits.time_exit_hours is None]
        assert len(no_clock) == 6, "three shapes x two populations"

    def test_each_book_is_fully_deployable(self) -> None:
        for s in spec.STRATEGIES:
            assert s.size_usd * s.max_concurrent == spec.STARTING_EQUITY


class TestItCannotHaltAnotherTournament:
    def test_it_has_its_own_version_and_hash(self) -> None:
        from app.movers import spec as movers
        assert spec.SPEC_VERSION == "matrix-1.0.0"
        assert spec.SPEC_HASH != movers.SPEC_HASH
        assert spec.SPEC_VERSION != movers.SPEC_VERSION

    def test_only_the_sampled_population_may_redraw(self) -> None:
        """A launch is a one-time event and must never be re-judged; a fixed
        universe of established tokens would otherwise be exhausted in one
        burst."""
        assert set(spec.REJUDGE_BY_SOURCE) == {"deepamm"}
