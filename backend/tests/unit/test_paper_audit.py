"""The permanent trade record: what it computes, and what it refuses to.

Sprint 30 §11. The arithmetic here is checked against figures worked out by
hand in the docstrings, because a cost model that is only checked against itself
proves nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.paper import audit
from app.paper.models import ClosedTrade, ExitReason

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def trade(**overrides: object) -> ClosedTrade:
    base: dict[str, object] = {
        "mint_address": "probe",
        "opened_at": NOW,
        "closed_at": NOW + timedelta(hours=6),
        "size_usd": Decimal(100),
        "entry_price": Decimal(10),
        "exit_price": Decimal(15),
        "quantity": Decimal(10),
        "reason": ExitReason.STOP,
    }
    base.update(overrides)
    return ClosedTrade(**base)  # type: ignore[arg-type]


def record(**overrides: object) -> audit.TradeAudit:
    base: dict[str, object] = {
        "symbol": "PROBE",
        "entry_market_cap": Decimal(120_000),
        "entry_liquidity_usd": Decimal(18_000),
        "exit_market_cap": Decimal(180_000),
        "exit_liquidity_usd": Decimal(18_000),
        "strategy_id": "trailing_stop_25_v1",
        "strategy_version": "1.0.0",
        "wallet_generation": 2,
    }
    base.update(overrides)
    return audit.record(trade(), **base)  # type: ignore[arg-type]


class TestGross:
    def test_gross_is_what_the_price_did(self) -> None:
        """$100 buys 10 units at 10; they leave at 15 for $150."""
        result = record()

        assert result.gross_return_usd == Decimal("50.0000")
        assert result.gross_return_pct == Decimal("50.0000")

    def test_a_loss_is_recorded_at_the_same_size_as_a_win(self) -> None:
        result = audit.record(
            trade(exit_price=Decimal(4)),
            symbol=None,
            entry_market_cap=None,
            entry_liquidity_usd=Decimal(18_000),
            exit_market_cap=None,
            exit_liquidity_usd=Decimal(18_000),
            strategy_id="trailing_stop_25_v1",
            strategy_version="1.0.0",
            wallet_generation=2,
        )

        assert result.gross_return_usd == Decimal("-60.0000")
        assert result.gross_return_pct == Decimal("-60.0000")


class TestNet:
    def test_the_fee_and_the_impact_are_charged_at_each_end(self) -> None:
        """$18,000 of total depth is $9,000 a side.

        Fee: 30 bps of $100 in, 30 bps of $150 out = 0.30 + 0.45.
        Impact: 100 x (100/9000) = 1.1111 in, 150 x (150/9000) = 2.50 out.
        Net: 150 - 2.95 - (100 + 1.4111) = 45.6389.
        """
        result = record()

        assert result.fee_usd == Decimal("0.7500")
        assert result.slippage_usd == Decimal("3.6111")
        assert result.net_return_usd == Decimal("45.6389")
        assert result.net_return_pct == Decimal("45.6389")
        assert result.cost_unavailable_reason is None

    def test_the_exit_costs_more_because_it_sells_a_bigger_position(self) -> None:
        """Sprint 27's finding, kept alive: cost is **progressive**. Charging the
        exit at the entry size would understate the cost of the winners."""
        winner = record()
        loser = audit.record(
            trade(exit_price=Decimal(4)),
            symbol=None,
            entry_market_cap=None,
            entry_liquidity_usd=Decimal(18_000),
            exit_market_cap=None,
            exit_liquidity_usd=Decimal(18_000),
            strategy_id="trailing_stop_25_v1",
            strategy_version="1.0.0",
            wallet_generation=2,
        )

        assert winner.slippage_usd is not None and loser.slippage_usd is not None
        assert winner.slippage_usd > loser.slippage_usd

    def test_no_depth_at_one_end_leaves_net_unavailable_with_its_reason(self) -> None:
        """Not zero, and not a guess. A half-costed round trip is worse than an
        uncosted one because it looks complete."""
        for missing in ("entry_liquidity_usd", "exit_liquidity_usd"):
            result = record(**{missing: None})

            assert result.net_return_usd is None
            assert result.net_return_pct is None
            assert result.fee_usd is None
            assert result.slippage_usd is None
            assert result.cost_unavailable_reason == audit.NO_DEPTH_REASON
            # Gross still stands: the price did what it did.
            assert result.gross_return_usd == Decimal("50.0000")

    def test_the_fee_rate_is_stored_beside_the_figure_it_produced(self) -> None:
        """A rate change later must not silently restate a net return already
        served."""
        assert record().swap_fee_bps == Decimal(30)


class TestWhatTheRecordCarries:
    def test_every_field_sprint_30_listed_is_present(self) -> None:
        row = record().as_row()

        for field in (
            "mint_address",
            "symbol",
            "entry_at",
            "entry_price",
            "entry_market_cap",
            "exit_at",
            "exit_price",
            "exit_market_cap",
            "gross_return_usd",
            "net_return_usd",
            "fee_usd",
            "slippage_usd",
            "exit_reason",
            "strategy_version",
        ):
            assert field in row, field

    def test_the_market_at_each_end_is_recorded_rather_than_pointed_at(self) -> None:
        """`token_market_snapshots` is pruned. A record that only referenced
        those rows would go dark for the oldest trades first — the ones a track
        record is actually judged on."""
        result = record()

        assert result.entry_market_cap == Decimal(120_000)
        assert result.exit_market_cap == Decimal(180_000)
        assert result.entry_liquidity_usd == Decimal(18_000)
        assert result.exit_liquidity_usd == Decimal(18_000)

    def test_the_disclosure_states_both_halves(self) -> None:
        """What the net figures include, and what they refuse. A reader deciding
        whether to trust one needs both."""
        assert "swap fee" in audit.DISCLOSURE
        assert "MEV" in audit.DISCLOSURE
        assert "ever rewritten" in audit.DISCLOSURE
