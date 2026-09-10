"""The constraint that matters most: this lab cannot touch anything else.

Two of these are source-parsing tests rather than behavioural ones, and that is
deliberate. "The lab never writes to the paper wallet" is a claim about every
code path including the ones no test exercises, so the honest way to hold it is
to assert that the code to do it does not exist — an AST walk over the whole
package, not a fixture that happens not to trigger it.
"""

from __future__ import annotations

import ast
import pathlib

PACKAGE = pathlib.Path(__file__).resolve().parent.parent
SOURCES = sorted(p for p in PACKAGE.rglob("*.py") if "tests" not in p.parts)

#: Every subsystem whose storage this lab must never reach.
FORBIDDEN_MODULES = (
    "app.paper", "app.paper_v2", "app.karthik", "app.karthik_ops",
    "app.real_wallet", "app.real_wallet_safety", "app.lab", "app.arena",
    "app.strategy_lab", "app.models.paper", "app.models.paper_v2",
    "app.models.karthik", "app.models.lab", "app.models.arena",
    "app.models.strategy_lab", "app.models.real_wallet_execution",
)

#: The one module allowed to know the shared schema exists.
FEED = "feed.py"


def imported_modules(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
    return found


def test_the_lab_imports_no_other_engine() -> None:
    """Not one module of the paper, Karthik, real-wallet or V6 lab engines."""
    offenders = []
    for path in SOURCES:
        for module in imported_modules(ast.parse(path.read_text())):
            for banned in FORBIDDEN_MODULES:
                if module == banned or module.startswith(f"{banned}."):
                    offenders.append(f"{path.name} imports {module}")
    assert not offenders, offenders


def test_only_the_feed_imports_a_shared_model() -> None:
    """One module knows the shared schema exists, so 'read-only' is checkable
    in one file rather than five.

    This asserts on IMPORTS, not on the text of the file. An earlier version
    grepped for table names and failed on a docstring that merely mentioned
    one — a test that reads prose instead of behaviour.
    """
    for path in SOURCES:
        if path.name == FEED:
            continue
        leaked = {m for m in imported_modules(ast.parse(path.read_text()))
                  if m.startswith("app.models")}
        assert not leaked, f"{path.name} imports {leaked}"


def test_the_feed_reads_only_the_four_documented_models() -> None:
    """A widening of the feed's reach has to be a deliberate edit here."""
    imported = imported_modules(ast.parse((PACKAGE / FEED).read_text()))
    assert {m for m in imported if m.startswith("app.models")} == {
        "app.models.market", "app.models.radar", "app.models.token",
        "app.models.research_data", "app.models.token_security"}


def test_the_feed_issues_no_write() -> None:
    """`select` only. No insert, update, delete, add or merge anywhere in the
    module that touches shared tables."""
    text = (PACKAGE / "feed.py").read_text()
    for verb in ("insert(", "update(", "delete(", ".add(", ".merge(",
                 ".flush(", ".commit("):
        assert verb not in text, f"feed.py contains {verb}"


def test_the_service_writes_only_lab_models() -> None:
    """`service.py` may write, but only rows of the lab's own three models."""
    tree = ast.parse((PACKAGE / "service.py").read_text())
    added = [
        node.args[0].func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and node.func.attr == "add"
        and node.args and isinstance(node.args[0], ast.Call)
        and isinstance(node.args[0].func, ast.Name)
    ]
    assert added, "expected the service to add rows"
    assert all(name.startswith("RafiqLab") for name in added), added


def test_lab_tables_are_visible_to_the_platform_metadata() -> None:
    """The lab's tables must be IN `app.models.Base.metadata`.

    This reads backwards for an isolation test and is the most important
    assertion in the file. A separate metadata was tried first; it meant
    autogenerate saw three tables in the database and none in the model tree,
    and emitted `drop_table` for each. A schema tool that would delete the
    ledger is not isolation, it is a loaded gun.
    """
    from app.models import Base as PlatformBase

    assert {t for t in PlatformBase.metadata.tables if t.startswith("rafiq")} == {
        "rafiq_lab_strategies", "rafiq_lab_positions", "rafiq_lab_daily_state"}


def test_every_lab_table_carries_the_prefix() -> None:
    """And nothing the lab declares escapes the namespace."""
    from app.labs.rafiq import models
    from app.models import Base as PlatformBase

    declared = {m.__tablename__ for m in vars(models).values()
                if isinstance(m, type) and hasattr(m, "__tablename__")}
    assert declared, "expected the lab to declare tables"
    assert all(t.startswith("rafiq_lab_") for t in declared), declared
    assert declared <= set(PlatformBase.metadata.tables)


def test_the_migration_is_purely_additive() -> None:
    """No ALTER, no DROP of anything that existed before it. A database that
    runs this migration and never enables the flag is byte-identical in every
    pre-existing table."""
    # Found by glob, not by name. The revision number depends on which chain
    # this branch sits on — it is 0056 where the lab was written and 0063 where
    # it was replayed onto a diverged main — and a test that hardcodes one of
    # them fails on the other branch for no reason anyone cares about.
    matches = sorted((PACKAGE.parents[2] / "alembic" / "versions")
                     .glob("*_rafiq_lab.py"))
    assert len(matches) == 1, f"expected exactly one rafiq migration, got {matches}"
    tree = ast.parse(matches[0].read_text())
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
    assert all(t.startswith("rafiq_lab_") for t in targets), targets


def test_the_api_is_read_only() -> None:
    """No POST, PUT, PATCH or DELETE route exists to be called."""
    from app.labs.rafiq.api import router
    methods = {m for route in router.routes for m in getattr(route, "methods", ())}
    assert methods <= {"GET", "HEAD", "OPTIONS"}, methods


def test_the_flag_defaults_off(monkeypatch) -> None:
    from app.labs.rafiq import config
    monkeypatch.delenv("RAFIQ_LAB_ENABLED", raising=False)
    assert config.enabled() is False
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    assert config.enabled() is True
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "0")
    assert config.enabled() is False


def test_the_beat_registration_resolves() -> None:
    """The task named in `beat_schedule` must be a task that exists.

    A beat entry pointing at a typo does not fail at import — it fails once a
    minute, in a worker log nobody is reading. This is the cheapest place to
    find out.
    """
    from app.workers.celery_app import celery_app

    celery_app.loader.import_default_modules()
    entry = celery_app.conf.beat_schedule["rafiq-lab-tick"]
    assert entry["task"] == "app.labs.rafiq.scheduler.rafiq_lab_tick"
    assert entry["task"] in celery_app.tasks
    # And nothing else on the beat was broken by adding it.
    unresolved = [e["task"] for e in celery_app.conf.beat_schedule.values()
                  if e["task"] not in celery_app.tasks]
    assert not unresolved, unresolved


async def test_the_beat_task_is_inert_while_the_flag_is_off(monkeypatch) -> None:
    """Registering the beat must not be the same as starting the lab.

    With the flag down `tick` returns before it opens a session at all, so a
    worker running this every minute touches no database.
    """
    from app.labs.rafiq.scheduler import tick

    monkeypatch.delenv("RAFIQ_LAB_ENABLED", raising=False)
    assert await tick() == {"skipped": "rafiq_lab_disabled"}


def test_safety_mapping_covers_the_real_enum() -> None:
    """The feed's safety mapping must use the platform's actual spellings.

    This is the one place the lab hard-codes a string it does not own. It got
    it wrong once — it looked for "PASSED" where MEMESCOPE emits "VERIFIED" —
    and the failure was silent in the worst way: every verdict fell through to
    UNKNOWN, which the consensus gate treats as absent, so Strategy E's
    mandatory safety stream could never confirm and E entered nothing at all.
    Nothing crashed and no test failed. Hence this one.
    """
    import re

    from app.security.contract import SecurityStatus

    source = (PACKAGE / FEED).read_text()
    mapping = re.search(r'safety = \{(.*?)\}\.get', source, re.S)
    assert mapping, "the safety mapping moved; update this test with it"
    mapped = set(re.findall(r'"([A-Z_]+)"', mapping.group(1)))

    members = {m.value for m in SecurityStatus}
    # Every status the platform can emit is either mapped or is the one that
    # deliberately falls through.
    assert mapped <= members, f"maps statuses that do not exist: {mapped - members}"
    assert SecurityStatus.VERIFIED.value in mapped, "the pass state must be mapped"
    assert SecurityStatus.FAILED.value in mapped, "the fail state must be mapped"
    assert members - mapped == {SecurityStatus.UNKNOWN.value}, (
        "only UNKNOWN may fall through to the default")
