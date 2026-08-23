"""17, 18. What this phase was forbidden to touch, asserted rather than promised.

The market-data safety phase was scoped to infrastructure reliability and
truthful execution accounting. It may not alter the strategy, the security
gate, the holding period, position sizing, the Real Wallet, or any historical
record. Those are easy things to break by accident and hard to notice, so each
is a test rather than a line in a summary.
"""

from __future__ import annotations

import ast
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

APP = Path(__file__).resolve().parents[2] / "app"


class TestTradingRulesAreUnchanged:
    def test_the_operational_strategy_still_trails_25_percent(self) -> None:
        from app.paper.strategy import TRAILING_STOP_25_SECURED_HOLD6H_V3

        assert TRAILING_STOP_25_SECURED_HOLD6H_V3.trailing_drawdown == Decimal("0.25")

    def test_hold6h_is_still_six_hours(self) -> None:
        from app.paper.strategy import TRAILING_STOP_25_SECURED_HOLD6H_V3

        assert TRAILING_STOP_25_SECURED_HOLD6H_V3.hold_for == timedelta(hours=6)

    def test_position_size_is_still_one_hundred_dollars(self) -> None:
        from app.paper.strategy import TRAILING_STOP_25_SECURED_HOLD6H_V3

        assert TRAILING_STOP_25_SECURED_HOLD6H_V3.trade_size_usd == Decimal(100)

    # "Exactly one strategy is operational" is deliberately NOT asserted here.
    # `conftest.force_operational_for_tests` is autouse and flips the archived
    # Track Record strategy on for the duration of every test, so any check
    # made from inside pytest measures the fixture rather than the product.
    # `test_sec2_invariant.py` already asserts it properly, by shelling out to
    # a clean interpreter with no conftest loaded — a second, weaker copy here
    # would fail for a reason that has nothing to do with this phase.

    def test_sec2_still_gates_the_same_two_strategies(self) -> None:
        from app.paper.strategy import SECURITY_GATED_STRATEGY_IDS

        assert frozenset(
            {"trailing_stop_25_secured_v2", "trailing_stop_25_secured_hold6h_v3"}
        ) == SECURITY_GATED_STRATEGY_IDS

    def test_sec2_still_requires_every_mandatory_check(self) -> None:
        from app.security.entry_policy import MANDATORY_CHECKS

        assert set(MANDATORY_CHECKS) == {
            "MINT_AUTHORITY",
            "FREEZE_AUTHORITY",
            "TOKEN_PROGRAM",
            "TOKEN_EXTENSIONS",
            "VENUE",
            "LIQUIDITY_SECURITY",
        }


class TestNothingRewritesHistory:
    """17. The audit ledger stays append-only."""

    def test_no_update_or_delete_against_the_audit_table(self) -> None:
        """Checked across the whole app, not just the file that owns the table.

        "Nothing is ever overwritten" is only worth anything if it is true of
        every module, and a guard scoped to one file would pass while a new
        one quietly rewrote a track record.
        """
        offenders: list[str] = []
        for path in APP.rglob("*.py"):
            source = path.read_text()
            for statement in ("update(PaperTradeAudit", "delete(PaperTradeAudit"):
                if statement in source:
                    offenders.append(f"{path.name}: {statement}")
        assert offenders == []

    def test_no_update_or_delete_against_closed_positions(self) -> None:
        """A closed position's exit price is a permanent record too.

        This phase changes when a position may be *opened*. Nothing in it may
        reach back and restate one that already closed.
        """
        source = (APP / "paper" / "market_health.py").read_text()
        for forbidden in ("update(", "delete(", "insert("):
            assert forbidden not in source

    def test_the_market_health_module_writes_nothing_at_all(self) -> None:
        """It is a measurement. A measurement that mutates is not one."""
        source = (APP / "paper" / "market_health.py").read_text()
        tree = ast.parse(source)
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert not any(module.startswith("sqlalchemy") for module in imports)


class TestRealWalletIsUntouched:
    """18. Nothing in this phase may reach real money."""

    def test_no_real_wallet_module_imports_the_market_data_gate(self) -> None:
        offenders = [
            path.name
            for path in (APP / "real_wallet").rglob("*.py")
            if "market_health" in path.read_text()
        ]
        assert offenders == []

    def test_the_safety_package_is_untouched_too(self) -> None:
        offenders = [
            path.name
            for path in (APP / "real_wallet_safety").rglob("*.py")
            if "market_health" in path.read_text()
        ]
        assert offenders == []

    def test_the_gate_never_reaches_real_wallet_code(self) -> None:
        """The other direction. A paper-only control must stay paper-only."""
        for name in ("market_health.py", "repository.py"):
            source = (APP / "paper" / name).read_text()
            assert "real_wallet" not in source


class TestExitPathsCannotBeGated:
    """8. The asymmetry, asserted at the level of the source itself."""

    def test_the_repository_gates_only_position_creation(self) -> None:
        """`_assert_market_data_fresh` has exactly one call site, and it is the insert.

        A second call site would be the moment the gate could start refusing
        something other than a new position.
        """
        source = (APP / "paper" / "repository.py").read_text()
        # Definition plus exactly one call.
        assert source.count("_assert_market_data_fresh(") == 2

    def test_the_close_helpers_never_consult_feed_health(self) -> None:
        source = (APP / "paper" / "repository.py").read_text()
        markers = (
            "async def close_position",
            "async def advance",
            "async def record_audit",
        )
        for marker in markers:
            start = source.find(marker)
            if start == -1:
                continue
            end = source.find("\n    async def ", start + 1)
            body = source[start : end if end != -1 else len(source)]
            assert "market_health" not in body
            assert "_assert_market_data_fresh" not in body
