"""The constraint that matters most: this tracker cannot touch anything else.

Source-parsing tests, as in the other labs, because "it does not touch the
existing screener" is a claim about every code path — including the ones no
test exercises.
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
TABLES = ["bt_candles", "bt_episode_events", "bt_episodes", "bt_index_closes",
          "bt_ingest_days", "bt_runs", "bt_states", "bt_universe"]

FORBIDDEN_MODULES = (
    "app.paper", "app.paper_v2", "app.karthik", "app.karthik_ops",
    "app.real_wallet", "app.real_wallet_safety", "app.lab", "app.arena",
    "app.strategy_lab", "app.radar", "app.models",
    # The other labs. Each owns its own tables and its own flag; importing one
    # from another is how two labs end up sharing a bug.
    "app.labs.breakout", "app.labs.rafiq", "app.labs.crypto_trend",
    "app.labs.early_movers",
    "app.services.market.service", "app.services.curve",
)
#: Pure modules. `bhavcopy.py` parses text; `levels.py`, `score.py`,
#: `states.py`, `outcomes.py` and `stats.py` are arithmetic over bars. None may
#: learn that a network or a database exists: a rate-limited fetch that could
#: change what a level says would make the replay unreproducible, and a state
#: machine that could read a return would not be a backtest.
PURE_MODULES = ("bhavcopy.py", "levels.py", "score.py", "states.py",
                "outcomes.py", "stats.py")


def migrations() -> list[pathlib.Path]:
    """Found by content, never by filename. Shipping a lab from one branch to
    another renumbers its migrations, and a hard-coded name would fail for a
    reason that has nothing to do with the lab."""
    hits = sorted(p for p in (BACKEND / "alembic" / "versions").glob("*.py")
                  if '"bt_' in p.read_text())
    assert hits, "no migration creates this lab's tables"
    return hits


def imported_modules(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
    return found


def test_the_tracker_imports_no_wallet_engine_or_other_lab() -> None:
    offenders = []
    for path in SOURCES:
        for module in imported_modules(ast.parse(path.read_text())):
            for banned in FORBIDDEN_MODULES:
                if module == banned or module.startswith(f"{banned}."):
                    offenders.append(f"{path.name} imports {module}")
    assert not offenders, offenders


def test_nothing_here_imports_a_broker_client() -> None:
    """The brief's hard rule: an unattended job must not depend on a token
    that expires daily. Asserted on IMPORTS rather than on the word appearing
    in the file — a docstring may say "Kite Connect", and a test that greps
    text would either fail on the docstring or be dodged by one."""
    banned = ("kiteconnect", "kite", "zerodha", "upstox", "angelbroking")
    offenders = []
    for path in SOURCES:
        for module in imported_modules(ast.parse(path.read_text())):
            root = module.split(".")[0].lower()
            if root in banned:
                offenders.append(f"{path.name} imports {module}")
    assert not offenders, offenders


def test_no_credential_is_read_anywhere_in_the_tracker() -> None:
    """Phases 1-2 are keyless by construction. The only environment variable
    this package reads is its own flag; anything else would be a dependency on
    something a human has to refresh."""
    reads = set()
    for path in SOURCES:
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("getenv", "environ")
                    and node.args and isinstance(node.args[0], ast.Constant)):
                reads.add(node.args[0].value)
    assert reads <= {"NSE_BREAKOUT_ENABLED"}, reads


@pytest.mark.parametrize("name", PURE_MODULES)
def test_a_pure_module_never_learns_a_network_or_a_database_exists(name) -> None:
    leaked = {m for m in imported_modules(ast.parse((PACKAGE / name).read_text()))
              if m.startswith(("httpx", "sqlalchemy", "app.db", "app.services",
                               "app.labs.nse_breakout.sources",
                               "app.labs.nse_breakout.ingest",
                               "app.labs.nse_breakout.models",
                               "app.labs.nse_breakout.data",
                               "app.labs.nse_breakout.episodes"))}
    assert not leaked, f"{name} imports {leaked}"


def test_every_table_carries_the_prefix_and_sits_on_the_platform_base() -> None:
    """On `app.db.base.Base` — the SAME object the platform's models use. A
    second `DeclarativeBase` hides these tables from alembic, which then emits
    `drop_table` for every one of them on the next autogenerate."""
    from app.db.base import Base as PlatformBase
    from app.labs.nse_breakout import models

    declared = {m for m in vars(models).values()
                if isinstance(m, type) and hasattr(m, "__tablename__")}
    assert sorted(m.__tablename__ for m in declared) == TABLES
    assert all(m.metadata is PlatformBase.metadata for m in declared)


def test_every_migration_is_purely_additive() -> None:
    created: list[str] = []
    for path in migrations():
        tree = ast.parse(path.read_text())
        upgrade = next(n for n in tree.body
                       if isinstance(n, ast.FunctionDef) and n.name == "upgrade")
        calls = [n for n in ast.walk(upgrade)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and isinstance(n.func.value, ast.Name) and n.func.value.id == "op"]
        ops = [n.func.attr for n in calls]
        assert ops, f"{path.name} does nothing"
        assert set(ops) <= {"create_table", "create_index", "add_column"}, \
            f"{path.name}: {ops}"
        created += [n.args[0].value for n in calls
                    if n.func.attr == "create_table"]
        # create_index's first argument is the index name, which also carries
        # the prefix, so one check covers both shapes.
        targets = [n.args[0].value for n in calls]
        assert all(t.startswith(("bt_", "ix_bt_", "uq_bt_")) for t in targets), \
            f"{path.name}: {targets}"
    assert sorted(created) == TABLES


def test_the_migration_matches_the_models() -> None:
    """Every column the models declare, the migration creates, with the same
    nullability — so `alembic check` has nothing to say once `app.models`
    imports them."""
    import sqlalchemy as sa

    from app.labs.nse_breakout import models

    created: dict[str, dict[str, bool]] = {}

    class Recorder:
        def create_table(self, name, *columns, **kw):
            created[name] = {c.name: c.nullable
                             for c in columns if isinstance(c, sa.Column)}

        def __repr__(self) -> str:
            return "<migration recorder>"

        def create_index(self, *a, **kw):
            pass

        def add_column(self, name, column, **kw):
            created[name][column.name] = column.nullable

    recorder = Recorder()
    for path in migrations():
        namespace: dict = {}
        exec(compile(path.read_text(), str(path), "exec"), namespace)  # noqa: S102
        namespace["op"] = recorder
        namespace["upgrade"]()

    for model in (models.BtUniverseMember, models.BtCandle, models.BtIndexClose,
                  models.BtIngestDay, models.BtRun, models.BtState,
                  models.BtEpisode, models.BtEpisodeEvent):
        expected = {c.name: c.nullable for c in model.__table__.columns}
        assert created[model.__tablename__] == expected, model.__tablename__


# --- the flag -------------------------------------------------------------------

def test_the_flag_defaults_off(monkeypatch) -> None:
    from app.labs.nse_breakout import config

    monkeypatch.delenv("NSE_BREAKOUT_ENABLED", raising=False)
    assert config.enabled() is False
    monkeypatch.setenv("NSE_BREAKOUT_ENABLED", "true")
    assert config.enabled() is True
    monkeypatch.setenv("NSE_BREAKOUT_ENABLED", "0")
    assert config.enabled() is False


@pytest.mark.parametrize("tick", ["ingest_tick", "backfill_tick"])
async def test_the_tick_is_inert_while_the_flag_is_off(monkeypatch, tick) -> None:
    """With the flag down every task returns before it opens a session or a
    socket. `NseArchive.__aenter__` is the only place a client is built; if it
    is entered, this fails."""
    from app.labs.nse_breakout import scheduler
    from app.labs.nse_breakout.sources import NseArchive

    async def boom(self):
        raise AssertionError("opened a network client with the flag off")

    monkeypatch.setattr(NseArchive, "__aenter__", boom)
    monkeypatch.delenv("NSE_BREAKOUT_ENABLED", raising=False)
    assert await getattr(scheduler, tick)() == {"skipped": "nse_breakout_disabled"}


# --- the schedule ---------------------------------------------------------------

def test_both_tasks_are_scheduled_at_the_exchange_s_cadence() -> None:
    """13:00 and 14:00 UTC are 18:30 and 19:30 IST — after the close, and
    again because the archive is occasionally late. 02:00 UTC is the next
    morning, for the day it was very late."""
    from app.labs.nse_breakout.scheduler import BACKFILL_TASK, INGEST_TASK
    from app.workers.celery_app import celery_app

    ingest = celery_app.conf.beat_schedule["nse-tracker-ingest"]
    assert ingest["task"] == INGEST_TASK
    assert set(ingest["schedule"].hour) == {13, 14, 2}
    assert set(ingest["schedule"].minute) == {0}

    backfill = celery_app.conf.beat_schedule["nse-tracker-backfill"]
    assert backfill["task"] == BACKFILL_TASK
    assert set(backfill["schedule"].minute) == {20}


def test_every_beat_entry_resolves_to_a_registered_task() -> None:
    """The whole beat, not just this lab's: an `include` line that shadows or
    breaks another module shows up here and nowhere else."""
    from app.workers.celery_app import celery_app

    celery_app.loader.import_default_modules()
    unresolved = [(name, e["task"])
                  for name, e in celery_app.conf.beat_schedule.items()
                  if e["task"] not in celery_app.tasks]
    assert not unresolved, unresolved


def test_the_scheduler_is_in_celery_include() -> None:
    """Without it the worker never imports the module, so the beat entry
    points at a task name nothing has registered."""
    from app.workers.celery_app import celery_app

    assert "app.labs.nse_breakout.scheduler" in celery_app.conf.include


# --- the registration that lives outside this package ---------------------------

def test_alembic_can_see_the_tracker_tables() -> None:
    """`alembic/env.py` imports `app.models` and nothing else. Until that
    package imports these models, autogenerate sees five tables in the database
    and none in the model tree, and emits `drop_table` for each."""
    code = ("import app.models; from app.db.base import Base; import sys; "
            f"sys.exit(0 if {set(TABLES)!r} <= set(Base.metadata.tables) else 1)")
    proc = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, check=False)  # noqa: S603
    assert proc.returncode == 0


def test_the_router_is_mounted() -> None:
    """FastAPI includes routers lazily, so the paths are not on `api_router`
    until an app is built — the included router object itself is what the
    `include_router` line puts there."""
    from app.api.v1.router import api_router
    from app.labs.nse_breakout import api as tracker

    included = [getattr(r, "original_router", r) for r in api_router.routes]
    assert any(r is tracker.router for r in included)


def test_the_phase_two_tasks_are_scheduled_after_the_data_they_read() -> None:
    """Detection is CHAINED to the ingest rather than given its own beat slot:
    a state evaluated against a bar the ingest has not stored yet would record
    yesterday's answer as today's. Outcomes and the replay are separate slots
    because neither depends on today's bar landing first."""
    from app.labs.nse_breakout.scheduler import (
        DETECT_TASK,
        OUTCOMES_TASK,
        REPLAY_TASK,
    )
    from app.workers.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    assert not [k for k, e in schedule.items() if e["task"] == DETECT_TASK], \
        "detection must be enqueued by the ingest, not scheduled beside it"
    assert schedule["nse-tracker-outcomes"]["task"] == OUTCOMES_TASK
    assert schedule["nse-tracker-replay"]["task"] == REPLAY_TASK


@pytest.mark.parametrize("tick", ["detect_tick", "outcomes_tick", "replay_tick"])
async def test_the_phase_two_ticks_are_inert_while_the_flag_is_off(
    monkeypatch, tick,
) -> None:
    from app.labs.nse_breakout import scheduler

    monkeypatch.delenv("NSE_BREAKOUT_ENABLED", raising=False)
    assert await getattr(scheduler, tick)() == {"skipped": "nse_breakout_disabled"}


@pytest.mark.parametrize("name", ["BACKFILL_DEADLINE_SECONDS",
                                  "REPLAY_DEADLINE_SECONDS",
                                  "OUTCOME_DEADLINE_SECONDS"])
def test_every_self_paced_pass_fits_inside_celery_s_soft_limit(name) -> None:
    """Every pass that manages its own budget, checked against Celery's OWN
    setting. One that overruns is killed before it commits, loses everything it
    walked, and — with `task_acks_late` — is handed straight back to do it all
    again."""
    from app.labs.nse_breakout import config
    from app.workers.celery_app import celery_app

    soft = celery_app.conf.task_soft_time_limit
    assert soft, "celery must impose a soft limit for this to mean anything"
    assert soft - getattr(config, name) >= 60, name


def test_the_replay_deadline_fits_inside_celery_s_soft_limit() -> None:
    """The same relationship the backfill has, asserted against Celery's own
    setting: a self-paced pass that overruns is killed before it commits and
    loses everything it walked."""
    from app.labs.nse_breakout import config
    from app.workers.celery_app import celery_app

    soft = celery_app.conf.task_soft_time_limit
    assert soft - config.REPLAY_DEADLINE_SECONDS >= 60


def test_nothing_that_decides_a_state_can_see_a_return() -> None:
    """The separation that makes the record a backtest rather than a story.

    `states.py` decides; the outcome columns are written by a different pass
    entirely. If the state machine ever imported `outcomes`, a rule could be
    written that reads what happened next — and every replayed statistic would
    become a description of its own answer.
    """
    imported = imported_modules(ast.parse((PACKAGE / "states.py").read_text()))
    assert "app.labs.nse_breakout.outcomes" not in imported
    assert "app.labs.nse_breakout.stats" not in imported
