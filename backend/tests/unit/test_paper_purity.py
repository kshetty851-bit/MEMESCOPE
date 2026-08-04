"""Purity constraints for the paper wallet's simulation core.

The same boundary `test_radar_purity.py` enforces, and here it is the product
claim rather than a style preference: a simulation that reaches for a clock, a
database or a random number is not reproducible, and a track record that cannot
be reproduced is an anecdote.

A stray import would remove that quietly, so the boundary is asserted.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PACKAGE = Path(__file__).resolve().parents[2] / "app" / "paper"

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

#: The package's deliberate I/O seams. `repository.py` owns database access,
#: `service.py` orchestrates, `scheduler.py` is the Celery entry point and
#: `api.py` is HTTP. Everything else stays pure — adding a fifth name here
#: would mean the boundary had eroded.
IO_MODULES = {"repository.py", "service.py", "scheduler.py", "api.py", "schemas.py"}

#: Modules outside the package the pure core may reach for. Deliberately only
#: itself: the strategy takes a signal type as a plain string rather than
#: importing `app.opportunities`, precisely so this stays a single entry.
ALLOWED_APP_MODULES = {"app.paper"}


def _pure_modules() -> list[Path]:
    return sorted(
        path
        for path in PACKAGE.rglob("*.py")
        if path.name not in IO_MODULES and path.name != "__init__.py"
    )


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return found


def test_there_are_pure_modules_to_check() -> None:
    # Guards against the suite silently passing because a rename emptied the
    # glob — a green test that checks nothing is worse than a red one.
    assert len(_pure_modules()) >= 4


@pytest.mark.parametrize("path", _pure_modules(), ids=lambda path: path.name)
def test_no_io_in_the_simulation_core(path: Path) -> None:
    for module in _imports(path):
        root = module.split(".")[0]
        assert root not in FORBIDDEN_ROOTS, f"{path.name} imports {module}"


@pytest.mark.parametrize("path", _pure_modules(), ids=lambda path: path.name)
def test_the_core_reaches_only_for_itself(path: Path) -> None:
    for module in _imports(path):
        if not module.startswith("app."):
            continue
        assert any(
            module == allowed or module.startswith(f"{allowed}.")
            for allowed in ALLOWED_APP_MODULES
        ), f"{path.name} imports {module}"


@pytest.mark.parametrize("path", _pure_modules(), ids=lambda path: path.name)
def test_the_core_never_reads_a_clock(path: Path) -> None:
    """`now` is always a parameter.

    A simulation that asks the system what time it is produces a different
    answer on every run, which is exactly the failure this package exists to
    avoid: the same stored rows must always yield the same trades.
    """
    source = path.read_text()
    for forbidden in ("datetime.now(", "datetime.utcnow(", "date.today("):
        assert forbidden not in source, f"{path.name} reads the clock: {forbidden}"
