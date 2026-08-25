"""The canonical token-security evaluation model.

One vocabulary, shared. Real Wallet already has its own fail-closed policy
gate (`app.real_wallet_safety`), which mixes token security with trade-size
market quality and answers ALLOW/REJECT. That is the right shape for *its*
job and the wrong shape for a shared contract, because it has no way to say
UNKNOWN: a token whose mint account could not be read and a token whose mint
authority is provably revoked both come out as "not ALLOW".

This module exists so the platform can say the third thing.

    SECURITY UNKNOWN IS NOT SECURITY SAFE.

Every check therefore carries its own four-valued status, and the roll-up is
computed rather than asserted. There are no booleans in this file for a fact
that can be unobservable.

Pure: no I/O, no clock, no randomness, no database.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

#: Bumped whenever a check is added, removed, or its pass/fail meaning
#: changes. Persisted on every row so a stored verdict can always be read
#: against the rules that produced it rather than today's.
#:
#: 1.0.0 — HQ-6. `LIQUIDITY_SECURITY` was structurally UNKNOWN for every
#:         token, because nothing in the platform read a pool account.
#: 1.1.0 — SEC-1. `LIQUIDITY_SECURITY` is verified on-chain against the
#:         pump.fun bonding curve and the derived PumpSwap migration pool.
#:         A 1.0.0 row saying UNKNOWN means "never checked"; a 1.1.0 row
#:         saying UNKNOWN means "checked and not establishable", and the two
#:         must never be counted together.
EVALUATOR_VERSION = "1.1.0"


class CheckStatus(enum.StrEnum):
    """The four-valued result of one security check.

    `UNKNOWN` and `NOT_APPLICABLE` are deliberately distinct. A plain SPL mint
    has no Token-2022 extensions to inspect — that is NOT_APPLICABLE, a
    complete answer. A mint whose account could not be fetched has extensions
    that may or may not exist — that is UNKNOWN, an absence of answer. Folding
    them together would let an RPC outage read as a clean bill of health.
    """

    PASS = "PASS"  # noqa: S105 — a check verdict, not a credential
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class SecurityStatus(enum.StrEnum):
    """The roll-up across every check.

    Ordered by severity when combined: one FAIL makes the token FAILED however
    many checks passed, and any remaining UNKNOWN prevents VERIFIED. VERIFIED
    means *every applicable check was actually performed and passed* — it is
    never reachable by silence.
    """

    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class CheckName(enum.StrEnum):
    """The checks this evaluator can genuinely perform.

    Deliberately short. A check is listed here only when the platform has a
    real source for it; a name with no evidence behind it would publish a
    shield the system cannot actually raise.

    Price impact, round-trip loss and quote freshness are **not** here. They
    are market-quality facts, they depend on a trade size, and they belong to
    the Real Wallet's execution policy — see `app.real_wallet_safety`. Mixing
    them in is what made the existing gate unable to answer "is this token
    safe" without first being told how much someone wanted to spend.
    """

    MINT_AUTHORITY = "MINT_AUTHORITY"
    FREEZE_AUTHORITY = "FREEZE_AUTHORITY"
    TOKEN_PROGRAM = "TOKEN_PROGRAM"  # noqa: S105
    TOKEN_EXTENSIONS = "TOKEN_EXTENSIONS"  # noqa: S105
    VENUE = "VENUE"
    LIQUIDITY_SECURITY = "LIQUIDITY_SECURITY"


class Reason:
    """Machine-readable reason codes, stable across releases.

    The first four are **reused verbatim** from `real_wallet_safety.Reason`
    rather than re-spelled, so a code means one thing platform-wide and a
    stored real-wallet row and a stored shared row can be read side by side.
    """

    # --- reused from the Real Wallet policy vocabulary --------------------
    MINT_AUTHORITY_ACTIVE = "MINT_AUTHORITY_ACTIVE"
    FREEZE_AUTHORITY_ACTIVE = "FREEZE_AUTHORITY_ACTIVE"
    UNSUPPORTED_TOKEN_PROGRAM = "UNSUPPORTED_TOKEN_PROGRAM"  # noqa: S105
    UNSUPPORTED_TOKEN_EXTENSION = "UNSUPPORTED_TOKEN_EXTENSION"  # noqa: S105
    VENUE_UNSUPPORTED = "VENUE_UNSUPPORTED"
    TOKEN_CONFIGURATION_UNKNOWN = "TOKEN_CONFIGURATION_UNKNOWN"  # noqa: S105

    # --- new, and only where the shared contract needs to say something --
    #: The mint account could not be read at all. Infrastructure failure,
    #: kept separate from a token that was read and found dangerous.
    MINT_ACCOUNT_UNAVAILABLE = "MINT_ACCOUNT_UNAVAILABLE"
    #: No market snapshot, so no venue to classify.
    VENUE_UNKNOWN = "VENUE_UNKNOWN"
    #: Liquidity security could not be established. Retained from HQ-6 as the
    #: generic fallback; SEC-1 added the specific codes below, which say *why*.
    LIQUIDITY_SECURITY_UNVERIFIED = "LIQUIDITY_SECURITY_UNVERIFIED"

    # --- SEC-1: on-chain liquidity verification --------------------------
    #: No account exists at the derived pump.fun bonding-curve address, or it
    #: is not owned by the pump.fun program.
    BONDING_CURVE_ABSENT = "BONDING_CURVE_ABSENT"
    #: The curve account exists but its bytes do not decode as a curve.
    BONDING_CURVE_INVALID = "BONDING_CURVE_INVALID"
    #: The curve reports `complete`, so the reserves moved somewhere this
    #: evaluation could not then verify.
    MIGRATION_DESTINATION_UNVERIFIED = "MIGRATION_DESTINATION_UNVERIFIED"
    #: No account at the derived canonical migration pool address. The token
    #: did not graduate to PumpSwap through pump.fun, so custody here is a
    #: question this evaluator does not answer.
    POOL_NOT_PROTOCOL_MIGRATED = "POOL_NOT_PROTOCOL_MIGRATED"
    #: The token was never in pump.fun's custody model, so that model has
    #: nothing to say about it. NOT a statement that its LP is safe — see
    #: `liquidity_verifier` for what this does and does not claim.
    POOL_CUSTODY_OUT_OF_SCOPE = "POOL_CUSTODY_OUT_OF_SCOPE"
    #: The pool account is not owned by the PumpSwap program.
    POOL_PROGRAM_MISMATCH = "POOL_PROGRAM_MISMATCH"
    #: The pool account exists but does not decode as a pool.
    POOL_ACCOUNT_INVALID = "POOL_ACCOUNT_INVALID"
    #: The pool's base/quote mint is not the token being evaluated.
    POOL_MINT_MISMATCH = "POOL_MINT_MISMATCH"
    #: A vault is missing, or its authority/mint does not match the pool.
    POOL_VAULT_INVALID = "POOL_VAULT_INVALID"
    #: LP tokens are outstanding, so a redeemable claim on the reserves
    #: exists. Whoever holds them can withdraw; this evaluator does not
    #: resolve holders, so this is UNKNOWN rather than a failure.
    LP_OUTSTANDING = "LP_OUTSTANDING"
    #: LP supply could not be read at all.
    LP_CUSTODY_UNKNOWN = "LP_CUSTODY_UNKNOWN"
    #: A custody mechanism was verified, but it is not the market this
    #: platform prices and would trade. Verifying a bonding curve says nothing
    #: about the Orca pool carrying the token's actual liquidity.
    TRADED_POOL_UNVERIFIED = "TRADED_POOL_UNVERIFIED"
    #: Evidence exists but is older than the check's own freshness window.
    EVIDENCE_STALE = "EVIDENCE_STALE"


#: How long each check's evidence stays usable, per check, because the facts
#: age at genuinely different rates.
#:
#: Mint and freeze authority are the long ones on purpose and the reason is
#: cryptographic rather than conservative: `SetAuthority` to `None` on a mint
#: is **irreversible**. A revoked authority can never come back, so a stored
#: "revoked" reading stays true indefinitely. The window is not there to guard
#: the fact; it is there to re-confirm that the *reading* was of the right
#: account. The reverse direction has no such guarantee — an authority that is
#: active today can be revoked in the next block — which is why an ACTIVE
#: reading is the one that must never be cached long.
#:
#: Venue and liquidity security follow the market and get short windows.
CHECK_FRESHNESS: dict[CheckName, timedelta] = {
    CheckName.MINT_AUTHORITY: timedelta(hours=24),
    CheckName.FREEZE_AUTHORITY: timedelta(hours=24),
    CheckName.TOKEN_PROGRAM: timedelta(hours=24),
    CheckName.TOKEN_EXTENSIONS: timedelta(hours=24),
    CheckName.VENUE: timedelta(minutes=15),
    CheckName.LIQUIDITY_SECURITY: timedelta(minutes=15),
}

#: The shortest window above. An evaluation older than this has at least one
#: check that can no longer be trusted as current.
EVALUATION_FRESHNESS = min(CHECK_FRESHNESS.values())


@dataclass(frozen=True, slots=True)
class SecurityCheck:
    """One named check, its verdict, and why.

    `evidence` carries the raw fact the verdict was read from — the authority
    flag, the venue string, the extension discriminants — so a stored row can
    be re-argued later without re-running the RPC.
    """

    name: CheckName
    status: CheckStatus
    reason_codes: tuple[str, ...] = ()
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {
            "name": str(self.name),
            "status": str(self.status),
            "reason_codes": list(self.reason_codes),
            "detail": self.detail,
            "evidence": self.evidence,
        }


def roll_up(checks: tuple[SecurityCheck, ...]) -> SecurityStatus:
    """Combine per-check statuses into one verdict.

    FAIL dominates: a token with one proven dangerous property is FAILED
    whatever else passed. UNKNOWN then dominates PASS, which is the whole
    point of the contract — VERIFIED requires that every applicable check was
    performed and returned PASS, so an evaluation that could not read
    something can never round up to safe.

    An evaluation with no checks at all is UNKNOWN, not VERIFIED: vacuous
    truth is exactly the failure mode this function exists to prevent.
    """
    if not checks:
        return SecurityStatus.UNKNOWN
    if any(check.status is CheckStatus.FAIL for check in checks):
        return SecurityStatus.FAILED
    if any(check.status is CheckStatus.UNKNOWN for check in checks):
        return SecurityStatus.UNKNOWN
    return SecurityStatus.VERIFIED


@dataclass(frozen=True, slots=True)
class TokenSecurityEvaluation:
    """One token, evaluated once, with everything needed to re-read it later.

    Immutable by construction. A persisted evaluation is historical evidence:
    it answers "what did we know about this mint at that instant", and it must
    keep answering that even after the token's security state has moved on.
    """

    mint_address: str
    evaluated_at: datetime
    overall_status: SecurityStatus
    checks: tuple[SecurityCheck, ...]
    evaluator_version: str = EVALUATOR_VERSION
    market_snapshot_at: datetime | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def reason_codes(self) -> tuple[str, ...]:
        """Every reason across every check, de-duplicated, order preserved."""
        codes: dict[str, None] = {}
        for check in self.checks:
            for code in check.reason_codes:
                codes[code] = None
        return tuple(codes)

    def check(self, name: CheckName) -> SecurityCheck | None:
        for item in self.checks:
            if item.name is name:
                return item
        return None

    def is_fresh(self, *, now: datetime | None = None) -> bool:
        """Whether every check is still inside its own freshness window."""
        moment = (now or datetime.now(UTC)).astimezone(UTC)
        return all(
            moment - self.evaluated_at <= CHECK_FRESHNESS[check.name]
            for check in self.checks
        )

    def stale_checks(self, *, now: datetime | None = None) -> tuple[CheckName, ...]:
        moment = (now or datetime.now(UTC)).astimezone(UTC)
        return tuple(
            check.name
            for check in self.checks
            if moment - self.evaluated_at > CHECK_FRESHNESS[check.name]
        )

    def as_json(self) -> dict[str, Any]:
        return {
            "mint_address": self.mint_address,
            "evaluated_at": self.evaluated_at.isoformat(),
            "overall_status": str(self.overall_status),
            "evaluator_version": self.evaluator_version,
            "market_snapshot_at": (
                self.market_snapshot_at.isoformat() if self.market_snapshot_at else None
            ),
            "reason_codes": list(self.reason_codes),
            "checks": [check.as_json() for check in self.checks],
            "evidence": self.evidence,
        }
