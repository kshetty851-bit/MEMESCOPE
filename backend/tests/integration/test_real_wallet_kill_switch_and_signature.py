"""The kill switch's exit, and the signature that makes a lost response survivable.

Two durable properties that had no coverage because neither had an
implementation: a switch could be armed and never cleared, and a signature was
only ever written after `/execute` answered.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.real_wallet_execution import (
    RealWalletKillSwitchEvent,
    RealWalletLiveIntent,
)
from app.real_wallet.live_readiness import (
    ExecutionState,
    LiveSubmissionGuard,
    SubmissionFacts,
)
from app.real_wallet.live_repository import (
    ConcurrentIntentTransitionError,
    LiveIntentRepository,
)
from app.real_wallet.transport_policy import readiness as transport_readiness

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
MINT = "M" * 44
WALLET = "W" * 44


async def _intent(repository: LiveIntentRepository, key: str):
    intent = await repository.create_intent(
        idempotency_key=key,
        mint_address=MINT,
        side="BUY",
        strategy_id="s",
        strategy_version="1",
        wallet_public_key=WALLET,
        input_mint=settings.JUPITER_USDC_MINT,
        output_mint=MINT,
    )
    assert intent is not None
    return intent


@pytest.mark.asyncio
async def test_a_kill_switch_can_be_cleared_only_with_an_actor_and_a_reason(
    db_session: AsyncSession,
) -> None:
    repository = LiveIntentRepository(db_session)
    await repository.activate_kill_switch(
        kind="consecutive_execution_failures", reason="failure_threshold", at=NOW
    )
    await db_session.commit()
    assert len(await repository.active_kill_switches()) == 1

    with pytest.raises(ValueError, match="actor_and_reason"):
        await repository.clear_kill_switch(
            kind="consecutive_execution_failures", actor="", reason="", at=NOW
        )

    cleared = await repository.clear_kill_switch(
        kind="consecutive_execution_failures",
        actor="admin@example.com",
        reason="investigated the RPC outage that armed it",
        at=NOW,
    )
    await db_session.commit()
    assert cleared is True
    assert await repository.active_kill_switches() == []

    # Clearing something already clear is False, not an exception and not a
    # second audit row: a repeated clear is a no-op, not an event.
    assert (
        await repository.clear_kill_switch(
            kind="consecutive_execution_failures",
            actor="admin@example.com",
            reason="again, for no reason",
            at=NOW,
        )
        is False
    )
    await db_session.commit()

    events = list(
        (
            await db_session.scalars(
                select(RealWalletKillSwitchEvent).order_by(
                    RealWalletKillSwitchEvent.created_at
                )
            )
        ).all()
    )
    assert [event.action for event in events] == ["armed", "cleared"]
    assert events[1].actor == "admin@example.com"
    assert "investigated" in events[1].reason


@pytest.mark.asyncio
async def test_clearing_a_kill_switch_does_not_unlock_anything_else(
    db_session: AsyncSession,
) -> None:
    """The clear removes one barrier. Every other barrier is untouched."""
    repository = LiveIntentRepository(db_session)
    await repository.activate_kill_switch(kind="manual", reason="operator", at=NOW)
    await db_session.commit()
    await repository.clear_kill_switch(
        kind="manual", actor="admin@example.com", reason="stand down after drill", at=NOW
    )
    await db_session.commit()

    # Kill switch inactive, and submission is still refused for every other
    # reason there is.
    decision = LiveSubmissionGuard().evaluate(SubmissionFacts(kill_switch_active=False))
    assert decision.allowed is False
    assert "KILL_SWITCH_ACTIVE" not in decision.reasons
    assert transport_readiness().submission_permitted is False


@pytest.mark.asyncio
async def test_the_failure_counter_survives_a_cleared_switch(
    db_session: AsyncSession,
) -> None:
    """Zeroing the counter on clear would let a repeating fault start clean each time."""
    repository = LiveIntentRepository(db_session)
    for _ in range(settings.REAL_WALLET_MAX_CONSECUTIVE_EXECUTION_FAILURES):
        await repository.record_execution_failure(reason="rpc_timeout", at=NOW)
    await db_session.commit()
    assert len(await repository.active_kill_switches()) == 1

    await repository.clear_kill_switch(
        kind="consecutive_execution_failures",
        actor="admin@example.com",
        reason="restarted the RPC provider",
        at=NOW,
    )
    await db_session.commit()

    health = await repository.health()
    assert health is not None
    assert (
        health.consecutive_failures
        >= settings.REAL_WALLET_MAX_CONSECUTIVE_EXECUTION_FAILURES
    )
    # So the very next failure re-arms immediately rather than after a fresh run.
    await repository.record_execution_failure(reason="rpc_timeout", at=NOW)
    await db_session.commit()
    assert len(await repository.active_kill_switches()) == 1


@pytest.mark.asyncio
async def test_a_signature_persisted_before_submission_survives_a_lost_response(
    db_session: AsyncSession,
) -> None:
    """The property that turns an unknown submission into a reconcilable one."""
    repository = LiveIntentRepository(db_session)
    intent = await _intent(repository, "signature-durability")
    for state in (
        ExecutionState.SAFETY_APPROVED,
        ExecutionState.ORDER_CREATED,
        ExecutionState.SIGNED,
    ):
        await repository.transition(intent=intent, next_state=state, at=NOW, detail={})
    await repository.record_signature_before_submission(
        intent=intent, signature="Sig" + "1" * 40, at=NOW
    )
    await repository.transition(
        intent=intent, next_state=ExecutionState.SUBMITTED, at=NOW, detail={}
    )
    await db_session.commit()

    # `/execute` timed out: the outcome is unknown and carries no signature.
    await repository.record_submission_result(
        intent=intent, signature=None, outcome="unknown"
    )
    await db_session.commit()

    # Read the columns straight back from the database rather than from the
    # identity map, so this asserts what was persisted and not what the session
    # happens to still be holding.
    row = (
        await db_session.execute(
            select(
                RealWalletLiveIntent.transaction_signature, RealWalletLiveIntent.state
            ).where(RealWalletLiveIntent.id == intent.id)
        )
    ).one()
    # The signature is still there. Reconciliation can ask the chain.
    assert row.transaction_signature == "Sig" + "1" * 40
    assert row.state == ExecutionState.SUBMITTED


@pytest.mark.asyncio
async def test_the_same_intent_cannot_be_signed_twice(
    db_session: AsyncSession,
) -> None:
    repository = LiveIntentRepository(db_session)
    intent = await _intent(repository, "double-sign")
    for state in (
        ExecutionState.SAFETY_APPROVED,
        ExecutionState.ORDER_CREATED,
        ExecutionState.SIGNED,
    ):
        await repository.transition(intent=intent, next_state=state, at=NOW, detail={})
    await repository.record_signature_before_submission(
        intent=intent, signature="Sig" + "2" * 40, at=NOW
    )
    await db_session.commit()

    with pytest.raises(ConcurrentIntentTransitionError):
        await repository.record_signature_before_submission(
            intent=intent, signature="Sig" + "3" * 40, at=NOW
        )
