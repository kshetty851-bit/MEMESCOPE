"""The growth ladder on the real wallet, and the caps that outrank it."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.config import settings
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


class TestTheCapOutranksTheLadder:
    def test_growth_can_never_lift_the_per_trade_ceiling(self, sized) -> None:
        """The cap bounds the blast radius of a mistake. If a growth rule could
        raise it, it would not be a bound."""
        sized(entry="5", base="100", cap="5")
        assert configured_entry_size_usd(Decimal("100000")) == Decimal("5")

    def test_it_clamps_rather_than_refusing(self, sized) -> None:
        """Clamped here on purpose: the POLICY refuses an oversized request
        outright, so an unclamped ladder would stop the wallet trading the
        moment it grew instead of sizing it correctly."""
        sized(entry="5", base="100", cap="12")
        assert configured_entry_size_usd(Decimal("800")) == Decimal("12")
        assert configured_entry_size_usd(Decimal("800")) <= settings.REAL_WALLET_MAX_TRADE_USD
