"""The one authoritative security decision for a new Paper entry.

Pure: no I/O, no clock of its own, no database. Given an evaluation and a
moment, it answers whether an entry may proceed. Everything that enforces
security calls *this* — the service that opens positions and the repository
invariant that backstops it — so there is exactly one place where the policy
lives and exactly one place to change it.

TWO CONCEPTS THAT MUST NOT COLLAPSE (§0)
----------------------------------------

    TOKEN SECURITY VERDICT   what the chain says about the token
    ENTRY AVAILABILITY       whether the wallet may buy it right now

They are not the same, and the difference is the whole reason this module is
separate from the evaluator. An RPC outage produces:

    security verdict  : UNKNOWN — nothing was established
    entry availability: REFUSED FOR NOW
    token label       : *not* unsafe

while an active mint authority produces:

    security verdict  : FAILED — a dangerous property was positively read
    entry availability: REFUSED
    token label       : unsafe

Both refuse the buy. Only one is a statement about the token. Calling an RPC
timeout "unsafe token" would poison the reason codes that later analysis
depends on, and would make a provider incident look like a wave of dangerous
launches.

WHY UNKNOWN BLOCKS ANYWAY
-------------------------

`LP_OUTSTANDING` is the case that makes this concrete. SEC-1 established that
LP holders are not resolved, so an outstanding LP supply is genuinely UNKNOWN
rather than FAIL — somebody can redeem those reserves and the platform cannot
say who. It is not evidence of an unsafe token, and it is not good enough to
buy against either. UNKNOWN refuses without being relabelled (§9).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.security.contract import (
    CHECK_FRESHNESS,
    EVALUATOR_VERSION,
    CheckName,
    CheckStatus,
    Reason,
    SecurityStatus,
    TokenSecurityEvaluation,
)

#: Every check that must positively PASS before a new Paper entry (§3).
#:
#: `TOKEN_EXTENSIONS` is the one member that may legitimately answer
#: NOT_APPLICABLE — a plain SPL mint has no extensions to carry, which is a
#: complete answer rather than a missing one. No other check may.
MANDATORY_CHECKS: tuple[CheckName, ...] = (
    CheckName.MINT_AUTHORITY,
    CheckName.FREEZE_AUTHORITY,
    CheckName.TOKEN_PROGRAM,
    CheckName.TOKEN_EXTENSIONS,
    CheckName.VENUE,
    CheckName.LIQUIDITY_SECURITY,
)

#: Checks whose NOT_APPLICABLE is an answer rather than a gap. Deliberately a
#: allowlist: a future check that starts returning NOT_APPLICABLE will block
#: entry until somebody decides it should not, which is the safe direction.
NOT_APPLICABLE_ALLOWED: frozenset[CheckName] = frozenset({CheckName.TOKEN_EXTENSIONS})

#: The oldest security evidence that may authorise a buy (§15).
#:
#: Taken from the shared contract's shortest per-check window rather than
#: invented here, so freshness at execution and freshness in the evaluator can
#: never disagree. Today that is the liquidity/venue window — the two facts
#: that actually move.
MAX_EVIDENCE_AGE = min(CHECK_FRESHNESS.values())

#: Reason codes that mean "the platform could not look", not "the token is
#: dangerous". Used only to classify the refusal, never to soften it.
INFRASTRUCTURE_REASONS: frozenset[str] = frozenset(
    {
        Reason.MINT_ACCOUNT_UNAVAILABLE,
        Reason.TOKEN_CONFIGURATION_UNKNOWN,
        Reason.LIQUIDITY_SECURITY_UNVERIFIED,
        Reason.LP_CUSTODY_UNKNOWN,
    }
)


class EntryOutcome(enum.StrEnum):
    """Whether the wallet may open a position, and why not when it may not."""

    #: Every mandatory check positively passed on fresh evidence.
    ALLOWED = "ALLOWED"
    #: A dangerous property was positively established.
    REFUSED_UNSAFE = "REFUSED_UNSAFE"
    #: Evidence exists and does not establish safety. The token is not
    #: labelled unsafe; it is simply not verified.
    REFUSED_UNKNOWN = "REFUSED_UNKNOWN"
    #: The platform could not evaluate. Retryable on a later candidate pass;
    #: says nothing at all about the token (§6).
    REFUSED_UNAVAILABLE = "REFUSED_UNAVAILABLE"


#: The single canonical refusal code recorded on a candidate decision, beside
#: the detailed per-check codes. Aggregate and detail both survive (§8).
SECURITY_GATE_REFUSAL = "security_gate"


@dataclass(frozen=True, slots=True)
class EntryDecision:
    outcome: EntryOutcome
    #: The evaluator's own verdict, unmodified. An UNKNOWN evaluation stays
    #: UNKNOWN here even though entry is refused (§5).
    security_status: SecurityStatus | None
    reason_codes: tuple[str, ...]
    detail: str
    evaluation_id: str | None = None
    evaluator_version: str | None = None
    evaluated_at: datetime | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.outcome is EntryOutcome.ALLOWED

    @property
    def retryable(self) -> bool:
        """Whether a later pass could plausibly reach a different answer.

        Only infrastructure refusals are retryable *as a classification*. It
        does not schedule anything: the token is reconsidered if and when it
        comes round again as an ordinary candidate (§7), and nothing here
        creates a queue, a backoff or a second pipeline.
        """
        return self.outcome is EntryOutcome.REFUSED_UNAVAILABLE

    def as_json(self) -> dict[str, Any]:
        return {
            "outcome": str(self.outcome),
            "security_status": (
                str(self.security_status) if self.security_status else None
            ),
            "reason_codes": list(self.reason_codes),
            "detail": self.detail,
            "evaluation_id": self.evaluation_id,
            "evaluator_version": self.evaluator_version,
            "evaluated_at": (
                self.evaluated_at.isoformat() if self.evaluated_at else None
            ),
        }


def _refuse(
    outcome: EntryOutcome,
    status: SecurityStatus | None,
    detail: str,
    codes: tuple[str, ...],
    evaluation: TokenSecurityEvaluation | None = None,
) -> EntryDecision:
    return EntryDecision(
        outcome=outcome,
        security_status=status,
        reason_codes=codes,
        detail=detail,
        evaluator_version=(evaluation.evaluator_version if evaluation else None),
        evaluated_at=(evaluation.evaluated_at if evaluation else None),
    )


def decide(
    evaluation: TokenSecurityEvaluation | None,
    *,
    now: datetime,
    evaluation_id: str | None = None,
    max_age: object = None,
) -> EntryDecision:
    """May this token be bought right now?

    Fail-closed at every step, and in this order, because the order is what
    keeps the *reason* honest: a missing evaluation is an availability
    problem, a stale one is an availability problem, and only evidence that is
    present and current is allowed to say anything about the token itself.
    """
    window = max_age if max_age is not None else MAX_EVIDENCE_AGE
    moment = now.astimezone(UTC)

    # --- is there anything to read? -------------------------------------
    if evaluation is None:
        return _refuse(
            EntryOutcome.REFUSED_UNAVAILABLE,
            None,
            "No security evaluation exists for this token yet.",
            (Reason.LIQUIDITY_SECURITY_UNVERIFIED,),
        )

    # --- was it produced by rules this build understands? ----------------
    # A row written by a *newer* evaluator may encode checks whose meaning
    # this build does not know; an older one may predate a check entirely.
    # HQ-6's own contract says a 1.0.0 UNKNOWN means "never checked" while a
    # 1.1.0 UNKNOWN means "checked and not establishable" — counting them
    # together would be exactly the silent downgrade this phase forbids.
    if evaluation.evaluator_version != EVALUATOR_VERSION:
        return _refuse(
            EntryOutcome.REFUSED_UNAVAILABLE,
            evaluation.overall_status,
            (
                f"Evaluation was produced by evaluator {evaluation.evaluator_version}, "
                f"and this build enforces {EVALUATOR_VERSION}."
            ),
            (Reason.EVIDENCE_STALE,),
            evaluation,
        )

    # --- is it current enough to authorise a buy? (§15, §16) -------------
    age = moment - evaluation.evaluated_at.astimezone(UTC)
    if age < timedelta(0) or age > window:
        return _refuse(
            EntryOutcome.REFUSED_UNAVAILABLE,
            evaluation.overall_status,
            "The security evaluation is older than a buy may rely on.",
            (Reason.EVIDENCE_STALE,),
            evaluation,
        )
    stale = evaluation.stale_checks(now=moment)
    if stale:
        return _refuse(
            EntryOutcome.REFUSED_UNAVAILABLE,
            evaluation.overall_status,
            "Part of the security evidence has aged past its own window: "
            + ", ".join(str(name) for name in stale),
            (Reason.EVIDENCE_STALE,),
            evaluation,
        )

    # --- every mandatory check, individually ----------------------------
    failed: list[str] = []
    unknown: list[str] = []
    missing: list[str] = []
    for name in MANDATORY_CHECKS:
        check = evaluation.check(name)
        if check is None:
            missing.append(str(name))
            continue
        if check.status is CheckStatus.PASS:
            continue
        if check.status is CheckStatus.NOT_APPLICABLE:
            if name not in NOT_APPLICABLE_ALLOWED:
                missing.append(str(name))
            continue
        if check.status is CheckStatus.FAIL:
            failed.extend(check.reason_codes or (str(name),))
        else:
            unknown.extend(check.reason_codes or (str(name),))

    if missing:
        return _refuse(
            EntryOutcome.REFUSED_UNAVAILABLE,
            evaluation.overall_status,
            "The evaluation does not carry every mandatory check: "
            + ", ".join(missing),
            (Reason.LIQUIDITY_SECURITY_UNVERIFIED,),
            evaluation,
        )

    # A positively dangerous property outranks an unresolved one: if a token
    # both fails and is unresolved, the failure is the honest headline.
    if failed:
        return EntryDecision(
            outcome=EntryOutcome.REFUSED_UNSAFE,
            security_status=evaluation.overall_status,
            reason_codes=tuple(dict.fromkeys(failed)),
            detail="A dangerous condition was positively established on-chain.",
            evaluation_id=evaluation_id,
            evaluator_version=evaluation.evaluator_version,
            evaluated_at=evaluation.evaluated_at,
        )

    if unknown:
        codes = tuple(dict.fromkeys(unknown))
        # Infrastructure and evidence-based UNKNOWN both refuse, and are
        # classified apart so a provider incident never reads as a wave of
        # dangerous tokens (§6).
        infrastructure = all(code in INFRASTRUCTURE_REASONS for code in codes)
        return EntryDecision(
            outcome=(
                EntryOutcome.REFUSED_UNAVAILABLE
                if infrastructure
                else EntryOutcome.REFUSED_UNKNOWN
            ),
            security_status=evaluation.overall_status,
            reason_codes=codes,
            detail=(
                "Security could not be checked; this is not a finding about the token."
                if infrastructure
                else "Security could not be established for this token."
            ),
            evaluation_id=evaluation_id,
            evaluator_version=evaluation.evaluator_version,
            evaluated_at=evaluation.evaluated_at,
        )

    # --- belt and braces -------------------------------------------------
    # Every mandatory check passed, so the roll-up must agree. If it does not,
    # something is inconsistent and the safe reading is "not verified".
    if evaluation.overall_status is not SecurityStatus.VERIFIED:
        return _refuse(
            EntryOutcome.REFUSED_UNKNOWN,
            evaluation.overall_status,
            "Mandatory checks passed but the overall verdict is not VERIFIED.",
            (Reason.LIQUIDITY_SECURITY_UNVERIFIED,),
            evaluation,
        )

    return EntryDecision(
        outcome=EntryOutcome.ALLOWED,
        security_status=SecurityStatus.VERIFIED,
        reason_codes=(),
        detail="Every mandatory security check passed on current evidence.",
        evaluation_id=evaluation_id,
        evaluator_version=evaluation.evaluator_version,
        evaluated_at=evaluation.evaluated_at,
        evidence={
            "mechanism": (
                (evaluation.check(CheckName.LIQUIDITY_SECURITY) or {}).evidence.get(
                    "mechanism"
                )
                if evaluation.check(CheckName.LIQUIDITY_SECURITY)
                else None
            )
        },
    )
