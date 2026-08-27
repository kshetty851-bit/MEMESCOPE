"""Partial-exit accounting: cash returns per fill, not per close.

This is the arithmetic V1 never had to do. A $25 position that sells a quarter
must release exactly a quarter of its cost basis and hand back exactly what
that quarter fetched — no more, because the rest is still at risk, and no less,
because the wallet is meant to be able to re-deploy it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.paper_v2 import metrics

WALLET = Decimal("1000")
SIZE = Decimal("25")
QTY = Decimal("1000")


def leg(remaining: str) -> metrics.OpenLeg:
    return metrics.OpenLeg(
        mint_address="mint",
        initial_notional=SIZE,
        initial_quantity=QTY,
        remaining_quantity=Decimal(remaining),
    )


class TestCostBasisReleases:
    def test_untouched_position_holds_its_whole_notional(self) -> None:
        assert leg("1000").cost_basis_remaining == SIZE

    def test_one_rung_releases_exactly_a_quarter(self) -> None:
        assert leg("750").cost_basis_remaining == Decimal("18.75")

    def test_three_rungs_leave_the_runner_at_a_quarter(self) -> None:
        assert leg("250").cost_basis_remaining == Decimal("6.25")

    def test_a_closed_position_holds_nothing(self) -> None:
        assert leg("0").cost_basis_remaining == Decimal("0")


class TestCashReturnsImmediately:
    def test_partial_proceeds_are_spendable_before_the_position_closes(self) -> None:
        """The point of the ladder: banked cash funds the next entry."""
        summary = metrics.summarise(
            starting_balance=WALLET,
            open_legs=[leg("750")],
            closed_legs=[],
            partial_proceeds=Decimal("7.80"),
            prices={"mint": Decimal("0.025")},
        )
        assert summary.cash == Decimal("982.80")  # 1000 - 25 + 7.80
        assert summary.capital_allocated == Decimal("18.75")

    def test_equity_is_cash_plus_what_is_still_held(self) -> None:
        summary = metrics.summarise(
            starting_balance=WALLET,
            open_legs=[leg("750")],
            closed_legs=[],
            partial_proceeds=Decimal("7.80"),
            prices={"mint": Decimal("0.025")},
        )
        assert summary.open_value == Decimal("18.750")
        assert summary.equity == Decimal("1001.550")

    def test_an_unpriced_holding_makes_equity_unknown_never_zero(self) -> None:
        summary = metrics.summarise(
            starting_balance=WALLET,
            open_legs=[leg("750")],
            closed_legs=[],
            partial_proceeds=Decimal("7.80"),
            prices={"mint": None},
        )
        assert summary.equity is None
        assert summary.unpriced_positions == 1
        # ...but the cost is still known.
        assert summary.capital_allocated == Decimal("18.75")


class TestWalletLevel:
    def test_a_total_loss_costs_exactly_the_notional(self) -> None:
        summary = metrics.summarise(
            starting_balance=WALLET,
            open_legs=[],
            closed_legs=[
                metrics.ClosedLeg("rug", SIZE, Decimal("0"), datetime(2026, 8, 22, tzinfo=UTC))
            ],
            partial_proceeds=Decimal("0"),
            prices={},
        )
        assert summary.realised_pnl == Decimal("-25")
        assert summary.cash == Decimal("975")
        assert summary.equity == Decimal("975")

    def test_a_rug_that_climbed_first_keeps_what_the_ladder_banked(self) -> None:
        """The hypothesis V2 exists to test, as arithmetic."""
        summary = metrics.summarise(
            starting_balance=WALLET,
            open_legs=[],
            closed_legs=[
                metrics.ClosedLeg(
                    "pumped_then_rugged", SIZE, Decimal("14.00"),
                    datetime(2026, 8, 22, tzinfo=UTC),
                )
            ],
            partial_proceeds=Decimal("0"),
            prices={},
        )
        assert summary.realised_pnl == Decimal("-11.00")
        assert summary.cash == Decimal("989.00")

    def test_drawdown_follows_close_order_not_mint_order(self) -> None:
        legs = [
            metrics.ClosedLeg("b", SIZE, Decimal("50"), datetime(2026, 8, 22, 1, tzinfo=UTC)),
            metrics.ClosedLeg("a", SIZE, Decimal("0"), datetime(2026, 8, 22, 2, tzinfo=UTC)),
        ]
        summary = metrics.summarise(
            starting_balance=WALLET,
            open_legs=[],
            closed_legs=legs,
            partial_proceeds=Decimal("0"),
            prices={},
            realised_curve=[Decimal("1025"), Decimal("1000")],
        )
        # peak 1025 -> trough 1000 is 2.44%, which only holds if order is by close.
        assert summary.max_drawdown_pct == Decimal("2.44")

    def test_utilisation_is_measured_against_wallet_capital(self) -> None:
        """Not against cumulative deployed capital, which is a different number."""
        summary = metrics.summarise(
            starting_balance=WALLET,
            open_legs=[leg("1000"), leg("1000")],
            closed_legs=[],
            partial_proceeds=Decimal("0"),
            prices={"mint": Decimal("0.025")},
        )
        assert summary.capital_utilisation_pct == Decimal("5")  # $50 of $1000
