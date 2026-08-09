"""Fail-closed components for the future real-wallet execution boundary.

Nothing in this module can submit a Solana transaction.  It deliberately
models the required decision, signing and reconciliation boundaries while the
only installed execution transport is a refusing one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.core.config import settings


class ExecutionState(StrEnum):
    CREATED = "created"
    SAFETY_APPROVED = "safety_approved"
    ORDER_CREATED = "order_created"
    SIGNED = "signed"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    BLOCKED = "blocked"


_TRANSITIONS: dict[ExecutionState, frozenset[ExecutionState]] = {
    ExecutionState.CREATED: frozenset(
        {ExecutionState.SAFETY_APPROVED, ExecutionState.BLOCKED}
    ),
    ExecutionState.SAFETY_APPROVED: frozenset(
        {ExecutionState.ORDER_CREATED, ExecutionState.BLOCKED}
    ),
    ExecutionState.ORDER_CREATED: frozenset(
        {ExecutionState.SIGNED, ExecutionState.FAILED, ExecutionState.BLOCKED}
    ),
    ExecutionState.SIGNED: frozenset(
        {ExecutionState.SUBMITTED, ExecutionState.FAILED, ExecutionState.BLOCKED}
    ),
    ExecutionState.SUBMITTED: frozenset(
        {
            ExecutionState.CONFIRMED,
            ExecutionState.FAILED,
            ExecutionState.RECONCILIATION_REQUIRED,
        }
    ),
    ExecutionState.RECONCILIATION_REQUIRED: frozenset(
        {ExecutionState.CONFIRMED, ExecutionState.FAILED}
    ),
    ExecutionState.CONFIRMED: frozenset(),
    ExecutionState.FAILED: frozenset(),
    ExecutionState.BLOCKED: frozenset(),
}


class InvalidExecutionTransitionError(ValueError):
    """An intent attempted to regress or otherwise bypass the state machine."""


def assert_transition(*, current: str, next_state: str) -> None:
    try:
        source = ExecutionState(current)
        destination = ExecutionState(next_state)
    except ValueError as exc:
        raise InvalidExecutionTransitionError("unknown_execution_state") from exc
    if destination not in _TRANSITIONS[source]:
        raise InvalidExecutionTransitionError(
            f"invalid_execution_transition:{source}:{destination}"
        )


@dataclass(frozen=True, slots=True)
class SubmissionFacts:
    """Server-derived facts required before a future execute call."""

    signer_ready: bool
    signer_matches_pinned_key: bool
    safety_passed: bool
    safety_fresh: bool
    policy_passed: bool
    valid_intent: bool
    not_previously_submitted: bool
    order_fresh: bool
    market_fresh: bool
    kill_switch_active: bool
    daily_loss_within_limit: bool
    open_position_within_limit: bool
    trade_size_within_limit: bool


@dataclass(frozen=True, slots=True)
class SubmissionDecision:
    allowed: bool
    reasons: tuple[str, ...]


class LiveSubmissionGuard:
    """One central, fail-closed decision point for any future `/execute` call."""

    def evaluate(self, facts: SubmissionFacts) -> SubmissionDecision:
        reasons: list[str] = []
        if settings.REAL_WALLET_EXECUTION_MODE != "live":
            reasons.append("MODE_NOT_LIVE")
        if not settings.REAL_WALLET_EXECUTION_ENABLED:
            reasons.append("EXECUTION_DISABLED")
        if not settings.REAL_WALLET_AUTOTRADE_ENABLED:
            reasons.append("AUTOTRADE_DISABLED")
        checks = {
            "SIGNER_UNAVAILABLE": facts.signer_ready,
            "SIGNER_PUBLIC_KEY_MISMATCH": facts.signer_matches_pinned_key,
            "SAFETY_NOT_APPROVED": facts.safety_passed,
            "SAFETY_STALE": facts.safety_fresh,
            "POLICY_REJECTED": facts.policy_passed,
            "INTENT_INVALID": facts.valid_intent,
            "INTENT_ALREADY_SUBMITTED": facts.not_previously_submitted,
            "ORDER_STALE": facts.order_fresh,
            "MARKET_STALE": facts.market_fresh,
            "KILL_SWITCH_ACTIVE": not facts.kill_switch_active,
            "DAILY_LOSS_LIMIT": facts.daily_loss_within_limit,
            "OPEN_POSITION_LIMIT": facts.open_position_within_limit,
            "TRADE_SIZE_LIMIT": facts.trade_size_within_limit,
        }
        reasons.extend(reason for reason, passed in checks.items() if not passed)
        return SubmissionDecision(allowed=not reasons, reasons=tuple(reasons))


class RealSubmissionUnavailableError(RuntimeError):
    """Raised by the deliberately non-networked transport in this release."""


class ArmedExecutionTransport:
    """A permanent no-submit boundary until a separately approved release.

    This type accepts neither a transaction payload nor a signer.  That makes
    accidental wire-up impossible: future live submission needs a new explicit
    transport implementation and a focused security review.
    """

    async def execute(self, *, intent_id: str, request_id: str) -> None:
        del intent_id, request_id
        raise RealSubmissionUnavailableError("real_submission_transport_not_installed")
