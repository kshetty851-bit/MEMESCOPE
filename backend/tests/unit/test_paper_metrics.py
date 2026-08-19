"""Wallet metrics, and the figures they refuse to state.

Everything here is derived from trades. The tests that matter most are the ones
asserting a figure stays `None` — a wallet that reports 0% win rate before it
has closed anything, or values an unpriced holding at zero, is stating results
it did not measure.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.paper.metrics import cash_for, max_drawdown_pct, pnl_since, summarise
from app.paper.models import ClosedTrade, ExitReason, OpenPosition

pytestmark = pytest.mark.unit

START = Decimal(1000)
OPENED = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def open_position(mint: str = "a", *, size: str = "100", price: str = "10") -> OpenPosition:
    entry = Decimal(price)
    return OpenPosition(
        mint_address=mint,
        opened_at=OPENED,
        entry_price=entry,
        quantity=Decimal(size) / entry,
        size_usd=Decimal(size),
        target_price=entry * 2,
        stop_price=entry / 2,
        expires_at=OPENED + timedelta(hours=48),
        peak_price=entry,
    )


def closed(
    mint: str,
    *,
    entry: str = "10",
    exit_price: str = "20",
    size: str = "100",
    hours: int = 5,
    reason: ExitReason = ExitReason.TARGET,
) -> ClosedTrade:
    entry_price = Decimal(entry)
    return ClosedTrade(
        mint_address=mint,
        opened_at=OPENED,
        closed_at=OPENED + timedelta(hours=hours),
        size_usd=Decimal(size),
        entry_price=entry_price,
        exit_price=Decimal(exit_price),
        quantity=Decimal(size) / entry_price,
        reason=reason,
    )


class TestCash:
    def test_cash_is_derived_from_the_positions_not_stored(self) -> None:
        """A stored balance is a second source of truth that drifts the moment
        one write lands without the other."""
        assert cash_for(START, [open_position()], []) == Decimal(900)

    def test_a_winning_close_returns_more_than_it_took(self) -> None:
        assert cash_for(START, [], [closed("a")]) == Decimal(1100)

    def test_a_stop_out_returns_half(self) -> None:
        assert cash_for(
            START, [], [closed("a", exit_price="5", reason=ExitReason.STOP)]
        ) == Decimal(950)

    def test_an_empty_wallet_holds_its_starting_balance(self) -> None:
        assert cash_for(START, [], []) == START


class TestRefusals:
    def test_an_unpriced_holding_makes_equity_unmeasured_not_zero(self) -> None:
        """Marking an unpriced holding to zero would report a loss the market
        never delivered."""
        result = summarise(
            starting_balance=START,
            open_positions=[open_position()],
            prices={"a": None},
            closed=[],
        )
        assert result.equity is None
        assert result.roi_pct is None
        assert result.return_usd is None
        assert result.unpriced_positions == 1
        assert result.priced_positions == 0
        # The partial display remains useful without pretending it is equity.
        assert result.known_partial_equity == Decimal("900.00")
        # Cash is still exact — it does not depend on any price.
        assert result.cash == Decimal(900)

    def test_a_wallet_with_no_closes_reports_no_win_rate(self) -> None:
        """0% would claim it lost everything it tried."""
        result = summarise(starting_balance=START, open_positions=[], prices={}, closed=[])
        assert result.win_rate_pct is None
        assert result.average_win is None
        assert result.average_loss is None
        assert result.max_drawdown_pct is None
        assert result.average_hold_hours is None

    def test_profit_factor_is_undefined_rather_than_infinite(self) -> None:
        """Three wins and no losses has not proven a ratio, and printing ∞
        reads as a claim."""
        result = summarise(
            starting_balance=START,
            open_positions=[],
            prices={},
            closed=[closed("a"), closed("b")],
        )
        assert result.profit_factor is None
        assert result.win_rate_pct == Decimal("100.00")


class TestMeasured:
    def test_the_headline_figures(self) -> None:
        result = summarise(
            starting_balance=START,
            open_positions=[open_position("c")],
            prices={"c": Decimal(15)},
            closed=[
                closed("a", exit_price="20"),
                closed("b", exit_price="5", reason=ExitReason.STOP),
            ],
        )
        # +100 on the winner, -50 on the stop.
        assert result.realised_pnl == Decimal("50.00")
        assert result.win_rate_pct == Decimal("50.00")
        assert result.average_win == Decimal("100.00")
        assert result.average_loss == Decimal("50.00")
        assert result.profit_factor == Decimal("2.00")
        assert result.largest_winner == Decimal(100)
        assert result.largest_loser == Decimal(-50)
        # 1000 - 100 open + 50 realised = 950 cash; the holding is worth 150.
        assert result.cash == Decimal("950.00")
        assert result.open_value == Decimal("150.00")
        assert result.equity == Decimal("1100.00")
        assert result.roi_pct == Decimal("10.00")
        assert result.return_usd == Decimal("100.00")
        assert result.open_positions == 1
        assert result.closed_positions == 2

    def test_partial_equity_includes_only_currently_priced_holdings(self) -> None:
        result = summarise(
            starting_balance=START,
            open_positions=[open_position("priced"), open_position("unpriced")],
            prices={"priced": Decimal(15), "unpriced": None},
            closed=[],
        )
        # Full equity stays unknown; the partial display is cash (800) + 150.
        assert result.equity is None
        assert result.known_partial_equity == Decimal("950.00")
        assert result.priced_positions == 1
        assert result.unpriced_positions == 1

    def test_every_exit_reason_is_counted_even_at_zero(self) -> None:
        """A reason that has never fired is a measured zero, not an absence."""
        result = summarise(
            starting_balance=START, open_positions=[], prices={}, closed=[closed("a")]
        )
        assert result.exits_by_reason == {
            "target": 1,
            "stop": 0,
            "expiry": 0,
            "manual": 0,
            "trailing_stop": 0,
            "terminal": 0,
        }

    def test_hold_time_averages_the_closed_trades(self) -> None:
        result = summarise(
            starting_balance=START,
            open_positions=[],
            prices={},
            closed=[closed("a", hours=4), closed("b", hours=8)],
        )
        assert result.average_hold_hours == Decimal("6.00")


class TestDrawdown:
    def test_it_measures_the_deepest_fall_from_a_running_high(self) -> None:
        result = max_drawdown_pct(
            START,
            [
                closed("a", exit_price="20", hours=1),  # +100 -> 1100
                closed("b", exit_price="5", hours=2, reason=ExitReason.STOP),  # -50 -> 1050
                closed("c", exit_price="5", hours=3, reason=ExitReason.STOP),  # -50 -> 1000
            ],
        )
        # Peak 1100, trough 1000 -> 9.09%.
        assert result == Decimal("9.09")

    def test_order_is_the_close_order_not_the_input_order(self) -> None:
        """Determinism: the same trades must produce the same curve however they
        arrived."""
        trades = [
            closed("a", exit_price="20", hours=1),
            closed("b", exit_price="5", hours=2, reason=ExitReason.STOP),
        ]
        assert max_drawdown_pct(START, trades) == max_drawdown_pct(
            START, list(reversed(trades))
        )

    def test_a_wallet_that_only_rose_has_no_drawdown(self) -> None:
        assert max_drawdown_pct(START, [closed("a")]) == Decimal("0.00")

    def test_nothing_closed_means_nothing_measured(self) -> None:
        assert max_drawdown_pct(START, []) is None


class TestTodaysPnl:
    def test_only_realised_trades_count(self) -> None:
        """An open position's unrealised move is not a figure anyone can act on,
        and mixing the two changes the number when nothing was traded."""
        midnight = OPENED.replace(hour=0)
        assert pnl_since([closed("a", hours=5)], since=midnight) == Decimal("100.00")

    def test_trades_closed_before_the_window_are_excluded(self) -> None:
        yesterday = closed("a", hours=-30)
        assert pnl_since([yesterday], since=OPENED) == Decimal("0.00")
