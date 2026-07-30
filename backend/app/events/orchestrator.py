"""The event orchestrator — the only component permitted to run a cycle.

## Why a single entry point matters

Event generation is not idempotent in the way a score is. Running the detector
twice against a moving cache would compare a state against itself and report
nothing, silently losing a change; running it from two places at once would
interleave cache writes and lose changes non-deterministically. So there is
exactly one function that advances the event log, and it holds the transaction.

## The transaction boundary is the whole design

A cycle writes two things per token: the events it detected, and the new cached
state. Those must land together or not at all.

If events commit and the cache does not, the next cycle re-detects the same
changes against the stale cache and re-emits them — the deduplication key
saves the log but the run is wasted. If the cache commits and the events do
not, the change is **lost permanently**: the cache now says "we already saw
this", so no future cycle will ever report it. That second failure is silent
and unrecoverable, which is why the commit is at the end of the whole batch
rather than per token.

## What this deliberately does not do

It does not analyse. Readings come from the existing analysts via the
orchestrator in `app/analysts`, unchanged. It does not decide what counts as a
change — `events/detector.py` owns that. This module loads, compares, persists
and reports. Every judgement it appears to make belongs to something else.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.analysts import orchestrator as analysts
from app.analysts.base import AnalystId
from app.core.logging import get_logger
from app.events.detector import TokenState, detect
from app.events.repository import EventRepository
from app.radar.repository import RadarRepository
from app.repositories.token import TokenRepository
from app.services.identity import assess as assess_identity

logger = get_logger(__name__)


@dataclass(slots=True)
class CycleSummary:
    """Operational telemetry for one run.

    Mutable during the cycle and reported at the end. `events_skipped` is the
    difference between what the detector proposed and what the log accepted, so
    a persistent gap there means deduplication is firing — usually a sign the
    cycle is running more often than state actually moves.
    """

    analysed: int = 0
    changed: int = 0
    events_generated: int = 0
    events_skipped: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    failures: int = 0
    elapsed_ms: int = 0
    failure_detail: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "analysed": self.analysed,
            "changed": self.changed,
            "events_generated": self.events_generated,
            "events_skipped": self.events_skipped,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "failures": self.failures,
            "elapsed_ms": self.elapsed_ms,
            "failure_detail": self.failure_detail[:10],
        }


class EventOrchestrator:
    """Runs event cycles. One instance per session, one cycle per call."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._events = EventRepository(session)
        self._radar = RadarRepository(session)
        self._tokens = TokenRepository(session)

    async def run_cycle(
        self, mints: list[str], *, now: datetime | None = None
    ) -> CycleSummary:
        """Analyse, compare, record. Commits once at the end.

        A token that fails is counted and skipped; one bad series must not cost
        the whole batch. Failures are logged at error level with the mint
        attached — there are no silent exceptions here, because a cycle that
        quietly drops tokens looks identical to a quiet market.
        """
        started = time.perf_counter()
        moment = now or datetime.now(UTC)
        summary = CycleSummary()

        if not mints:
            summary.elapsed_ms = int((time.perf_counter() - started) * 1000)
            return summary

        # Two batched lookups for the whole cycle rather than per token: the
        # previous states, and the name collisions clone risk needs.
        previous = await self._events.cached_states(mints)
        collisions = await self._tokens.name_collisions(mints)

        pending_states: list[TokenState] = []
        proposed = 0

        for mint in mints:
            try:
                state = await self._observe(mint, collisions, moment)
            except Exception as exc:
                summary.failures += 1
                summary.failure_detail.append(f"{mint}: {type(exc).__name__}: {exc}")
                logger.exception("event_cycle_token_failed", mint=mint)
                continue

            if state is None:
                continue

            summary.analysed += 1
            before = previous.get(mint)
            if before is None:
                summary.cache_misses += 1
            else:
                summary.cache_hits += 1

            events = detect(before, state)
            if events:
                summary.changed += 1
                proposed += len(events)
                landed = await self._events.record(events, occurred_at=moment)
                summary.events_generated += landed

            pending_states.append(state)

        for state in pending_states:
            await self._events.remember_state(state, observed_at=moment)

        # Events and cache land together. See the module docstring: a cache that
        # commits without its events loses the change permanently.
        await self._session.commit()

        summary.events_skipped = proposed - summary.events_generated
        summary.elapsed_ms = int((time.perf_counter() - started) * 1000)

        logger.info("event_cycle_completed", **summary.as_dict())
        return summary

    async def _observe(
        self,
        mint: str,
        collisions: dict[str, tuple[int, int]],
        moment: datetime,
    ) -> TokenState | None:
        """Current state for one token, from the existing analysts.

        Returns None when there is nothing to observe — a token with no market
        history is not a change, and emitting a first-sighting event for it
        would put a row in the log for something the platform cannot read.
        """
        series = await self._radar.load_series(mint)
        if series is None:
            return None

        entry = await self._radar.get(mint)
        found = collisions.get(mint)
        identity = (
            assess_identity(sharing_name=found[0], discovered_before=found[1])
            if found is not None
            else None
        )

        days_since = Decimal(0)
        if entry is not None:
            days_since = Decimal((moment - entry.first_detected_at).total_seconds()) / Decimal(
                86_400
            )

        verdict = analysts.assess(
            series,
            current_multiple=entry.current_multiple if entry else None,
            peak_multiple=entry.peak_multiple if entry else None,
            days_since_detection=days_since,
            clone_risk=identity.clone_risk.value if identity else None,
            sharing_name=identity.sharing_name if identity else 1,
        )

        readings = verdict.readings
        return TokenState(
            mint_address=mint,
            mission_state=verdict.mission_state,
            research_priority=verdict.priority,
            combined_score=verdict.score,
            confidence=verdict.confidence,
            liquidity_score=readings[AnalystId.LIQUIDITY].score,
            momentum_score=readings[AnalystId.MOMENTUM].score,
            risk_score=readings[AnalystId.RISK].score,
            clone_risk=identity.clone_risk.value if identity else None,
            exit_severity=None,
            warning_codes=frozenset(w.code for w in verdict.warnings),
        )
