"""The growth ladder on the real wallet, and the caps that outrank it."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.config import settings
from app import sizing
from app.real_wallet.policy import configured_entry_size_usd


@pytest.fixture
def sized(monkeypatch: pytest.MonkeyPatch):
    def _apply(*, entry: str, base: str, cap: str):
        monkeypatch.setattr(settings, "REAL_WALLET_ENTRY_SIZE_USD", Decimal(entry))
        monkeypatch.setattr(settings, "REAL_WALLET_SIZING_BASE_USD", Decimal(base))
        monkeypatch.setattr(settings, "REAL_WALLET_MAX_TRADE_USD", Decimal(cap))
    return _apply


class TestUnconfigured:
    def test_no_entry_size_still_refuses(self, sized) -> None:
        sized(entry="0", base="100", cap="500")
        assert configured_entry_size_usd(Decimal("400")) is None

    def test_no_sizing_base_means_no_ladder(self, sized) -> None:
        """Unset base = nobody said when a real order should double."""
        sized(entry="5", base="0", cap="500")
        assert configured_entry_size_usd(Decimal("100000")) == Decimal("5")

    def test_no_equity_reading_stakes_the_base_size(self, sized) -> None:
        sized(entry="5", base="100", cap="500")
        assert configured_entry_size_usd(None) == Decimal("5")


class TestTheLadderApplies:
    def test_it_doubles_at_twice_the_base(self, sized) -> None:
        sized(entry="5", base="100", cap="500")
        assert configured_entry_size_usd(Decimal("199")) == Decimal("5")
        assert configured_entry_size_usd(Decimal("200")) == Decimal("10")
        assert configured_entry_size_usd(Decimal("400")) == Decimal("20")
        assert configured_entry_size_usd(Decimal("800")) == Decimal("40")

    def test_a_drawdown_takes_the_stake_back_down(self, sized) -> None:
        sized(entry="5", base="100", cap="500")
        assert configured_entry_size_usd(Decimal("400")) == Decimal("20")
        assert configured_entry_size_usd(Decimal("150")) == Decimal("5")


class TestTheCapMovesWithTheLadder:
    """The cap now SCALES rather than freezing the stake — a deliberate change,
    made on instruction, and the reasoning it replaced is worth stating.

    The cap used to be absolute: growth could never lift it, because a bound a
    growth rule can raise is not a bound. That is sound against the specific
    failure it names — equity is a COMPUTED figure, and one bad mark on an
    illiquid position inflates it, so an equity-scaled cap lets a bad mark
    enlarge its own blast radius.

    What replaces it is not "no bound" but a different one. `MAX_DOUBLINGS`
    caps the ladder at 2^6, so a wildly wrong equity can widen the per-trade
    ceiling by at most 64x rather than without limit — and 64x from a $5 base
    is $320, which measurement puts at the edge of what these pools absorb:
    round-trip cost on live V6-07 candidates runs 1.7-2.5% at $5 and 3.0-11.8%
    at $500. The market stops cooperating before the ladder does.
    """

    def test_growth_now_lifts_the_per_trade_ceiling(self, sized) -> None:
        """A fixed cap over a growing stake is an off switch, not a bound: the
        stake reaches it once and every later doubling is silently discarded."""
        sized(entry="5", base="100", cap="5")
        assert configured_entry_size_usd(Decimal("200")) == Decimal("10")
        assert configured_entry_size_usd(Decimal("400")) == Decimal("20")

    def test_the_ladder_itself_is_still_bounded(self, sized) -> None:
        """MAX_DOUBLINGS is what stops an inflated equity widening the ceiling
        without limit. It is the bound that survived the change."""
        sized(entry="5", base="100", cap="5")
        ceiling = Decimal("5") * (2 ** sizing.MAX_DOUBLINGS)
        assert configured_entry_size_usd(Decimal("1000000000")) == ceiling

    def test_it_clamps_rather_than_refusing(self, sized) -> None:
        """Clamped here on purpose: the POLICY refuses an oversized request
        outright, so an unclamped ladder would stop the wallet trading the
        moment it grew instead of sizing it correctly."""
        sized(entry="5", base="100", cap="12")
        grown = configured_entry_size_usd(Decimal("800"))
        assert grown == Decimal("40")          # 8x ladder, under the 8x cap of 96
        assert grown <= settings.REAL_WALLET_MAX_TRADE_USD * 8
