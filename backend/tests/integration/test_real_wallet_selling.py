"""The real wallet has to be able to SELL what it buys, on time, in SOL.

Every piece was there and none of it joined up for the graduation arm: the exit
loop did not know the strategy, waited for a price the 5-minute rule does not
need, sold into USDC, sized the sell in whole tokens as if they were base units,
and gave up for good the first time a sell was refused. Settlement could not
measure native SOL at all. These walk a SOL-paid position through the real
repository, exit loop and executor.

The amounts are a real mainnet round trip: 0.030075 SOL in for
1,640,115.442951 tokens, 0.029185068 SOL back, 105,000 lamports of fee a side.
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from solders.hash import Hash
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from app.core.config import settings
from app.labs.graduation import live_decisions
from app.models.real_wallet_execution import RealWalletLiveIntent, RealWalletPosition
from app.real_wallet import executor as ex
from app.real_wallet import sol_price
from app.real_wallet.autotrade import AutotradeSwitchService
from app.real_wallet.driver import RealWalletDriver
from app.real_wallet.executor import RealWalletExecutor
from app.real_wallet.exit_driver import RealWalletExitDriver
from app.real_wallet.live_readiness import ExecutionState, LiveSubmissionGuard
from app.real_wallet.live_repository import LiveIntentRepository
from app.real_wallet.reconciliation import ChainOutcome, ChainReceipt
from app.real_wallet.sol_price import SolUsdPrice

pytestmark = pytest.mark.integration

WALLET = "7WctMGpqz1tGkYStBBjJRMnmuh9uwJubYV2tL4pLwRr9"
MINT = "SeLLPathTestMint11111111111111111111111pump"
SOL = settings.EXECUTION_SOL_MINT
TOKENS_RAW = 1_640_115_442_951
SPENT = 30_075_000
RECEIVED = 29_185_068
FEE = 105_000
EPS = Decimal("1e-9")


def _usd(at: datetime, usd: str = "100") -> SolUsdPrice:
    return SolUsdPrice(usd=Decimal(usd), observed_at=at, source="test")


async def _to_submitted(repo: LiveIntentRepository, intent: RealWalletLiveIntent,
                        at: datetime) -> None:
    for state in (ExecutionState.SAFETY_APPROVED, ExecutionState.ORDER_CREATED,
                  ExecutionState.SIGNED):
        await repo.transition(intent=intent, next_state=state, detail={}, at=at)
    await repo.record_signature_before_submission(
        intent=intent, signature=f"sig-{uuid.uuid4().hex}", at=at)
    await repo.transition(intent=intent, next_state=ExecutionState.SUBMITTED,
                          detail={}, at=at)


async def _bought(session, *, at: datetime, price: SolUsdPrice | None = None,
                  strategy: str = "G-B3-5M") -> RealWalletPosition:
    """A settled SOL-paid buy: $3.00 authorised as 0.03 SOL, 0.030075 spent."""
    repo = LiveIntentRepository(session)
    buy = await repo.create_intent(
        idempotency_key=f"buy-{uuid.uuid4().hex}", mint_address=MINT, side="BUY",
        strategy_id=strategy, strategy_version="test", wallet_public_key=WALLET,
        requested_usd=Decimal("3.00"), input_mint=SOL, output_mint=MINT,
        actual_input_amount_raw=30_000_000,
    )
    assert buy is not None
    await _to_submitted(repo, buy, at)
    return await repo.confirm_settlement(
        intent=buy, signature=buy.transaction_signature or "",
        actual_input_amount_raw=SPENT, actual_input_decimals=9,
        actual_output_amount_raw=TOKENS_RAW, actual_output_decimals=6,
        network_fee_lamports=FEE, at=at, sol_price=price,
    )


async def _sell(session, position: RealWalletPosition, *, at: datetime,
                price: SolUsdPrice | None) -> RealWalletPosition:
    repo = LiveIntentRepository(session)
    sell = await repo.create_sell_intent(
        idempotency_key=f"sell-{uuid.uuid4().hex}", position_id=position.id,
        strategy_id="G-B3-5M", strategy_version="test", wallet_public_key=WALLET)
    await _to_submitted(repo, sell, at)
    return await repo.confirm_settlement(
        intent=sell, signature=sell.transaction_signature or "",
        actual_input_amount_raw=TOKENS_RAW, actual_input_decimals=6,
        actual_output_amount_raw=RECEIVED, actual_output_decimals=9,
        network_fee_lamports=FEE, at=at, sol_price=price,
    )


# --- settlement ---------------------------------------------------------------

@pytest.mark.parametrize("priced", [True, False])
async def test_a_sol_paid_buy_is_recorded_at_what_it_cost_in_dollars(db_session, priced):
    """Priced by the settlement's SOL reading, or — with none — by the rate the
    driver sized it at. A confirmed buy left unrecorded is a holding nothing
    will ever sell."""
    now = datetime.now(UTC)
    position = await _bought(db_session, at=now, price=_usd(now) if priced else None)
    assert position.status == "OPEN"
    assert position.quantity == Decimal("1640115.442951")
    assert position.entry_actual_input_amount == Decimal("0.030075")
    assert abs(position.entry_price_usd * position.quantity - Decimal("3.0075")) < EPS


async def test_a_sell_back_into_sol_closes_in_dollars(db_session):
    now = datetime.now(UTC)
    position = await _bought(db_session, at=now, price=_usd(now))
    closed = await _sell(db_session, position, at=now, price=_usd(now))
    assert closed.status == "CLOSED"
    # $2.9185068 back against $3.0075 in.
    assert abs(closed.realised_gross_pnl_usd - Decimal("-0.0889932")) < EPS
    # Less 105,000 lamports a side at $100: $0.0105 each.
    assert abs(closed.realised_net_pnl_usd - Decimal("-0.1099932")) < EPS
    loss = await LiveIntentRepository(db_session).realised_loss_today(now)
    assert abs(loss - Decimal("0.1099932")) < EPS


async def test_an_unpriced_sell_still_closes_at_the_rate_the_entry_was_valued_at(db_session):
    now = datetime.now(UTC)
    position = await _bought(db_session, at=now, price=None)
    closed = await _sell(db_session, position, at=now, price=None)
    assert closed.status == "CLOSED"
    assert abs(closed.realised_gross_pnl_usd - Decimal("-0.0889932")) < EPS
    assert closed.realised_net_pnl_usd is None
    # A loss limit that skipped unpriced trades could be switched off by an outage.
    loss = await LiveIntentRepository(db_session).realised_loss_today(now)
    assert abs(loss - Decimal("0.0889932")) < EPS


# --- the exit loop ------------------------------------------------------------

async def test_a_graduation_position_with_no_price_is_sold_at_five_minutes(db_session):
    now = datetime.now(UTC)
    position = await _bought(db_session, at=now - timedelta(seconds=200), price=_usd(now))
    driver = RealWalletExitDriver(db_session)

    early = await driver.tick(now=now)
    assert (early.exits_requested, early.skipped) == (0, {"unpriceable": 1})

    due = await driver.tick(now=now + timedelta(seconds=101))
    assert due.exits_requested == 1, due.as_dict()
    sell = await LiveIntentRepository(db_session).by_id(position.exit_intent_id)
    assert sell is not None
    assert sell.idempotency_key == f"v6exit:{position.id}"
    assert (sell.side, sell.input_mint, sell.output_mint) == ("SELL", MINT, SOL)
    # Base units, not the whole-token quantity read as base units.
    assert sell.authorized_input_amount_raw == TOKENS_RAW
    assert sell.authorized_input_decimals == 6
    assert position.exit_reason == "time_exit_unpriced"


async def test_a_graduation_sale_follows_the_paper_clock_not_the_fill(db_session):
    """The wallet bought 40 seconds after the lab decided. Counting the five
    minutes from its own fill sold 40 seconds late, into the window in which
    these pools are drained; it now sells when the paper book does."""
    now = datetime.now(UTC)
    filled = now - timedelta(seconds=200)
    decided = filled - timedelta(seconds=40)
    await live_decisions.record(db_session, [live_decisions.Mirrored(
        mint=MINT, opened_at=decided, liquidity_usd=Decimal("250000"),
        impact=None, price_native=Decimal("0.000001"))])
    position = await _bought(db_session, at=filled, price=_usd(now))
    driver = RealWalletExitDriver(db_session)

    # 300s after the decision, 260s after the fill: due by the paper clock.
    out = await driver.tick(now=decided + timedelta(seconds=301))
    assert out.exits_requested == 1, out.as_dict()
    assert position.exit_reason == "time_exit_unpriced"


async def test_only_the_graduation_arm_counts_from_the_decision(db_session):
    now = datetime.now(UTC)
    filled = now - timedelta(seconds=200)
    await live_decisions.record(db_session, [live_decisions.Mirrored(
        mint=MINT, opened_at=filled - timedelta(seconds=40),
        liquidity_usd=Decimal("250000"), impact=None,
        price_native=Decimal("0.000001"))])
    position = await _bought(db_session, at=filled, price=_usd(now), strategy="V7-06")
    started = await RealWalletExitDriver(db_session)._clock_start(position)
    assert started == position.opened_at


async def test_an_exit_that_sold_nothing_is_asked_for_again(db_session):
    now = datetime.now(UTC)
    position = await _bought(db_session, at=now - timedelta(minutes=6), price=_usd(now))
    driver = RealWalletExitDriver(db_session)
    repo = LiveIntentRepository(db_session)
    assert (await driver.tick(now=now)).exits_requested == 1
    first = await repo.by_id(position.exit_intent_id)
    assert first is not None
    await repo.transition(intent=first, next_state=ExecutionState.BLOCKED, detail={}, at=now)

    assert (await driver.tick(now=now)).skipped == {"exit_retry_waiting": 1}
    assert (await driver.tick(now=now + timedelta(seconds=20))).exits_requested == 1
    second = await repo.by_id(position.exit_intent_id)
    assert second is not None and second.id != first.id
    assert second.idempotency_key == f"v6exit:{position.id}:2"
    assert second.authorized_input_amount_raw == TOKENS_RAW
    assert position.exit_reason == "time_exit_unpriced"

    # Reverted on chain sold nothing either; the wait doubles.
    for state in (ExecutionState.SAFETY_APPROVED, ExecutionState.ORDER_CREATED,
                  ExecutionState.FAILED):
        await repo.transition(intent=second, next_state=state, detail={}, at=now)
    assert (await driver.tick(now=now + timedelta(seconds=25))).skipped == {
        "exit_retry_waiting": 1}
    assert (await driver.tick(now=now + timedelta(seconds=40))).exits_requested == 1
    assert await repo.sell_attempts(position.id) == 3


@pytest.mark.parametrize("outcome", [ExecutionState.SUBMITTED,
                                     ExecutionState.RECONCILIATION_REQUIRED])
async def test_an_exit_that_may_have_sold_is_never_asked_for_again(db_session, outcome):
    now = datetime.now(UTC)
    position = await _bought(db_session, at=now - timedelta(minutes=6), price=_usd(now))
    driver = RealWalletExitDriver(db_session)
    repo = LiveIntentRepository(db_session)
    await driver.tick(now=now)
    sell = await repo.by_id(position.exit_intent_id)
    assert sell is not None
    await _to_submitted(repo, sell, now)
    if outcome is ExecutionState.RECONCILIATION_REQUIRED:
        await repo.transition(intent=sell, next_state=outcome, detail={}, at=now)

    out = await driver.tick(now=now + timedelta(hours=1))
    assert (out.exits_requested, out.skipped) == (0, {"exit_already_requested": 1})
    assert await repo.sell_attempts(position.id) == 1


async def test_nothing_is_asked_for_under_a_kill_switch(db_session):
    now = datetime.now(UTC)
    position = await _bought(db_session, at=now - timedelta(minutes=6), price=_usd(now))
    await LiveIntentRepository(db_session).activate_kill_switch(
        kind="manual", reason="test", at=now)
    out = await RealWalletExitDriver(db_session).tick(now=now)
    assert (out.exits_requested, out.skipped) == (0, {"kill_switch_active": 1})
    assert position.exit_intent_id is None


# --- the executor -------------------------------------------------------------

class _Orders:
    async def prepare(self, intent: RealWalletLiveIntent) -> Any:
        return SimpleNamespace(request_id=f"req-{uuid.uuid4().hex}",
                               evidence={"intent_fingerprint": "fp"})


class _Signer:
    async def identity(self) -> dict[str, bool]:
        return {"can_sign": True, "matches_pinned_key": True}


class _Chain:
    """The wallet's RPC: a verified network holding one SOL."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.calls: list[str] = []

    async def __aenter__(self) -> _Chain:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


@pytest.fixture
def live(monkeypatch):
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
    for name, value in (
        ("REAL_WALLET_EXECUTION_MODE", "live"),
        ("REAL_WALLET_EXECUTION_ENABLED", True),
        ("REAL_WALLET_AUTOTRADE_ENABLED", True),
        ("REAL_WALLET_PUBLIC_KEY", WALLET),
        ("REAL_WALLET_MAX_TRADE_USD", Decimal("100")),
        ("REAL_WALLET_MAX_OPEN_POSITIONS", 6),
        ("REAL_WALLET_MAX_TOTAL_EXPOSURE_USD", Decimal("600")),
        ("REAL_WALLET_MAX_DAILY_NOTIONAL_USD", Decimal("10000")),
        ("REAL_WALLET_MAX_DAILY_TRADES", 100),
        ("REAL_WALLET_MAX_DAILY_LOSS_USD", Decimal("30")),
        ("REAL_WALLET_SIZING_BASE_USD", Decimal("0")),
        ("REAL_WALLET_BALANCE_CEILING_ENABLED", False),
        ("REAL_WALLET_MIN_SOL_FEE_RESERVE", Decimal("0.01")),
    ):
        monkeypatch.setattr(settings, name, value)


def _executor(session) -> RealWalletExecutor:
    return RealWalletExecutor(session, order_factory=_Orders(),  # type: ignore[arg-type]
                              signer=_Signer(), transport=object())  # type: ignore[arg-type]


async def _buy_intent(session, *, usd: str = "50") -> RealWalletLiveIntent:
    intent = await LiveIntentRepository(session).create_intent(
        idempotency_key=f"b-{uuid.uuid4().hex}", mint_address=f"Other{uuid.uuid4().hex[:30]}",
        side="BUY", strategy_id="G-B3-5M", strategy_version="test",
        wallet_public_key=WALLET, requested_usd=Decimal(usd), input_mint=SOL,
        output_mint=MINT, actual_input_amount_raw=int(Decimal(usd) / 100 * 10**9),
    )
    assert intent is not None
    return intent


async def test_with_the_switch_off_a_sell_goes_out_and_a_buy_does_not(db_session, live):
    now = datetime.now(UTC)
    assert not (await AutotradeSwitchService(db_session).state()).enabled
    position = await _bought(db_session, at=now - timedelta(minutes=6), price=_usd(now))
    await RealWalletExitDriver(db_session).tick(now=now)
    executor = _executor(db_session)
    sell_id = position.exit_intent_id
    assert sell_id is not None

    # No SEC-2 verdict is asked for, so none can go stale ten minutes later.
    assert (await executor.advance(sell_id, now=now)).state == ExecutionState.SAFETY_APPROVED
    later = now + timedelta(minutes=10)
    moved = await executor.advance(sell_id, now=later)
    assert moved.state == ExecutionState.ORDER_CREATED, moved
    sell = await LiveIntentRepository(db_session).by_id(sell_id)
    assert sell is not None
    assert (sell.safety_evaluation_id, sell.requested_usd) == (None, None)
    decision = LiveSubmissionGuard().evaluate(await executor._facts(sell, later))
    assert decision.allowed, decision.reasons

    buy = await _buy_intent(db_session)
    assert (await executor.advance(buy.id, now=later)).reason == "autotrade_switch_off"


async def test_a_thirty_dollar_day_refuses_a_buy_at_the_last_step(db_session, live):
    now = datetime.now(UTC)
    executor = _executor(db_session)
    buy = await _buy_intent(db_session)
    assert (await executor._facts(buy, now)).daily_loss_within_limit

    db_session.add(RealWalletPosition(
        mint_address="LostTodayMint", status="CLOSED", quantity=Decimal(1),
        entry_price_usd=Decimal(100), opened_at=now - timedelta(minutes=10),
        closed_at=now - timedelta(minutes=5), realised_gross_pnl_usd=Decimal("-29"),
        realised_net_pnl_usd=Decimal("-30")))
    await db_session.flush()
    facts = await executor._facts(buy, now)
    assert not facts.daily_loss_within_limit
    assert "DAILY_LOSS_LIMIT" in LiveSubmissionGuard().evaluate(facts).reasons


def _unsigned_transaction(payer: str) -> str:
    """What the order evidence keeps: an unsigned transaction with a blockhash."""
    message = MessageV0.try_compile(Pubkey.from_string(payer), [], [], Hash.new_unique())
    return base64.b64encode(
        bytes(VersionedTransaction.populate(message, [Signature.default()]))).decode()


class _Unknown:
    def __init__(self, rpc: Any) -> None:
        pass

    async def inspect(self, intent: Any) -> ChainReceipt:
        return ChainReceipt(outcome=ChainOutcome.UNKNOWN,
                            signature=intent.transaction_signature)


async def test_a_sell_that_never_landed_is_failed_and_asked_for_again(
        db_session, live, monkeypatch):
    class Chain(_Chain):
        async def call(self, method: str, params: Any, **kwargs: Any) -> Any:
            return ({"value": False} if method == "isBlockhashValid"
                    else {"value": [None]})

    monkeypatch.setattr(ex, "StandardSolanaRPC", Chain)
    monkeypatch.setattr(ex, "SolanaRpcTransactionReconciler", _Unknown)
    now = datetime.now(UTC)
    position = await _bought(db_session, at=now - timedelta(minutes=6), price=_usd(now))
    driver = RealWalletExitDriver(db_session)
    repo = LiveIntentRepository(db_session)
    await driver.tick(now=now)
    sell = await repo.by_id(position.exit_intent_id)
    assert sell is not None
    await _to_submitted(repo, sell, now)
    sell.order_evidence = {"unsigned_transaction": _unsigned_transaction(WALLET)}
    executor = _executor(db_session)

    waiting = await executor.advance(sell.id, now=now + timedelta(seconds=60))
    assert (waiting.changed, waiting.reason) == (False, "chain_unknown")
    dropped = await executor.advance(sell.id, now=now + timedelta(minutes=6))
    assert (dropped.state, dropped.reason) == (ExecutionState.FAILED, "expired_unlanded")
    retried = await driver.tick(now=now + timedelta(minutes=7))
    assert retried.exits_requested == 1
    assert position.exit_intent_id != sell.id


# --- the driver ---------------------------------------------------------------

@pytest.fixture
def grad_signal(monkeypatch, live):
    async def usd(self: Any, now: datetime) -> Decimal:
        return Decimal("100")

    async def lamports(self: Any, wallet: str) -> int:
        return 1_000_000_000

    monkeypatch.setattr(RealWalletDriver, "_sol_usd", usd)
    monkeypatch.setattr(RealWalletDriver, "_wallet_lamports", lamports)
    monkeypatch.setattr(settings, "REAL_WALLET_ENTRY_SIZE_USD", Decimal("100"))

    async def signal(session: Any, now: datetime) -> None:
        await live_decisions.record(session, [live_decisions.Mirrored(
            mint="DriverLossTestMint111111111111111111111pump",
            opened_at=now - timedelta(seconds=5), liquidity_usd=Decimal("250000"),
            impact=None, price_native=Decimal("0.000001"))])
        await AutotradeSwitchService(session).start(
            actor="op@x.com", reason="loss limit test", strategy_id="G-B3-5M", at=now)

    return signal


@pytest.mark.parametrize(("lost", "created"), [("-30", 0), ("-29.99", 1)])
async def test_a_thirty_dollar_day_stops_new_buys(db_session, grad_signal, lost, created):
    now = datetime.now(UTC)
    db_session.add(RealWalletPosition(
        mint_address="LostTodayMint", status="CLOSED", quantity=Decimal(1),
        entry_price_usd=Decimal(100), opened_at=now - timedelta(minutes=10),
        closed_at=now - timedelta(minutes=5), realised_net_pnl_usd=Decimal(lost)))
    await grad_signal(db_session, now)
    out = await RealWalletDriver(db_session).tick(now=now)
    assert out.created == created, out
    if not created:
        assert out.skipped == "policy:MAX_DAILY_LOSS"


async def test_sells_do_not_use_up_the_daily_buy_count(db_session, grad_signal, monkeypatch):
    monkeypatch.setattr(settings, "REAL_WALLET_MAX_DAILY_TRADES", 1)
    now = datetime.now(UTC)
    await LiveIntentRepository(db_session).create_intent(
        idempotency_key="an-exit-today", mint_address="SoldTodayMint", side="SELL",
        strategy_id="G-B3-5M", strategy_version="test", wallet_public_key=WALLET,
        input_mint="SoldTodayMint", output_mint=SOL)
    await grad_signal(db_session, now)
    out = await RealWalletDriver(db_session).tick(now=now)
    assert out.created == 1, out
