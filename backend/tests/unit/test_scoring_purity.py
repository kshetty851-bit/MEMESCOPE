"""Purity constraints, enforced rather than assumed.

The engine's value comes from what it *cannot* do: no database, no network, no
clock, no randomness. Those properties are what make backfill exact, shadow
evaluation possible, and these tests fixture-free. A stray import would take all
of that away quietly, so the boundary is asserted here.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PACKAGE = Path(__file__).resolve().parents[2] / "app" / "services" / "scoring"

#: Anything that implies I/O, a framework, or a shared runtime.
FORBIDDEN_ROOTS = {
    "fastapi",
    "starlette",
    "redis",
    "sqlalchemy",
    "httpx",
    "requests",
    "celery",
    "asyncio",
    "socket",
    "random",
    "secrets",
    "time",
}

#: The package's deliberate I/O seams, mirroring the market package's split:
#: `service.py` is the write path owned by the enrichment worker, and
#: `query_service.py` is the read path owned by the API. Everything else stays
#: pure, so the engine remains testable without fixtures and relocatable without
#: a refactor. Adding a third name here would mean that boundary had eroded.
IO_MODULES = {"service.py", "query_service.py"}

#: Modules outside the package the engine is allowed to reach for, each for a
#: documented reason. Extending this set is a design decision, not a detail.
ALLOWED_APP_MODULES = {
    # `ScoreGrade` - the persisted enum, imported so grading cannot drift from
    # the column it is written to. An enum, not a session.
    "app.models.score",
    # `SchedulePolicy` - the single source of truth for refresh cadence, used to
    # derive tier-relative windows. A frozen dataclass, not the service.
    "app.services.market.scheduler",
    # Default window sizes and the active model version.
    "app.core.config",
}


def _modules() -> list[Path]:
    """Every module expected to be pure - that is, all but the I/O seam."""
    return sorted(path for path in PACKAGE.rglob("*.py") if path.name not in IO_MODULES)


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_the_package_has_modules_to_check() -> None:
    """Guards against the sweep silently passing on an empty glob."""
    assert len(_modules()) >= 15


def test_the_io_seams_are_exactly_the_named_two() -> None:
    """The exemption must stay a short, explicit list.

    If a third module starts talking to the database, the property that makes
    the engine backfillable and fixture-free has been lost - and it would be
    lost quietly, which is why it is asserted rather than trusted.
    """
    assert {"service.py", "query_service.py"} == IO_MODULES
    for name in IO_MODULES:
        assert (PACKAGE / name).exists()


@pytest.mark.parametrize("name", sorted(IO_MODULES))
def test_no_io_seam_commits(name: str) -> None:
    """They write and read; the caller decides when a write becomes durable.

    Committing inside would take the transaction boundary away from the
    enrichment worker, which is the only component that knows what belongs in
    one unit of work.
    """
    source = (PACKAGE / name).read_text()
    assert "session.commit()" not in source
    assert "session.rollback()" not in source


@pytest.mark.parametrize("name", sorted(IO_MODULES))
def test_no_io_seam_publishes(name: str) -> None:
    """Events are published after commit, by the caller, never from inside."""
    source = (PACKAGE / name).read_text()
    assert "publish_score" not in source
    assert "get_redis" not in source


def test_the_read_path_never_writes() -> None:
    """The API must have no route that can trigger an evaluation.

    That is the whole reason the read and write paths are separate services, so
    it is worth asserting rather than leaving to review.
    """
    source = (PACKAGE / "query_service.py").read_text()
    for forbidden in ("upsert_many", "add_many", "session.add(", "evaluate("):
        assert forbidden not in source, f"query_service.py calls {forbidden}"


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_no_module_imports_io_or_a_framework(path: Path) -> None:
    for name in _imported_names(path):
        root = name.split(".")[0]
        assert root not in FORBIDDEN_ROOTS, f"{path.name} imports {name}"


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_reaches_outside_the_package_only_where_documented(path: Path) -> None:
    for name in _imported_names(path):
        if not name.startswith("app."):
            continue
        if name.startswith("app.services.scoring"):
            continue
        assert name in ALLOWED_APP_MODULES, f"{path.name} imports {name}"


def test_the_engine_itself_reads_no_settings() -> None:
    """Tunables reach `evaluate()` as arguments, never as ambient config.

    Without this, two processes on different configuration would produce
    different scores from identical stored data - and the reproducibility
    contract would be untestable.
    """
    engine = PACKAGE / "engine.py"
    assert "app.core.config" not in engine.read_text()


def test_nothing_reads_the_clock() -> None:
    """Time enters only as `FeatureSet.evaluated_at`, supplied by the caller."""
    for path in _modules():
        source = path.read_text()
        for forbidden in ("datetime.now(", "datetime.utcnow(", "time.time("):
            assert forbidden not in source, f"{path.name} reads the clock"
