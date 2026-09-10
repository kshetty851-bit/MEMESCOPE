"""The constraint that matters most: this lab cannot touch anything else.

Source-parsing tests, as in the Rafiq lab, because "the lab never writes to
the paper wallet" is a claim about every code path including the ones no
test exercises.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

PACKAGE = pathlib.Path(__file__).resolve().parent.parent
BACKEND = PACKAGE.parents[2]
SOURCES = sorted(p for p in PACKAGE.rglob("*.py") if "tests" not in p.parts)
MIGRATION = BACKEND / "alembic" / "versions" / "20260910_0057_crypto_trend_lab.py"

FORBIDDEN_MODULES = (
    "app.paper", "app.paper_v2", "app.karthik", "app.karthik_ops",
    "app.real_wallet", "app.real_wallet_safety", "app.lab", "app.arena",
    "app.strategy_lab", "app.labs.rafiq", "app.models",
)


def imported_modules(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
    return found


def test_the_lab_imports_no_other_engine_and_no_shared_model() -> None:
    """Stricter than the Rafiq lab: this one has no feed. It reads two public
    APIs and its own tables, so not one module may import `app.models`."""
    offenders = []
    for path in SOURCES:
        for module in imported_modules(ast.parse(path.read_text())):
            for banned in FORBIDDEN_MODULES:
                if module == banned or module.startswith(f"{banned}."):
                    offenders.append(f"{path.name} imports {module}")
    assert not offenders, offenders


def test_every_lab_table_carries_the_prefix_and_sits_on_the_platform_base() -> None:
    """On `app.db.base.Base` — the SAME object the platform's models use — not
    a second `DeclarativeBase`. The Rafiq lab tried a second one and got a
    migration that would have dropped its own ledger."""
    from app.db.base import Base as PlatformBase
    from app.labs.crypto_trend import models

    declared = {m for m in vars(models).values()
                if isinstance(m, type) and hasattr(m, "__tablename__")}
    assert {m.__tablename__ for m in declared} == {
        "ct_universe", "ct_candles", "ct_funding", "ct_runs"}
    assert all(m.metadata is PlatformBase.metadata for m in declared)


def test_the_migration_is_purely_additive() -> None:
    tree = ast.parse(MIGRATION.read_text())
    upgrade = next(n for n in tree.body
                   if isinstance(n, ast.FunctionDef) and n.name == "upgrade")
    ops = [n.func.attr for n in ast.walk(upgrade)
           if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
           and isinstance(n.func.value, ast.Name) and n.func.value.id == "op"]
    assert ops, "expected the migration to do something"
    assert set(ops) <= {"create_table", "create_index"}, ops
    targets = [n.args[0].value for n in ast.walk(upgrade)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "create_table"]
    assert sorted(targets) == ["ct_candles", "ct_funding", "ct_runs", "ct_universe"]


def test_the_migration_matches_the_models() -> None:
    """Every column the models declare, the migration creates, with the same
    nullability — so `alembic check` has nothing to say once the models are
    imported by `app.models`."""
    import sqlalchemy as sa
    from alembic import op as alembic_op

    from app.labs.crypto_trend import models

    created: dict[str, dict[str, bool]] = {}

    class Recorder:
        def create_table(self, name, *columns, **kw):
            created[name] = {c.name: c.nullable for c in columns if isinstance(c, sa.Column)}

        def create_index(self, *a, **kw):
            pass

    namespace: dict = {}
    exec(compile(MIGRATION.read_text(), str(MIGRATION), "exec"), namespace)  # noqa: S102
    namespace["op"] = Recorder()
    namespace["upgrade"]()
    assert alembic_op  # imported only to prove the module is loadable here

    for model in (models.CtUniverseMember, models.CtCandle, models.CtFunding, models.CtRun):
        expected = {c.name: c.nullable for c in model.__table__.columns}
        assert created[model.__tablename__] == expected, model.__tablename__


def test_the_api_is_read_only() -> None:
    from app.labs.crypto_trend.api import router
    methods = {m for route in router.routes for m in getattr(route, "methods", ())}
    assert methods <= {"GET", "HEAD", "OPTIONS"}, methods
    assert [r.path for r in router.routes] == ["/labs/crypto-trend/health"]


def test_the_flag_defaults_off(monkeypatch) -> None:
    from app.labs.crypto_trend import config
    monkeypatch.delenv("CRYPTO_TREND_LAB_ENABLED", raising=False)
    assert config.enabled() is False
    monkeypatch.setenv("CRYPTO_TREND_LAB_ENABLED", "true")
    assert config.enabled() is True
    monkeypatch.setenv("CRYPTO_TREND_LAB_ENABLED", "0")
    assert config.enabled() is False


async def test_the_tick_is_inert_while_the_flag_is_off(monkeypatch) -> None:
    """With the flag down `tick` returns before it opens a session or a
    socket. `MarketSource.__aenter__` is the only place a client is built;
    if it is entered, this fails."""
    from app.labs.crypto_trend import scheduler
    from app.labs.crypto_trend.sources import MarketSource

    async def boom(self):
        raise AssertionError("opened a network client with the flag off")

    monkeypatch.setattr(MarketSource, "__aenter__", boom)
    monkeypatch.delenv("CRYPTO_TREND_LAB_ENABLED", raising=False)
    assert await scheduler.tick() == {"skipped": "crypto_trend_lab_disabled"}


def test_the_celery_task_exists_under_its_documented_name() -> None:
    from app.labs.crypto_trend.scheduler import crypto_trend_lab_tick
    assert crypto_trend_lab_tick.name == (
        "app.labs.crypto_trend.scheduler.crypto_trend_lab_tick")


# --- the registrations that live outside this package ---------------------------

def test_alembic_can_see_the_lab_tables() -> None:
    """`alembic/env.py` imports `app.models` and nothing else. Until that
    package imports this lab's models, autogenerate sees four tables in the
    database and none in the model tree, and emits `drop_table` for each."""
    code = ("import app.models; from app.db.base import Base; "
            "import sys; sys.exit(0 if 'ct_candles' in Base.metadata.tables else 1)")
    proc = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, check=False)  # noqa: S603
    assert proc.returncode == 0


def test_the_beat_registration_resolves() -> None:
    from app.workers.celery_app import celery_app

    celery_app.loader.import_default_modules()
    entry = celery_app.conf.beat_schedule["crypto-trend-lab-tick"]
    assert entry["task"] == "app.labs.crypto_trend.scheduler.crypto_trend_lab_tick"
    assert entry["task"] in celery_app.tasks
    # And nothing else on the beat was broken by adding it.
    unresolved = [e["task"] for e in celery_app.conf.beat_schedule.values()
                  if e["task"] not in celery_app.tasks]
    assert not unresolved, unresolved
