"""One address the money may leave for, and nothing else.

The wallet is asymmetric on purpose. Deposits are open — the execution address is
public and anyone may send to it. Withdrawals go to exactly one nominated
destination, so that if any other barrier is ever wrong, the worst outcome is the
money going back to its owner rather than to whoever asked.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core.config import settings
from app.real_wallet import withdrawal

pytestmark = pytest.mark.unit

OWNER = "FoHVQyJmv5AHPjccV3BWpMoKiMHLPkF5cfQdqo1nH5TN"
OTHER = "7WctMGpqz1tGkYStBBjJRMnmuh9uwJubYV2tL4pLwRr9"


@pytest.fixture(autouse=True)
def _nominated(monkeypatch):
    monkeypatch.setattr(settings, "REAL_WALLET_WITHDRAWAL_ADDRESS", OWNER)
    monkeypatch.setattr(settings, "REAL_WALLET_PUBLIC_KEY", OTHER)


def test_the_nominated_address_is_permitted():
    assert withdrawal.assert_permitted(OWNER) == OWNER
    assert withdrawal.policy().usable is True


def test_every_other_address_is_refused():
    for bad in (OTHER, "So11111111111111111111111111111111111111112", ""):
        with pytest.raises(withdrawal.WithdrawalDestinationError):
            withdrawal.assert_permitted(bad)


def test_an_unset_destination_permits_nothing_rather_than_anything():
    """The failure mode of 'empty means allow all' is total. Same direction as
    the RPC host allowlist, for the same reason."""
    settings.REAL_WALLET_WITHDRAWAL_ADDRESS = ""
    assert withdrawal.policy().usable is False
    with pytest.raises(withdrawal.WithdrawalDestinationError,
                       match="not_configured"):
        withdrawal.assert_permitted(OWNER)


def test_a_destination_that_is_the_wallet_itself_is_refused(monkeypatch):
    """Never what an operator meant, and a self-transfer that quietly succeeds
    hides the misconfiguration until the day it matters."""
    monkeypatch.setattr(settings, "REAL_WALLET_WITHDRAWAL_ADDRESS", OTHER)
    assert withdrawal.policy().usable is False
    with pytest.raises(withdrawal.WithdrawalDestinationError,
                       match="execution_wallet_itself"):
        withdrawal.assert_permitted(OTHER)


def test_a_malformed_destination_is_refused_rather_than_trusted(monkeypatch):
    monkeypatch.setattr(settings, "REAL_WALLET_WITHDRAWAL_ADDRESS", "not-an-address")
    assert withdrawal.policy().usable is False
    with pytest.raises(withdrawal.WithdrawalDestinationError, match="not_a_valid"):
        withdrawal.assert_permitted("not-an-address")


def test_the_comparison_is_case_sensitive():
    """base58 is case-sensitive: two addresses differing only in case are two
    different accounts, and case-folding here would widen the allowlist."""
    with pytest.raises(withdrawal.WithdrawalDestinationError):
        withdrawal.assert_permitted(OWNER.lower())
    with pytest.raises(withdrawal.WithdrawalDestinationError):
        withdrawal.assert_permitted(OWNER.upper())


def test_surrounding_whitespace_does_not_defeat_the_check():
    assert withdrawal.assert_permitted(f"  {OWNER}  ") == OWNER


def test_the_module_moves_nothing():
    """It answers one question about one string. No key, no transaction, no RPC —
    which is what makes it cheap to audit."""
    tree = ast.parse(Path(withdrawal.__file__).read_text())
    imported: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module)
        elif isinstance(n, ast.Import):
            imported.update(a.name for a in n.names)
    assert not {"httpx", "solders", "nacl"} & imported
    assert not any("signer" in m or "transport" in m or "rpc" in m for m in imported)


def test_the_only_transfer_path_asks_before_it_quotes():
    """Refused at the QUOTE, the first step out — so a transfer to anywhere else
    never acquires an id, an approval or a signature. A check at the last moment
    is a check a future caller can skip."""
    from app.real_wallet import devnet_workflow

    tree = ast.parse(Path(devnet_workflow.__file__).read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef)
              and n.name == "quote_native_transfer")
    called = {ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)}
    assert "withdrawal.assert_permitted" in called


def test_readiness_reports_the_lock_and_names_the_address():
    from app.real_wallet import funding_readiness as fr

    check = {c.key: c for c in fr.evaluate().checks}["withdrawal_address_nominated"]
    assert check.status is fr.Status.PASS
    assert OWNER in check.detail
