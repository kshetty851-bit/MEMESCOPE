"""What Karthik may do, and the far longer list of what he may not.

§7 of the brief is the reason this file exists as *code* rather than as a
paragraph in a README. The boundary it describes — Karthik operates the Karthik
Paper Wallet and touches nothing else — is only worth something if a wrong
call fails at runtime instead of shipping.

── THE SHAPE OF THE GUARANTEE ───────────────────────────────────────────

Two frozen sets and one function. `SAFE_REPAIRS` is the complete list of
operational faults Karthik may act on; `FORBIDDEN_STRATEGY_IDS` is the set of
wallets he may never be bound to. Both are compiled into the image, and the
only way to add an entry is a code change that goes through review. There is no
name taken from a request body and resolved to a callable, no `eval`, no
dynamic import.

`permit()` fails **closed**: an action absent from the allowlist is refused, and
so is an action present in it while autonomy is `OBSERVE_ONLY`. Those are two
different refusals with two different reasons, and the audit trail records
which one happened — "not allowlisted" and "allowlisted but not armed" are very
different facts about a deployment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

#: The two autonomy modes from §23. `OBSERVE_ONLY` is the production default
#: and stays the default until the owner explicitly decides otherwise: §23 is
#: unambiguous that arming this is a separate decision taken *after* reviewing
#: observe-only behaviour, not a flag that rides along with the deployment
#: that introduced it.
AutonomyMode = Literal["OBSERVE_ONLY", "SAFE_AUTOREPAIR"]

#: Read from the environment rather than from `Settings`, following
#: `hq_ops.remediation.autonomy_enabled`. The reason is the same one that
#: applies there: the value has to be readable by a worker that never builds a
#: settings object, and a mis-typed variable must fail to *arm* rather than
#: fail to boot.
AUTONOMY_ENV_VAR = "KARTHIK_AUTONOMY"

#: The env var that binds Karthik to a wallet. Empty means unbound, which is
#: the state the module was written in and the state it must be correct in.
WALLET_ENV_VAR = "KARTHIK_WALLET_STRATEGY_ID"


@dataclass(frozen=True, slots=True)
class SafeRepair:
    """One permitted operational repair.

    Every field is the evidence a reader needs to decide whether the entry is
    reasonable *without* reading the implementation. A repair whose effect
    cannot be described in one sentence is a repair that does not belong on an
    allowlist.
    """

    key: str
    summary: str
    #: What must be true for this to be attempted, in a sentence. Evaluated
    #: against a fresh reading immediately before execution, never against the
    #: reading that triggered detection.
    precondition: str
    #: True when the action changes nothing a later run could not redo. Every
    #: entry here is reversible; the field exists so an irreversible one could
    #: never be added without somebody typing `False` and being asked why.
    reversible: bool


#: **The complete list of things Karthik may do to a running system.**
#:
#: Every entry is derived from §8 and every one of them acts on *derived or
#: transient* state: a cache, a subscription, a read model, a heartbeat, an
#: idempotent job. Not one of them writes a trade, a fill, a price, a cash
#: balance or an accounting row — that is the property that makes the list
#: safe, and it is asserted by a test rather than promised here.
SAFE_REPAIRS: dict[str, SafeRepair] = {
    repair.key: repair
    for repair in (
        SafeRepair(
            key="karthik.monitor_loop_restart",
            summary="Restart Karthik's own monitoring loop after it stopped reporting.",
            precondition=(
                "The loop's heartbeat is older than its expected interval and the worker "
                "itself answers a ping."
            ),
            reversible=True,
        ),
        SafeRepair(
            key="karthik.read_model_refresh",
            summary=(
                "Recompute the derived read model the panel renders from authoritative rows."
            ),
            precondition=(
                "The read model's stamp is older than the newest authoritative row it "
                "summarises."
            ),
            reversible=True,
        ),
        SafeRepair(
            key="karthik.position_subscriptions_reprime",
            summary="Re-prime market subscriptions for open Karthik positions.",
            precondition=(
                "An open position has no quote newer than the staleness window while the "
                "provider is answering."
            ),
            reversible=True,
        ),
        SafeRepair(
            key="karthik.opportunity_job_retry",
            summary="Retry one idempotent opportunity-processing job that failed.",
            precondition=(
                "The job is idempotent, failed, and has been attempted fewer than three times."
            ),
            reversible=True,
        ),
        SafeRepair(
            key="karthik.quote_retry",
            summary="Retry one idempotent quote retrieval.",
            precondition=(
                "The quote request failed transiently and the provider is not rate-limiting."
            ),
            reversible=True,
        ),
        SafeRepair(
            key="karthik.ui_state_repair",
            summary=(
                "Clear stale non-persistent realtime state so the panel stops showing a "
                "superseded reading."
            ),
            precondition=(
                "The cached reading is older than the authoritative row it claims to describe."
            ),
            reversible=True,
        ),
        SafeRepair(
            key="karthik.report_rerun",
            summary="Re-run a report that was scheduled and did not produce a row.",
            precondition=(
                "The report's window has closed, no row exists for it, and its inputs are "
                "readable."
            ),
            reversible=True,
        ),
    )
}

#: Wallets Karthik must never be bound to.
#:
#: §7's isolation requirement, enforced at the point where it can actually be
#: violated: binding. Listing the *strategy ids* rather than the wallet rows is
#: deliberate — a generation can be archived and relaunched, and the identity
#: worth protecting is the rules, not the row.
FORBIDDEN_STRATEGY_IDS: frozenset[str] = frozenset(
    {
        # Original Paper Wallet, every generation of it.
        "equal_weight_v1",
        "trailing_stop_25_v1",
        "trailing_stop_25_secured_v2",
        "trailing_stop_25_secured_hold6h_v3",
        "survival_s2_v1_1",
        "paper_2x_trail25_v1",
        "paper_all_scanned_tp125_sl50_v1",
        "paper_track_record_tp125_sl50_v1",
        "universe_trailing_stop_25_v1",
    }
)


def autonomy() -> AutonomyMode:
    """The current mode. Anything unrecognised reads as `OBSERVE_ONLY`.

    Deliberately not a strict parse that raises. A typo in a deployment
    variable must degrade to the safe mode, not take the process down — and it
    must not silently arm, which is the failure an `in ("true","1")` style
    check would have if somebody ever inverted it.
    """
    raw = os.getenv(AUTONOMY_ENV_VAR, "").strip().upper()
    return "SAFE_AUTOREPAIR" if raw == "SAFE_AUTOREPAIR" else "OBSERVE_ONLY"


@dataclass(frozen=True, slots=True)
class Permission:
    """The answer to "may this run", and why. Recorded verbatim in the audit."""

    allowed: bool
    reason: str
    #: `not_allowlisted` | `observe_only` | `allowed`. A machine-readable
    #: version of `reason`, so the panel can style the two refusals apart.
    verdict: str


def permit(action_key: str, *, mode: AutonomyMode | None = None) -> Permission:
    """May Karthik execute `action_key` right now?

    Fails closed on both axes. An unknown key is refused because it is not on
    the list; a known key under `OBSERVE_ONLY` is refused because nothing is
    armed. Keeping those apart matters: the first is a bug or an attack, the
    second is the intended state of a fresh production deployment.
    """
    resolved = mode if mode is not None else autonomy()
    repair = SAFE_REPAIRS.get(action_key)
    if repair is None:
        return Permission(
            allowed=False,
            verdict="not_allowlisted",
            reason=(
                f"{action_key!r} is not in Karthik's allowlist. Refused without "
                f"evaluation — the allowlist is the whole permission model."
            ),
        )
    if resolved != "SAFE_AUTOREPAIR":
        return Permission(
            allowed=False,
            verdict="observe_only",
            reason=(
                f"{action_key!r} is allowlisted but Karthik is in OBSERVE_ONLY. "
                f"Detected, diagnosed and recorded; nothing executed."
            ),
        )
    return Permission(allowed=True, verdict="allowed", reason=repair.summary)
