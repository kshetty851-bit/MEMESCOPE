"""Family members' OWN wallets trading (stage 2, 2026-09-25), through the real
driver and executor against a real database.

What must hold: a member's wallet trades only when its own switch is on; it
buys on its own balance and ticket, beside the owner's order for the same
coin; its limits count its own book and nobody else's; and the owner's
wallet behaves exactly as before.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from solders.keypair import Keypair
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.labs.graduation import live_decisions
from app.models.real_wallet_execution import RealWalletLiveIntent, RealWalletPosition
from app.models.real_wallet_family import RealWalletFamilyMember
from app.real_wallet import executor as ex
from app.real_wallet import sol_price
from app.real_wallet.autotrade import AutotradeSwitchService
from app.real_wallet.driver import RealWalletDriver
from app.real_wallet.executor import RealWalletExecutor

pytestmark = pytest.mark.integration

OWNER = "7WctMGpqz1tGkYStBBjJRMnmuh9uwJubYV2tL4pLwRr9"
KARTHIK = "FoHVQyJmv5AHPjccV3BWpMoKiMHLPkF5cfQdqo1nH5TN"
JAYA = str(Keypair().pubkey())
MINT = "FamilyWalletTestMint111111111111111111pump"
SOL = "So11111111111111111111111111111111111111112"


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    async def _price(self, now):
        return Decimal("100")

    monkeypatch.setattr(RealWalletDriver, "_sol_usd", _price)
    for name, value in (
        ("REAL_WALLET_PUBLIC_KEY", OWNER),
        ("REAL_WALLET_WITHDRAWAL_ADDRESS", KARTHIK),
        ("REAL_WALLET_FAMILY_WALLETS", f"jaya={JAYA}"),
        ("REAL_WALLET_ENTRY_SIZE_USD", Decimal("100")),
        ("REAL_WALLET_MAX_TRADE_USD", Decimal("400")),
        ("REAL_WALLET_MAX_TOTAL_EXPOSURE_USD", Decimal("1000")),
        ("REAL_WALLET_MAX_DAILY_NOTIONAL_USD", Decimal("10000")),
        ("REAL_WALLET_MAX_DAILY_LOSS_USD", Decimal("100")),
        ("REAL_WALLET_BALANCE_CEILING_ENABLED", False),
        ("REAL_WALLET_MIN_SOL_FEE_RESERVE", Decimal("0.01")),
    ):
        monkeypatch.setattr(settings, name, value)


def _funded(monkeypatch, **sol: str) -> None:
    """Balances by wallet: owner=..., jaya=..."""
    by_wallet = {OWNER: sol.get("owner", "3"), JAYA: sol.get("jaya", "3")}

    async def _lamports(self, wallet):
        return int(Decimal(by_wallet[wallet]) * 1_000_000_000)

    monkeypatch.setattr(RealWalletDriver, "_wallet_lamports", _lamports)


async def _jaya(session, *, own: bool, ticket: str = "20", share: bool = False) -> None:
    for name in ("JAYA", "ASHA", "APOORVA"):
        session.add(RealWalletFamilyMember(name=name, enabled=False, ticket_usd=Decimal("25")))
    await session.flush()
    row = await session.get(RealWalletFamilyMember, "JAYA")
    row.enabled = share
    row.own_enabled, row.own_ticket_usd = own, Decimal(ticket)
    await session.flush()


async def _signal(session, now: datetime, *, owner_on: bool = True) -> None:
    await live_decisions.record(session, [live_decisions.Mirrored(
        strategy_id="G-QUIET", mint=MINT, opened_at=now - timedelta(seconds=5),
        liquidity_usd=Decimal("250000"), impact=None, price_native=Decimal("0.000001"))])
    switch = AutotradeSwitchService(session)
    await switch.start(actor="op@x.com", reason="family wallet test",
                       strategy_id="G-QUIET", at=now)
    if not owner_on:
        await switch.stop(actor="op@x.com", reason="owner off", at=now)


async def _intents(session) -> dict[str, RealWalletLiveIntent]:
    rows = (await session.execute(select(RealWalletLiveIntent))).scalars().all()
    return {r.wallet_public_key: r for r in rows}


async def test_a_wallet_that_is_off_buys_nothing_and_the_owner_is_unchanged(
        db_session, monkeypatch):
    _funded(monkeypatch)
    await _jaya(db_session, own=False)
    now = datetime.now(UTC)
    await _signal(db_session, now)
    out = await RealWalletDriver(db_session).tick(now=now)
    assert (out.created, out.family) == (1, {"JAYA": "own_wallet_off"})
    intents = await _intents(db_session)
    assert set(intents) == {OWNER}
    assert intents[OWNER].requested_usd == Decimal("100")
    assert intents[OWNER].idempotency_key == f"v6:G-QUIET:{MINT}"


async def test_a_wallet_that_is_on_buys_the_same_coin_on_its_own_money(
        db_session, monkeypatch):
    _funded(monkeypatch)
    await _jaya(db_session, own=True, ticket="20")
    now = datetime.now(UTC)
    await _signal(db_session, now)
    out = await RealWalletDriver(db_session).tick(now=now)
    assert out.created == 1 and out.family == {"JAYA": f"created:{MINT}"}
    intents = await _intents(db_session)
    assert set(intents) == {OWNER, JAYA}
    jaya = intents[JAYA]
    assert (jaya.requested_usd, jaya.mint_address) == (Decimal("20"), MINT)
    assert jaya.idempotency_key == f"v6:G-QUIET:{MINT}:JAYA"
    assert jaya.actual_input_amount_raw == Decimal("200000000")   # $20 at $100/SOL
    # The owner's order is his own ticket; Jaya's own wallet is not a share.
    assert intents[OWNER].requested_usd == Decimal("100")

    # A second tick buys nothing more: each wallet trades a coin once.
    again = await RealWalletDriver(db_session).tick(now=now)
    assert again.family == {"JAYA": "no_fresh_candidate"}


async def test_the_member_wallet_trades_while_the_owner_is_stopped(db_session, monkeypatch):
    _funded(monkeypatch)
    await _jaya(db_session, own=True)
    now = datetime.now(UTC)
    await _signal(db_session, now, owner_on=False)
    out = await RealWalletDriver(db_session).tick(now=now)
    assert out.skipped == "autotrade_switch_off"
    assert out.family == {"JAYA": f"created:{MINT}"}


async def test_an_empty_member_wallet_sits_out(db_session, monkeypatch):
    _funded(monkeypatch, jaya="0.005")          # below the fee reserve
    await _jaya(db_session, own=True)
    now = datetime.now(UTC)
    await _signal(db_session, now)
    out = await RealWalletDriver(db_session).tick(now=now)
    assert out.family == {"JAYA": "entry_not_fundable"}
    assert set(await _intents(db_session)) == {OWNER}


async def test_the_owners_losses_do_not_stop_the_members_wallet(db_session, monkeypatch):
    _funded(monkeypatch)
    await _jaya(db_session, own=True)
    now = datetime.now(UTC)
    db_session.add(RealWalletPosition(
        mint_address="OwnerLostMint", status="CLOSED", quantity=Decimal(1),
        entry_price_usd=Decimal(200), opened_at=now - timedelta(minutes=10),
        closed_at=now - timedelta(minutes=5), wallet_public_key=OWNER,
        realised_gross_pnl_usd=Decimal("-150"), realised_net_pnl_usd=Decimal("-150")))
    await db_session.flush()
    await _signal(db_session, now)
    out = await RealWalletDriver(db_session).tick(now=now)
    assert out.created == 0 and out.skipped.startswith("policy:")   # the owner's limit
    assert out.family == {"JAYA": f"created:{MINT}"}                 # not Jaya's


async def test_the_members_losses_do_not_stop_the_owner(db_session, monkeypatch):
    _funded(monkeypatch)
    await _jaya(db_session, own=True)
    now = datetime.now(UTC)
    db_session.add(RealWalletPosition(
        mint_address="JayaLostMint", status="CLOSED", quantity=Decimal(1),
        entry_price_usd=Decimal(200), opened_at=now - timedelta(minutes=10),
        closed_at=now - timedelta(minutes=5), wallet_public_key=JAYA,
        realised_gross_pnl_usd=Decimal("-150"), realised_net_pnl_usd=Decimal("-150")))
    await db_session.flush()
    await _signal(db_session, now)
    out = await RealWalletDriver(db_session).tick(now=now)
    assert out.created == 1
    assert out.family["JAYA"].startswith("policy:")


async def test_two_wallets_may_hold_the_same_coin_but_one_wallet_only_once(db_session):
    now = datetime.now(UTC)

    def open_position(wallet: str) -> RealWalletPosition:
        return RealWalletPosition(mint_address=MINT, status="OPEN", quantity=Decimal(1),
                                  entry_price_usd=Decimal(1), opened_at=now,
                                  wallet_public_key=wallet)

    db_session.add_all([open_position(OWNER), open_position(JAYA)])
    await db_session.flush()
    db_session.add(open_position(JAYA))
    with pytest.raises(IntegrityError):
        await db_session.flush()


# --- the executor judges a family order on the family wallet ------------------

class _Signer:
    async def identity(self) -> dict[str, bool]:
        return {"can_sign": True, "matches_pinned_key": True}

    async def identity_family(self) -> dict[str, Any]:
        return {"family": {"JAYA": {"public_key": JAYA, "matches_pinned_key": True}}}


class _Chain:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _Chain:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


@pytest.fixture
def chain(monkeypatch):
    async def verified(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(verified=True)

    class Balance:
        def __init__(self, rpc: Any) -> None:
            pass

        async def get_sol_balance(self, wallet: str) -> Any:
            return SimpleNamespace(sol=Decimal("1"))

    async def price(now: datetime) -> Decimal:
        return Decimal("100")

    monkeypatch.setattr(ex, "StandardSolanaRPC", _Chain)
    monkeypatch.setattr(ex, "require_verified_network", verified)
    monkeypatch.setattr(ex, "ExecutionWalletBalanceService", Balance)
    monkeypatch.setattr(sol_price, "current_usd", price)
    monkeypatch.setattr(settings, "REAL_WALLET_MAX_DAILY_LOSS_USD", Decimal("30"))


async def _buy(session, wallet: str) -> RealWalletLiveIntent:
    from app.real_wallet.live_repository import LiveIntentRepository

    intent = await LiveIntentRepository(session).create_intent(
        idempotency_key=f"b-{uuid.uuid4().hex}", mint_address=MINT, side="BUY",
        strategy_id="G-QUIET", strategy_version="test", wallet_public_key=wallet,
        requested_usd=Decimal("20"), input_mint=SOL, output_mint=MINT,
        actual_input_amount_raw=200_000_000)
    assert intent is not None
    return intent


def _executor(session) -> RealWalletExecutor:
    return RealWalletExecutor(session, order_factory=object(),  # type: ignore[arg-type]
                              signer=_Signer(), transport=object())  # type: ignore[arg-type]


async def test_a_family_buy_runs_on_the_family_switch_not_the_owners(db_session, chain):
    now = datetime.now(UTC)
    await _jaya(db_session, own=True)
    await _signal(db_session, now, owner_on=False)
    facts = await _executor(db_session)._facts(await _buy(db_session, JAYA), now)
    assert facts.autotrade_switch_on
    assert facts.signer_ready and facts.signer_matches_pinned_key

    row = await db_session.get(RealWalletFamilyMember, "JAYA")
    row.own_enabled = False
    await db_session.flush()
    facts = await _executor(db_session)._facts(await _buy(db_session, JAYA), now)
    assert not facts.autotrade_switch_on


async def test_a_family_buy_is_judged_on_the_family_wallets_losses(db_session, chain):
    now = datetime.now(UTC)
    await _jaya(db_session, own=True)
    db_session.add(RealWalletPosition(
        mint_address="OwnerLostMint", status="CLOSED", quantity=Decimal(1),
        entry_price_usd=Decimal(100), opened_at=now - timedelta(minutes=10),
        closed_at=now - timedelta(minutes=5), wallet_public_key=OWNER,
        realised_gross_pnl_usd=Decimal("-50"), realised_net_pnl_usd=Decimal("-50")))
    await db_session.flush()
    executor = _executor(db_session)
    assert (await executor._facts(await _buy(db_session, JAYA), now)).daily_loss_within_limit
    owner_facts = await executor._facts(await _buy(db_session, OWNER), now)
    assert not owner_facts.daily_loss_within_limit


# --- who may press the switch -------------------------------------------------

async def test_the_family_password_can_stop_a_wallet_but_never_start_it(db_session):
    from fastapi import HTTPException

    from app.models.user import UserRole
    from app.real_wallet import family, family_api

    await _jaya(db_session, own=False)
    token, _ = family.issue_token("JAYA")
    body = family_api.OwnSettingsIn(enabled=True, ticket_usd=Decimal("20"))

    with pytest.raises(HTTPException) as refused:
        await family_api.member_own_settings("jaya", body, db_session, viewer=None,
                                             x_family_token=token)
    assert refused.value.status_code == 403

    karthik = SimpleNamespace(role=UserRole.ADMIN, email="karthik@example.com")
    on = await family_api.member_own_settings("jaya", body, db_session, viewer=karthik,
                                              x_family_token=token)
    assert on["enabled"] is True

    # Stopping needs only the family password.
    off = await family_api.member_own_settings(
        "jaya", family_api.OwnSettingsIn(enabled=False, ticket_usd=Decimal("20")),
        db_session, viewer=None, x_family_token=token)
    assert off["enabled"] is False

    # Changing the size is Karthik's too.
    with pytest.raises(HTTPException) as resize:
        await family_api.member_own_settings(
            "jaya", family_api.OwnSettingsIn(enabled=False, ticket_usd=Decimal("50")),
            db_session, viewer=None, x_family_token=token)
    assert resize.value.status_code == 403


async def test_a_member_without_a_wallet_has_no_switch(db_session, monkeypatch):
    from fastapi import HTTPException

    from app.real_wallet import family, family_api

    await _jaya(db_session, own=False)
    token, _ = family.issue_token("ASHA")
    with pytest.raises(HTTPException) as missing:
        await family_api.member_own_settings(
            "asha", family_api.OwnSettingsIn(enabled=False, ticket_usd=Decimal("20")),
            db_session, viewer=None, x_family_token=token)
    assert missing.value.status_code == 404
