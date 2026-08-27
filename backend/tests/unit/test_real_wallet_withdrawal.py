"""One address the money may leave for, and nothing else.

The wallet is asymmetric on purpose. Deposits are open — the execution address is
public and anyone may send to it. Withdrawals go to exactly one nominated
destination, so that if any other barrier is ever wrong, the worst outcome is the
money going back to its owner rather than to whoever asked.
"""

from __future__ import annotations

import ast
from decimal import Decimal
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


def test_the_compose_anchor_actually_passes_the_address_through():
    """Checked on the PARSED document, not its text — a comment naming the
    variable is harmless, an env key is what matters, and matching text cannot
    tell them apart.

    Absent from the anchor the value never reaches the container and the policy
    refuses everything: fail-closed, but for silently the wrong reason. This
    anchor has swallowed a variable five times before.
    """
    import yaml

    root = Path(__file__).resolve().parents[3]
    doc = yaml.safe_load((root / "docker-compose.yml").read_text())
    anchor = doc["x-backend-env"]
    assert "REAL_WALLET_WITHDRAWAL_ADDRESS" in anchor
    assert "${REAL_WALLET_WITHDRAWAL_ADDRESS" in str(
        anchor["REAL_WALLET_WITHDRAWAL_ADDRESS"]
    )


def test_the_balance_ceiling_is_a_typo_guard_not_a_growth_cap():
    """Two jobs used to be one number and the smaller one won.

    The SETTING is the operator's risk decision. The field bound is a typo guard
    — it stops `500` written for `5.00`. It was 5 SOL, chosen as 20x the 0.25
    default when this was scoped as a canary, and a typo guard sized for a canary
    caps legitimate growth. Profits compound in the wallet by design (no
    auto-sweep), so the ceiling must be able to sit above where the book is
    going.
    """
    from pydantic import ValidationError

    from app.core.config import Settings

    field = Settings.model_fields["REAL_WALLET_MAX_BALANCE_SOL"]
    bounds = {type(m).__name__: getattr(m, "le", getattr(m, "gt", None))
              for m in field.metadata}
    assert bounds.get("Le") == Decimal("25000"), "a canary-sized guard caps growth"
    # Still a guard: an absurd value is refused rather than accepted.
    with pytest.raises(ValidationError):
        Settings(REAL_WALLET_MAX_BALANCE_SOL=100000)
    # And zero or negative is still meaningless.
    with pytest.raises(ValidationError):
        Settings(REAL_WALLET_MAX_BALANCE_SOL=0)


def test_the_ceiling_blocks_buying_and_never_selling():
    """A wallet that grows past its ceiling stops opening positions and can
    always still close them. Success must not trap the book."""
    import ast
    from pathlib import Path

    from app.real_wallet import policy as policy_mod

    tree = ast.parse(Path(policy_mod.__file__).read_text())
    holders = [
        fn.name for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef)
        and "MAX_BALANCE_SOL" in ast.unparse(fn)
    ]
    # The ceiling lives on the entry path alone.
    assert holders == ["evaluate_canary_entry"], holders


# --- the withdraw path -------------------------------------------------------
# The only route in MEMESCOPE that moves money without a trade. Every other one
# can lose value; this one can only ever send the operator their own money, and
# that is the whole reason it is allowed to exist.


def test_the_destination_is_never_a_parameter():
    """It cannot be passed in, so it cannot be passed in wrongly. An endpoint
    that accepted a recipient would be one validation bug from a drain."""
    import ast as _ast

    from app.real_wallet import withdraw_service

    tree = _ast.parse(Path(withdraw_service.__file__).read_text())
    fn = next(n for n in _ast.walk(tree)
              if isinstance(n, _ast.AsyncFunctionDef) and n.name == "prepare")
    args = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
    assert "destination" not in args
    assert "to" not in args
    src = _ast.unparse(fn)
    assert "withdrawal.assert_permitted" in src


def test_the_signer_proves_the_destination_for_itself():
    """`sign_withdrawal` receives BYTES rather than an id, so the caller could
    hand it anything. It is safe only because the signer re-derives the
    destination from those bytes and compares it against the address in ITS OWN
    environment — the check that survives a fully compromised API."""
    import ast as _ast

    from app.real_wallet import mainnet_signer as ms

    tree = _ast.parse(Path(ms.__file__).read_text())
    fn = next(n for n in _ast.walk(tree)
              if isinstance(n, _ast.AsyncFunctionDef) and n.name == "sign_withdrawal")
    src = _ast.unparse(fn)
    assert "settings.REAL_WALLET_WITHDRAWAL_ADDRESS" in src
    assert "inspect_native_transfer" in src
    # The spec it verifies against is built here, never received.
    assert "NativeTransferSpec(" in src
    assert "withdrawal_destination_is_the_wallet_itself" in src


def test_a_withdrawal_is_submitted_once_and_never_retried():
    """A submitted transfer whose response was lost is UNCERTAIN. Asking again
    is how one withdrawal becomes two."""
    import ast as _ast

    from app.real_wallet import withdraw_service

    tree = _ast.parse(Path(withdraw_service.__file__).read_text())
    fn = next(n for n in _ast.walk(tree)
              if isinstance(n, _ast.AsyncFunctionDef) and n.name == "submit")
    src = _ast.unparse(fn)
    assert "attempts=1" in src
    assert "'maxRetries': 0" in src or '"maxRetries": 0' in src
    assert "for " not in src and "while " not in src, "no retry loop"


def test_it_refuses_to_strand_the_wallet_below_its_fee_reserve():
    """The reserve pays for the NEXT transaction, including a later withdrawal.
    Emptying to the last lamport strands whatever is left."""
    import ast as _ast

    from app.real_wallet import withdraw_service

    src = _ast.unparse(_ast.parse(Path(withdraw_service.__file__).read_text()))
    assert "REAL_WALLET_MIN_SOL_FEE_RESERVE" in src
    assert "would_leave_less_than_fee_reserve" in src


def test_the_chain_is_proven_before_a_transfer_is_built():
    """A transfer assembled against the wrong chain pays an address that may not
    be the operator's on that chain."""
    import ast as _ast

    from app.real_wallet import withdraw_service

    fn = next(n for n in _ast.walk(
        _ast.parse(Path(withdraw_service.__file__).read_text()))
        if isinstance(n, _ast.AsyncFunctionDef) and n.name == "prepare")
    src = _ast.unparse(fn)
    verify_at = src.index("require_verified_network")
    build_at = src.index("build_unsigned_native_transfer")
    assert verify_at < build_at
