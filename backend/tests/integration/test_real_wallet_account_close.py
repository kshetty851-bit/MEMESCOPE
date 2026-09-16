"""The sweep that gives back rent parked in emptied token accounts.

It is automatic, so what it leaves alone matters as much as what it closes:
nothing while a trade is in flight or a kill switch is on, nothing for a mint
the wallet still holds or has not reconciled, and one refusal never stops the
rest.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from solders.hash import Hash
from solders.pubkey import Pubkey

from app.core.config import settings
from app.models.real_wallet_execution import RealWalletPosition
from app.real_wallet import account_close as ac
from app.real_wallet.live_readiness import ExecutionState
from app.real_wallet.live_repository import LiveIntentRepository
from app.real_wallet.mainnet_signer_client import MainnetSignerRejectedError
from app.services.rpc.base import RpcError

pytestmark = pytest.mark.integration

WALLET = str(Pubkey.new_unique())
TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"


def _account(amount: str, mint: str) -> dict[str, Any]:
    return {"pubkey": str(Pubkey.new_unique()), "account": {"data": {"parsed": {"info": {
        "mint": mint, "state": "initialized", "isNative": False,
        "tokenAmount": {"amount": amount, "decimals": 6}}}}}}


class _Chain:
    def __init__(self, accounts: dict[str, list[dict[str, Any]]],
                 refuse_send: set[str] = frozenset()) -> None:
        self.accounts = accounts
        self.refuse_send = refuse_send
        self.sent: list[str] = []

    async def __aenter__(self) -> _Chain:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def call(self, method: str, params: Any, *, attempts: int = 3) -> Any:
        if method == "getTokenAccountsByOwner":
            assert params[0] == WALLET
            return {"value": self.accounts.get(params[1]["programId"], [])}
        if method == "getLatestBlockhash":
            return {"value": {"blockhash": str(Hash.new_unique())}}
        if method == "sendTransaction":
            closed = ac.inspect(params[0], wallet=WALLET).accounts[0]
            if closed in self.refuse_send:
                raise RpcError("sendTransaction error: account has tokens")
            self.sent.append(closed)
            return f"sig-{len(self.sent)}"
        raise AssertionError(method)


class _Signer:
    def __init__(self, refuse: set[str] = frozenset()) -> None:
        self.refuse = refuse
        self.asked: list[str] = []

    async def sign_close_accounts(self, encoded: str) -> dict[str, Any]:
        account = ac.inspect(encoded, wallet=WALLET).accounts[0]
        self.asked.append(account)
        if account in self.refuse:
            raise MainnetSignerRejectedError("close_rejected:test")
        return {"signed_transaction": encoded, "signature": "s", "accounts": [account]}


@pytest.fixture
def live(monkeypatch):
    async def verified(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(ac, "require_verified_network", verified)
    monkeypatch.setattr(settings, "REAL_WALLET_PUBLIC_KEY", WALLET)
    monkeypatch.setattr(settings, "REAL_WALLET_EXECUTION_MODE", "live")
    monkeypatch.setattr(settings, "REAL_WALLET_EXECUTION_ENABLED", True)


async def _intent(session, mint: str) -> Any:
    intent = await LiveIntentRepository(session).create_intent(
        idempotency_key=f"i-{uuid.uuid4().hex}", mint_address=mint, side="BUY",
        strategy_id="G-B3-5M", strategy_version="test", wallet_public_key=WALLET,
        requested_usd=Decimal("50"), input_mint="So11111111111111111111111111111111111111112",
        output_mint=mint, actual_input_amount_raw=500_000_000)
    assert intent is not None
    return intent


async def test_it_closes_the_empty_ones_and_keeps_what_is_still_needed(db_session, live):
    empty = _account("0", "SoldMint")
    held = _account("0", "HeldMint")
    unresolved = _account("0", "UnresolvedMint")
    full = _account("5", "FullMint")
    refused = _account("0", "RefusedMint")
    empty_2022 = _account("0", "SoldMint2022")
    chain = _Chain({TOKEN: [empty, held, unresolved, full, refused],
                    TOKEN_2022: [empty_2022]})
    signer = _Signer(refuse={refused["pubkey"]})

    now = datetime.now(UTC)
    db_session.add(RealWalletPosition(
        mint_address="HeldMint", status="OPEN", quantity=Decimal(1),
        entry_price_usd=Decimal(1), opened_at=now))
    repo = LiveIntentRepository(db_session)
    stuck = await _intent(db_session, "UnresolvedMint")
    for state in (ExecutionState.SAFETY_APPROVED, ExecutionState.ORDER_CREATED,
                  ExecutionState.SIGNED):
        await repo.transition(intent=stuck, next_state=state, detail={}, at=now)
    await repo.record_signature_before_submission(intent=stuck, signature="stuck-sig", at=now)
    for state in (ExecutionState.SUBMITTED, ExecutionState.RECONCILIATION_REQUIRED):
        await repo.transition(intent=stuck, next_state=state, detail={}, at=now)
    await db_session.flush()

    out = await ac.sweep(db_session, rpc=chain, signer=signer)  # type: ignore[arg-type]

    assert set(out.closed) == {empty["pubkey"], empty_2022["pubkey"]}
    assert out.refused == (refused["pubkey"],)
    assert set(chain.sent) == set(out.closed)
    assert held["pubkey"] not in signer.asked
    assert unresolved["pubkey"] not in signer.asked
    assert full["pubkey"] not in signer.asked
    assert out.skipped is None


async def test_a_close_the_chain_refuses_costs_nothing_and_stops_nothing(db_session, live):
    first, second = _account("0", "A"), _account("0", "B")
    chain = _Chain({TOKEN: [first, second]}, refuse_send={first["pubkey"]})
    out = await ac.sweep(db_session, rpc=chain, signer=_Signer())  # type: ignore[arg-type]
    assert out.refused == (first["pubkey"],)
    assert out.closed == (second["pubkey"],)


async def test_it_waits_while_a_trade_is_in_flight(db_session, live):
    await _intent(db_session, "BuyingMint")
    chain = _Chain({TOKEN: [_account("0", "SoldMint")]})
    out = await ac.sweep(db_session, rpc=chain, signer=_Signer())  # type: ignore[arg-type]
    assert (out.skipped, chain.sent) == ("trade_in_flight", [])


async def test_it_sends_nothing_under_a_kill_switch(db_session, live):
    await LiveIntentRepository(db_session).activate_kill_switch(
        kind="manual", reason="test", at=datetime.now(UTC))
    chain = _Chain({TOKEN: [_account("0", "SoldMint")]})
    out = await ac.sweep(db_session, rpc=chain, signer=_Signer())  # type: ignore[arg-type]
    assert (out.skipped, chain.sent) == ("kill_switch_active", [])


async def test_it_follows_the_execution_flags_not_the_trading_switch(
    db_session, live, monkeypatch
):
    chain = _Chain({TOKEN: [_account("0", "SoldMint")]})
    monkeypatch.setattr(settings, "REAL_WALLET_EXECUTION_MODE", "armed")
    out = await ac.sweep(db_session, rpc=chain, signer=_Signer())  # type: ignore[arg-type]
    assert out.skipped == "execution_not_live"
    # The autotrade switch is off by default and does not stop it.
    monkeypatch.setattr(settings, "REAL_WALLET_EXECUTION_MODE", "live")
    out = await ac.sweep(db_session, rpc=chain, signer=_Signer())  # type: ignore[arg-type]
    assert len(out.closed) == 1


async def test_a_sweep_closes_at_most_its_limit(db_session, live):
    chain = _Chain({TOKEN: [_account("0", f"M{i}") for i in range(4)]})
    out = await ac.sweep(db_session, rpc=chain, signer=_Signer(), limit=3)  # type: ignore[arg-type]
    assert len(out.closed) == 3
