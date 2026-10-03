"""Purity and isolation of the Meme Lifecycle Lab.

The Lab's claim is that a replay over the same stored rows always yields the
same events and the same paper trades. A module that reaches for a clock, a
database or a random number breaks that silently, so the boundary is asserted,
as for the paper wallet and the radar.

Isolation is the other half: the Lab never trades. ``REAL_TRADING`` is a
constant, and no module in the package — pure or I/O — may import a wallet,
a signer or the RPC layer. A strategy that cannot reach an execution path
cannot accidentally take one.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.lifecycle_lab import domain

pytestmark = pytest.mark.unit

PACKAGE = Path(__file__).resolve().parents[2] / "app" / "lifecycle_lab"

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

#: The package's deliberate I/O seams. Everything else is a pure engine. A
#: name appearing here because a *decision* moved into an I/O module would be
#: the boundary eroding, and is the thing to refuse.
IO_MODULES = {
    "repository.py",
    "service.py",
    "scheduler.py",
    "api.py",
    "schemas.py",
    "collector.py",
    "enrolment.py",
}

#: Pure modules outside the package the engines may reuse: the paper wallet's
#: simulation core and the lab's frozen execution model, both themselves pure.
ALLOWED_APP_MODULES = {"app.lifecycle_lab", "app.paper", "app.lab.execution"}

FORBIDDEN_EVERYWHERE = (
    "app.real_wallet",
    "app.real_wallet_safety",
    "solders",
    "app.services.rpc",
)


def _all_modules() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def _pure_modules() -> list[Path]:
    return sorted(
        path
        for path in _all_modules()
        if path.name not in IO_MODULES
        and path.name != "__init__.py"
        and "adapters" not in path.relative_to(PACKAGE).parts
    )


def _imports(path: Path) -> list[str]:
    """Absolute module names imported, including ``from x import y`` as both
    ``x`` and ``x.y`` (``from app import real_wallet`` must not slip by)."""
    tree = ast.parse(path.read_text())
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append(node.module)
            found.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def test_there_are_pure_modules_to_check() -> None:
    # A rename that empties the glob must fail loudly, not pass vacuously.
    names = {p.name for p in _pure_modules()}
    assert {"domain.py", "pit.py", "attention.py", "events.py", "timeliness.py"} <= names


@pytest.mark.parametrize("path", _pure_modules(), ids=lambda p: p.name)
def test_no_io_in_the_pure_core(path: Path) -> None:
    for module in _imports(path):
        assert module.split(".")[0] not in FORBIDDEN_ROOTS, f"{path.name} imports {module}"


@pytest.mark.parametrize("path", _pure_modules(), ids=lambda p: p.name)
def test_pure_core_reaches_only_for_pure_modules(path: Path) -> None:
    for module in _imports(path):
        if module != "app" and not module.startswith("app."):
            continue
        assert any(
            module == allowed or module.startswith(f"{allowed}.")
            for allowed in ALLOWED_APP_MODULES
        ), f"{path.name} imports {module}"


@pytest.mark.parametrize("path", _pure_modules(), ids=lambda p: p.name)
def test_pure_core_never_reads_a_clock(path: Path) -> None:
    """``now`` is always a parameter: a replay that asks the system for the
    time gives a different answer on every run."""
    source = path.read_text()
    for forbidden in ("datetime.now(", "utcnow(", "date.today("):
        assert forbidden not in source, f"{path.name} reads the clock: {forbidden}"


@pytest.mark.parametrize("path", _all_modules(), ids=lambda p: str(p.relative_to(PACKAGE)))
def test_no_module_can_reach_an_execution_path(path: Path) -> None:
    for module in _imports(path):
        for forbidden in FORBIDDEN_EVERYWHERE:
            assert module != forbidden and not module.startswith(f"{forbidden}."), (
                f"{path.name} imports {module}"
            )


def test_real_trading_is_off() -> None:
    assert domain.REAL_TRADING is False
