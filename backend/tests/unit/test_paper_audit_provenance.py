"""Each side of a trade describes itself, and a gap-through stays a gap-through.

Two guarantees, both regressions of real defects found on 2026-08-21:

* **Provenance is per side.** `audit.build` branched on
  `entry_execution is not None and exit_execution is not None`, so one missing
  quote sent the whole record to the legacy path — 66 of 260 rows (25%)
  mislabelled their exit model, and 53 of those had a real Jupiter exit quote
  on the position row that the ledger discarded.

* **A trailing stop is a trigger, not a fill.** The trigger says *when*; the
  observation says *what*. UOTF's trigger was $0.0864 and the next executable
  price was $0.0000016, and the ledger must keep saying the second number.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.paper import audit, exits
from app.paper.execution import (
    JUPITER_MODEL_VERSION,
    LEGACY_MODEL_VERSION,
    jupiter_quote_from_raw,
)
from app.paper.models import ClosedTrade, ExitReason, Quote

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 21, 11, 25, tzinfo=UTC)


def quote(side: str, *, out: str, usd: Decimal, slot: int, label: str):
    """One Jupiter quote, shaped like the ones the wallet actually stores."""
    return jupiter_quote_from_raw(
        {
            "inputMint": "probe" if side == "exit" else "usdc",
            "outputMint": "usdc" if side == "exit" else "probe",
            "inAmount": "100000000",
            "outAmount": out,
            "priceImpactPct": "0.02",
            "contextSlot": slot,
            "platformFee": None,
            "routePlan": [{"swapInfo": {"label": label}}],
            "_memescope_latency_ms": "4",
        },
        side=side,
        quoted_at=NOW + timedelta(hours=1),
        input_decimals=6,
        output_decimals=6,
        input_amount_usd=None if side == "exit" else Decimal(100),
        output_amount_usd=usd if side == "exit" else None,
        estimated_price_usd=Decimal("1.2"),
        usdc_mint="usdc",
    )


def record(**overrides: object) -> audit.TradeAudit:
    base: dict[str, object] = {
        "symbol": "PROBE",
        "entry_market_cap": Decimal(100_000),
        "entry_liquidity_usd": Decimal(10_000),
        "exit_market_cap": Decimal(150_000),
        "exit_liquidity_usd": Decimal(10_000),
        "strategy_id": "trailing_stop_25_secured_hold6h_v3",
        "strategy_version": "3.0.0-hold6h",
        "wallet_generation": 9,
    }
    base.update(overrides)
    closed = ClosedTrade(
        mint_address="probe",
        opened_at=NOW,
        closed_at=NOW + timedelta(hours=4),
        size_usd=Decimal(100),
        entry_price=Decimal(1),
        exit_price=Decimal("1.2"),
        quantity=Decimal(100),
        reason=ExitReason.STOP,
    )
    return audit.record(closed, **base)  # type: ignore[arg-type]


EXIT_QUOTE = quote(
    "exit", out="120000000", usd=Decimal(120), slot=440_705_353, label="BisonFi"
)
ENTRY_QUOTE = quote("entry", out="100000000", usd=Decimal(100), slot=1, label="Pump.fun Amm")


class TestJupiterExitWithFallbackEntry:
    """14. The USMS shape: no entry quote, a real exit route. Keep the exit."""

    def test_a_real_exit_quote_survives_a_fallback_entry(self) -> None:
        result = record(entry_execution=None, exit_execution=EXIT_QUOTE)

        assert result.exit_execution_model_version == JUPITER_MODEL_VERSION
        assert result.exit_execution_route == "BisonFi"
        assert result.exit_execution_context_slot == 440_705_353
        assert result.exit_execution_price_impact_pct is not None

    def test_the_entry_still_reports_itself_as_legacy(self) -> None:
        """Preserving the exit must not overstate the entry."""
        result = record(
            entry_execution=None,
            exit_execution=EXIT_QUOTE,
            execution_fallback_reason="Token decimals unavailable for Jupiter entry quote.",
        )
        assert result.entry_execution_model_version == LEGACY_MODEL_VERSION
        assert result.entry_execution_route is None
        assert result.entry_execution_context_slot is None

    def test_the_fallback_reason_lands_only_on_the_side_it_describes(self) -> None:
        """The precise mislabelling that made the first audit read wrong.

        The ledger reported "Token decimals unavailable for Jupiter **entry**
        quote" in the exit column of a trade whose exit had a live two-hop
        route, so the record contradicted the position row it came from.
        """
        result = record(
            entry_execution=None,
            exit_execution=EXIT_QUOTE,
            execution_fallback_reason="Token decimals unavailable for Jupiter entry quote.",
        )
        assert "entry quote" in str(result.entry_execution_quote)
        assert "entry quote" not in str(result.exit_execution_quote)

    def test_net_is_priced_from_the_real_exit_quote(self) -> None:
        """Best truthful evidence, not the model that happens to be simplest.

        The exit is what turns a position back into money, so a real sell
        quote prices net even when the buy was modelled.
        """
        result = record(entry_execution=None, exit_execution=EXIT_QUOTE)
        assert result.net_return_usd == Decimal("20.0000")
        assert result.cost_unavailable_reason is None
        assert result.execution_confidence == "jupiter_exit_only"


class TestJupiterEntryWithFallbackExit:
    """15. The mirror. Each side keeps its own truth."""

    def test_a_real_entry_quote_survives_a_fallback_exit(self) -> None:
        result = record(entry_execution=ENTRY_QUOTE, exit_execution=None)

        assert result.entry_execution_model_version == JUPITER_MODEL_VERSION
        assert result.entry_execution_route == "Pump.fun Amm"
        assert result.exit_execution_model_version == LEGACY_MODEL_VERSION
        assert result.exit_execution_route is None

    def test_the_summary_version_follows_whatever_priced_net(self) -> None:
        """The exit decides net, so a modelled exit keeps the summary legacy.

        Claiming `jupiter_quote_v2` for the record as a whole would overstate
        which half of it a route actually priced.
        """
        result = record(entry_execution=ENTRY_QUOTE, exit_execution=None)
        assert result.execution_model_version == LEGACY_MODEL_VERSION
        assert result.execution_confidence == "jupiter_entry_only"


class TestBothSidesUnchanged:
    """The two paths that already worked keep working, unchanged."""

    def test_two_quotes_still_report_a_full_jupiter_round_trip(self) -> None:
        result = record(entry_execution=ENTRY_QUOTE, exit_execution=EXIT_QUOTE)
        assert result.execution_model_version == JUPITER_MODEL_VERSION
        assert result.execution_confidence == "jupiter_route"
        assert result.entry_execution_route == "Pump.fun Amm"
        assert result.exit_execution_route == "BisonFi"

    def test_no_quotes_at_all_is_still_the_legacy_round_trip(self) -> None:
        result = record(entry_execution=None, exit_execution=None)
        assert result.execution_model_version == LEGACY_MODEL_VERSION
        assert result.execution_confidence == "legacy_estimate"
        assert result.entry_execution_model_version == LEGACY_MODEL_VERSION
        assert result.exit_execution_model_version == LEGACY_MODEL_VERSION


class TestGapThroughStaysHonest:
    """16. The number that must never improve.

    UOTF: entry $0.06804, peak $0.1152, trailing trigger $0.0864, and the next
    observation 37 seconds later at $0.000001616 after the pool was drained.
    Booking the trigger would have turned a -100% trade into a -25% one.
    """

    ENTRY = Decimal("0.06804")
    PEAK = Decimal("0.1152")
    TRIGGER = PEAK * Decimal("0.75")  # 0.0864
    CRASH = Decimal("0.000001616")

    def test_a_trailing_stop_fills_at_the_observed_price_not_the_trigger(self) -> None:
        found, _ = exits.resolve(
            exits.ExitRules(trailing_drawdown=Decimal("0.25")),
            entry_price=self.ENTRY,
            opened_at=NOW,
            quotes=[Quote(price_usd=self.CRASH, captured_at=NOW + timedelta(hours=4))],
            peak=self.PEAK,
        )
        assert found is not None
        assert found.reason is ExitReason.STOP
        # The trigger is recorded as evidence of *when*...
        assert found.trigger_price == self.TRIGGER
        # ...and the fill is what the market actually showed.
        assert found.price_usd == self.CRASH
        assert found.price_usd < self.TRIGGER

    def test_a_fixed_stop_fills_at_the_observed_price_too(self) -> None:
        found, _ = exits.resolve(
            exits.ExitRules(stop_loss_multiple=Decimal("0.5")),
            entry_price=self.ENTRY,
            opened_at=NOW,
            quotes=[Quote(price_usd=self.CRASH, captured_at=NOW + timedelta(hours=4))],
        )
        assert found is not None
        assert found.price_usd == self.CRASH
        assert found.trigger_price == self.ENTRY * Decimal("0.5")

    def test_the_ledger_books_the_gap_through_loss_in_full(self) -> None:
        """-100%, not -25%. The whole reason this is asserted.

        1,469.72 units bought for $100 and sold at $0.000001616 return
        $0.0024. Nothing in the audit path may round that toward the stop.
        """
        closed = ClosedTrade(
            mint_address="UOTF",
            opened_at=NOW,
            closed_at=NOW + timedelta(hours=4),
            size_usd=Decimal(100),
            entry_price=self.ENTRY,
            exit_price=self.CRASH,
            quantity=Decimal("1469.723691945914168136"),
            reason=ExitReason.STOP,
        )
        result = audit.record(
            closed,
            symbol="UOTF",
            entry_market_cap=Decimal(68_040_742),
            entry_liquidity_usd=Decimal("658554.08"),
            exit_market_cap=Decimal(1616),
            exit_liquidity_usd=Decimal("1641.57"),
            strategy_id="trailing_stop_25_secured_hold6h_v3",
            strategy_version="3.0.0-hold6h",
            wallet_generation=9,
        )
        assert result.gross_return_pct < Decimal("-99.99")
        assert result.exit_price == self.CRASH

    def test_a_target_still_fills_at_the_level_it_asked_for(self) -> None:
        """The deliberate asymmetry, pinned so nobody "fixes" it.

        A take-profit is a limit and fills at its own price; booking the
        observed price there would claim the *upside* of a gap, which is the
        same error pointing the other way.
        """
        target = self.ENTRY * 2
        found, _ = exits.resolve(
            exits.ExitRules(take_profit_multiple=Decimal(2)),
            entry_price=self.ENTRY,
            opened_at=NOW,
            quotes=[Quote(price_usd=target * 10, captured_at=NOW + timedelta(hours=1))],
        )
        assert found is not None
        assert found.reason is ExitReason.TARGET
        assert found.price_usd == target
