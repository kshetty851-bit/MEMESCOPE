"""The constraint that matters most: this lab cannot touch anything else.

Source-parsing tests, as the Crypto Trend and Graduation labs do it, because
"the lab never writes to a wallet" is a claim about every code path including
the ones no test exercises.

This lab is smaller than its siblings in what it is allowed to reach: it has
no scheduler, no API router and no live trading, so it touches the platform in
exactly two places — the declarative `Base` its two tables hang off, and the
session factory the loader and the exporter use.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

PACKAGE = pathlib.Path(__file__).resolve().parent.parent
BACKEND = PACKAGE.parents[2]
SOURCES = sorted(p for p in PACKAGE.rglob("*.py") if "tests" not in p.parts)
MIGRATION = BACKEND / "alembic" / "versions" / "20260913_0085_forex_lab.py"
TABLES = ["fx_candles", "fx_ingest_hours", "fx_sweep_runs"]

FORBIDDEN_MODULES = (
    "app.paper",
    "app.paper_v2",
    "app.karthik",
    "app.karthik_ops",
    "app.real_wallet",
    "app.real_wallet_safety",
    "app.lab",
    "app.arena",
    "app.strategy_lab",
    "app.models",
    "app.radar",
    # Sibling labs. Each is independently gated and independently deletable;
    # an import here would make that false in one direction.
    "app.labs.rafiq",
    "app.labs.crypto_trend",
    "app.labs.breakout",
    "app.labs.early_movers",
    "app.labs.graduation",
)
#: The ONLY platform modules this lab reaches into. `api.py` adds the FastAPI
#: session dependency; it reads and serves, and mounts no write route at all.
ALLOWED_PLATFORM = ("app.db.base", "app.db.session")
#: `api.py` is allowed FastAPI; nothing else in the package is.
#: Nothing in these may know a network exists. `ingest.py` is the only module
#: in the package allowed to.
PURE_MODULES = ("engine.py", "ticks.py", "backtest.py", "report.py", "config.py", "market.py")
#: Every module the package ships.
MODULES = (
    "config.py",
    "market.py",
    "models.py",
    "ticks.py",
    "ingest.py",
    "store.py",
    "engine.py",
    "backtest.py",
    "report.py",
    "api.py",
    "__main__.py",
)


def imported_modules(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
    return found


def tree(path: pathlib.Path) -> ast.AST:
    return ast.parse(path.read_text())


def test_every_module_is_present() -> None:
    assert {p.name for p in SOURCES} == {*MODULES, "__init__.py"}


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_module_imports_another_engine_or_lab(path: pathlib.Path) -> None:
    for imported in imported_modules(tree(path)):
        for forbidden in FORBIDDEN_MODULES:
            assert imported != forbidden and not imported.startswith(f"{forbidden}."), (
                f"{path.name} imports {imported}"
            )


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_platform_imports_are_on_the_allow_list(path: pathlib.Path) -> None:
    """A new `app.` import is a decision, not an accident. This test is the
    place that decision gets made."""
    for imported in imported_modules(tree(path)):
        if not imported.startswith("app."):
            continue
        if imported.startswith("app.labs.forex_lab"):
            continue
        assert imported in ALLOWED_PLATFORM, f"{path.name} imports {imported}"


@pytest.mark.parametrize("name", PURE_MODULES)
def test_pure_modules_know_of_no_network(name: str) -> None:
    imported = imported_modules(tree(PACKAGE / name))
    assert not imported & {"httpx", "websockets", "requests", "aiohttp", "socket"}
    assert "app.labs.forex_lab.ingest" not in imported


def test_only_the_loader_opens_a_socket() -> None:
    users = {p.name for p in SOURCES if imported_modules(tree(p)) & {"httpx"}}
    assert users == {"ingest.py"}


def test_the_engine_cannot_reach_a_database() -> None:
    """The brief requires a pure engine, and this is what makes that testable to
    the cent: a strategy that could read a row could also read the future."""
    imported = imported_modules(tree(PACKAGE / "engine.py"))
    assert not {i for i in imported if i.startswith("app.")} - {"app.labs.forex_lab"}
    assert not imported & {"sqlalchemy", "asyncpg", "psycopg"}
    assert "app.labs.forex_lab.models" not in imported
    assert "app.labs.forex_lab.store" not in imported


def test_the_migration_touches_only_this_lab_s_tables() -> None:
    """Purely additive: it creates two tables and alters nothing."""
    src = MIGRATION.read_text()
    node = tree(MIGRATION)
    created = [
        c.args[0].value
        for c in ast.walk(node)
        if isinstance(c, ast.Call)
        and isinstance(c.func, ast.Attribute)
        and c.func.attr == "create_table"
        and c.args
        and isinstance(c.args[0], ast.Constant)
    ]
    assert sorted(created) == TABLES
    for forbidden in (
        "alter_column",
        "drop_column",
        "add_column",
        "rename_table",
        "execute",
        "drop_constraint",
    ):
        assert f"op.{forbidden}(" not in src, forbidden


def test_the_migration_parents_to_the_branch_production_actually_runs() -> None:
    """0084 is main's head, and main is what production deploys.

    The same lab was first written on `karthik-hq`, where this migration is
    0069 parented to `0068_graduation_features`. That branch is 264 commits
    behind main and the two number the same slots differently — main's 0068 is
    `nse_breakout_phase2` and its 0069 is `graduation_lab` — so a migration
    parented to karthik-hq's 0068 cannot run on a database that has never seen
    it, which is to say it cannot run on production.
    """
    src = MIGRATION.read_text()
    assert 'revision: str = "0085_forex_lab"' in src
    assert 'down_revision: str = "0084_v6_fast_accum"' in src
    assert len("0085_forex_lab") <= 32, "alembic_version.version_num is varchar(32)"


def test_the_flag_defaults_to_off() -> None:
    import os

    from app.labs.forex_lab import config

    saved = os.environ.pop("FOREX_LAB_ENABLED", None)
    try:
        assert config.enabled() is False
        os.environ["FOREX_LAB_ENABLED"] = "true"
        assert config.enabled() is True
        os.environ["FOREX_LAB_ENABLED"] = "0"
        assert config.enabled() is False
    finally:
        os.environ.pop("FOREX_LAB_ENABLED", None)
        if saved is not None:
            os.environ["FOREX_LAB_ENABLED"] = saved


def test_the_api_mounts_nothing_that_writes() -> None:
    """A backtest result is computed once by an operator command. A route that
    let a browser re-run the sweep with a different gate would be a second,
    unpublished experiment competing with the pre-registered one."""
    src = (PACKAGE / "api.py").read_text()
    for verb in ("@router.post", "@router.put", "@router.patch", "@router.delete"):
        assert verb not in src, verb


def test_the_api_is_the_only_module_that_imports_fastapi() -> None:
    users = {p.name for p in SOURCES if imported_modules(tree(p)) & {"fastapi"}}
    assert users == {"api.py"}
