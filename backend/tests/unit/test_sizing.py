"""The growth ladder — the rule that stakes more as an account compounds."""

from __future__ import annotations

from decimal import Decimal

from app.sizing import MAX_DOUBLINGS, growth_multiplier, scaled

BASE = Decimal("100")


def _m(equity: str) -> Decimal:
    return growth_multiplier(Decimal(equity), base=BASE)


class TestTheLadder:
    def test_a_fresh_account_stakes_the_base_size(self) -> None:
        assert _m("100") == 1

    def test_it_does_not_double_a_penny_early(self) -> None:
        assert _m("199.99") == 1

    def test_it_doubles_exactly_at_two_hundred(self) -> None:
        assert _m("200") == 2

    def test_it_doubles_again_at_four_hundred(self) -> None:
        assert _m("400") == 4

    def test_and_again_at_eight_hundred(self) -> None:
        assert _m("800") == 8

    def test_it_holds_the_rung_between_thresholds(self) -> None:
        for equity in ("400", "500", "799.99"):
            assert _m(equity) == 4, equity


class TestTheWayDown:
    """The rung is read from equity as it stands, never from the peak."""

    def test_a_drawdown_takes_the_stake_back_down(self) -> None:
        assert _m("450") == 4
        assert _m("350") == 2
        assert _m("150") == 1

    def test_it_never_shrinks_below_the_base_stake(self) -> None:
        for equity in ("99", "10", "0.01", "0"):
            assert growth_multiplier(Decimal(equity), base=BASE) == 1, equity


class TestGuards:
    def test_an_unknown_equity_stakes_the_base_size(self) -> None:
        """No reading is not a reason to bet more."""
        assert growth_multiplier(None, base=BASE) == 1

    def test_a_nonsense_base_does_not_multiply(self) -> None:
        assert growth_multiplier(Decimal("1000"), base=Decimal(0)) == 1

    def test_the_ladder_is_capped(self) -> None:
        """An inflated equity mark cannot produce an unbounded order."""
        absurd = growth_multiplier(Decimal("10000000000"), base=BASE)
        assert absurd == Decimal(2) ** MAX_DOUBLINGS


class TestCapsWin:
    def test_a_hard_cap_beats_the_growth_rule(self) -> None:
        """Safety bounds exist to bound mistakes; growth cannot lift them."""
        assert scaled(Decimal("5"), Decimal(8), cap=Decimal("5")) == Decimal("5")

    def test_below_the_cap_the_rule_applies_in_full(self) -> None:
        assert scaled(Decimal("5"), Decimal(4), cap=Decimal("100")) == Decimal("20")

    def test_with_no_cap_it_simply_scales(self) -> None:
        assert scaled(Decimal("7.5"), Decimal(2)) == Decimal("15")
