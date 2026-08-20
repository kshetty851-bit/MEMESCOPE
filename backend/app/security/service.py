"""Where security evaluation is *scheduled*, and why it is scheduled there.

THE FUNNEL, AS THE CODE ACTUALLY RUNS IT

    scanner discovers a mint            ~thousands
      -> radar_tokens row
    enrichment prices it                 market-qualified
      -> token_market_snapshots
    scoring ranks it                     scored
      -> radar entries, ordered
    PaperWalletService._open_entries reads the top N by score
      -> eligibility.judge() per row     candidates
      -> the eligible ones               <- SECURITY EVALUATES HERE
      -> strategy.entry_for()
      -> a position

Evaluating at discovery would mean one `getAccountInfo` for every mint the
scanner ever sees, most of which are never priced, never scored and never
considered. Evaluating at the scored stage still means an RPC per Radar row
per pass, on a review that runs every minute.

The eligible set is the right place because it is the smallest set that
still contains every token the wallet could actually buy. A token that
`judge()` refused cannot be bought this pass whatever its security says, so
evaluating it buys no information about a trade that could happen; a token
`judge()` passed is one decision away from a position, so its security is
the fact the platform most needs and does not have.

The set is small by construction — `judge()` refuses on already-traded
first, so on a typical pass it is a handful of rows, not the top 250.

IT DOES NOT GATE ANYTHING IN THIS PHASE.

`evaluate_candidates` is called for its evidence and its return value is
discarded by the caller. A FAILED verdict does not remove a candidate, does
not change a refusal count, and does not reach the strategy. That is
deliberate and temporary: the phase measures the consequence of enforcement
before anyone enables it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.security.contract import EVALUATOR_VERSION, TokenSecurityEvaluation
from app.security.evaluator import TokenSecurityEvaluator
from app.security.repository import TokenSecurityRepository
from app.services.rpc.base import SolanaRPC

logger = get_logger(__name__)


def _reusable(evaluation: TokenSecurityEvaluation, now: datetime) -> bool:
    """Whether a stored evaluation can stand in for a fresh one.

    Freshness alone is not enough, and SEC-2 found that the hard way: a row
    written by an older evaluator can be minutes old and still be unusable,
    because a version bump changes what a verdict *means*. HQ-6's own contract
    says a 1.0.0 UNKNOWN means "never checked" while a 1.1.0 UNKNOWN means
    "checked and not establishable".

    Without this check the cache served pre-SEC-1 rows to the entry gate,
    which refused them as stale — so after any evaluator bump a full freshness
    window of candidates would be blocked while perfectly good evidence sat
    one RPC call away. Measured at 23 of 80 candidates before the fix.
    """
    return (
        evaluation.evaluator_version == EVALUATOR_VERSION
        and evaluation.is_fresh(now=now)
    )


class TokenSecurityService:
    """Evaluate, cache by freshness, and persist. Never decides a trade."""

    def __init__(self, session: AsyncSession, *, rpc: SolanaRPC | None = None) -> None:
        self._session = session
        self._repository = TokenSecurityRepository(session)
        self._evaluator = TokenSecurityEvaluator(session, rpc=rpc)

    async def evaluate_candidates(
        self, mints: Sequence[str], *, now: datetime | None = None
    ) -> list[TokenSecurityEvaluation]:
        """Evaluate up to the configured cap, reusing anything still fresh.

        Bounded three ways, because an unbounded security sweep would starve
        the enrichment and paper lanes it shares a worker with:

        * the cap, so one pass can never fan out further than configured;
        * per-check freshness, so a mint inspected minutes ago is not
          re-inspected — most passes therefore make no RPC call at all;
        * sequential execution, so N mints are N calls spread over time
          rather than N simultaneous connections to one node.
        """
        moment = (now or datetime.now(UTC)).astimezone(UTC)
        wanted = list(dict.fromkeys(mints))[: settings.TOKEN_SECURITY_MAX_PER_PASS]
        if not wanted:
            return []

        cached = await self._repository.latest_for_mints(wanted)
        results: list[TokenSecurityEvaluation] = []
        for mint in wanted:
            existing = cached.get(mint)
            if existing is not None and _reusable(existing, moment):
                results.append(existing)
                continue
            evaluation = await self._evaluator.evaluate(mint_address=mint, now=moment)
            await self._repository.record(evaluation)
            results.append(evaluation)
        return results

    async def evaluate_now(
        self, mint: str, *, now: datetime | None = None
    ) -> TokenSecurityEvaluation:
        """One mint, unconditionally re-read. For analysis and backfill only."""
        evaluation = await self._evaluator.evaluate(mint_address=mint, now=now)
        await self._repository.record(evaluation)
        return evaluation


async def capture_candidate_security(
    session: AsyncSession, mints: Sequence[str], *, now: datetime | None = None
) -> None:
    """Best-effort evidence capture from inside the paper review pass.

    Swallows everything, on the same principle as `paper.research_ledger`:
    observation must never be able to change a trading decision, and the
    loudest possible failure of this phase would be a security *audit* that
    stopped the wallet it was auditing.
    """
    if not settings.TOKEN_SECURITY_EVALUATION_ENABLED or not mints:
        return
    try:
        await TokenSecurityService(session).evaluate_candidates(mints, now=now)
    except Exception:
        logger.exception("token_security_capture_failed", mints=list(mints)[:10])
