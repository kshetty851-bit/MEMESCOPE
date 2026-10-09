"""The BTC Range Lab is paper only, and must not be able to become anything else.

Parses the package's source rather than trusting a convention. The lab has no
wallet, no order router and no key: this keeps it that way mechanically, because
the boundary is invisible in a diff and a stray import is how it would erode.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PACKAGE = Path(__file__).resolve().parents[2] / "app" / "labs" / "btc_range"

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
    assert {p.name for p in _sources()} >= {"api.py", "service.py", "schemas.py", "prose.py"}


@pytest.mark.parametrize("path", _sources(), ids=lambda p: p.name)
def test_no_wallet_or_money_moving_imports(path: Path) -> None:
    for module in _imported_modules(ast.parse(path.read_text())):
        assert not _forbidden(module), f"{path.name} imports {module}"


def test_the_checker_catches_what_it_claims_to() -> None:
    """A guard that cannot fail is not one."""
    assert _forbidden("app.paper.service")
    assert _forbidden("solders.keypair")
    assert _forbidden("app.lab.models")
    assert not _forbidden("app.labs.btc_range.engine")
    assert not _forbidden("app.labs.graduation")


def _routes() -> list[tuple[str, str]]:
    """(HTTP method, path) for every route decorator in api.py."""
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


def test_api_declares_only_gets_and_the_one_backtest_post() -> None:
    routes = _routes()
    assert routes, "api.py declares no routes"
    posts = [path for method, path in routes if method != "get"]
    assert posts == ["/backtest"], routes
    assert [m for m, _ in routes if m not in {"get", "post"}] == []
    assert sorted(path for method, path in routes if method == "get") == [
        "/config", "/monthly", "/status"]


def test_api_writes_no_sql() -> None:
    """`api/` never writes SQL: it reaches the database through the service."""
    modules = _imported_modules(ast.parse((PACKAGE / "api.py").read_text()))
    assert not [m for m in modules if m == "sqlalchemy" or m.startswith("sqlalchemy.")]
    assert "app.labs.btc_range.repository" not in modules


def test_service_never_imports_fastapi() -> None:
    modules = _imported_modules(ast.parse((PACKAGE / "service.py").read_text()))
    assert not [m for m in modules if m.split(".")[0] in {"fastapi", "starlette"}]


@pytest.mark.parametrize("name", ("service.py", "schemas.py", "bounds.py", "prose.py"))
def test_nothing_in_the_request_path_commits(name: str) -> None:
    """`get_db` owns the transaction; the lab's request path only reads."""
    tree = ast.parse((PACKAGE / name).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"commit", "add", "add_all", "delete"}, (
                f"{name} calls .{node.attr}"
            )
