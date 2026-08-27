"""V1 and V2 cannot reach each other's money. Structural, not aspirational.

These read the source and the schema rather than exercising one happy path,
because the requirement is "there must be no possibility of V1 positions
appearing in V2 calculations or vice versa" — and a passing scenario proves
only that one scenario passed.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

from app.core.config import Settings
from app.models.paper_v2 import PaperV2Fill, PaperV2Position, PaperV2Wallet
from app.paper import strategy as v1_strategy
from app.paper_v2 import api as v2_api
from app.paper_v2 import metrics as v2_metrics
from app.paper_v2 import service as v2_service

V1_TABLES = {"paper_wallets", "paper_positions", "paper_trade_audit"}


def code_of(module_or_fn) -> str:
    """Executable source only — docstrings and comments stripped.

    These tests assert what the code *does*, not what it talks about. A
    docstring explaining "V2 never touches `paper_positions`" is the opposite
    of a violation, and a scan that failed on it would push the explanation out
    of the file to keep the test green.
    """
    # dedent: a method's source arrives indented, which ast rejects.
    tree = ast.parse(textwrap.dedent(inspect.getsource(module_or_fn)))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)
V2_TABLES = {"paper_v2_wallets", "paper_v2_positions", "paper_v2_fills"}


class TestCapitalIsolation:
    def test_v2_is_not_in_any_v1_capital_lineage(self) -> None:
        """The single most important assertion in this file."""
        for lineage in v1_strategy.CAPITAL_LINEAGES:
            assert v2_service.STRATEGY_ID not in lineage

    def test_v1_lineage_lookup_never_returns_the_v2_strategy(self) -> None:
        for sid in (
            "trailing_stop_25_v1",
            "trailing_stop_25_secured_v2",
            "trailing_stop_25_secured_hold6h_v3",
        ):
            assert v2_service.STRATEGY_ID not in v1_strategy.lineage_for(sid)

    def test_v2_funds_itself_alone(self) -> None:
        assert v1_strategy.lineage_for(v2_service.STRATEGY_ID) == frozenset(
            {v2_service.STRATEGY_ID}
        )

    def test_v2_starting_capital_is_new_and_not_read_from_v1(self) -> None:
        source = code_of(v2_service)
        assert "PAPER_V2_STARTING_BALANCE" in source
        assert "PAPER_WALLET_STARTING_BALANCE" not in source


class TestSchemaIsolation:
    def test_v2_tables_are_distinct_from_v1_tables(self) -> None:
        names = {
            PaperV2Wallet.__tablename__,
            PaperV2Position.__tablename__,
            PaperV2Fill.__tablename__,
        }
        assert names == V2_TABLES
        assert not (names & V1_TABLES)

    def test_no_v2_module_names_a_v1_table(self) -> None:
        for module in (v2_service, v2_metrics, v2_api):
            source = code_of(module)
            for table in V1_TABLES:
                assert table not in source, f"{module.__name__} names {table}"

    def test_no_v2_module_imports_the_v1_wallet_engine(self) -> None:
        """Sharing market and cost code is fine. Sharing the wallet is not."""
        for module in (v2_service, v2_metrics, v2_api):
            source = code_of(module)
            assert "from app.paper.service" not in source
            assert "PaperWalletService" not in source
            assert "from app.models.paper import" not in source

    def test_a_rung_can_only_be_recorded_once_per_position(self) -> None:
        """Idempotence enforced by the database, not only by the resolver."""
        indexes = {ix.name for ix in PaperV2Fill.__table__.indexes}
        assert "uq_paper_v2_fills_rung" in indexes
        rung_ix = next(
            ix for ix in PaperV2Fill.__table__.indexes if ix.name == "uq_paper_v2_fills_rung"
        )
        assert rung_ix.unique is True


class TestControlIsolation:
    def test_v1_and_v2_entry_pauses_are_different_settings(self) -> None:
        fields = Settings.model_fields
        assert "PAPER_WALLET_ENTRIES_PAUSED" in fields
        assert "PAPER_V2_ENTRIES_PAUSED" in fields

    def test_v2_never_reads_v1s_entry_pause(self) -> None:
        """Pausing V1 must not pause V2."""
        source = code_of(v2_service)
        assert "PAPER_WALLET_ENTRIES_PAUSED" not in source

    def test_v1_never_reads_v2s_controls(self) -> None:
        from app.paper import service as v1_svc

        source = code_of(v1_svc)
        assert "PAPER_V2_MODE" not in source
        assert "PAPER_V2_ENTRIES_PAUSED" not in source

    def test_v2_ships_disabled(self) -> None:
        """Implementation being finished is not evidence a strategy works."""
        assert Settings.model_fields["PAPER_V2_MODE"].default == "disabled"

    def test_v2_refuses_to_open_unless_paper_active(self) -> None:
        source = code_of(v2_service.PaperV2Service.entry_refusal)
        assert "paper_active" in source


class TestSizing:
    def test_size_is_fixed_and_never_liquidity_aware(self) -> None:
        source = code_of(v2_service.PaperV2Service.open_entry)
        assert "wallet.trade_size_usd" in source
        # Sizing must not scale with depth, equity or anything else.
        for smell in ("liquidity_usd *", "* liquidity", "equity *", "k *"):
            assert smell not in source

    def test_v2_never_borrows(self) -> None:
        source = code_of(v2_service.PaperV2Service.open_entry)
        assert "await self.cash(wallet) < size" in source
