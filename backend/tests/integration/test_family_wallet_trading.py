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
USER1 = str(Keypair().pubkey())
MINT = "FamilyWalletTestMint111111111111111111pump"
SOL = "So11111111111111111111111111111111111111112"


def _open_token() -> str:
    from app.real_wallet import family

    return family.issue_token({"investment"})[0]


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    async def _price(self, now):
        return Decimal("100")

    monkeypatch.setattr(RealWalletDriver, "_sol_usd", _price)
    for name, value in (
        ("REAL_WALLET_PUBLIC_KEY", OWNER),
        ("REAL_WALLET_WITHDRAWAL_ADDRESS", KARTHIK),
        ("REAL_WALLET_FAMILY_WALLETS", f"user1={USER1}"),
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
    """Balances by wallet: owner=..., user1=..."""
    by_wallet = {OWNER: sol.get("owner", "3"), USER1: sol.get("user1", "3")}

    async def _lamports(self, wallet):
        return int(Decimal(by_wallet[wallet]) * 1_000_000_000)

    monkeypatch.setattr(RealWalletDriver, "_wallet_lamports", _lamports)


async def _user1(session, *, own: bool, ticket: str = "20") -> None:
    for name in ("USER1", "USER2", "USER3"):
        session.add(RealWalletFamilyMember(name=name))
    await session.flush()
    row = await session.get(RealWalletFamilyMember, "USER1")
    row.own_enabled, row.own_ticket_usd = own, Decimal(ticket)
    await session.flush()


async def _signal(session, now: datetime, *, owner_on: bool = True) -> None:
    await live_decisions.record(session, [live_decisions.Mirrored(
        strategy_id="G-QUIET", mint=MINT, opened_at=now - timedelta(seconds=5),
        graduated_at=now - timedelta(seconds=35),
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
    await _user1(db_session, own=False)
    now = datetime.now(UTC)
    await _signal(db_session, now)
    out = await RealWalletDriver(db_session).tick(now=now)
    assert (out.created, out.family) == (1, {"USER1": "own_wallet_off"})
    intents = await _intents(db_session)
    assert set(intents) == {OWNER}
    assert intents[OWNER].requested_usd == Decimal("100")
    assert intents[OWNER].idempotency_key == f"v6:G-QUIET:{MINT}"


async def test_a_wallet_that_is_on_buys_the_same_coin_on_its_own_money(
        db_session, monkeypatch):
    _funded(monkeypatch)
    await _user1(db_session, own=True, ticket="20")
    now = datetime.now(UTC)
    await _signal(db_session, now)
    out = await RealWalletDriver(db_session).tick(now=now)
    assert out.created == 1 and out.family == {"USER1": f"created:{MINT}"}
    intents = await _intents(db_session)
    assert set(intents) == {OWNER, USER1}
    user1 = intents[USER1]
    assert (user1.requested_usd, user1.mint_address) == (Decimal("20"), MINT)
    assert user1.idempotency_key == f"v6:G-QUIET:{MINT}:USER1"
    assert user1.actual_input_amount_raw == Decimal("200000000")   # $20 at $100/SOL
    # The owner's order is his own ticket, untouched by User1's wallet.
    assert intents[OWNER].requested_usd == Decimal("100")

    # A second tick buys nothing more: each wallet trades a coin once.
    again = await RealWalletDriver(db_session).tick(now=now)
    assert again.family == {"USER1": "no_fresh_candidate"}


async def test_the_coin_cap_counts_the_user_wallets_not_the_owners(db_session, monkeypatch):
    """Karthik, 2026-09-28: "dont include my main wallet here"."""
    _funded(monkeypatch)
    monkeypatch.setattr(settings, "REAL_WALLET_MAX_COIN_USD", Decimal("20"))
    await _user1(db_session, own=True, ticket="20")
    now = datetime.now(UTC)
    await _signal(db_session, now)
    out = await RealWalletDriver(db_session).tick(now=now)
    # The owner's $100 is in and does not count: USER 1's $20 fits the $20 cap.
    assert out.created == 1 and out.family == {"USER1": f"created:{MINT}"}
    assert set(await _intents(db_session)) == {OWNER, USER1}


async def test_the_user_wallets_together_stop_at_the_coin_cap(db_session, monkeypatch):
    _funded(monkeypatch)
    monkeypatch.setattr(settings, "REAL_WALLET_MAX_COIN_USD", Decimal("30"))
    await _user1(db_session, own=True, ticket="20")
    now = datetime.now(UTC)
    # Another user wallet already put $20 into this coin.
    db_session.add(RealWalletLiveIntent(
        idempotency_key="other-user", mint_address=MINT, side="BUY",
        strategy_id="G-QUIET", strategy_version="v", wallet_public_key=str(Keypair().pubkey()),
        requested_usd=Decimal("20"), input_mint=SOL, output_mint=MINT,
        actual_input_amount_raw=1, state="closed", created_at=now - timedelta(minutes=1)))
    await db_session.flush()
    await _signal(db_session, now)
    out = await RealWalletDriver(db_session).tick(now=now)
    assert out.family == {"USER1": "coin_cap_reached"}


async def test_stopping_the_owner_stops_the_member_wallet_too(db_session, monkeypatch):
    """Karthik, 2026-09-25: "stop family wallets when I stop mine"."""
    _funded(monkeypatch)
    await _user1(db_session, own=True)
    now = datetime.now(UTC)
    await _signal(db_session, now, owner_on=False)
    out = await RealWalletDriver(db_session).tick(now=now)
    assert out.skipped == "autotrade_switch_off"
    assert out.family == {"USER1": "owner_wallet_stopped"}
    assert set(await _intents(db_session)) == set()

    # Started again: User1's own switch was never touched, so she resumes.
    await AutotradeSwitchService(db_session).start(
        actor="op@x.com", reason="back on", strategy_id="G-QUIET", at=now)
    again = await RealWalletDriver(db_session).tick(now=now)
    assert again.family == {"USER1": f"created:{MINT}"}


async def test_an_empty_member_wallet_sits_out(db_session, monkeypatch):
    _funded(monkeypatch, user1="0.005")          # below the fee reserve
    await _user1(db_session, own=True)
    now = datetime.now(UTC)
    await _signal(db_session, now)
    out = await RealWalletDriver(db_session).tick(now=now)
    assert out.family == {"USER1": "entry_not_fundable"}
    assert set(await _intents(db_session)) == {OWNER}


async def test_the_owners_losses_do_not_stop_the_members_wallet(db_session, monkeypatch):
    _funded(monkeypatch)
    await _user1(db_session, own=True)
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
    assert out.family == {"USER1": f"created:{MINT}"}                 # not User1's


async def test_the_members_losses_do_not_stop_the_owner(db_session, monkeypatch):
    _funded(monkeypatch)
    await _user1(db_session, own=True)
    now = datetime.now(UTC)
    db_session.add(RealWalletPosition(
        mint_address="User1LostMint", status="CLOSED", quantity=Decimal(1),
        entry_price_usd=Decimal(200), opened_at=now - timedelta(minutes=10),
        closed_at=now - timedelta(minutes=5), wallet_public_key=USER1,
        realised_gross_pnl_usd=Decimal("-150"), realised_net_pnl_usd=Decimal("-150")))
    await db_session.flush()
    await _signal(db_session, now)
    out = await RealWalletDriver(db_session).tick(now=now)
    assert out.created == 1
    assert out.family["USER1"].startswith("policy:")


async def test_two_wallets_may_hold_the_same_coin_but_one_wallet_only_once(db_session):
    now = datetime.now(UTC)

    def open_position(wallet: str) -> RealWalletPosition:
        return RealWalletPosition(mint_address=MINT, status="OPEN", quantity=Decimal(1),
                                  entry_price_usd=Decimal(1), opened_at=now,
                                  wallet_public_key=wallet)

    db_session.add_all([open_position(OWNER), open_position(USER1)])
    await db_session.flush()
    db_session.add(open_position(USER1))
    with pytest.raises(IntegrityError):
        await db_session.flush()


# --- the executor judges a family order on the family wallet ------------------

class _Signer:
    async def identity(self) -> dict[str, bool]:
        return {"can_sign": True, "matches_pinned_key": True}

    async def identity_family(self) -> dict[str, Any]:
        return {"family": {"USER1": {"public_key": USER1, "matches_pinned_key": True}}}


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


async def test_a_family_buy_needs_both_switches_on(db_session, chain):
    now = datetime.now(UTC)
    await _user1(db_session, own=True)
    await _signal(db_session, now)                      # owner on, User1 on
    facts = await _executor(db_session)._facts(await _buy(db_session, USER1), now)
    assert facts.autotrade_switch_on
    assert facts.signer_ready and facts.signer_matches_pinned_key

    await AutotradeSwitchService(db_session).stop(     # owner off, User1 on
        actor="op@x.com", reason="stop all", at=now)
    facts = await _executor(db_session)._facts(await _buy(db_session, USER1), now)
    assert not facts.autotrade_switch_on

    await AutotradeSwitchService(db_session).start(    # owner on, User1 off
        actor="op@x.com", reason="on", strategy_id="G-QUIET", at=now)
    row = await db_session.get(RealWalletFamilyMember, "USER1")
    row.own_enabled = False
    await db_session.flush()
    facts = await _executor(db_session)._facts(await _buy(db_session, USER1), now)
    assert not facts.autotrade_switch_on


async def test_a_family_buy_is_judged_on_the_family_wallets_losses(db_session, chain):
    now = datetime.now(UTC)
    await _user1(db_session, own=True)
    db_session.add(RealWalletPosition(
        mint_address="OwnerLostMint", status="CLOSED", quantity=Decimal(1),
        entry_price_usd=Decimal(100), opened_at=now - timedelta(minutes=10),
        closed_at=now - timedelta(minutes=5), wallet_public_key=OWNER,
        realised_gross_pnl_usd=Decimal("-50"), realised_net_pnl_usd=Decimal("-50")))
    await db_session.flush()
    executor = _executor(db_session)
    assert (await executor._facts(await _buy(db_session, USER1), now)).daily_loss_within_limit
    owner_facts = await executor._facts(await _buy(db_session, OWNER), now)
    assert not owner_facts.daily_loss_within_limit


# --- who may press the switch -------------------------------------------------

async def test_karthik_starts_stops_and_sizes_a_user_wallet(db_session):
    from app.models.user import UserRole
    from app.real_wallet import family_api

    await _user1(db_session, own=False)
    karthik = SimpleNamespace(role=UserRole.ADMIN, email="karthik@example.com")
    on = await family_api.member_own_settings(
        "user1", family_api.OwnSettingsIn(enabled=True, ticket_usd=Decimal("50")),
        db_session, viewer=karthik, x_users_token=_open_token())
    assert (on["enabled"], on["ticket_usd"]) == (True, "50")
    off = await family_api.member_own_settings(
        "user1", family_api.OwnSettingsIn(enabled=False, ticket_usd=Decimal("50")),
        db_session, viewer=karthik, x_users_token=_open_token())
    assert off["enabled"] is False


async def test_a_member_without_a_wallet_has_no_switch(db_session):
    from fastapi import HTTPException

    from app.models.user import UserRole
    from app.real_wallet import family, family_api

    await _user1(db_session, own=False)
    karthik = SimpleNamespace(role=UserRole.ADMIN, email="karthik@example.com")
    with pytest.raises(HTTPException) as missing:
        await family_api.member_own_settings(
            "user2", family_api.OwnSettingsIn(enabled=False, ticket_usd=Decimal("20")),
            db_session, viewer=karthik, x_users_token=family.issue_token({"investment"})[0])
    assert missing.value.status_code == 404


# --- ten users take turns --------------------------------------------------------

async def test_users_take_turns_longest_waiting_first(db_session, monkeypatch):
    """Five users at $50 and a $200 coin cap: the coin fills with the four
    users who have waited longest, never "USER1 first"."""
    users = {f"USER{i}": str(Keypair().pubkey()) for i in range(1, 6)}
    monkeypatch.setattr(settings, "REAL_WALLET_FAMILY_WALLETS",
                        ",".join(f"{m.lower()}={k}" for m, k in users.items()))
    monkeypatch.setattr(settings, "REAL_WALLET_MAX_COIN_USD", Decimal("200"))

    async def _lamports(self, wallet):
        return 3_000_000_000

    monkeypatch.setattr(RealWalletDriver, "_wallet_lamports", _lamports)
    for member in users:
        db_session.add(RealWalletFamilyMember(name=member, own_enabled=True,
                                              own_ticket_usd=Decimal("50")))
    now = datetime.now(UTC)
    # USER1 and USER2 bought most recently; USER5 never has.
    for member, ago in (("USER1", 10), ("USER2", 20), ("USER3", 60), ("USER4", 90)):
        db_session.add(RealWalletLiveIntent(
            idempotency_key=f"earlier:{member}", mint_address=f"Earlier{member}pump",
            side="BUY", strategy_id="G-QUIET", strategy_version="v",
            wallet_public_key=users[member], requested_usd=Decimal("50"),
            input_mint=SOL, output_mint=f"Earlier{member}pump", actual_input_amount_raw=1,
            state="closed", created_at=now - timedelta(minutes=ago)))
    await db_session.flush()
    await _signal(db_session, now)

    out = await RealWalletDriver(db_session).tick(now=now)
    # Four users at $50 = $200 (the owner's $100 is not counted): USER5
    # (never), then 4, 3, 2 — and USER1, who bought last, is left out.
    assert out.family["USER1"] == "coin_cap_reached"
    for member in ("USER2", "USER3", "USER4", "USER5"):
        assert out.family[member] == f"created:{MINT}"


# --- family investment: coin-size bands (2026-09-28) ----------------------------

async def _five_on_band(session, monkeypatch, *, band: str, fdv: str | None,
                        now: datetime) -> None:
    from app.labs.graduation.models import GradPostgradSample

    users = {f"USER{i}": str(Keypair().pubkey()) for i in range(1, 6)}
    monkeypatch.setattr(settings, "REAL_WALLET_FAMILY_WALLETS",
                        ",".join(f"{m.lower()}={k}" for m, k in users.items()))

    async def _lamports(self, wallet):
        return 3_000_000_000

    monkeypatch.setattr(RealWalletDriver, "_wallet_lamports", _lamports)
    for member in users:
        session.add(RealWalletFamilyMember(name=member, own_enabled=True,
                                           own_ticket_usd=Decimal("50"), own_band=band))
    if fdv is not None:
        # An old reading far outside the band, then the one that counts.
        session.add(GradPostgradSample(ts=now - timedelta(minutes=10), mint=MINT,
                                       source="dexscreener", fdv=Decimal("900000000")))
        session.add(GradPostgradSample(ts=now - timedelta(seconds=4), mint=MINT,
                                       source="dexscreener", fdv=Decimal(fdv)))
    await session.flush()
    await _signal(session, now)


async def test_a_band_lets_only_two_wallets_into_one_coin(db_session, monkeypatch):
    now = datetime.now(UTC)
    await _five_on_band(db_session, monkeypatch, band="1m-20m", fdv="8000000", now=now)
    out = await RealWalletDriver(db_session).tick(now=now)
    created = [m for m, r in out.family.items() if r.startswith("created:")]
    assert len(created) == 2
    assert sorted(r for r in out.family.values() if not r.startswith("created:")) == \
        ["band_coin_limit"] * 3


@pytest.mark.parametrize("band, fdv", [("1m-20m", "25000000"), ("5m-100m", "150000000"),
                                       ("5m-100m", "2000000"), ("1m-20m", None)])
async def test_a_coin_outside_the_band_or_unmeasured_is_not_bought(
        db_session, monkeypatch, band, fdv):
    now = datetime.now(UTC)
    await _five_on_band(db_session, monkeypatch, band=band, fdv=fdv, now=now)
    out = await RealWalletDriver(db_session).tick(now=now)
    assert set(out.family.values()) == {"market_cap_outside_band"}
    assert set(await _intents(db_session)) == {OWNER}


async def test_karthik_sets_a_wallets_band_and_a_bad_band_is_refused(db_session):
    from fastapi import HTTPException

    from app.models.user import UserRole
    from app.real_wallet import family_api

    await _user1(db_session, own=False)
    karthik = SimpleNamespace(role=UserRole.ADMIN, email="karthik@example.com")
    out = await family_api.member_own_settings(
        "user1", family_api.OwnSettingsIn(enabled=False, ticket_usd=Decimal("50"),
                                          band="1m-20m"), db_session, viewer=karthik,
        x_users_token=_open_token())
    assert out["band"] == "1m-20m"
    # Leaving the band out keeps it.
    out = await family_api.member_own_settings(
        "user1", family_api.OwnSettingsIn(enabled=True, ticket_usd=Decimal("50")),
        db_session, viewer=karthik, x_users_token=_open_token())
    assert (out["enabled"], out["band"]) == (True, "1m-20m")
    with pytest.raises(HTTPException) as bad:
        await family_api.member_own_settings(
            "user1", family_api.OwnSettingsIn(enabled=True, ticket_usd=Decimal("50"),
                                              band="0-1b"), db_session, viewer=karthik,
            x_users_token=_open_token())
    assert bad.value.status_code == 422
