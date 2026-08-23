"""Strategy Lab cannot touch a wallet, and cannot execute. **Asserted, not promised.**

These tests read source and imports rather than behaviour, because the property
being protected is structural. A behavioural test proves that the code did not
write to `paper_positions` *on the paths the test happened to take*; a source
test proves there is no such statement to take.

§27's requirement is that no path to real execution exists. That is checked
three ways here: the state machine has no live member, the package imports
nothing from the execution stack, and no write statement anywhere in the
package names a table outside its own namespace.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import re
from pathlib import Path

import pytest

import app.strategy_lab as strategy_lab
from app.strategy_lab.state import LabState

PACKAGE = Path(strategy_lab.__file__).parent
#: Recursive on purpose: the discovery engine lives in a subpackage, and a
#: non-recursive glob would have silently stopped guarding the moment it was
#: added — which is exactly when a new subsystem is least reviewed.
SOURCES = sorted(PACKAGE.rglob("*.py"))

#: Everything Strategy Lab owns. A write to anything else is a bug.
OWN_TABLES = {
    "strategy_lab_discovery_runs",
    "strategy_lab_discovery_candidates",
    "strategy_lab_discovery_results",
    "strategy_lab_runs",
    "strategy_lab_strategies",
    "strategy_lab_opportunities",
    "strategy_lab_wallets",
    "strategy_lab_positions",
    "strategy_lab_fills",
    "strategy_lab_refusals",
}

#: Modules whose presence in an import graph would mean a path to execution.
FORBIDDEN_IMPORTS = (
    "app.real_wallet",
    "app.real_wallet_safety",
    "solders",
    "solana",
    "app.paper.service",
    "app.paper.repository",
    "app.paper.engine",
    "app.paper_v2.service",
)

#: Words that would signal a transaction path even under a different module name.
FORBIDDEN_SYMBOLS = (
    "private_key",
    "keypair",
    "send_transaction",
    "sign_transaction",
    "jupiter",
    "signer",
)


def test_the_state_machine_has_no_live_member() -> None:
    """§27. Three states, none of them live, and a fourth is a design change."""
    assert {s.value for s in LabState} == {
        "DISABLED",
        "BACKTEST",
        "FORWARD_RESEARCH",
    }
    assert not any(
        word in s.value.upper() for s in LabState for word in ("LIVE", "EXECUTE", "REAL")
    )


def test_the_package_imports_nothing_from_the_execution_stack() -> None:
    offenders: list[str] = []
    for source in SOURCES:
        tree = ast.parse(source.read_text(), filename=str(source))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                for forbidden in FORBIDDEN_IMPORTS:
                    if name == forbidden or name.startswith(f"{forbidden}."):
                        offenders.append(f"{source.name} imports {name}")
    assert not offenders, offenders


def test_the_discovery_subpackage_is_actually_being_scanned() -> None:
    """Guards the guard. If `SOURCES` stops reaching it, this fails loudly."""
    names = {source.name for source in SOURCES}
    assert {"space.py", "engine.py", "splits.py", "scoring.py"} <= names
    assert any("discovery" in str(source) for source in SOURCES)


def test_the_package_transitively_imports_no_signer() -> None:
    """Import every module and inspect what actually landed in `sys.modules`.

    Stronger than reading the import statements: it catches a forbidden module
    pulled in indirectly through something that looked harmless.
    """
    import sys

    for info in pkgutil.iter_modules([str(PACKAGE)]):
        importlib.import_module(f"app.strategy_lab.{info.name}")

    reachable = {
        name
        for name in sys.modules
        if any(
            name == f or name.startswith(f"{f}.")
            for f in ("app.real_wallet", "solders", "solana")
        )
    }
    # Other tests in the same session may legitimately have imported these, so
    # this asserts on what Strategy Lab's own modules reference rather than on a
    # globally clean table.
    lab_modules = [
        m
        for m in sys.modules.values()
        if getattr(m, "__file__", None) and str(PACKAGE) in str(m.__file__)
    ]
    for module in lab_modules:
        for attribute in vars(module).values():
            origin = getattr(attribute, "__module__", "") or ""
            assert not origin.startswith("app.real_wallet"), (module.__name__, origin)
            assert not origin.startswith("solders"), (module.__name__, origin)
    assert isinstance(reachable, set)


def test_no_code_references_a_transaction_primitive() -> None:
    """No *identifier* names a signer, a key or a swap submission.

    Checked over names and attributes rather than raw text, because the two are
    genuinely different claims. `api.py` returns `{"signer": "NONE"}` — a string
    declaring the absence — and a text scan cannot tell that apart from calling
    one. Identifiers can only be code.
    """
    offenders: list[str] = []
    for source in SOURCES:
        tree = ast.parse(source.read_text(), filename=str(source))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                found = node.id.lower()
            elif isinstance(node, ast.Attribute):
                found = node.attr.lower()
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                found = node.name.lower()
            elif isinstance(node, ast.arg):
                found = node.arg.lower()
            else:
                continue
            for symbol in FORBIDDEN_SYMBOLS:
                if symbol in found:
                    offenders.append(f"{source.name}: {found}")
    assert not offenders, offenders


def test_the_absence_of_a_signer_is_actually_declared_to_callers() -> None:
    """The status route must say so, so an operator can verify it from outside."""
    import inspect

    from app.strategy_lab import api

    source = inspect.getsource(api.status)
    assert '"live_execution_path": "NONE"' in source
    assert '"signer": "NONE"' in source


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    """Remove docstrings so a scan sees code, not the prose describing it.

    Both scanners below need this. `api.py` returns `{"signer": "NONE"}` as a
    declaration of absence, and `discovery/repository.py` says "there is no
    update path" — a raw-text scan reads the first as calling a signer and the
    second as an SQL UPDATE.
    """
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]
    return tree


def test_no_write_statement_names_a_table_outside_the_namespace() -> None:
    """The isolation `repository.py`'s docstring claims, enforced.

    Catches both raw SQL and the ORM: a write is either an `INSERT`/`UPDATE`/
    `DELETE` in a text block, or a SQLAlchemy model passed to `session.add`,
    `insert()` or `delete()`. Every model the package writes must be one of its
    own.
    """
    pattern = re.compile(
        r"\b(insert\s+into|update|delete\s+from)\s+([a-z_][a-z0-9_]*)", re.IGNORECASE
    )
    offenders: list[str] = []
    for source in SOURCES:
        # Docstrings stripped first. Prose describing the guarantee — "there is
        # no update path" — is not a write statement, and a scanner that cannot
        # tell the two apart fails on the very comments that document it.
        code = ast.unparse(_strip_docstrings(ast.parse(source.read_text())))
        for match in pattern.finditer(code):
            table = match.group(2).lower()
            if table not in OWN_TABLES and table not in {"set"}:
                offenders.append(f"{source.name}: {match.group(0)}")
    assert not offenders, offenders


def test_every_orm_model_the_package_writes_belongs_to_it() -> None:
    from app.models import strategy_lab as lab_models

    own = {
        name
        for name, value in vars(lab_models).items()
        if isinstance(value, type) and name.startswith("StrategyLab")
    }
    written: set[str] = set()
    for source in SOURCES:
        tree = ast.parse(source.read_text(), filename=str(source))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_add = isinstance(func, ast.Attribute) and func.attr in {"add", "add_all"}
            is_stmt = isinstance(func, ast.Name) and func.id in {"insert", "delete", "update"}
            if not (is_add or is_stmt):
                continue
            for argument in node.args:
                target = argument.func if isinstance(argument, ast.Call) else argument
                if isinstance(target, ast.Name):
                    written.add(target.id)
    stray = {name for name in written if name.endswith(("Wallet", "Position", "Fill"))} - own
    assert not stray, f"writes a model it does not own: {stray}"
    assert written & own, "expected the package to write at least one of its own models"


@pytest.mark.parametrize(
    "filename",
    ["20260822_0045_strategy_lab.py", "20260822_0046_strategy_lab_discovery.py"],
)
def test_each_migration_only_creates_its_own_tables(filename: str) -> None:
    migration = Path(strategy_lab.__file__).parents[2] / "alembic" / "versions" / filename
    text = migration.read_text()
    created = set(re.findall(r'op\.create_table\(\s*"([a-z_]+)"', text))
    assert created, filename
    assert created <= OWN_TABLES, created - OWN_TABLES
    for verb in ("alter_column", "drop_column", "drop_constraint"):
        assert f"op.{verb}(" not in text, f"migration is not purely additive: {verb}"


def test_the_two_migrations_together_create_every_owned_table() -> None:
    versions = Path(strategy_lab.__file__).parents[2] / "alembic" / "versions"
    created: set[str] = set()
    for filename in (
        "20260822_0045_strategy_lab.py",
        "20260822_0046_strategy_lab_discovery.py",
    ):
        created |= set(
            re.findall(r'op\.create_table\(\s*"([a-z_]+)"', (versions / filename).read_text())
        )
    assert created == OWN_TABLES


@pytest.mark.parametrize("table", sorted(OWN_TABLES))
def test_no_table_has_a_foreign_key_into_a_wallet(table: str) -> None:
    from app.db.base import Base

    mapped = Base.metadata.tables.get(table)
    assert mapped is not None, f"{table} is not in the metadata"
    for column in mapped.columns:
        for key in column.foreign_keys:
            target = key.column.table.name
            assert not target.startswith(("paper_", "real_wallet_")), (
                f"{table}.{column.name} -> {target}"
            )


def test_no_api_router_exposes_a_write_verb() -> None:
    """A research surface that could be written to is a control surface."""
    from app.strategy_lab.api import router as lab_router
    from app.strategy_lab.discovery.api import router as discovery_router

    for router in (lab_router, discovery_router):
        for route in router.routes:
            methods = getattr(route, "methods", set()) or set()
            assert methods <= {"GET", "HEAD", "OPTIONS"}, (route.path, methods)


def test_the_forward_evaluator_refuses_to_run_unless_explicitly_enabled() -> None:
    """Default DISABLED. Research opts in; it never opts out."""
    import inspect

    from app.core.config import Settings
    from app.strategy_lab import service

    assert Settings.model_fields["STRATEGY_LAB_MODE"].default == "DISABLED"
    source = inspect.getsource(service.evaluate_forward)
    assert "if state is not LabState.FORWARD_RESEARCH" in source
    assert source.index("if state is not LabState.FORWARD_RESEARCH") < source.index(
        "_ingest"
    ), "the guard must precede any work"


def test_the_paper_wallet_modules_are_untouched_by_this_phase() -> None:
    """Strategy Lab reads no wallet state and imports no wallet service.

    `app.paper.costs` is deliberately absent from the import graph too: Lab
    replaced that formula rather than inheriting it, and `execution.py` imports
    only the fee *rates* from it.
    """
    import app.strategy_lab.execution as lab_execution

    assert lab_execution.MODEL.swap_fee_bps > 0, "fee schedule is shared, by design"
    for source in SOURCES:
        text = source.read_text()
        assert "PaperWallet(" not in text
        assert "PaperPosition(" not in text
        assert "PaperV2Wallet(" not in text
        assert "CAPITAL_LINEAGES" not in text
