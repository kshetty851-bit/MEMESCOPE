"""Closing empty token accounts is signed automatically, so the inspection is
the whole of its safety.

`CloseAccount` moves an account's lamports to a destination and deletes it; the
token program refuses while the account holds tokens. So the only thing that
can go wrong is WHERE the lamports go and WHO signs. Every forged transaction
below tries to change one of those, or to smuggle something else in, and must
be refused from the bytes alone.
"""

from __future__ import annotations

import base64
import json
import stat
from pathlib import Path

import pytest
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message, MessageV0
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction, VersionedTransaction

from app.core.config import settings
from app.real_wallet import account_close as ac
from app.real_wallet import mainnet_signer as ms
from app.real_wallet.balance import ExecutionWalletBalanceService, ExecutionWalletTokenBalance

pytestmark = pytest.mark.unit

TOKEN = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
TOKEN_2022 = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
KEY = Keypair()
WALLET = KEY.pubkey()
ACCOUNT = Pubkey.new_unique()
OTHER = Pubkey.new_unique()
BLOCKHASH = Hash.new_unique()


def _close(account=ACCOUNT, destination=WALLET, owner=WALLET, program=TOKEN,
           data=bytes([9]), extra=()) -> Instruction:
    return Instruction(program, data, [
        AccountMeta(account, is_signer=False, is_writable=True),
        AccountMeta(destination, is_signer=False, is_writable=True),
        AccountMeta(owner, is_signer=True, is_writable=False),
        *extra,
    ])


def _encode(instructions, payer=WALLET) -> str:
    message = Message.new_with_blockhash(list(instructions), payer, BLOCKHASH)
    return base64.b64encode(bytes(Transaction.new_unsigned(message))).decode()


def _inspect(encoded: str):
    return ac.inspect(encoded, wallet=str(WALLET))


def test_it_builds_what_it_accepts_for_both_token_programs():
    second = Pubkey.new_unique()
    encoded = ac.build(wallet=str(WALLET), blockhash=str(BLOCKHASH), accounts=[
        (str(ACCOUNT), str(TOKEN)), (str(second), str(TOKEN_2022))])
    inspected = _inspect(encoded)
    assert inspected.accounts == (str(ACCOUNT), str(second))
    message = Transaction.from_bytes(base64.b64decode(encoded)).message
    assert str(message.account_keys[0]) == str(WALLET)
    assert message.header.num_required_signatures == 1


@pytest.mark.parametrize(("forged", "reason"), [
    # The rent goes somewhere else.
    (lambda: _encode([_close(destination=OTHER)]), "close_must_pay"),
    # Someone else is the authority, so a second signature is needed.
    (lambda: _encode([_close(owner=OTHER)]), "only_the_wallet_may_sign"),
    # Someone else pays the fee.
    (lambda: _encode([_close()], payer=OTHER), "fee_payer_is_not_the_wallet"),
    # Not a token program at all.
    (lambda: _encode([transfer(TransferParams(from_pubkey=WALLET, to_pubkey=OTHER,
                                              lamports=1))]), "not_a_token_program"),
    # A token instruction that is not CloseAccount (Transfer, amount 1).
    (lambda: _encode([_close(data=bytes([3]) + (1).to_bytes(8, "little"))]),
     "not_a_close_account"),
    # Anything riding along, even a compute-budget instruction.
    (lambda: _encode([_close(), Instruction(
        Pubkey.from_string("ComputeBudget111111111111111111111111111111"),
        bytes([3]) + (1).to_bytes(8, "little"), [])]), "not_a_token_program"),
    # An extra account passed to the close.
    (lambda: _encode([_close(extra=(AccountMeta(OTHER, False, True),))]),
     "close_must_pay"),
    # Closing the wallet itself.
    (lambda: _encode([_close(account=WALLET)]), "unexpected_close_target"),
    # The same account twice.
    (lambda: _encode([_close(), _close()]), "unexpected_close_target"),
    # More than one transaction's worth.
    (lambda: _encode([_close(account=Pubkey.new_unique()) for _ in range(9)]),
     "unexpected_instruction_count"),
])
def test_a_forged_close_is_refused(forged, reason):
    with pytest.raises(ac.AccountCloseRejectedError, match=reason):
        _inspect(forged())


def test_an_unrelated_account_cannot_ride_along():
    """A readonly key the instructions never use still changes what is signed."""
    message = Message.new_with_blockhash([_close(), Instruction(
        TOKEN, bytes([9]), [AccountMeta(Pubkey.new_unique(), False, True),
                            AccountMeta(WALLET, False, True),
                            AccountMeta(WALLET, True, False),
                            AccountMeta(OTHER, False, False)])], WALLET, BLOCKHASH)
    encoded = base64.b64encode(bytes(Transaction.new_unsigned(message))).decode()
    with pytest.raises(ac.AccountCloseRejectedError):
        _inspect(encoded)


def test_a_versioned_or_garbled_transaction_is_refused():
    v0 = MessageV0.try_compile(WALLET, [_close()], [], BLOCKHASH)
    encoded = base64.b64encode(
        bytes(VersionedTransaction.populate(v0, [Signature.default()]))).decode()
    with pytest.raises(ac.AccountCloseRejectedError):
        _inspect(encoded)
    with pytest.raises(ac.AccountCloseRejectedError, match="malformed"):
        _inspect("not base64!")


def _balance(**kw) -> ExecutionWalletTokenBalance:
    return ExecutionWalletTokenBalance(**{
        "token_account": "Acc", "mint_address": "Mint", "raw_amount": "0",
        "decimals": 6, "program_id": str(TOKEN), **kw})


def test_only_accounts_a_close_would_succeed_on_and_nothing_needs_are_picked():
    wallet = str(WALLET)
    keep = _balance(token_account="empty")
    skipped = [
        _balance(token_account="holds tokens", raw_amount="1"),
        _balance(token_account="frozen", state="frozen"),
        _balance(token_account="foreign closer", close_authority=str(OTHER)),
        _balance(token_account="wrapped sol", is_native=True),
        _balance(token_account="native mint", mint_address=ac.NATIVE_MINT),
        _balance(token_account="fees withheld", withheld_amount=5),
        _balance(token_account="fees unreadable", withheld_amount=-1),
        _balance(token_account="open position", mint_address="Held"),
        _balance(token_account="other program", program_id=str(OTHER)),
    ]
    picked = ac.closable([keep, *skipped], wallet=wallet, keep_mints=frozenset({"Held"}))
    assert [b.token_account for b in picked] == ["empty"]
    mine = _balance(token_account="own closer", close_authority=wallet)
    assert ac.closable([mine], wallet=wallet) == [mine]


def test_the_balance_reader_keeps_what_decides_closability():
    result = {"value": [{"pubkey": "Acc", "account": {"data": {"parsed": {"info": {
        "mint": "Mint", "state": "frozen", "isNative": False,
        "closeAuthority": str(OTHER),
        "tokenAmount": {"amount": "0", "decimals": 6},
        "extensions": [{"extension": "transferFeeAmount",
                        "state": {"withheldAmount": 12}}]}}}}}]}
    (row,) = ExecutionWalletBalanceService._parse_token_accounts(
        result, program_id=str(TOKEN_2022))
    assert (row.state, row.close_authority, row.is_native, row.withheld_amount) == (
        "frozen", str(OTHER), False, 12)


# --- the signer -----------------------------------------------------------------

@pytest.fixture
def signer_env(tmp_path, monkeypatch):
    key = tmp_path / "k.json"
    key.write_text(json.dumps(list(bytes(KEY))))
    key.chmod(stat.S_IRUSR | stat.S_IWUSR)
    monkeypatch.setenv("MAINNET_SIGNER_FILE", str(key))
    monkeypatch.setattr(settings, "REAL_WALLET_PUBLIC_KEY", str(WALLET))

    async def chain() -> str:
        return "mainnet-genesis"

    monkeypatch.setattr(ms, "_verified_chain", chain)


async def test_the_signer_signs_a_close_into_the_wallet(signer_env):
    encoded = ac.build(wallet=str(WALLET), blockhash=str(BLOCKHASH),
                       accounts=[(str(ACCOUNT), str(TOKEN))])
    out = await ms.sign_close_accounts(encoded)
    assert out["accounts"] == [str(ACCOUNT)]
    signed = Transaction.from_bytes(base64.b64decode(out["signed_transaction"]))
    assert str(signed.signatures[0]) == out["signature"]
    assert signed.verify_with_results() == [True]


async def test_the_signer_re_inspects_rather_than_trusting_the_caller(signer_env):
    with pytest.raises(ms.MainnetSignerError, match="close_rejected"):
        await ms.sign_close_accounts(_encode([_close(destination=OTHER)]))


async def test_the_signer_routes_the_operation(signer_env):
    captured: dict = {}
    encoded = _encode([_close(destination=OTHER)])

    class _Writer:
        def write(self, payload): captured["body"] = json.loads(payload)
        async def drain(self): ...
        def close(self): ...
        async def wait_closed(self): ...

    class _Reader:
        async def readline(self):
            return (json.dumps({"op": "sign_close_accounts",
                                "transaction": encoded}) + "\n").encode()

    await ms._handle_connection(_Reader(), _Writer())
    assert captured["body"]["ok"] is False
    assert captured["body"]["error"].startswith("close_rejected:")


def test_the_signer_inspects_with_its_own_wallet_setting():
    import ast

    tree = ast.parse(Path(ms.__file__).read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "sign_close_accounts")
    src = ast.unparse(fn)
    assert [a.arg for a in fn.args.args] == ["encoded_transaction"]
    assert "account_close.inspect(encoded_transaction, wallet=expected)" in src
    assert "settings.REAL_WALLET_PUBLIC_KEY" in src


# --- the schedule -----------------------------------------------------------------

def test_the_sweep_is_scheduled_and_cannot_take_the_beat_down():
    import ast

    from app.real_wallet import scheduler as rw_scheduler
    from app.workers.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["real-wallet-close-empty-accounts"]
    assert entry["task"] == "app.real_wallet.scheduler.real_wallet_close_empty_accounts"
    assert entry["task"] in celery_app.tasks
    tree = ast.parse(Path(rw_scheduler.__file__).read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef)
              and n.name == "_real_wallet_close_empty_accounts")
    handlers = [h for n in ast.walk(fn) if isinstance(n, ast.Try) for h in n.handlers]
    assert handlers
    assert not any(isinstance(n, ast.Raise) for h in handlers for n in ast.walk(h))
    assert "pg_try_advisory_xact_lock" in ast.unparse(fn)
