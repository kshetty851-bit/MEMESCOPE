"""The death rule: the one exit that cannot be revised, so the one that must
be corroborated.

Before this guard, a single `inactive` reading closed a position at $0.00 for
ever. Measured over seven days and 806 `dead_zero` exits, 56 of them (6.9%)
were written off while the token was trading again within ten minutes at more
than half the entry price — $337 of stake booked as total losses on positions
actually worth $860. The case below with a 17-second gap is a real one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.lab.service import DEATH_CONFIRMATION_WINDOW, live_print
from app.models.market import TradingStatus

NOW = datetime(2026, 9, 9, 4, 17, 30, tzinfo=UTC)


def row(seconds_ago: int, *, status=TradingStatus.TRADING, price="0.00181"):
    return SimpleNamespace(
        captured_at=NOW - timedelta(seconds=seconds_ago),
        price_usd=Decimal(price) if price is not None else None,
        liquidity_usd=Decimal("132525"),
        trading_status=status,
    )


class TestAGlitchIsNotADeath:
    def test_the_real_case_that_cost_twenty_dollars(self) -> None:
        """04:17:08 read inactive; 04:17:25 the same token traded 7.4% ABOVE
        entry. Newest-first, as `_mark` selects them."""
        rows = [
            row(5, status=TradingStatus.TRADING, price="0.001949"),
            row(22, status=TradingStatus.INACTIVE, price=None),
            row(221, status=TradingStatus.TRADING, price="0.001814"),
        ]
        found = live_print(rows, NOW)
        assert found is not None, "a trading print inside the window is not death"
        assert found.price_usd == Decimal("0.001949")

    def test_it_marks_against_the_live_print_not_merely_vetoes(self) -> None:
        """Skipping the tick would leave the position unmarked on the very
        cycle a good price existed."""
        live = row(30, price="0.5")
        assert live_print([row(1, status=TradingStatus.INACTIVE, price=None), live],
                          NOW) is live


class TestARealDeathStillCloses:
    def test_sustained_inactive_is_death(self) -> None:
        rows = [row(i, status=TradingStatus.INACTIVE, price=None)
                for i in (5, 40, 80)]
        assert live_print(rows, NOW) is None

    def test_a_live_print_outside_the_window_does_not_rescue(self) -> None:
        """Otherwise a token that stopped being polled would never close —
        which is how this lab once froze its worst positions for ever."""
        stale = int(DEATH_CONFIRMATION_WINDOW.total_seconds()) + 60
        rows = [row(5, status=TradingStatus.INACTIVE, price=None),
                row(stale, price="1.0")]
        assert live_print(rows, NOW) is None

    def test_a_zero_priced_print_is_not_a_rescue(self) -> None:
        rows = [row(5, status=TradingStatus.INACTIVE, price=None),
                row(20, price="0")]
        assert live_print(rows, NOW) is None

    def test_no_observations_at_all(self) -> None:
        assert live_print([], NOW) is None


class TestTheWindowIsBounded:
    def test_two_minutes(self) -> None:
        """Long enough to outlast a provider hiccup, short enough that a real
        death closes on the same beat it would have before, plus two minutes."""
        assert DEATH_CONFIRMATION_WINDOW == timedelta(minutes=2)
