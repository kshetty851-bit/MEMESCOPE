"""The Forex lab's computing core reads nothing but its arguments.

Research is only worth running if it is replayable: the same candles and the
same config must give the same trades on any machine on any day. A stray clock,
random number, environment read or network import in the core would make a
saved run impossible to reproduce - and a result that cannot be reproduced
cannot be checked.

Checked on the parse tree, not on the text, so prose about determinism cannot
fail a test about determinism. Same boundary as `test_btc_range_purity.py`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PACKAGE = Path(__file__).resolve().parents[4] / "app" / "labs" / "forex"

#: The pure modules. `providers.py` (network), `repository.py`, `service.py`,
#: `api.py`, `schemas.py` and `__main__.py` are the I/O seams and are
#: deliberately absent.
PURE_MODULES = (
    "types.py",
    "sessions.py",
    "indicators.py",
    "strategies.py",
    "engine.py",
    "data.py",
    "csv_import.py",
    "metrics.py",
    "research.py",
    "targets.py",
    "compare.py",
    "rng.py",
    "pipeline.py",
    "codec.py",
    "meta.py",
    "serialize.py",
    "jobs.py",
    "prose.py",
)

FORBIDDEN_ROOTS = {
    "fastapi",
    "starlette",
    "sqlalchemy",
    "httpx",
    "requests",
    "redis",
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
    "subprocess",
}
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
def test_the_core_imports_only_itself_from_the_app(name: str) -> None:
    """`app.core` would bring settings, and with them the environment, into a
    function that must depend on its arguments alone."""
    for module in _imports(name):
        if module.startswith("app"):
            assert module.startswith("app.labs.forex"), f"{name} imports {module}"


@pytest.mark.parametrize("name", PURE_MODULES)
def test_the_core_never_reads_a_clock(name: str) -> None:
    """Time is an input only through candles and `now` parameters."""
    for node in ast.walk(_tree(name)):
        if isinstance(node, ast.Attribute) and node.attr in CLOCK_ATTRIBUTES:
            owner = node.value
            owner_name = owner.id if isinstance(owner, ast.Name) else ""
            assert owner_name not in {"datetime", "date", "time"}, (
                f"{name} reads the clock: {owner_name}.{node.attr}"
            )


def test_the_checker_catches_what_it_claims_to() -> None:
    """A guard that cannot fail is not one."""
    tree = ast.parse("import random\nfrom datetime import datetime\nx = datetime.now()")
    modules = [n.names[0].name for n in ast.walk(tree) if isinstance(n, ast.Import)]
    assert "random" in modules and modules[0].split(".")[0] in FORBIDDEN_ROOTS
    attrs = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute)]
    assert attrs and attrs[0].attr in CLOCK_ATTRIBUTES
