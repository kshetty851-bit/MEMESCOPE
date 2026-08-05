"""The two Radar benchmarks, and why they are two.

Sprint 25 recorded that "buy every Radar token" and "equal-weight Radar" were
one measurement under two labels, and refused the duplication. Sprint 30 asked
for both, so they were made genuinely different: one carries the wallet's cash
constraint and one does not. These tests hold that difference to something a
reader can check, and hold both to starting where the wallet started.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.paper import benchmark
from app.paper.benchmark import Constituent

pytestmark = pytest.mark.unit

START = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
CAPITAL = Decimal(1000)
SIZE = Decimal(100)


def token(name: str, *, entry: str | None, now: str | None, offset: int = 0) -> Constituent:
    return Constituent(
        mint_address=name,
        available_at=START + timedelta(minutes=offset),
        entry_price=None if entry is None else Decimal(entry),
        current_price=None if now is None else Decimal(now),
    )


class TestEqualWeightRadar:
    def test_it_is_the_mean_of_the_multiples(self) -> None:
        """Equal weight means the same dollars into each, so each contributes
        its own multiple in equal share."""
        result = benchmark.equal_weight_radar(
            [token("a", entry="10", now="20"), token("b", entry="10", now="5")],
            capital=CAPITAL,
        )

        # (2.0 + 0.5) / 2 = 1.25
        assert result.return_pct == Decimal("25.00")
        assert result.positions == 2

    def test_it_takes_the_whole_universe_however_large(self) -> None:
        """Unconstrained by cash and indifferent to rank: where the other
        benchmark measures the exit rule, this one measures whether ranking
        helped at all."""
        universe = [token(f"m{i}", entry="10", now="20", offset=i) for i in range(40)]

        result = benchmark.equal_weight_radar(universe, capital=CAPITAL)

        assert result.positions == 40
        assert result.return_pct == Decimal("100.00")


class TestBuyEveryRadarToken:
    def test_it_stops_when_the_capital_is_spent(self) -> None:
        """$1,000 at $100 each is ten positions, and nothing is ever sold to
        make room for the eleventh."""
        universe = [token(f"m{i}", entry="10", now="20", offset=i) for i in range(40)]

        result = benchmark.buy_every_radar_token(universe, capital=CAPITAL, trade_size=SIZE)

        assert result.positions == 10

    def test_it_fills_in_the_order_tokens_became_available(self) -> None:
        """Not by return — that would be hindsight — and not by whatever order
        the rows arrived in, which would make the figure depend on a query plan.
        """
        universe = [
            token("late", entry="10", now="100", offset=99),
            token("early", entry="10", now="11", offset=1),
        ]

        result = benchmark.buy_every_radar_token(
            universe, capital=Decimal(100), trade_size=SIZE
        )

        assert result.positions == 1
        # The early one, at +10%, not the late 10x.
        assert result.return_pct == Decimal("10.00")

    def test_the_two_benchmarks_diverge_once_more_tokens_qualify_than_cash(
        self,
    ) -> None:
        """The reason both are published. While ten or fewer qualify they hold
        the same tokens; past that they are answering different questions."""
        universe = [
            *[token(f"early{i}", entry="10", now="5", offset=i) for i in range(10)],
            *[token(f"late{i}", entry="10", now="40", offset=50 + i) for i in range(10)],
        ]

        constrained = benchmark.buy_every_radar_token(
            universe, capital=CAPITAL, trade_size=SIZE
        )
        index = benchmark.equal_weight_radar(universe, capital=CAPITAL)

        assert constrained.return_pct == Decimal("-50.00")
        assert index.return_pct == Decimal("125.00")
        assert constrained.positions != index.positions


class TestAbsence:
    def test_an_unpriceable_token_is_counted_rather_than_dropped(self) -> None:
        """Dropping it would make survivorship the benchmark's advantage — it
        would silently hold only the tokens that stayed measurable."""
        universe = [
            token("priced", entry="10", now="20"),
            token("never_priced", entry=None, now=None, offset=1),
            token("gone_dark", entry="10", now=None, offset=2),
        ]

        index = benchmark.equal_weight_radar(universe, capital=CAPITAL)

        assert index.positions == 1
        assert index.unpriced == 2

    def test_an_unmeasurable_period_says_so_rather_than_reporting_zero(self) -> None:
        """Zero percent is a result. "Nothing could be priced" is not."""
        universe = [token("a", entry=None, now=None)]

        for result in (
            benchmark.equal_weight_radar(universe, capital=CAPITAL),
            benchmark.buy_every_radar_token(universe, capital=CAPITAL, trade_size=SIZE),
        ):
            assert result.return_pct is None
            assert result.unavailable_reason is not None

    def test_an_empty_universe_is_not_a_flat_one(self) -> None:
        assert benchmark.equal_weight_radar([], capital=CAPITAL).return_pct is None

    def test_holding_sol_publishes_its_reason_rather_than_a_number(self) -> None:
        """Sprint 30 §13 asked for the published reason to keep being shown.
        The platform stores no SOL series, so the comparison would be
        fabricated."""
        assert "fabricated" in benchmark.HOLD_SOL_UNAVAILABLE
        assert "no SOL price history" in benchmark.HOLD_SOL_UNAVAILABLE
