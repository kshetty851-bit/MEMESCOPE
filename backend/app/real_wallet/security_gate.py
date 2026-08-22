"""The SEC-2 gate, for real money, using the same code Paper uses.

## Why this module is three lines of logic and a long comment

Real Wallet already had a security gate: `RealWalletSafetyGate` in
`app.real_wallet_safety`. It reads mint authority, freeze authority, the token
program and its extensions, the venue, liquidity, and both sides of a Jupiter
quote — genuinely good work, and *a second implementation of the same policy*.

Two implementations of "is this token safe to buy" is the failure mode SEC-2
exists to prevent. They drift. One gets a fix the other does not. Paper reports
a strategy's results under one definition of safe while Real spends money under
another, and the paper track record stops being evidence for the real one.

So this does not re-derive anything. It calls `TokenSecurityService` — the same
evaluator, the same cache, the same freshness contract — and hands the result to
`entry_policy.decide`, the same pure function `PaperService` calls before it
opens a position. Identical inputs produce an identical verdict by construction
rather than by review.

`RealWalletSafetyGate` is deliberately *not* deleted. It checks things SEC-2
does not — round-trip loss, price impact on both sides, position-to-liquidity
ratio, execution-price deviation — which are execution-quality questions rather
than token-safety ones. Both must pass. This one is the veto that Paper shares.

## Fail-closed, and the reason it says why

UNKNOWN, stale, missing, evaluator-version mismatch and infrastructure outage
all refuse. They refuse with *different* outcomes because `entry_policy` already
draws the distinction that matters: `REFUSED_UNSAFE` is a statement about the
token, `REFUSED_UNAVAILABLE` is a statement about the platform. Collapsing them
would make an RPC incident look like a wave of dangerous launches, in the real
ledger as well as the paper one.

Nothing here signs, submits, sizes, or enables anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.security import entry_policy
from app.security.service import TokenSecurityService

logger = get_logger(__name__)

#: The canonical refusal recorded on a real intent when SEC-2 says no. The
#: per-check codes travel beside it; the aggregate is what the dashboard counts.
REAL_SECURITY_GATE_REFUSAL = "real_security_gate"


@dataclass(frozen=True, slots=True)
class RealSecurityVerdict:
    """One SEC-2 answer for one prospective real BUY."""

    decision: entry_policy.EntryDecision
    #: True only for `ALLOWED`. Every other outcome — including every flavour of
    #: UNKNOWN — is a refusal, so callers never have to interpret an enum.
    allowed: bool
    #: True when the evidence was present, current, and produced by the
    #: evaluator version this build enforces. A caller records this separately
    #: from `allowed` so "we checked and it failed" is distinguishable from
    #: "we could not check", which is the whole point of §6.
    evidence_fresh: bool

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return self.decision.reason_codes

    def as_json(self) -> dict[str, object]:
        return {
            **self.decision.as_json(),
            "gate": "sec2_shared_with_paper",
            "evidence_fresh": self.evidence_fresh,
        }


async def evaluate_real_entry(
    session: AsyncSession, *, mint_address: str, now: datetime | None = None
) -> RealSecurityVerdict:
    """Ask SEC-2 whether this mint may be bought with real money right now.

    Time-of-check/time-of-use: the evidence is re-read here, immediately before
    the buy, exactly as `PaperService._security_for_entry` does. The service
    reuses a cached row only inside its own freshness window and re-runs the RPC
    otherwise, and `entry_policy.decide` then age-checks again — against
    `MAX_EVIDENCE_AGE` and against each check's own window. A PASS that expired
    between evaluation and use cannot authorise a real buy.

    Any exception from the security service is an *availability* refusal. A
    security service that is down must stop entries without labelling anything
    unsafe.
    """
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    try:
        evaluations = await TokenSecurityService(session).evaluate_candidates(
            [mint_address], now=moment
        )
        evaluation = evaluations[0] if evaluations else None
    except Exception:
        logger.warning("real_security_gate_unavailable", mint_address=mint_address)
        evaluation = None

    decision = entry_policy.decide(evaluation, now=moment)
    return RealSecurityVerdict(
        decision=decision,
        allowed=decision.outcome is entry_policy.EntryOutcome.ALLOWED,
        evidence_fresh=decision.outcome is not entry_policy.EntryOutcome.REFUSED_UNAVAILABLE,
    )
