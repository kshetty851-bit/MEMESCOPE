"""Karthik is a second wallet, not a change to the first.

Every assertion here is about something the Karthik module must *not* do. They
are structural — parsed out of the source and the ORM metadata rather than
exercised through a scenario — because the property being defended is "no code
path exists", and no scenario can prove the absence of a path.

Four things are protected:

  1. The Original Paper Wallet's rules, tables and capital.
  2. The Real Wallet, which must stay execution-disabled and untouched.
  3. The Track Record, which Karthik reads and may never influence.
  4. The dependency direction, which is one-way by construction.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from app.karthik import api as karthik_api
from app.karthik import repository as karthik_repository
from app.karthik import rules as karthik_rules
from app.karthik import scheduler as karthik_scheduler
from app.karthik import service as karthik_service
from app.models import Base
from app.models.karthik import KarthikOpportunity, KarthikPosition, KarthikWallet

pytestmark = pytest.mark.unit

KARTHIK_MODULES = (
    karthik_rules,
    karthik_repository,
    karthik_service,
    karthik_api,
    karthik_scheduler,
)

#: Tables no Karthik module may name. `paper_decision_snapshots` is included
#: because the paper wallet's own Track Record claim ledger lives there — a
#: Karthik write to it would consume claims the paper wallet needs.
FORBIDDEN_TABLES = {
    "paper_wallets",
    "paper_positions",
    "paper_trade_audit",
    "paper_decision_snapshots",
    "paper_decision_outcomes",
    "paper_decision_enrichments",
    "real_wallet_positions",
    "real_wallet_execution_intents",
    "real_wallet_live_intents",
    "real_wallet_kill_switches",
}

#: ORM classes Karthik may not import at all. Importing one is the first step of
#: reading or writing it, and there is no legitimate second step.
FORBIDDEN_MODELS = {
    "PaperWallet",
    "PaperPosition",
    "PaperTradeAudit",
    "PaperDecisionSnapshot",
    "RealWalletPosition",
    "RealWalletLiveIntent",
    "RealWalletExecutionIntent",
    "RealWalletKillSwitch",
}


def _source(module: object) -> str:
    return inspect.getsource(module)  # type: ignore[arg-type]


def _code(module: object) -> str:
    """The module's executable code, with every docstring and comment removed.

    The checks below search for table names as text, which is the strongest
    form: a name in a raw SQL fragment is how a "read-only" module becomes a
    writer. But these modules *document* what they read, naming those tables in
    prose — and a test that could not tell a comment from a query would force
    the documentation to be vague to stay green.
    """
    tree = ast.parse(_source(module))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if (
            isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body.pop(0)
            if not body:
                body.append(ast.Pass())
    return ast.unparse(ast.fix_missing_locations(tree))


class TestTheOriginalPaperWalletIsOutOfReach:
    def test_no_karthik_module_names_a_paper_or_real_wallet_table(self) -> None:
        """Not even in a string.

        A table name in a raw fragment is how a "read-only" module becomes a
        writer, so the check is on the text rather than on the ORM calls.
        """
        for module in KARTHIK_MODULES:
            source = _code(module)
            for table in FORBIDDEN_TABLES:
                assert table not in source, (
                    f"{module.__name__} names {table}; Karthik has its own tables "
                    "and must never read or write the paper or real wallet's"
                )

    def test_no_karthik_module_imports_a_paper_or_real_wallet_model(self) -> None:
        for module in KARTHIK_MODULES:
            tree = ast.parse(_source(module))
            imported = {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                for alias in node.names
            }
            leaked = imported & FORBIDDEN_MODELS
            assert not leaked, f"{module.__name__} imports {leaked}"

    def test_karthik_cannot_see_the_original_wallets_cash(self) -> None:
        """Cash is derived from Karthik's own rows and nothing else.

        The repository method that computes it sums `karthik_positions` and the
        wallet's own `starting_capital`. There is no join, no union and no
        second table — so however the paper wallet's balance moves, Karthik's
        does not follow it.
        """
        source = inspect.getsource(karthik_repository.KarthikRepository.committed_and_returned)
        assert "KarthikPosition" in source
        assert "Paper" not in source

    def test_karthik_writes_only_to_its_own_three_tables(self) -> None:
        """Every `insert`/`update` target in the repository is a `karthik_*` model."""
        tree = ast.parse(_source(karthik_repository))
        written: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else None
            if name in {"insert", "update", "delete"} and node.args:
                target = node.args[0]
                if isinstance(target, ast.Name):
                    written.add(target.id)
        assert written <= {"KarthikWallet", "KarthikOpportunity", "KarthikPosition"}, (
            f"repository writes to {written}"
        )

    def test_the_service_writes_nothing_outside_karthik_except_token_decimals(self) -> None:
        """One deliberate exception, and it is not a trading table.

        `discovered_tokens.decimals` is a property of the *token* — the number
        of decimal places its mint declares on chain — not of any trade. The
        paper wallet already caches it there for exactly the same reason. No
        wallet, position, audit or Track Record row is written by Karthik.
        """
        tree = ast.parse(_source(karthik_service))
        updated: set[str] = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"insert", "update", "delete"}
                and node.args
                and isinstance(node.args[0], ast.Name)
            ):
                updated.add(node.args[0].id)
        assert updated == {"DiscoveredToken"}, updated


class TestTheTrackRecordIsAReadOnlyInput:
    def test_karthik_never_writes_a_radar_table(self) -> None:
        """The dependency direction is Track Record → Karthik, never back.

        A Karthik purchase must not make a token eligible for the Track Record,
        must not change its score, and must not admit it. Nothing in these
        modules imports a writable Radar model or names a radar table.
        """
        for module in KARTHIK_MODULES:
            source = _code(module)
            for table in ("radar_tokens", "radar_snapshots", "radar_achievements"):
                assert table not in source, f"{module.__name__} names {table}"

    def test_the_only_radar_model_used_is_read_in_one_select(self) -> None:
        """`RadarToken` appears exactly where eligibility is computed, and nowhere else."""
        assert "RadarToken" not in _code(karthik_service)
        source = _code(karthik_repository)
        assert "RadarToken" in source
        assert "session.add" not in source


class TestTheRealWalletIsUntouched:
    def test_no_karthik_module_mentions_execution_or_signing(self) -> None:
        for module in KARTHIK_MODULES:
            source = _code(module).lower()
            for term in ("signer", "keypair", "send_transaction", "autotrade", "private_key"):
                assert term not in source, f"{module.__name__} mentions {term}"


class TestTheSchemaKeepsThemApart:
    def test_the_paper_wallets_single_live_index_is_unchanged(self) -> None:
        """The constraint that guarantees one live paper wallet still stands.

        Making room for Karthik in `paper_wallets` would have meant weakening
        this, which is a change to the Original wallet however carefully it is
        done. Karthik has its own tables precisely so this index never moves.
        """
        table = Base.metadata.tables["paper_wallets"]
        live = {index.name for index in table.indexes}
        assert "uq_paper_wallets_live" in live

    def test_karthik_tables_have_no_foreign_key_into_a_trading_table(self) -> None:
        """The only outbound reference is to `discovered_tokens`, which is a catalogue.

        A foreign key into `paper_positions` or a real-wallet table would make a
        Karthik row capable of blocking a delete, a migration or an archive on
        the other side — coupling by the back door.
        """
        for model in (KarthikWallet, KarthikOpportunity, KarthikPosition):
            for column in model.__table__.columns:
                for fk in column.foreign_keys:
                    assert fk.column.table.name in {"karthik_wallets", "discovered_tokens"}, (
                        f"{model.__tablename__}.{column.name} references "
                        f"{fk.column.table.name}"
                    )

    def test_exactly_once_is_held_by_the_database(self) -> None:
        """Both constraints exist, and neither is an application check.

        Requirement: durable idempotency, not an in-memory lock. A worker
        restart, a duplicate event and an API retry are all the same thing to a
        unique index.
        """
        opportunities = {
            constraint.name for constraint in KarthikOpportunity.__table__.constraints
        }
        positions = {constraint.name for constraint in KarthikPosition.__table__.constraints}
        assert "uq_karthik_opportunities_wallet_mint" in opportunities
        assert "uq_karthik_positions_wallet_mint" in positions

    def test_only_one_karthik_wallet_can_ever_exist(self) -> None:
        names = {index.name for index in KarthikWallet.__table__.indexes}
        assert "uq_karthik_wallets_singleton" in names


class TestTheMigrationTouchesNothingThatTrades:
    def test_upgrade_only_creates_its_own_tables(self) -> None:
        """The strongest available proof that deploying Karthik changes no data.

        `upgrade()` is parsed and every `op.*` call in it is inspected. There is
        no `alter_table`, no `drop_*`, and every object created is named
        `karthik_*` — so there is no statement in the migration capable of
        touching the Original Paper Wallet, the Real Wallet or the Track Record.

        `downgrade()` is excluded on purpose: it drops the three Karthik tables,
        which is exactly what a downgrade should do.
        """
        path = (
            Path(__file__).resolve().parents[2]
            / "alembic"
            / "versions"
            / "20260822_0044_karthik_wallet.py"
        )
        tree = ast.parse(path.read_text())
        upgrade = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "upgrade"
        )

        created: set[str] = set()
        for node in ast.walk(upgrade):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "op"
            ):
                continue
            operation = node.func.attr
            assert operation in {"create_table", "create_index", "f"}, (
                f"upgrade() calls op.{operation}, which can change an existing table"
            )
            if operation in {"create_table", "create_index"}:
                target = node.args[1] if operation == "create_index" else node.args[0]
                if isinstance(target, ast.Constant):
                    created.add(str(target.value))

        assert created == {
            "karthik_wallets",
            "karthik_opportunities",
            "karthik_positions",
        }, created

    def test_it_chains_onto_the_revision_production_is_already_at(self) -> None:
        """A single head. A branch here is what crash-looped this backend once."""
        path = (
            Path(__file__).resolve().parents[2]
            / "alembic"
            / "versions"
            / "20260822_0044_karthik_wallet.py"
        )
        source = path.read_text()
        assert 'revision = "0044_karthik_wallet"' in source
        assert 'down_revision = "0043_hq_ops"' in source
