"""The Lab is research instrumentation and must never be able to move money.

Parses the package's own source rather than trusting a convention: a Lab
failure must not be able to disturb paper, karthik or real-wallet accounting,
and the boundary is worth enforcing mechanically because it is invisible in a
diff. Mirrors `test_arena_isolation.py`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

LAB = Path(__file__).resolve().parents[2] / "app" / "lab"
FORBIDDEN_PREFIXES = ("app.paper", "app.karthik", "app.real_wallet",
                      "app.models.paper", "app.models.karthik",
                      "app.models.real_wallet", "app.universe")
FORBIDDEN_NAMES = ("PaperWallet", "PaperPosition", "KarthikWallet",
                   "KarthikPosition", "RealWallet")


def _sources():
    return sorted(LAB.glob("*.py"))


def test_the_package_exists_and_has_files():
    assert _sources(), "app/lab must contain source"


@pytest.mark.parametrize("path", _sources(), ids=lambda p: p.name)
def test_no_money_moving_imports(path: Path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith(FORBIDDEN_PREFIXES), \
                f"{path.name} imports {node.module}"
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(FORBIDDEN_PREFIXES), \
                    f"{path.name} imports {alias.name}"


@pytest.mark.parametrize("path", _sources(), ids=lambda p: p.name)
def test_no_money_moving_names(path: Path):
    text = path.read_text()
    for name in FORBIDDEN_NAMES:
        assert name not in text, f"{path.name} references {name}"


@pytest.mark.parametrize("path", _sources(), ids=lambda p: p.name)
def test_lab_writes_only_lab_tables(path: Path):
    """Every model the Lab constructs must be a Lab model."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "app.models.lab":
            for alias in node.names:
                assert alias.name.startswith("Lab"), alias.name


BANNED_MODULES = ("random", "app.core.config", "app.db")


@pytest.mark.parametrize("name", ("spec.py", "rules.py", "execution.py"))
def test_rules_and_spec_are_pure(name: str):
    """No clock, no randomness, no settings inside the frozen rule modules —
    a decision that cannot be replayed cannot be checked.

    Checked on the parse tree, not on the text: prose about determinism must
    not be able to fail a test about determinism.
    """
    tree = ast.parse((LAB / name).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(BANNED_MODULES), alias.name
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith(BANNED_MODULES), node.module
        # `datetime.now(...)` / `settings.X` reads are the two impure calls
        # these modules could plausibly acquire.
        if isinstance(node, ast.Attribute) and node.attr == "now":
            raise AssertionError(f"{name} reads a clock")
        if isinstance(node, ast.Name) and node.id == "settings":
            raise AssertionError(f"{name} reads settings")
