"""The Lab is research instrumentation and must never be able to move money.

Parses the package's own source rather than trusting a convention: a Lab
failure must not be able to disturb paper, karthik or real-wallet accounting,
and the boundary is worth enforcing mechanically because it is invisible in a
diff.
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
#: Constants the Lab shares with the universe wallet, so "on a peg" and
#: "effectively an index" have one definition on this platform. Allowed by
#: exact name, never by prefix, and `test_the_allowed_modules_stay_pure` holds
#: each one to constants: the day one of them imports a service, it is
#: money-moving code again and this list is what fails.
ALLOWED_PURE = ("app.universe.rules",)


def _sources():
    return sorted(LAB.glob("*.py"))


def test_the_package_exists_and_has_files():
    assert _sources(), "app/lab must contain source"


@pytest.mark.parametrize("path", _sources(), ids=lambda p: p.name)
def test_no_money_moving_imports(path: Path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            # `from app.universe import rules` names the module in the alias;
            # `from app.universe.rules import X` names it in `module`.
            imported = {f"{node.module}.{a.name}" for a in node.names}
            if node.module in ALLOWED_PURE or imported <= set(ALLOWED_PURE):
                continue
            assert not node.module.startswith(FORBIDDEN_PREFIXES), \
                f"{path.name} imports {node.module}"
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(FORBIDDEN_PREFIXES), \
                    f"{path.name} imports {alias.name}"


@pytest.mark.parametrize("module", ALLOWED_PURE)
def test_the_allowed_modules_stay_pure(module: str):
    """An allowed module may import nothing from `app` at all."""
    path = LAB.parent.joinpath(*module.split(".")[1:]).with_suffix(".py")
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("app"), f"{module} imports {node.module}"
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("app"), f"{module} imports {alias.name}"


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


# --- what counts as a price -------------------------------------------------

#: Files allowed to decide a coin's current price from raw snapshots.
#:
#: `marks.py` owns the rule for views. `service.py` and `sellability.py` own it
#: for the engine's own marking, which has always guarded INACTIVE via
#: `live_print` and the INACTIVE branch of `_mark`.
_PRICE_OWNERS = {"marks.py", "service.py", "sellability.py", "execution.py"}


@pytest.mark.parametrize("path", _sources(), ids=lambda p: p.name)
def test_only_the_mark_owners_read_a_raw_price(path: Path):
    """Nothing else may read `TokenMarketSnapshot.price_usd`.

    An INACTIVE snapshot carries a price and it is not one. On 2026-09-09 the
    trades view read those directly and showed a position correctly written
    off as dead sitting at +174%, because the provider reported 0.0001867 on a
    pool that had collapsed to 0.00000366 and stopped trading — fifty-one
    times higher, with nothing traded.

    The rule was already known: the engine's marking has always excluded
    INACTIVE, and the payoff research lost a whole population to the same
    mistake from the other side. Knowing it was not enough, so this makes the
    next raw read fail here instead of on the page.
    """
    if path.name in _PRICE_OWNERS:
        return
    text = path.read_text()
    assert "TokenMarketSnapshot.price_usd" not in text, (
        f"{path.name} reads a raw snapshot price. Use "
        f"`app.lab.marks.latest_trading_price`, which excludes INACTIVE rows — "
        f"see that module's docstring for why."
    )
