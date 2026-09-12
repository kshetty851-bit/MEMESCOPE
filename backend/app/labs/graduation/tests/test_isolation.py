"""The constraint that matters most: this lab cannot touch anything else.

Source-parsing tests, as the Crypto Trend and Early Movers labs do it, because
"the lab never writes to the paper wallet" is a claim about every code path
including the ones no test exercises.

## What this lab DOES import, and why that is deliberate

`app.services.curve` and `app.services.rpc` are platform SERVICES, not engines
and not labs: a pure PDA derivation, a pure account decoder verified against
mainnet, and a plain JSON-RPC client. Re-implementing the curve layout inside
the lab would mean two definitions of the same bytes, free to drift apart —
which is exactly the failure the platform's own curve module was written to
avoid. So they are allowed here, by name, and nothing else is.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

PACKAGE = pathlib.Path(__file__).resolve().parent.parent
BACKEND = PACKAGE.parents[2]
SOURCES = sorted(p for p in PACKAGE.rglob("*.py") if "tests" not in p.parts)
MIGRATIONS = (
    BACKEND / "alembic" / "versions" / "20260911_0069_graduation_lab.py",
    BACKEND / "alembic" / "versions" / "20260911_0070_graduation_rpc_polling.py",
    BACKEND / "alembic" / "versions" / "20260911_0071_graduation_features.py",
    BACKEND / "alembic" / "versions" / "20260911_0073_graduation_paper_book.py",
)
TABLES = ["grad_checkpoints", "grad_curve_samples", "grad_features",
          "grad_migrations", "grad_paper_positions", "grad_postgrad_samples",
          "grad_tokens", "grad_trades"]

FORBIDDEN_MODULES = (
    "app.paper", "app.paper_v2", "app.karthik", "app.karthik_ops",
    "app.real_wallet", "app.real_wallet_safety", "app.lab", "app.arena",
    "app.strategy_lab", "app.models", "app.radar",
    # Sibling labs. Each is independently gated and independently deletable;
    # an import here would make that false in one direction.
    "app.labs.rafiq", "app.labs.crypto_trend", "app.labs.breakout",
    "app.labs.early_movers",
)
#: The ONLY platform modules this lab reaches into. Pure or transport, never
#: an engine that trades, scores or holds a wallet.
ALLOWED_PLATFORM = (
    "app.core.backoff", "app.core.logging", "app.db.base", "app.db.session",
    "app.workers.celery_app", "app.workers.runtime",
    "app.services.curve.pda", "app.services.curve.state",
    "app.services.rpc.standard",
    "app.services.market.providers.rate_budget",
)
#: Nothing in these may know a network exists. `sources.py` is the only module
#: in the package allowed to.
PURE_MODULES = ("curve.py", "parse.py", "watchset.py", "backtest.py")
#: Every module the package ships.
MODULES = ("config.py", "curve.py", "parse.py", "watchset.py", "sources.py",
           "postgrad.py", "recorder.py", "features.py", "backtest.py",
           "scheduler.py", "models.py", "api.py", "paper.py", "analyst.py",
           "__main__.py")


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
            assert imported != forbidden and not imported.startswith(f"{forbidden}."), \
                f"{path.name} imports {imported}"


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_platform_imports_are_on_the_allow_list(path: pathlib.Path) -> None:
    """A new `app.` import is a decision, not an accident. This test is the
    place that decision gets made."""
    for imported in imported_modules(tree(path)):
        if not imported.startswith("app."):
            continue
        if imported.startswith("app.labs.graduation"):
            continue
        assert imported in ALLOWED_PLATFORM, f"{path.name} imports {imported}"


@pytest.mark.parametrize("name", PURE_MODULES)
def test_pure_modules_know_of_no_network(name: str) -> None:
    """A parser that could open a socket is a parser a test cannot trust."""
    imported = imported_modules(tree(PACKAGE / name))
    assert not imported & {"httpx", "websockets", "requests", "aiohttp", "socket"}
    assert "app.labs.graduation.sources" not in imported


def test_only_sources_opens_a_socket() -> None:
    users = {p.name for p in SOURCES
             if imported_modules(tree(p)) & {"websockets", "httpx"}}
    assert users == {"sources.py"}


def executable_strings(tree: ast.AST) -> list[str]:
    """Every string literal that is NOT a docstring.

    Docstrings are excluded deliberately: this package's prose explains at
    length why the metered stream is gone, and a plain substring search over
    the file would match that explanation and fail. Comments never reach the
    AST at all, so they need no handling.
    """
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef
                      | ast.AsyncFunctionDef)
        and node.body and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docstrings]


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_module_subscribes_to_the_metered_trade_stream(
        path: pathlib.Path) -> None:
    """The whole point of this revision. `subscribeTokenTrade` is metered at
    0.01 SOL per 10,000 events; the chain reports the same curve state for the
    price of an RPC call. A reintroduction should fail a test, not a bill.

    Checked over executable string literals, so the docstrings that explain the
    absence do not themselves trip it.
    """
    for literal in executable_strings(tree(path)):
        assert "subscribeTokenTrade" not in literal, path.name
        assert "subscribeAccountTrade" not in literal, path.name


def test_models_declare_only_grad_tables() -> None:
    """A table without the prefix is a table some other migration owns."""
    source = (PACKAGE / "models.py").read_text()
    names = [line.split('"')[1] for line in source.splitlines()
             if "__tablename__" in line]
    assert sorted(names) == TABLES


@pytest.mark.parametrize("path", MIGRATIONS, ids=lambda p: p.name)
def test_migrations_touch_only_this_lab(path: pathlib.Path) -> None:
    """0067 ALTERs, unlike 0066 — but only `grad_*` tables. A database that
    runs both and never sets the flag is unchanged in every table that is not
    this lab's."""
    source = path.read_text()
    body = source.split("def upgrade()")[1].split("def downgrade()")[0]
    assert "op.execute" not in body, "raw SQL is unreviewable here"
    # Table-first operations, then `create_index`, whose FIRST argument is the
    # index name and whose second is the table. Getting that backwards is how
    # this test passed on a migration that touched someone else's table.
    targets = re.findall(
        r'op\.(?:create_table|add_column|alter_column|drop_column|drop_table|'
        r'drop_constraint)\(\s*"([^"]+)"', body)
    targets += re.findall(
        r'op\.create_index\(\s*"[^"]+",\s*"([^"]+)"', body)
    assert targets, f"{path.name}: no operations found — did the regex rot?"
    for target in targets:
        assert target in TABLES, f"{path.name} touches {target}"

    # Every index this migration creates must name a table it is allowed to.
    indexes = re.findall(r'op\.create_index\([^)]*?\)', body, re.DOTALL)
    assert len(indexes) == body.count("op.create_index("), "unbalanced parse"


def test_each_migration_creates_the_tables_it_claims() -> None:
    by_migration = {
        "0069": ["grad_checkpoints", "grad_migrations", "grad_tokens",
                 "grad_trades"],
        "0070": ["grad_curve_samples", "grad_postgrad_samples"],
        "0071": ["grad_features"],
        "0073": ["grad_paper_positions"],
    }
    for path, expected in zip(MIGRATIONS, by_migration.values(), strict=True):
        created = re.findall(r'op\.create_table\(\s*"([^"]+)"', path.read_text())
        assert sorted(created) == expected, path.name


@pytest.mark.parametrize("name", ("features.py", "backtest.py"))
def test_raw_sql_names_only_this_labs_tables(name: str) -> None:
    """These two issue arbitrary SQL, so the table names they mention are
    worth pinning."""
    mentioned = set(re.findall(r"\bgrad_[a-z_]+\b", (PACKAGE / name).read_text()))
    assert mentioned <= set(TABLES), mentioned - set(TABLES)


def test_the_api_is_read_only() -> None:
    """A status board must not be able to change what it reports. The router
    has no non-GET route, and this fails if one is ever added."""
    from app.labs.graduation.api import router

    methods = {m for route in router.routes for m in route.methods}
    assert methods == {"GET"}, methods


def test_the_status_endpoint_can_report_a_stalled_recorder() -> None:
    """A row count cannot show a dead RPC — the stored rows stay exactly where
    they were and every other figure on the page still reads normally. The
    pulse has to come from a timestamp that advances on every successful read.

    `grad_tokens.last_sample_at` is that timestamp: the poller sets it whether
    or not the reserves moved, so it stops the moment reads stop. It also
    crosses processes, which matters — the API runs in the backend container
    and cannot see the recorder's in-memory counters at all.
    """
    body = (PACKAGE / "api.py").read_text()
    assert "GradToken.last_sample_at" in body
    assert "recorder_stalled" in body
    # A stall is only a stall when there is something to read.
    assert "base.watch_set > 0" in body


def test_the_backtester_writes_nothing() -> None:
    """It is a replay. A backtester that can INSERT is one that will, and the
    recorded series is the only asset this lab has."""
    body = (PACKAGE / "backtest.py").read_text()
    for banned in ("insert(", "session.commit", "update(", "delete("):
        assert banned not in body, banned


def test_the_backtester_ships_no_tuned_strategy() -> None:
    """B0 and B1 exist to be beaten. A harness that arrives with a winner in it
    is a harness nobody audits."""
    from app.labs.graduation.backtest import BASELINES

    assert set(BASELINES) == {"B0_open_timebox_5m", "B1_f90_timebox_5m"}


@pytest.mark.parametrize("path", MIGRATIONS, ids=lambda p: p.name)
def test_the_migration_id_fits_the_alembic_column(path: pathlib.Path) -> None:
    """`alembic_version.version_num` is varchar(32). A longer id fails at
    runtime, on the deploy, after the tables are already created."""
    source = path.read_text()
    for field in ("revision", "down_revision"):
        value = source.split(f'{field}: str = "')[1].split('"')[0]
        assert len(value) <= 32, (field, value, len(value))


def test_the_flag_defaults_off() -> None:
    """Read at call time, so a worker cannot cache a lab the operator
    turned off."""
    import os

    from app.labs.graduation import config

    original = os.environ.pop("LAB_GRADUATION_ENABLED", None)
    try:
        assert config.enabled() is False
        os.environ["LAB_GRADUATION_ENABLED"] = "true"
        assert config.enabled() is True
        os.environ["LAB_GRADUATION_ENABLED"] = "no"
        assert config.enabled() is False
    finally:
        if original is None:
            os.environ.pop("LAB_GRADUATION_ENABLED", None)
        else:
            os.environ["LAB_GRADUATION_ENABLED"] = original


def test_the_rpc_url_is_never_surfaced_with_its_credential() -> None:
    """A provider endpoint carries the key IN the URL. Printing the endpoint
    prints the secret, and the recorder's startup banner did exactly that on
    its first production start — a live Helius key into the container log.

    Nothing that a human or a log sees may call `rpc_url()` directly.
    """
    import os

    from app.labs.graduation import config

    original = os.environ.get("SOLANA_RPC_URL")
    os.environ["SOLANA_RPC_URL"] = "https://mainnet.helius-rpc.com/?api-key=SEKRIT"
    try:
        assert "SEKRIT" in config.rpc_url()
        assert "SEKRIT" not in config.safe_rpc_url()
        assert config.safe_rpc_url().startswith("https://mainnet.helius-rpc.com")
    finally:
        if original is None:
            os.environ.pop("SOLANA_RPC_URL", None)
        else:
            os.environ["SOLANA_RPC_URL"] = original

    # The two modules a person reads output from must use the safe form.
    for name in ("__main__.py", "recorder.py"):
        body = (PACKAGE / name).read_text()
        assert "config.rpc_url()" not in body, name


def test_the_rpc_url_defaults_to_public_mainnet_and_is_overridable() -> None:
    import os

    from app.labs.graduation import config

    original = os.environ.pop("SOLANA_RPC_URL", None)
    try:
        assert config.rpc_url() == "https://api.mainnet-beta.solana.com"
        os.environ["SOLANA_RPC_URL"] = "https://node.example/rpc"
        assert config.rpc_url() == "https://node.example/rpc"
    finally:
        if original is None:
            os.environ.pop("SOLANA_RPC_URL", None)
        else:
            os.environ["SOLANA_RPC_URL"] = original
