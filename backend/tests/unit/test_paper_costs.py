"""Execution costs, and the three things they refuse to model.

Sprint 27. Every figure before this assumed a fill at the observed mid price on
a market where **57 of 85 Radar tokens hold under $5,000 of liquidity**. The
tests that matter here are the refusals: a model that guessed at slippage,
priority fees or bonding-curve depth would produce a more comfortable number and
a less true one.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.paper import costs

pytestmark = pytest.mark.unit


class TestPriceImpact:
    def test_impact_is_the_constant_product_identity(self) -> None:
        """Buying with S against a USD reserve Y fills S/Y worse than spot.
        Exact, not an approximation."""
        # $100 into a $2,000 pool -> $1,000 USD side -> 10% impact -> $10.
        found = costs.side_cost(Decimal(100), Decimal(2_000))
        assert found is not None
        assert found.impact == Decimal(10)

    def test_a_deeper_pool_costs_less(self) -> None:
        thin = costs.side_cost(Decimal(100), Decimal(2_000))
        deep = costs.side_cost(Decimal(100), Decimal(2_000_000))
        assert thin is not None and deep is not None
        assert thin.impact > deep.impact * 100

    def test_liquidity_is_halved_because_providers_report_both_sides(self) -> None:
        """Getting this backwards doubles or halves every cost figure, so it is
        explicit rather than hidden in a constant."""
        both = costs.side_cost(Decimal(100), Decimal(2_000))
        one_sided = costs.side_cost(
            Decimal(100),
            Decimal(2_000),
            model=costs.CostModel(swap_fee_bps=Decimal(30), liquidity_is_both_sides=False),
        )
        assert both is not None and one_sided is not None
        assert both.impact == one_sided.impact * 2

    def test_a_larger_order_costs_more_than_proportionally(self) -> None:
        """Impact scales with the square of size, which is why the exit of a
        winner is the expensive side."""
        small = costs.side_cost(Decimal(100), Decimal(10_000))
        large = costs.side_cost(Decimal(200), Decimal(10_000))
        assert small is not None and large is not None
        assert large.impact == small.impact * 4


class TestFees:
    def test_the_fee_is_the_published_rate(self) -> None:
        found = costs.side_cost(Decimal(1_000), Decimal(1_000_000_000))
        assert found is not None
        # 30 bps of $1,000.
        assert found.fee == Decimal(3)

    def test_the_rate_is_configuration_not_a_measurement(self) -> None:
        model = costs.CostModel(swap_fee_bps=Decimal(100))
        found = costs.side_cost(Decimal(1_000), Decimal(1_000_000_000), model=model)
        assert found is not None
        assert found.fee == Decimal(10)


class TestRefusals:
    def test_unknown_depth_returns_nothing_rather_than_assuming_a_pool(self) -> None:
        """Bonding-curve pairs report no liquidity. Treating that as deep would
        understate exactly the trades most likely to be expensive."""
        assert costs.side_cost(Decimal(100), None) is None
        assert costs.side_cost(Decimal(100), Decimal(0)) is None

    def test_a_half_costed_round_trip_is_refused_entirely(self) -> None:
        """Worse than an uncosted one, because it looks complete."""
        assert (
            costs.round_trip(
                entry_notional=Decimal(100),
                entry_liquidity=Decimal(10_000),
                exit_notional=Decimal(150),
                exit_liquidity=None,
            )
            is None
        )
        assert (
            costs.round_trip(
                entry_notional=Decimal(100),
                entry_liquidity=None,
                exit_notional=Decimal(150),
                exit_liquidity=Decimal(10_000),
            )
            is None
        )

    def test_the_disclosure_names_every_refusal(self) -> None:
        """The three exclusions are as much a part of the model as the two
        inclusions, so they ship with it."""
        text = costs.DISCLOSURE.lower()
        assert "slippage" in text
        assert "mev" in text or "priority" in text
        assert "bonding-curve" in text

    def test_a_zero_size_order_has_no_cost_to_state(self) -> None:
        assert costs.side_cost(Decimal(0), Decimal(10_000)) is None


class TestRoundTrip:
    def test_the_exit_is_charged_on_what_the_position_is_worth(self) -> None:
        """Selling a position that tripled is a three-times larger order.
        Charging it as the entry size would understate the cost of exactly the
        winners."""
        found = costs.round_trip(
            entry_notional=Decimal(100),
            entry_liquidity=Decimal(10_000),
            exit_notional=Decimal(300),
            exit_liquidity=Decimal(10_000),
        )
        assert found is not None
        assert found.exit.impact == found.entry.impact * 9

    def test_net_proceeds_take_both_sides(self) -> None:
        found = costs.round_trip(
            entry_notional=Decimal(100),
            entry_liquidity=Decimal(1_000_000),
            exit_notional=Decimal(200),
            exit_liquidity=Decimal(1_000_000),
        )
        assert found is not None
        net = costs.net_proceeds(
            entry_notional=Decimal(100), exit_notional=Decimal(200), costs=found
        )
        # Gross profit is 100; costs are subtracted from it.
        assert net < Decimal(100)
        assert net == Decimal(200) - found.exit.total - (Decimal(100) + found.entry.total)

    def test_a_flat_trade_loses_the_cost(self) -> None:
        """The floor case: doing nothing profitable still pays the venue."""
        found = costs.round_trip(
            entry_notional=Decimal(100),
            entry_liquidity=Decimal(10_000),
            exit_notional=Decimal(100),
            exit_liquidity=Decimal(10_000),
        )
        assert found is not None
        net = costs.net_proceeds(
            entry_notional=Decimal(100), exit_notional=Decimal(100), costs=found
        )
        assert net < 0


class TestDeterminism:
    def test_the_same_inputs_always_cost_the_same(self) -> None:
        args = {
            "entry_notional": Decimal(100),
            "entry_liquidity": Decimal("1857.42"),
            "exit_notional": Decimal("243.19"),
            "exit_liquidity": Decimal("1902.11"),
        }
        assert costs.round_trip(**args) == costs.round_trip(**args)  # type: ignore[arg-type]
