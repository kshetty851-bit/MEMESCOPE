"""Strategy Lab V2 replay.

The lab is research-only and scoped to Generation 2 paper-wallet entries. These
tests protect the properties that matter for evidence: identical entries across
rules, deterministic replay, cost-aware ranking, and no dependence on stored
production trigger prices for counterfactual exits.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import ClassVar

import pytest

from app.paper import lab

pytestmark = pytest.mark.unit

START = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def entry(mint: str, *prices: tuple[int, str], liquidity: str = "10000") -> lab.TradeInput:
    return lab.TradeInput(
        position_id=uuid.uuid4(),
        mint_address=mint,
        symbol=mint.upper(),
        opened_at=START,
        entry_price=Decimal("10"),
        size_usd=Decimal("100"),
        quantity=Decimal("10"),
        entry_market_cap=Decimal("100000"),
        entry_liquidity_usd=Decimal(liquidity),
        entry_rank=1,
        status="closed",
        actual_closed_at=START + timedelta(hours=2),
        actual_exit_reason="stop",
        manual=False,
        peak_price=Decimal("10"),
        first_detected_at=START - timedelta(hours=1),
        radar_score=Decimal("80"),
        confidence=Decimal("70"),
        category="strong",
        quotes=tuple(
            lab.QuotePoint(
                at=START + timedelta(hours=hour),
                price=Decimal(price),
                liquidity_usd=Decimal(liquidity),
            )
            for hour, price in prices
        ),
    )


class TestGenerationTwoReplay:
    ENTRIES: ClassVar[list[lab.TradeInput]] = [
        entry("a", (0, "10"), (1, "20"), (2, "14"), (3, "50")),
        entry("b", (0, "10"), (1, "9"), (2, "7")),
        entry("c", (0, "10"), (25, "12"), (50, "11")),
    ]

    def test_every_strategy_uses_the_same_entries(self) -> None:
        results = lab.replay_all(self.ENTRIES)
        taken = {
            result.id: {
                (trade.mint_address, trade.entry_price, trade.opened_at)
                for trade in result.trades
            }
            for result in results
        }
        first = next(iter(taken.values()))
        for strategy_id, entries in taken.items():
            assert entries == first, strategy_id

    def test_replay_is_deterministic(self) -> None:
        assert lab.replay_all(self.ENTRIES) == lab.replay_all(self.ENTRIES)

    def test_counterfactual_exit_uses_observed_breach_quote(self) -> None:
        baseline = next(
            item for item in lab.replay_all(self.ENTRIES) if item.id == lab.BASELINE_ID
        )
        trade = next(item for item in baseline.trades if item.mint_address == "a")
        assert trade.exit_reason == "stop"
        assert trade.exit_price == Decimal("14")

    def test_no_stop_strategy_marks_at_latest_observation(self) -> None:
        hold = next(
            item for item in lab.replay_all(self.ENTRIES) if item.id == "hold_until_latest"
        )
        trade = next(item for item in hold.trades if item.mint_address == "a")
        assert trade.closed_at is None
        assert trade.mark_price == Decimal("50")

    def test_ranking_is_net_cost_aware(self) -> None:
        results = {item.id: item for item in lab.replay_all(self.ENTRIES)}
        order = lab.rank(results)
        net_returns = [results[key].net_return_pct or Decimal("-999999") for key in order]
        assert net_returns == sorted(net_returns, reverse=True)


class TestPatternsAndDisclosures:
    def test_generation_scope_constants_are_explicit(self) -> None:
        assert lab.GENERATION == 2
        assert lab.STRATEGY_ID == "trailing_stop_25_v1"

    def test_segments_publish_sample_size_and_cost_drag(self) -> None:
        rows = lab.segment(
            [entry("thin", (0, "10"), (1, "8"), liquidity="1000")],
            lab.liquidity_band,
        )
        assert rows[0].n == 1
        assert rows[0].slippage_drag_pct is not None

    def test_token_comparison_crowns_nobody_without_positive_peak(self) -> None:
        results = lab.replay_all([entry("loser", (0, "10"), (1, "5"))])
        comparison = lab.replay_tokens(results, limit=10)[0]
        assert comparison.best_strategy_id is None

    def test_final_decision_is_one_of_the_published_choices(self) -> None:
        code, text = lab.final_decision(lab.replay_all([entry("a", (0, "10"), (1, "8"))]))
        assert code in {"A", "B", "C"}
        assert text
