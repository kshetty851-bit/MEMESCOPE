"""The constraint that matters most: this lab cannot touch anything else.

Source-parsing tests, as in the Crypto Trend and Rafiq labs, because "the lab
never writes to the paper wallet" is a claim about every code path including
the ones no test exercises.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

import pytest

PACKAGE = pathlib.Path(__file__).resolve().parent.parent
BACKEND = PACKAGE.parents[2]
SOURCES = sorted(p for p in PACKAGE.rglob("*.py") if "tests" not in p.parts)
MIGRATIONS = {
    BACKEND / "alembic" / "versions" / "20260911_0063_breakout_lab.py":
        ["bo_candles", "bo_runs", "bo_universe"],
    BACKEND / "alembic" / "versions" / "20260911_0064_breakout_setups.py":
        ["bo_episodes", "bo_levels", "bo_setup_snapshots"],
    BACKEND / "alembic" / "versions" / "20260911_0065_breakout_trader.py":
        ["bo_account", "bo_equity", "bo_positions", "bo_trades"],
}
TABLES = sorted(t for tables in MIGRATIONS.values() for t in tables)
#: Levels, momentum and the state machine are pure computation over `data.py`.
#: Nothing in them may know a network exists — a rate-limited candle pass must
#: never stop setups being evaluated on the bars that ARE stored.
PURE_MODULES = ("levels.py", "momentum.py", "setups.py", "rules.py")

FORBIDDEN_MODULES = (
    "app.paper", "app.paper_v2", "app.karthik", "app.karthik_ops",
    "app.real_wallet", "app.real_wallet_safety", "app.lab", "app.arena",
    "app.strategy_lab", "app.radar", "app.labs.rafiq", "app.labs.crypto_trend",
    "app.labs.early_movers", "app.models",
    # The platform's own DexScreener and GeckoTerminal clients. The lab keeps
    # a thin client of its own; see `sources.py` for why.
    "app.services.market.providers.dexscreener",
    "app.services.market.providers.geckoterminal",
    "app.services.market.service", "app.services.curve",
)
#: The ONE thing this lab may import from `app.services`: the shared token
#: bucket, which the Crypto Trend lab reuses for the same purpose.
ALLOWED_SERVICE_IMPORTS = ("app.services.market.providers.rate_budget",)


def imported_modules(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
    return found


def test_the_lab_imports_no_other_engine_lab_or_shared_model() -> None:
    offenders = []
    for path in SOURCES:
        for module in imported_modules(ast.parse(path.read_text())):
            for banned in FORBIDDEN_MODULES:
                if module == banned or module.startswith(f"{banned}."):
                    offenders.append(f"{path.name} imports {module}")
    assert not offenders, offenders


def test_the_only_platform_service_imported_is_the_rate_budget() -> None:
    """Reusing the token bucket is reuse; reusing the pump.fun feed's market
    provider would couple a lab to the platform, which is the thing labs exist
    not to do."""
    leaked = set()
    for path in SOURCES:
        leaked |= {m for m in imported_modules(ast.parse(path.read_text()))
                   if m.startswith("app.services")
                   and not m.startswith(ALLOWED_SERVICE_IMPORTS)}
    assert not leaked, leaked


def test_every_lab_table_carries_the_prefix_and_sits_on_the_platform_base() -> None:
    """On `app.db.base.Base` — the SAME object the platform's models use — not
    a second `DeclarativeBase`. The Rafiq lab tried a second one and got a
    migration that would have dropped its own ledger."""
    from app.db.base import Base as PlatformBase
    from app.labs.breakout import models

    declared = {m for m in vars(models).values()
                if isinstance(m, type) and hasattr(m, "__tablename__")}
    assert {m.__tablename__ for m in declared} == set(TABLES)
    assert all(m.metadata is PlatformBase.metadata for m in declared)


@pytest.mark.parametrize("migration", list(MIGRATIONS), ids=lambda p: p.stem[-18:])
def test_the_migration_is_purely_additive(migration) -> None:
    tree = ast.parse(migration.read_text())
    upgrade = next(n for n in tree.body
                   if isinstance(n, ast.FunctionDef) and n.name == "upgrade")
    ops = [n.func.attr for n in ast.walk(upgrade)
           if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
           and isinstance(n.func.value, ast.Name) and n.func.value.id == "op"]
    assert ops, "expected the migration to do something"
    assert set(ops) <= {"create_table", "create_index", "add_column"}, ops
    targets = [n.args[0].value for n in ast.walk(upgrade)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr in ("create_table", "add_column", "create_index")]
    created = [n.args[0].value for n in ast.walk(upgrade)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "create_table"]
    assert sorted(created) == MIGRATIONS[migration]
    # create_index's first argument is the index name, which also carries the
    # prefix, so one check covers both shapes.
    assert all(t.startswith(("bo_", "ix_bo_", "uq_bo_")) for t in targets), targets


def test_the_migration_matches_the_models() -> None:
    """Every column the models declare, the migration creates, with the same
    nullability — so `alembic check` has nothing to say once the models are
    imported by `app.models`."""
    import sqlalchemy as sa

    from app.labs.breakout import models

    created: dict[str, dict[str, bool]] = {}

    class Recorder:
        def create_table(self, name, *columns, **kw):
            created[name] = {c.name: c.nullable for c in columns if isinstance(c, sa.Column)}

        def create_index(self, *a, **kw):
            pass

        def add_column(self, name, column, **kw):
            created[name][column.name] = column.nullable

    for migration in MIGRATIONS:
        namespace: dict = {}
        exec(compile(migration.read_text(), str(migration), "exec"), namespace)  # noqa: S102
        namespace["op"] = Recorder()
        namespace["upgrade"]()

    for model in (models.BoUniverseMember, models.BoCandle, models.BoRun,
                  models.BoLevels, models.BoSetupSnapshot, models.BoEpisode,
                  models.BoAccount, models.BoPosition, models.BoTrade,
                  models.BoEquity):
        expected = {c.name: c.nullable for c in model.__table__.columns}
        assert created[model.__tablename__] == expected, model.__tablename__


def test_the_api_is_read_only() -> None:
    from app.labs.breakout.api import router

    methods = {m for route in router.routes for m in getattr(route, "methods", ())}
    assert methods <= {"GET", "HEAD", "OPTIONS"}, methods
    assert [r.path for r in router.routes] == [
        "/labs/breakout/health", "/labs/breakout/universe", "/labs/breakout/setups",
        "/labs/breakout/setups/{mint}", "/labs/breakout/episodes",
        "/labs/breakout/stats", "/labs/breakout/account", "/labs/breakout/positions",
        "/labs/breakout/trades", "/labs/breakout/equity",
        "/labs/breakout/trade_stats"]


def test_the_book_cannot_be_moved_over_http() -> None:
    """The read-only assertion above already proves it, but say it explicitly:
    there is no route that opens, closes or sizes a position. Trading is
    driven by the scheduled tick and the CLI, and nothing else."""
    from app.labs.breakout.api import router

    names = {getattr(r, "name", "") for r in router.routes}
    assert not (names & {"open", "close", "buy", "sell", "flatten", "reset_halt"})


def test_the_detection_modules_never_learn_a_network_exists() -> None:
    """Levels, momentum and the state machine read `data.py` and compute. If
    one of them grew an httpx import, a rate-limited candle pass could start
    silently changing what the setups say."""
    for name in PURE_MODULES:
        imported = imported_modules(ast.parse((PACKAGE / name).read_text()))
        leaked = {m for m in imported
                  if m.startswith(("httpx", "app.services",
                                   "app.labs.breakout.sources",
                                   "app.labs.breakout.universe",
                                   "app.labs.breakout.candles"))
                  and m != "app.labs.breakout.candles"}
        assert not leaked, f"{name} imports {leaked}"


# --- the flag -------------------------------------------------------------------

def test_trading_has_its_own_flag_and_it_defaults_off(monkeypatch) -> None:
    """Two flags, not one. Detection and recording are safe to run anywhere;
    opening positions is a separate decision, and a single switch would mean
    you could not have the watchlist without the book."""
    from app.labs.breakout import config

    monkeypatch.setenv("BREAKOUT_LAB_ENABLED", "true")
    monkeypatch.delenv("BREAKOUT_TRADING_ENABLED", raising=False)
    assert config.enabled() is True
    assert config.trading_enabled() is False
    monkeypatch.setenv("BREAKOUT_TRADING_ENABLED", "true")
    assert config.trading_enabled() is True


async def test_the_trader_tick_is_inert_while_either_flag_is_off(monkeypatch) -> None:
    from app.labs.breakout import scheduler

    monkeypatch.setenv("BREAKOUT_LAB_ENABLED", "true")
    monkeypatch.delenv("BREAKOUT_TRADING_ENABLED", raising=False)
    assert await scheduler.trader_tick() == {"skipped": "breakout_trading_disabled"}
    monkeypatch.delenv("BREAKOUT_LAB_ENABLED", raising=False)
    monkeypatch.setenv("BREAKOUT_TRADING_ENABLED", "true")
    assert await scheduler.trader_tick() == {"skipped": "breakout_lab_disabled"}


def test_the_flag_defaults_off(monkeypatch) -> None:
    from app.labs.breakout import config

    monkeypatch.delenv("BREAKOUT_LAB_ENABLED", raising=False)
    assert config.enabled() is False
    monkeypatch.setenv("BREAKOUT_LAB_ENABLED", "true")
    assert config.enabled() is True
    monkeypatch.setenv("BREAKOUT_LAB_ENABLED", "0")
    assert config.enabled() is False


async def test_the_tick_is_inert_while_the_flag_is_off(monkeypatch) -> None:
    """With the flag down every task returns before it opens a session or a
    socket. `BreakoutSource.__aenter__` is the only place a client is built;
    if it is entered, this fails."""
    from app.labs.breakout import scheduler
    from app.labs.breakout.sources import BreakoutSource

    async def boom(self):
        raise AssertionError("opened a network client with the flag off")

    monkeypatch.setattr(BreakoutSource, "__aenter__", boom)
    monkeypatch.delenv("BREAKOUT_LAB_ENABLED", raising=False)
    assert await scheduler.universe_tick() == {"skipped": "breakout_lab_disabled"}
    assert await scheduler.candles_tick() == {"skipped": "breakout_lab_disabled"}
    assert await scheduler.tick() == {"skipped": "breakout_lab_disabled"}


def test_nothing_is_enqueued_while_the_flag_is_off(monkeypatch) -> None:
    from app.labs.breakout import scheduler

    def boom(*a, **k):
        raise AssertionError("enqueued the candle task with the flag off")

    monkeypatch.setattr(scheduler.breakout_candles_tick, "delay", boom)
    monkeypatch.delenv("BREAKOUT_LAB_ENABLED", raising=False)
    scheduler.enqueue_candles()


async def test_health_answers_without_touching_the_database_while_off(monkeypatch) -> None:
    from app.labs.breakout.data import data_health

    monkeypatch.delenv("BREAKOUT_LAB_ENABLED", raising=False)
    assert await data_health(None) == {"running": False}  # type: ignore[arg-type]


# --- the schedule ---------------------------------------------------------------

def test_both_tasks_exist_and_only_the_tick_is_scheduled() -> None:
    """The candle pass runs by being enqueued from the universe pass. It has
    no beat entry of its own, so nothing can run it before its data exists."""
    from app.labs.breakout.scheduler import breakout_candles_tick, breakout_lab_tick
    from app.workers.celery_app import celery_app

    assert breakout_lab_tick.name == "app.labs.breakout.scheduler.breakout_lab_tick"
    assert breakout_candles_tick.name == (
        "app.labs.breakout.scheduler.breakout_candles_tick")
    assert celery_app.conf.beat_schedule["breakout-lab-tick"]["task"] == breakout_lab_tick.name
    assert not [k for k, e in celery_app.conf.beat_schedule.items()
                if e["task"] == breakout_candles_tick.name]


def test_the_beat_entry_runs_every_fifteen_minutes() -> None:
    from app.workers.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule["breakout-lab-tick"]["schedule"]
    assert set(schedule.minute) == {0, 15, 30, 45}


def test_every_beat_entry_resolves_to_a_registered_task() -> None:
    """The whole beat, not just this lab's: adding an `include` line that
    shadows or breaks another module would show up here and nowhere else."""
    from app.workers.celery_app import celery_app

    celery_app.loader.import_default_modules()
    unresolved = [(name, e["task"]) for name, e in celery_app.conf.beat_schedule.items()
                  if e["task"] not in celery_app.tasks]
    assert not unresolved, unresolved


def test_the_lab_scheduler_is_in_celery_include() -> None:
    """Without it the worker never imports the module, so the beat entry
    points at a task name nothing has registered."""
    from app.workers.celery_app import celery_app

    assert "app.labs.breakout.scheduler" in celery_app.conf.include


# --- the registration that lives outside this package ---------------------------

def test_alembic_can_see_the_lab_tables() -> None:
    """`alembic/env.py` imports `app.models` and nothing else. Until that
    package imports this lab's models, autogenerate sees three tables in the
    database and none in the model tree, and emits `drop_table` for each."""
    code = ("import app.models; from app.db.base import Base; import sys; "
            "sys.exit(0 if {'bo_candles', 'bo_episodes', 'bo_levels', "
            "'bo_setup_snapshots', 'bo_account', 'bo_positions', 'bo_trades', "
            "'bo_equity'} <= set(Base.metadata.tables) else 1)")
    proc = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, check=False)  # noqa: S603
    assert proc.returncode == 0


def test_the_router_is_mounted() -> None:
    """FastAPI includes routers lazily, so the paths are not on `api_router`
    until an app is built — the included router object itself is what the
    `include_router` line puts there."""
    from app.api.v1.router import api_router
    from app.labs.breakout import api as breakout_lab

    included = [getattr(r, "original_router", r) for r in api_router.routes]
    assert any(r is breakout_lab.router for r in included)
