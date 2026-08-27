"""Regression tests for the no-submit live-readiness boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings
from app.models.real_wallet_execution import RealWalletExecutionEvent, RealWalletLiveIntent
from app.real_wallet.live_readiness import (
    ArmedExecutionTransport,
    ExecutionState,
    InvalidExecutionTransitionError,
    LiveSubmissionGuard,
    RealSubmissionUnavailableError,
    SubmissionFacts,
    assert_transition,
)
from app.real_wallet.live_repository import (
    ConcurrentIntentTransitionError,
    LiveIntentRepository,
)
from app.real_wallet.reconciliation import (
    ChainOutcome,
    ChainReceipt,
    RealWalletReconciliationService,
    TransactionReconciler,
)

pytestmark = pytest.mark.unit


def _facts(**overrides: bool) -> SubmissionFacts:
    values = {
        "signer_ready": True,
        "signer_matches_pinned_key": True,
        "safety_passed": True,
        "safety_fresh": True,
        "policy_passed": True,
        "valid_intent": True,
        "not_previously_submitted": True,
        "order_fresh": True,
        "market_fresh": True,
        "kill_switch_active": False,
        "daily_loss_within_limit": True,
        "open_position_within_limit": True,
        "trade_size_within_limit": True,
        "mainnet_verified": True,
        "transaction_approved": True,
        "not_previously_signed": True,
        "canary_limits_satisfied": True,
        "transport_release_approved": True,
        # The operator start/stop control. `off` refuses on its own, which is
        # exactly what the exhaustiveness test below then proves per field.
        "autotrade_switch_on": True,
    }
    values.update(overrides)
    return SubmissionFacts(**values)


def test_the_facts_helper_covers_every_field_the_guard_reads() -> None:
    """A field added to SubmissionFacts without being added here would silently
    stop being exercised — the helper must stay exhaustive."""
    # `SubmissionFacts` is a slots dataclass, so it has no __dict__ — asdict is
    # the only way to enumerate what an instance actually carries.
    from dataclasses import asdict, fields

    assert {f.name for f in fields(SubmissionFacts)} == set(asdict(_facts()))


def test_every_submission_fact_defaults_to_refusing() -> None:
    """A caller that forgets a fact must be refused, never accidentally allowed.

    This is the property that makes adding a condition safe: a new field cannot
    silently pass at an existing call site, because the unset value is the one
    that blocks.
    """
    decision = LiveSubmissionGuard().evaluate(SubmissionFacts())
    assert decision.allowed is False
    assert "KILL_SWITCH_ACTIVE" in decision.reasons


def test_disabled_dry_run_and_armed_modes_cannot_submit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for mode in ("disabled", "dry_run", "armed"):
        monkeypatch.setattr(settings, "REAL_WALLET_EXECUTION_MODE", mode)
        decision = LiveSubmissionGuard().evaluate(_facts())
        assert decision.allowed is False
        assert "MODE_NOT_LIVE" in decision.reasons


def test_live_guard_requires_every_server_derived_condition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "REAL_WALLET_EXECUTION_MODE", "live")
    monkeypatch.setattr(settings, "REAL_WALLET_EXECUTION_ENABLED", True)
    monkeypatch.setattr(settings, "REAL_WALLET_AUTOTRADE_ENABLED", True)
    assert LiveSubmissionGuard().evaluate(_facts()).allowed is True

    decision = LiveSubmissionGuard().evaluate(
        _facts(safety_fresh=False, signer_matches_pinned_key=False, kill_switch_active=True)
    )
    assert decision.allowed is False
    assert {"SAFETY_STALE", "SIGNER_PUBLIC_KEY_MISMATCH", "KILL_SWITCH_ACTIVE"} <= set(
        decision.reasons
    )


def test_impossible_state_regressions_are_rejected() -> None:
    assert_transition(
        current=ExecutionState.CREATED, next_state=ExecutionState.SAFETY_APPROVED
    )
    with pytest.raises(InvalidExecutionTransitionError):
        assert_transition(current=ExecutionState.CONFIRMED, next_state=ExecutionState.CREATED)


async def test_armed_transport_refuses_execute_without_accepting_a_payload() -> None:
    with pytest.raises(RealSubmissionUnavailableError, match="not_installed"):
        await ArmedExecutionTransport().execute(intent_id="intent", request_id="request")


def test_unknown_execution_mode_is_rejected_by_settings() -> None:
    with pytest.raises(ValidationError):
        Settings(REAL_WALLET_EXECUTION_MODE="unexpected")


async def test_duplicate_live_intent_is_database_idempotent(db_session: AsyncSession) -> None:
    repository = LiveIntentRepository(db_session)
    values = {
        "idempotency_key": "v1-signal:mint:buy",
        "mint_address": "live-readiness-mint",
        "side": "BUY",
        "strategy_id": "trailing_stop_25_v1",
        "strategy_version": "1.0.0",
        "wallet_public_key": "configured-public-key",
        "requested_usd": Decimal("5"),
    }

    assert await repository.create_intent(**values) is not None
    assert await repository.create_intent(**values) is None
    await db_session.flush()
    assert await db_session.scalar(select(func.count(RealWalletLiveIntent.id))) == 1
    assert await db_session.scalar(select(func.count(RealWalletExecutionEvent.id))) == 1


async def test_stale_worker_cannot_append_a_second_transition_event(
    db_session: AsyncSession,
) -> None:
    repository = LiveIntentRepository(db_session)
    intent = await repository.create_intent(
        idempotency_key="v1-signal:mint:transition",
        mint_address="live-transition-mint",
        side="BUY",
        strategy_id="trailing_stop_25_v1",
        strategy_version="1.0.0",
        wallet_public_key="configured-public-key",
        requested_usd=Decimal("5"),
    )
    assert intent is not None
    await repository.transition(
        intent=intent,
        next_state=ExecutionState.SAFETY_APPROVED,
        detail={},
        at=datetime.now(UTC),
    )
    stale = SimpleNamespace(id=intent.id, state=ExecutionState.CREATED)
    with pytest.raises(ConcurrentIntentTransitionError):
        await repository.transition(
            intent=stale,  # type: ignore[arg-type]
            next_state=ExecutionState.SAFETY_APPROVED,
            detail={},
            at=datetime.now(UTC),
        )
    await db_session.flush()
    assert await db_session.scalar(select(func.count(RealWalletExecutionEvent.id))) == 2


class _UnknownReconciler(TransactionReconciler):
    async def inspect(self, intent: RealWalletLiveIntent) -> ChainReceipt:
        del intent
        return ChainReceipt(outcome=ChainOutcome.UNKNOWN)


class _RecordingRepository:
    def __init__(self) -> None:
        self.transitions: list[tuple[ExecutionState, dict[str, object]]] = []

    async def transition(self, **kwargs: object) -> None:
        self.transitions.append((kwargs["next_state"], kwargs["detail"]))  # type: ignore[arg-type]


async def test_unknown_submission_requires_reconciliation_without_resubmission() -> None:
    repository = _RecordingRepository()
    intent = SimpleNamespace(state=ExecutionState.SUBMITTED)
    outcome = await RealWalletReconciliationService(
        repository=repository,  # type: ignore[arg-type]
        reconciler=_UnknownReconciler(),
    ).reconcile(intent=intent, at=datetime.now(UTC))  # type: ignore[arg-type]

    assert outcome is ChainOutcome.UNKNOWN
    assert repository.transitions == [
        (
            ExecutionState.RECONCILIATION_REQUIRED,
            {
                "reconciled": True,
                "outcome": "unknown",
                "confirmed_evidence_complete": False,
            },
        )
    ]
