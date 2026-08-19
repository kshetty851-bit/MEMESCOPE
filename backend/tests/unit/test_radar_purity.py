"""Purity constraints for the Radar engine.

The same boundary `test_scoring_purity.py` enforces for the scoring engine, for
the same reasons: no database, no network, no clock, no randomness. Those
properties are what make the track record auditable — a score recorded a month
ago can be recomputed exactly from the stored series — and what keeps these
tests fixture-free.

A stray import would remove all of that quietly, so the boundary is asserted.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PACKAGE = Path(__file__).resolve().parents[2] / "app" / "radar"

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

#: The Radar's deliberate I/O seams. `repository.py` owns canonical database
#: access, `quality.py` owns isolated research-ledger I/O, `service.py`
#: orchestrates, `scheduler.py` is the Celery entry point, and `api.py` is HTTP.
#: Everything else stays pure.
IO_MODULES = {
    "repository.py",
    "quality.py",
    "service.py",
    "scheduler.py",
    "api.py",
    "schemas.py",
}

#: Modules outside the package the pure engine may reach for.
ALLOWED_APP_MODULES = {"app.radar"}


def _pure_modules() -> list[Path]:
    return sorted(
        path
        for path in PACKAGE.rglob("*.py")
        if path.name not in IO_MODULES and path.name != "__init__.py"
    )


def test_there_are_pure_modules_to_check() -> None:
    # Guards against the suite silently passing because a rename emptied the
    # glob — a green test that checks nothing is worse than a red one.
    assert len(_pure_modules()) >= 8


@pytest.mark.parametrize("module", _pure_modules(), ids=lambda p: p.name)
def test_pure_module_imports_nothing_that_implies_io(module: Path) -> None:
    tree = ast.parse(module.read_text(), filename=str(module))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root not in FORBIDDEN_ROOTS, f"{module.name} imports {alias.name}"
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            assert root not in FORBIDDEN_ROOTS, f"{module.name} imports from {node.module}"
            if root == "app":
                allowed = any(node.module.startswith(prefix) for prefix in ALLOWED_APP_MODULES)
                assert allowed, f"{module.name} reaches outside the package: {node.module}"


@pytest.mark.parametrize("module", _pure_modules(), ids=lambda p: p.name)
def test_pure_module_never_reads_a_clock(module: Path) -> None:
    """`datetime.now()` and `utcnow()` are the subtle way purity is lost.

    A module that reads the clock cannot be replayed: the same stored series
    would score differently tomorrow, and the track record's central claim —
    that a recorded score is reproducible — would quietly stop being true.
    Time enters the engine as an explicit `now` argument instead.
    """
    tree = ast.parse(module.read_text(), filename=str(module))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {
                "now",
                "utcnow",
                "today",
            }, f"{module.name} reads the clock via .{node.func.attr}()"
