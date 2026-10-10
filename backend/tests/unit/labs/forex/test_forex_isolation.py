"""The Forex lab is research and paper only, and must not be able to become
anything else.

Parses the package's source rather than trusting a convention: the lab has no
broker, no order router and no key, and this keeps it that way mechanically,
because the boundary is invisible in a diff and a stray import is how it would
erode.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PACKAGE = Path(__file__).resolve().parents[4] / "app" / "labs" / "forex"

#: Matched as `name` or `name.<anything>`, never by raw prefix: `app.lab` is the
#: research Lab, and a prefix match would also (wrongly) forbid `app.labs`.
FORBIDDEN = (
    "app.paper",
    "app.karthik",
    "app.real_wallet",
    "app.real_wallet_safety",
    "app.lab",
    "app.copycontrol",
    "app.universe",
    "solders",
)


def _sources() -> list[Path]:
    return sorted(PACKAGE.glob("*.py"))


def _forbidden(module: str) -> bool:
    return any(module == f or module.startswith(f + ".") for f in FORBIDDEN)


def _imported_modules(tree: ast.AST) -> list[str]:
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.append(node.module)
            # `from app import paper` names the module in the alias.
            out.extend(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            out.extend(alias.name for alias in node.names)
    return out


def test_the_package_has_source() -> None:
    names = {p.name for p in _sources()}
    assert names >= {"api.py", "service.py", "schemas.py", "prose.py", "repository.py"}


@pytest.mark.parametrize("path", _sources(), ids=lambda p: p.name)
def test_no_wallet_or_money_moving_imports(path: Path) -> None:
    for module in _imported_modules(ast.parse(path.read_text())):
        assert not _forbidden(module), f"{path.name} imports {module}"


def test_the_checker_catches_what_it_claims_to() -> None:
    """A guard that cannot fail is not one."""
    assert _forbidden("app.paper.service")
    assert _forbidden("solders.keypair")
    assert _forbidden("app.lab.models")
    assert not _forbidden("app.labs.forex.engine")
    assert not _forbidden("app.labs.graduation")


def _routes() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for node in ast.walk(ast.parse((PACKAGE / "api.py").read_text())):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for deco in node.decorator_list:
            if (
                isinstance(deco, ast.Call)
                and isinstance(deco.func, ast.Attribute)
                and isinstance(deco.func.value, ast.Name)
                and deco.func.value.id == "router"
            ):
                path = deco.args[0]
                assert isinstance(path, ast.Constant)
                found.append((deco.func.attr, str(path.value)))
    return found


def test_the_api_declares_exactly_the_documented_routes() -> None:
    assert sorted(_routes()) == sorted(
        [
            ("get", "/meta"),
            ("get", "/data"),
            ("get", "/data/quality"),
            ("post", "/data/import"),
            ("post", "/data/fetch"),
            ("post", "/runs"),
            ("get", "/runs"),
            ("get", "/runs/{run_id}"),
            ("get", "/runs/{run_id}/trades.csv"),
            ("get", "/versions"),
            ("post", "/versions"),
        ]
    )


def test_no_route_can_update_or_delete() -> None:
    """Candles and versions are append-only; a run is never edited from outside."""
    assert {m for m, _ in _routes()} <= {"get", "post"}


def test_api_writes_no_sql() -> None:
    """`api/` never writes SQL: it reaches the database through the service."""
    modules = _imported_modules(ast.parse((PACKAGE / "api.py").read_text()))
    assert not [m for m in modules if m == "sqlalchemy" or m.startswith("sqlalchemy.")]
    assert "app.labs.forex.repository" not in modules


def test_service_never_imports_fastapi() -> None:
    modules = _imported_modules(ast.parse((PACKAGE / "service.py").read_text()))
    assert not [m for m in modules if m.split(".")[0] in {"fastapi", "starlette"}]


@pytest.mark.parametrize("name", ("repository.py",))
def test_repositories_flush_and_never_commit(name: str) -> None:
    """`get_db` owns the request's transaction (CLAUDE.md)."""
    tree = ast.parse((PACKAGE / name).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"commit", "rollback"}, f"{name} calls .{node.attr}"


def test_only_the_background_runner_commits_in_the_service() -> None:
    """Request-path functions never commit. The only commit lives in
    `_checkpoint`, which the job runner owns (CLAUDE.md: workers own their own
    sessions and commit explicitly)."""
    tree = ast.parse((PACKAGE / "service.py").read_text())
    committers: list[str] = []
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            for node in ast.walk(fn):
                if isinstance(node, ast.Attribute) and node.attr in {"commit", "rollback"}:
                    committers.append(fn.name)
    assert set(committers) <= {"_checkpoint", "execute_run"}, committers
