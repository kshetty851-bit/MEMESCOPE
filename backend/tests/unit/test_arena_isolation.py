"""The Arena may never reach production wallet accounting.

Parsed from source rather than asserted in prose: an Arena failure must not be
able to disturb the paper wallet, the Karthik wallet or the real wallet, and a
future edit that imports one of them fails here.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PACKAGE = Path(__file__).resolve().parents[2] / "app" / "arena"
FORBIDDEN = ("app.paper", "app.karthik", "app.real_wallet", "app.models.paper",
             "app.models.karthik", "app.models.real_wallet")


def _modules():
    return sorted(PACKAGE.rglob("*.py"))


def test_there_are_arena_modules_to_check():
    assert len(_modules()) >= 4


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_no_arena_module_imports_a_wallet(path):
    tree = ast.parse(path.read_text())
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    offenders = [m for m in imported if any(m.startswith(f) for f in FORBIDDEN)]
    assert not offenders, f"{path.name} imports production wallet code: {offenders}"


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_no_arena_module_writes_a_production_table(path):
    text = path.read_text()
    for table in ("paper_positions", "paper_wallets", "karthik_positions",
                  "karthik_wallets", "real_wallet"):
        assert table not in text, f"{path.name} references {table}"


def test_rules_module_is_pure():
    """No I/O, no clock, no randomness — a decision that cannot be replayed
    cannot be checked."""
    tree = ast.parse((PACKAGE / "rules.py").read_text())
    banned = {"datetime", "time", "random", "requests", "httpx", "os"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                assert a.name.split(".")[0] not in banned, a.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in banned, node.module
