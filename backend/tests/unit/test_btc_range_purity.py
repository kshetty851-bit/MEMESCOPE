"""Purity constraints for the BTC range lab's strategy engine.

The same boundary `test_paper_purity.py` enforces, and here it is the product
claim: the live paper book is a replay of `run_backtest` over stored candles,
so the book and a backtest agree only while the engine reads nothing but its
arguments. A stray clock, random number, settings read or database import would
make the same candles yield different trades on different days, and the record
could no longer be reproduced.

Checked on the parse tree, not on the text, so prose about determinism cannot
fail a test about determinism.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PACKAGE = Path(__file__).resolve().parents[2] / "app" / "labs" / "btc_range"

#: The pure modules. `source.py`, `ingest.py` and `repository.py` are the I/O
#: seams (exchange read, candle writes, database) and are deliberately absent.
PURE_MODULES = ("types.py", "engine.py", "execution.py")

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
    "os",
    "pathlib",
    "logging",
    "structlog",
}

#: The only app modules the pure core may reach for: its own contract and
#: engine. Importing `app.core` would bring settings, and with them the
#: environment, into a function that must depend on its arguments alone.
ALLOWED_APP_MODULES = {"app.labs.btc_range.types", "app.labs.btc_range.engine"}

CLOCK_ATTRIBUTES = {"now", "utcnow", "today", "time", "monotonic", "perf_counter"}


def _tree(name: str) -> ast.AST:
    return ast.parse((PACKAGE / name).read_text())


def _imports(name: str) -> list[str]:
    found: list[str] = []
    for node in ast.walk(_tree(name)):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return found


def test_the_pure_modules_exist() -> None:
    # A rename must not turn this file into a green test that checks nothing.
    for name in PURE_MODULES:
        assert (PACKAGE / name).is_file(), name


@pytest.mark.parametrize("name", PURE_MODULES)
def test_no_io_imports(name: str) -> None:
    for module in _imports(name):
        assert module.split(".")[0] not in FORBIDDEN_ROOTS, f"{name} imports {module}"


@pytest.mark.parametrize("name", PURE_MODULES)
def test_the_core_reaches_only_for_its_own_contract(name: str) -> None:
    for module in _imports(name):
        if module.startswith("app"):
            assert module in ALLOWED_APP_MODULES, f"{name} imports {module}"


@pytest.mark.parametrize("name", PURE_MODULES)
def test_the_core_never_reads_a_clock(name: str) -> None:
    """`now` is not a parameter here because time is not an input at all:
    every timestamp comes from a candle, so there is nothing to ask the system."""
    for node in ast.walk(_tree(name)):
        if isinstance(node, ast.Attribute) and node.attr in CLOCK_ATTRIBUTES:
            owner = node.value
            owner_name = owner.id if isinstance(owner, ast.Name) else ""
            assert owner_name not in {"datetime", "date", "time"}, (
                f"{name} reads the clock: {owner_name}.{node.attr}"
            )


@pytest.mark.parametrize("name", PURE_MODULES)
def test_no_floats(name: str) -> None:
    """Money and prices are Decimal; a float literal or `float()` is a precision leak."""
    for node in ast.walk(_tree(name)):
        if isinstance(node, ast.Constant):
            assert not isinstance(node.value, float), f"{name} has a float literal"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "float", f"{name} calls float()"
