"""The replay engine: same entries, same history, different exits.

Two properties carry the sprint:

  - **Every strategy sees identical entries.** If entries differed, a rule could
    win by having been offered better tokens, and the table would be measuring
    luck.
  - **Replaying is deterministic.** The same rows must produce byte-identical
    results however many times they are run, or none of the published figures
    means anything.

The rest is refusal: figures that stay `None` when nothing supports them, and an
annualised return that declines to extrapolate from a short window.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import ClassVar

import pytest

from app.paper import exits, lab
from app.paper.models import ExitReason, Quote

pytestmark = pytest.mark.unit

START = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def detection(mint: str, *prices: tuple[int, str], symbol: str | None = None) -> lab.Detection:
    return lab.Detection(
        mint_address=mint,
        symbol=symbol or mint.upper(),
        detected_at=START,
        quotes=tuple(
            Quote(captured_at=START + timedelta(hours=h), price_usd=Decimal(p))
            for h, p in prices
        ),
    )


def strategy(rules: exits.ExitRules, sid: str = "probe") -> exits.LabStrategy:
    return exits.LabStrategy(id=sid, name=sid, description="", rules=rules)


class TestIdenticalEntries:
    def test_every_strategy_enters_the_same_tokens_at_the_same_price(self) -> None:
        """The whole basis of the comparison."""
        detections = [
            detection("a", (0, "10"), (1, "25"), (2, "4")),
            detection("b", (0, "50"), (1, "60"), (2, "55")),
        ]

        entries = {
            item.id: {
                (trade.mint_address, trade.entry_price, trade.opened_at)
                for trade in lab.replay(detections, item).trades
            }
            for item in exits.LAB_STRATEGIES
        }

        first = next(iter(entries.values()))
        for sid, taken in entries.items():
            assert taken == first, f"{sid} entered a different set"

    def test_an_unpriced_detection_is_never_entered(self) -> None:
        """Skipped rather than entered at a price nobody observed."""
        result = lab.replay([lab.Detection("a", "A", START, ())], strategy(exits.BASELINE))
        assert result.trades == ()

    def test_a_zero_priced_detection_is_never_entered(self) -> None:
        result = lab.replay([detection("a", (0, "0"), (1, "5"))], strategy(exits.BASELINE))
        assert result.trades == ()


class TestDeterminism:
    DETECTIONS: ClassVar[list[lab.Detection]] = [
        detection("a", (0, "10"), (1, "25"), (2, "4"), (3, "40")),
        detection("b", (0, "50"), (1, "120"), (2, "30")),
        detection("c", (0, "7"), (1, "7"), (60, "9")),
    ]

    def test_replaying_twice_gives_identical_results(self) -> None:
        for item in exits.LAB_STRATEGIES:
            first = lab.replay(self.DETECTIONS, item)
            second = lab.replay(self.DETECTIONS, item)
            assert first == second, item.id

    def test_the_ranking_is_stable(self) -> None:
        results = {s.id: lab.replay(self.DETECTIONS, s) for s in exits.LAB_STRATEGIES}
        assert lab.rank(results) == lab.rank(results)

    def test_the_equity_curve_does_not_depend_on_trade_order(self) -> None:
        forwards = lab.replay(self.DETECTIONS, strategy(exits.BASELINE))
        backwards = lab.replay(list(reversed(self.DETECTIONS)), strategy(exits.BASELINE))
        assert forwards.equity_curve == backwards.equity_curve
        assert forwards.max_drawdown_pct == backwards.max_drawdown_pct


class TestExitRulesActuallyDiffer:
    HISTORY: ClassVar[list[lab.Detection]] = [
        detection("a", (0, "10"), (1, "12"), (2, "4"), (3, "50"))
    ]

    def test_the_baseline_stops_out(self) -> None:
        result = lab.replay(self.HISTORY, exits.baseline())
        assert result.trades[0].reason is ExitReason.STOP
        assert result.trades[0].exit_price == Decimal(5)

    def test_removing_the_stop_changes_the_outcome(self) -> None:
        no_stop = strategy(
            exits.ExitRules(take_profit_multiple=Decimal(2), hold_for=timedelta(hours=48))
        )
        result = lab.replay(self.HISTORY, no_stop)
        assert result.trades[0].reason is ExitReason.TARGET
        assert result.trades[0].exit_price == Decimal(20)

    def test_a_rule_that_never_fires_leaves_the_position_open(self) -> None:
        result = lab.replay(
            self.HISTORY, strategy(exits.ExitRules(take_profit_multiple=Decimal(100)))
        )
        trade = result.trades[0]
        assert trade.is_open
        assert result.open_count == 1
        # Marked at the latest reading, not at zero.
        assert trade.mark_price == Decimal(50)


class TestGivebackAndPeak:
    def test_peak_and_giveback_explain_the_rule(self) -> None:
        """A rule with a high average peak and a high giveback was right and did
        not collect. This is the figure that makes the table diagnostic."""
        history = [detection("a", (0, "10"), (1, "30"), (2, "15"))]
        result = lab.replay(history, strategy(exits.ExitRules(hold_for=timedelta(hours=2))))
        trade = result.trades[0]

        assert trade.peak_pct == Decimal(200)  # 10 -> 30
        assert trade.return_pct == Decimal(50)  # exits at 15
        # Handed back 15 of a 30 peak.
        assert trade.giveback_pct == Decimal(50)

    def test_the_peak_never_counts_a_high_after_the_exit(self) -> None:
        history = [detection("a", (0, "10"), (1, "12"), (2, "4"), (3, "900"))]
        result = lab.replay(history, exits.baseline())
        # Stopped at hour 2; the 900 belongs to the token, not the trade.
        assert result.trades[0].peak_price == Decimal(12)


class TestRefusals:
    def test_annualising_a_short_window_is_refused(self) -> None:
        """The single most misleading figure a backtest can print."""
        result = lab.replay(
            [detection("a", (0, "10"), (1, "25"))],
            strategy(exits.ExitRules(hold_for=timedelta(hours=1))),
        )
        assert result.annualised_return_pct is None
        assert result.annualised_unavailable_reason is not None
        assert "extrapolat" in result.annualised_unavailable_reason

    def test_a_long_enough_window_is_annualised(self) -> None:
        result = lab.replay(
            [detection("a", (0, "10"), (24 * 200, "20"))],
            strategy(exits.ExitRules(hold_for=timedelta(days=100))),
        )
        assert result.annualised_return_pct is not None
        assert result.annualised_unavailable_reason is None

    def test_nothing_closed_reports_no_win_rate(self) -> None:
        result = lab.replay(
            [detection("a", (0, "10"), (1, "11"))],
            strategy(exits.ExitRules(take_profit_multiple=Decimal(50))),
        )
        assert result.win_rate_pct is None
        assert result.max_drawdown_pct is None
        assert result.average_hold_hours is None

    def test_profit_factor_is_undefined_rather_than_infinite(self) -> None:
        result = lab.replay(
            [detection("a", (0, "10"), (1, "25"))],
            strategy(exits.ExitRules(take_profit_multiple=Decimal(2))),
        )
        assert result.closed_count == 1
        assert result.profit_factor is None

    def test_an_empty_replay_states_nothing(self) -> None:
        result = lab.replay([], exits.baseline())
        assert result.total_return_pct is None
        assert result.win_rate_pct is None
        assert result.equity_curve == ()


class TestComparison:
    DETECTIONS: ClassVar[list[lab.Detection]] = [
        detection("winner", (0, "10"), (1, "40"), (2, "20")),
        detection("flat", (0, "10"), (1, "10"), (2, "10")),
        detection("loser", (0, "10"), (1, "3")),
    ]

    def results(self) -> dict[str, lab.LabResult]:
        return {s.id: lab.replay(self.DETECTIONS, s) for s in exits.LAB_STRATEGIES}

    def test_capture_is_measured_against_the_peak_the_token_reached(self) -> None:
        """A rule that returned 40% on a token that peaked at 50% captured more
        of the available move than one that returned 60% on a 300% peak."""
        comparisons = {c.mint_address: c for c in lab.compare_by_token(self.results())}
        winner = comparisons["winner"]

        assert winner.peak_pct == Decimal(300)
        assert winner.best_strategy_id is not None
        assert winner.best_capture_pct is not None

    def test_a_token_that_never_rose_crowns_nobody(self) -> None:
        """Rather than crowning whichever rule lost least."""
        comparisons = {c.mint_address: c for c in lab.compare_by_token(self.results())}
        assert comparisons["loser"].best_strategy_id is None

    def test_every_strategy_appears_for_every_token(self) -> None:
        comparisons = lab.compare_by_token(self.results())
        ids = {s.id for s in exits.LAB_STRATEGIES}
        for comparison in comparisons:
            assert set(comparison.returns) == ids

    def test_comparison_order_is_deterministic(self) -> None:
        first = [c.mint_address for c in lab.compare_by_token(self.results())]
        second = [c.mint_address for c in lab.compare_by_token(self.results())]
        assert first == second

    def test_ranking_puts_the_best_return_first(self) -> None:
        results = self.results()
        order = lab.rank(results)
        returns = [results[key].total_return_pct or Decimal("-999999") for key in order]
        assert returns == sorted(returns, reverse=True)
