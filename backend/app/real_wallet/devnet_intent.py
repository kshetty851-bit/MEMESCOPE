"""Pure Phase 2 manual-devnet intent lifecycle.

This module has no signer, HTTP client, or submission transport.  Its only
job is to make an invalid transition impossible before I/O boundaries are
introduced.
"""

from __future__ import annotations

from enum import StrEnum


class DevnetIntentState(StrEnum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    SIMULATED = "SIMULATED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    SIGNED = "SIGNED"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


_TRANSITIONS: dict[DevnetIntentState, frozenset[DevnetIntentState]] = {
    DevnetIntentState.DRAFT: frozenset(
        {
            DevnetIntentState.QUOTED,
            DevnetIntentState.FAILED,
            DevnetIntentState.CANCELLED,
            DevnetIntentState.EXPIRED,
        }
    ),
    DevnetIntentState.QUOTED: frozenset(
        {
            DevnetIntentState.SIMULATED,
            DevnetIntentState.FAILED,
            DevnetIntentState.EXPIRED,
            DevnetIntentState.CANCELLED,
        }
    ),
    DevnetIntentState.SIMULATED: frozenset(
        {
            DevnetIntentState.AWAITING_APPROVAL,
            DevnetIntentState.FAILED,
            DevnetIntentState.EXPIRED,
        }
    ),
    DevnetIntentState.AWAITING_APPROVAL: frozenset(
        {
            DevnetIntentState.APPROVED,
            DevnetIntentState.FAILED,
            DevnetIntentState.CANCELLED,
            DevnetIntentState.EXPIRED,
        }
    ),
    DevnetIntentState.APPROVED: frozenset(
        {
            DevnetIntentState.SIGNED,
            DevnetIntentState.EXPIRED,
            DevnetIntentState.FAILED,
        }
    ),
    DevnetIntentState.SIGNED: frozenset(
        {
            DevnetIntentState.SUBMITTED,
            DevnetIntentState.FAILED,
            DevnetIntentState.EXPIRED,
        }
    ),
    DevnetIntentState.SUBMITTED: frozenset(
        {
            DevnetIntentState.CONFIRMED,
            DevnetIntentState.FAILED,
            DevnetIntentState.EXPIRED,
        }
    ),
    DevnetIntentState.CONFIRMED: frozenset(),
    DevnetIntentState.FAILED: frozenset(),
    DevnetIntentState.CANCELLED: frozenset(),
    DevnetIntentState.EXPIRED: frozenset(),
}


class DevnetIntentTransitionError(ValueError):
    pass


def require_transition(*, current: str, next_state: str) -> None:
    try:
        before = DevnetIntentState(current)
        after = DevnetIntentState(next_state)
    except ValueError as exc:
        raise DevnetIntentTransitionError("unknown_devnet_intent_state") from exc
    if after not in _TRANSITIONS[before]:
        raise DevnetIntentTransitionError(f"invalid_devnet_intent_transition:{before}:{after}")
