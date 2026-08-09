"""Mock-only regression coverage for the durable confirmed real-wallet lifecycle."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.paper import PaperPosition
from app.models.real_wallet_execution import (
    RealWalletExecutionEvent,
    RealWalletLiveIntent,
    RealWalletPosition,
)
from app.real_wallet.lifecycle import (
    PreparedTestOrder,
    TestOnlyRealWalletLifecycle,
)
from app.real_wallet.live_readiness import ExecutionState
from app.real_wallet.live_repository import LiveIntentRepository
from app.real_wallet.live_transport import JupiterExecuteOutcome, JupiterExecutionResult
from app.real_wallet.reconciliation import ChainOutcome, ChainReceipt, TransactionReconciler

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 9, tzinfo=UTC)
MINT = "M" * 44
WALLET = "W" * 44


class _Orders:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def prepare(self, intent: RealWalletLiveIntent) -> PreparedTestOrder:
        self.calls.append(str(intent.id))
        return PreparedTestOrder(
            request_id=f"request-{len(self.calls)}",
            input_mint=intent.input_mint or "",
            output_mint=intent.output_mint or "",
            unsigned_transaction="unsigned-test-transaction",
            evidence={"request_id": f"request-{len(self.calls)}", "transaction": "omit-me"},
        )


class _Signer:
    def sign(self, unsigned_transaction: str) -> str:
        assert unsigned_transaction == "unsigned-test-transaction"
        return "signed-test-transaction"


class _Transport:
    def __init__(self, results: list[JupiterExecutionResult]) -> None:
        self.results = deque(results)
        self.calls: list[tuple[str, str]] = []

    async def execute(
        self, *, signed_transaction: str, request_id: str
    ) -> JupiterExecutionResult:
        self.calls.append((signed_transaction, request_id))
        return self.results.popleft()


class _Receipts(TransactionReconciler):
    def __init__(self, receipts: dict[str, ChainReceipt]) -> None:
        self.receipts = receipts

    async def inspect(self, intent: RealWalletLiveIntent) -> ChainReceipt:
        return self.receipts.get(
            intent.transaction_signature or "", ChainReceipt(outcome=ChainOutcome.UNKNOWN)
        )


def _success(signature: str) -> JupiterExecutionResult:
    return JupiterExecutionResult(
        outcome=JupiterExecuteOutcome.SUCCESS,
        signature=signature,
        total_input_amount=None,
        total_output_amount=None,
        error_code=None,
    )


async def _submit_buy(
    lifecycle: TestOnlyRealWalletLifecycle, *, key: str, mint: str = MINT
) -> RealWalletLiveIntent:
    intent = await lifecycle.create_buy(
        idempotency_key=key,
        mint_address=mint,
        strategy_id="test_strategy",
        strategy_version="v1",
        wallet_public_key=WALLET,
        requested_usd=Decimal("5"),
    )
    assert await lifecycle.advance(intent.id, at=NOW) == ExecutionState.SAFETY_APPROVED
    assert await lifecycle.advance(intent.id, at=NOW) == ExecutionState.SUBMITTED
    return intent


async def test_mocked_buy_confirm_position_sell_confirm_close_is_exactly_once(
    db_session: AsyncSession,
) -> None:
    orders = _Orders()
    transport = _Transport([_success("buy-signature"), _success("sell-signature")])
    lifecycle = TestOnlyRealWalletLifecycle(
        db_session,
        order_factory=orders,
        signer=_Signer(),
        transport=transport,
        reconciler=_Receipts(
            {
                "buy-signature": ChainReceipt(
                    outcome=ChainOutcome.CONFIRMED,
                    signature="buy-signature",
                    actual_input_amount="5000000",
                    actual_input_decimals=6,
                    actual_output_amount="2500000",
                    actual_output_decimals=6,
                    network_fee_lamports=5000,
                ),
                "sell-signature": ChainReceipt(
                    outcome=ChainOutcome.CONFIRMED,
                    signature="sell-signature",
                    actual_input_amount="2500000",
                    actual_input_decimals=6,
                    actual_output_amount="5123456",
                    actual_output_decimals=6,
                    network_fee_lamports=5000,
                ),
            }
        ),
    )

    buy = await _submit_buy(lifecycle, key="signal-1:buy")
    duplicate = await lifecycle.create_buy(
        idempotency_key="signal-1:buy",
        mint_address=MINT,
        strategy_id="test_strategy",
        strategy_version="v1",
        wallet_public_key=WALLET,
        requested_usd=Decimal("5"),
    )
    assert duplicate.id == buy.id
    assert len(transport.calls) == 1

    assert await lifecycle.recover(at=NOW) == {
        "stranded_failed": 0,
        "unresolved_reconciled": 1,
    }
    position = await db_session.scalar(select(RealWalletPosition))
    assert position is not None
    assert position.status == "OPEN"
    assert position.quantity == Decimal("2.5")
    assert position.entry_actual_input_amount == Decimal("5")
    assert position.entry_actual_output_amount == Decimal("2.5")

    sell = await lifecycle.create_sell(
        idempotency_key="position-1:sell", position_id=position.id
    )
    assert sell.requested_token_quantity == position.quantity
    assert await lifecycle.advance(sell.id, at=NOW) == ExecutionState.SAFETY_APPROVED
    assert await lifecycle.advance(sell.id, at=NOW) == ExecutionState.SUBMITTED
    assert len(transport.calls) == 2

    await lifecycle.recover(at=NOW)
    positions = list((await db_session.scalars(select(RealWalletPosition))).all())
    assert len(positions) == 1
    closed = positions[0]
    assert closed.status == "CLOSED"
    assert closed.exit_actual_input_amount == closed.quantity == Decimal("2.5")
    assert closed.exit_actual_output_amount == Decimal("5.123456")
    assert closed.realised_gross_pnl_usd == Decimal("0.123456")
    assert closed.realised_net_pnl_usd == Decimal("0.123456")
    assert await db_session.scalar(select(func.count()).select_from(PaperPosition)) == 0

    events = await db_session.scalar(
        select(func.count())
        .select_from(RealWalletExecutionEvent)
        .where(
            RealWalletExecutionEvent.intent_id == buy.id,
            RealWalletExecutionEvent.event_type == ExecutionState.CONFIRMED,
        )
    )
    assert events == 1


async def test_unknown_submit_is_never_resent_and_recovery_requires_reconciliation(
    db_session: AsyncSession,
) -> None:
    transport = _Transport(
        [
            JupiterExecutionResult(
                outcome=JupiterExecuteOutcome.UNKNOWN,
                signature=None,
                total_input_amount=None,
                total_output_amount=None,
                error_code=None,
            )
        ]
    )
    lifecycle = TestOnlyRealWalletLifecycle(
        db_session,
        order_factory=_Orders(),
        signer=_Signer(),
        transport=transport,
        reconciler=_Receipts({}),
    )
    intent = await _submit_buy(lifecycle, key="unknown-submit:buy", mint="UnknownMint")
    assert len(transport.calls) == 1

    # A duplicate delivery after the network outcome is uncertain cannot call
    # the transport again, even before the recovery worker runs.
    assert await lifecycle.advance(intent.id, at=NOW) == ExecutionState.SUBMITTED
    assert len(transport.calls) == 1
    await lifecycle.recover(at=NOW)
    recovered = await LiveIntentRepository(db_session).by_id(intent.id)
    assert recovered is not None
    assert recovered.state == ExecutionState.RECONCILIATION_REQUIRED
    assert len(transport.calls) == 1


async def test_crash_before_submit_fails_closed_and_counts_consecutive_failures(
    db_session: AsyncSession,
) -> None:
    repository = LiveIntentRepository(db_session)
    intent = await repository.create_intent(
        idempotency_key="crash:buy",
        mint_address="CrashMint",
        side="BUY",
        strategy_id="test_strategy",
        strategy_version="v1",
        wallet_public_key=WALLET,
        requested_usd=Decimal("5"),
        input_mint="USDC",
        output_mint="CrashMint",
    )
    assert intent is not None
    await repository.transition(
        intent=intent,
        next_state=ExecutionState.SAFETY_APPROVED,
        detail={},
        at=NOW,
    )
    await repository.transition(
        intent=intent,
        next_state=ExecutionState.ORDER_CREATED,
        detail={},
        at=NOW,
    )
    await db_session.commit()

    lifecycle = TestOnlyRealWalletLifecycle(
        db_session,
        order_factory=_Orders(),
        signer=_Signer(),
        transport=_Transport([]),
        reconciler=_Receipts({}),
    )
    assert await lifecycle.recover(at=NOW) == {
        "stranded_failed": 1,
        "unresolved_reconciled": 0,
    }
    recovered = await repository.by_id(intent.id)
    assert recovered is not None
    assert recovered.state == ExecutionState.FAILED
    health = await repository.health()
    assert health is not None
    assert health.consecutive_failures == 1


async def test_two_terminal_execution_failures_activate_kill_switch_and_block_next_submit(
    db_session: AsyncSession,
) -> None:
    failure = JupiterExecutionResult(
        outcome=JupiterExecuteOutcome.FAILED,
        signature=None,
        total_input_amount=None,
        total_output_amount=None,
        error_code="mock_execute_failed",
    )
    transport = _Transport([failure, failure, _success("must-not-run")])
    orders = _Orders()
    lifecycle = TestOnlyRealWalletLifecycle(
        db_session,
        order_factory=orders,
        signer=_Signer(),
        transport=transport,
        reconciler=_Receipts({}),
    )
    for key in ("failed-1", "failed-2"):
        intent = await lifecycle.create_buy(
            idempotency_key=key,
            mint_address=f"{key}-mint",
            strategy_id="test_strategy",
            strategy_version="v1",
            wallet_public_key=WALLET,
            requested_usd=Decimal("5"),
        )
        assert await lifecycle.advance(intent.id, at=NOW) == ExecutionState.SAFETY_APPROVED
        assert await lifecycle.advance(intent.id, at=NOW) == ExecutionState.FAILED
    assert len(transport.calls) == 2

    blocked = await lifecycle.create_buy(
        idempotency_key="blocked-3",
        mint_address="blocked-mint",
        strategy_id="test_strategy",
        strategy_version="v1",
        wallet_public_key=WALLET,
        requested_usd=Decimal("5"),
    )
    assert await lifecycle.advance(blocked.id, at=NOW) == ExecutionState.SAFETY_APPROVED
    assert await lifecycle.advance(blocked.id, at=NOW) == ExecutionState.BLOCKED
    assert len(transport.calls) == 2
    assert len(orders.calls) == 2
