"""TokenScoringService - the only module in this package that touches a database.

Everything else under `app/services/scoring/` is pure. This module is the seam:
it loads what the engine needs, calls it, and writes down what came back. It
holds no scoring logic of its own - no weights, no thresholds, no arithmetic on
scores - so the engine stays independently testable and this stays a thin,
readable orchestration.

**Transaction boundary.** The service never commits. It writes into the session
it was handed and returns the events its caller should publish *after* that
session commits. Publishing before the commit would let an event describe a
score that never landed; owning the commit would stop the enrichment worker from
deciding what belongs in one transaction.

**Independence.** Nothing here imports `services.market` beyond the scheduler's
frozen policy. A scoring failure can therefore never damage enrichment: the
worker runs scoring in its own transaction, after snapshots are already durable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.market import TokenMarketSnapshot
from app.models.score import ScoreTrigger, TokenScoreHistory
from app.models.token import DiscoveredToken
from app.repositories.market import MarketSnapshotRepository
from app.repositories.score import ScoreHistoryRepository, ScoreRepository
from app.repositories.token import TokenRepository
from app.services.market.scheduler import SchedulePolicy
from app.services.scoring.engine import ScoreResult, evaluate
from app.services.scoring.features import build_feature_set, window_seconds_for
from app.services.scoring.grading import EliteGate
from app.services.scoring.materiality import (
    MaterialityPolicy,
    PreviousScore,
    decide,
)
from app.services.scoring.models.base import ModelConfig
from app.services.scoring.models.registry import get_model

logger = get_logger(__name__)

HUNDRED = Decimal(100)


@dataclass(frozen=True, slots=True)
class ScoringOutcome:
    """What one scoring pass did. Mirrors `EnrichmentOutcome` in shape and intent."""

    requested: int = 0
    scored: int = 0
    #: Had no market data yet, or too little declared weight to score honestly.
    skipped: int = 0
    #: Token row missing entirely - a mint was passed that we never discovered.
    unknown: int = 0
    history_written: int = 0
    failed: int = 0
    #: Published by the caller *after* commit, never from inside this service.
    events: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, int]:
        return {
            "requested": self.requested,
            "scored": self.scored,
            "skipped": self.skipped,
            "unknown": self.unknown,
            "history_written": self.history_written,
            "failed": self.failed,
        }


class TokenScoringService:
    """Scores tokens and persists the result. One instance per session."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        model: ModelConfig | None = None,
        policy: SchedulePolicy | None = None,
    ) -> None:
        self.session = session
        # Resolved once per instance. An unknown `SCORING_MODEL_VERSION` raises
        # here - at service construction, before any token is touched - rather
        # than silently scoring with a model nobody chose.
        self.model = model or get_model()
        self.policy = policy or SchedulePolicy.from_settings()
        self.tokens = TokenRepository(session)
        self.snapshots = MarketSnapshotRepository(session)
        self.scores = ScoreRepository(session)
        self.history = ScoreHistoryRepository(session)

    # --- Public API ----------------------------------------------------------

    async def score_mints(
        self, mint_addresses: Sequence[str], *, now: datetime | None = None
    ) -> ScoringOutcome:
        """Evaluate and persist scores for a batch of mints.

        Three queries for the whole batch regardless of its size: the snapshot
        window, the current scores, and recent history. The alternative - a
        query per token - would put a round trip in the hot path for every
        token on every refresh.
        """
        if not mint_addresses:
            return ScoringOutcome()

        evaluated_at = now or datetime.now(UTC)
        mints = list(dict.fromkeys(mint_addresses))

        tokens = await self.tokens.get_many_by_mints(mints)
        known = [mint for mint in mints if mint in tokens]
        unknown = len(mints) - len(known)
        if unknown:
            logger.warning("scoring_unknown_mints", count=unknown)
        if not known:
            return ScoringOutcome(requested=len(mints), unknown=unknown)

        # Two queries for the batch. The current `token_scores` rows are
        # deliberately *not* loaded: materiality, the delta, and the Elite
        # streak all come from history, and the stale-write guard lives in the
        # upsert's SQL. Reading them would be a round trip whose result nothing
        # consumes.
        windows = await self._load_windows(tokens, known, now=evaluated_at)
        recent_history = await self.history.recent_for_mints(
            known, limit_per_mint=self.model.elite_gate.sustain_evaluations + 1
        )

        score_rows: list[dict[str, Any]] = []
        history_rows: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        scored = skipped = failed = 0

        for mint in known:
            token = tokens[mint]
            history_rows_for_mint = recent_history.get(mint, [])
            window = windows.get(mint, [])
            # A token with no indexed pool yet has an empty window; that is a
            # normal state, and the engine reports it as unscorable rather than
            # this loop having to special-case it.
            latest_snapshot = window[0] if window else None

            try:
                result = self._evaluate(
                    token,
                    window,
                    history=history_rows_for_mint,
                    now=evaluated_at,
                )
            except Exception:
                # One token's failure must not cost the batch. The score simply
                # is not updated; the sweep will retry it.
                failed += 1
                logger.exception("scoring_failed", mint=mint)
                continue

            if not result.scorable:
                skipped += 1
                continue

            score_rows.append(self._to_score_row(token, result, latest_snapshot, evaluated_at))
            scored += 1

            decision = decide(
                score=result.score,
                grade=result.grade,
                is_elite=result.is_elite,
                has_veto=result.has_veto,
                evaluated_at=evaluated_at,
                previous=_previous_of(history_rows_for_mint),
                policy=self._materiality_policy(),
            )
            if decision.write_history:
                history_rows.append(
                    self._to_history_row(
                        token,
                        result,
                        latest_snapshot,
                        evaluated_at,
                        decision.trigger,
                        decision.delta,
                    )
                )
                events.append(
                    _event_of(result, decision.delta, evaluated_at, decision.trigger)
                )

        written = await self.scores.upsert_many(score_rows)
        await self.history.add_many(history_rows)

        # Only announce what actually landed. A row rejected by the monotonic
        # guard is a stale evaluation losing to a fresher one, and broadcasting
        # it would tell subscribers the score moved backwards.
        applied = set(written)
        events = [event for event in events if event["mint_address"] in applied]

        logger.info(
            "scoring_completed",
            requested=len(mints),
            scored=scored,
            skipped=skipped,
            history=len(history_rows),
            failed=failed,
            model_version=self.model.version,
        )

        return ScoringOutcome(
            requested=len(mints),
            scored=scored,
            skipped=skipped,
            unknown=unknown,
            history_written=len(history_rows),
            failed=failed,
            events=tuple(events),
        )

    async def find_stale(self, *, now: datetime, limit: int) -> list[str]:
        """Mints whose score is older than their own tier allows.

        Staleness is tier-relative, so it cannot be expressed as one SQL
        predicate. The cheapest bound - the fastest tier's - pre-filters in the
        database, and each candidate is then checked against its own tier here.
        That keeps one indexed query in front of a small in-memory pass instead
        of scanning the table per tier.
        """
        multiple = settings.SCORING_STALE_AFTER_TIER_MULTIPLE
        widest_candidate_cutoff = now - timedelta(
            seconds=multiple * self.policy.fresh_interval_seconds
        )
        candidates = await self.scores.stale_before(
            cutoff=widest_candidate_cutoff, limit=limit
        )
        if not candidates:
            return []

        tokens = await self.tokens.get_many_by_mints([row.mint_address for row in candidates])

        stale: list[str] = []
        for row in candidates:
            token = tokens.get(row.mint_address)
            if token is None:  # pragma: no cover - see below
                # Unreachable in practice: `token_scores.token_id` cascades on
                # delete, so a score cannot outlive its token, and both reads
                # share one transaction snapshot. Kept so that relaxing the
                # cascade later degrades to skipping the row rather than to an
                # AttributeError inside a scheduled job.
                continue
            _, interval, _ = self._window_for(token, now=now)
            if (now - row.evaluated_at).total_seconds() >= multiple * interval:
                stale.append(row.mint_address)
        return stale

    def scorable_since(self, *, now: datetime) -> datetime:
        """The oldest snapshot the engine could still build any window from.

        A token whose newest observation predates this cannot be scored under
        any tier: `window_seconds_for` clamps the history window to
        `K x tier_interval`, so the widest window in the system is the slowest
        tier's. Selecting such a token can only ever produce a skip.

        Derived from the policy rather than hardcoded, so raising
        `SCORING_FEATURE_WINDOW` or the old tier's interval widens this with it
        and the sweep does not silently start ignoring tokens it could score.
        """
        widest = max(
            window_seconds_for(
                Decimal(0), policy=self.policy, feature_window=settings.SCORING_FEATURE_WINDOW
            )[2],
            # The tier is chosen by age, so ask the policy directly for the
            # slowest interval rather than inventing an age that maps to it.
            min(
                max(
                    settings.SCORING_FEATURE_WINDOW * self.policy.old_interval_seconds,
                    settings.SCORING_WINDOW_MIN_SECONDS,
                ),
                settings.SCORING_WINDOW_MAX_SECONDS,
            ),
        )
        return now - timedelta(seconds=widest)

    # --- Internals -----------------------------------------------------------

    def _materiality_policy(self) -> MaterialityPolicy:
        return MaterialityPolicy(
            min_delta=Decimal(str(settings.SCORING_HISTORY_MIN_DELTA)),
            grade_deadband=Decimal(str(settings.SCORING_GRADE_DEADBAND)),
            min_interval_seconds=settings.SCORING_HISTORY_MIN_INTERVAL_SECONDS,
        )

    def _window_for(self, token: DiscoveredToken, *, now: datetime) -> tuple[str, int, int]:
        origin = token.block_time or token.discovered_at
        age_minutes = Decimal(max(0.0, (now - origin).total_seconds())) / Decimal(60)
        return window_seconds_for(age_minutes, policy=self.policy)

    async def _load_windows(
        self,
        tokens: dict[str, DiscoveredToken],
        mints: Sequence[str],
        *,
        now: datetime,
    ) -> dict[str, list[TokenMarketSnapshot]]:
        """Load the snapshot window for every mint in one query.

        Tiers differ within a batch, so the query uses the widest window present
        and `build_feature_set` trims each token to its own. One round trip,
        with the trimming done where the per-token tier is already known.
        """
        widest = max(
            (self._window_for(tokens[mint], now=now)[2] for mint in mints),
            default=settings.SCORING_WINDOW_MIN_SECONDS,
        )
        return await self.snapshots.window_for_mints(
            mints,
            since=now - timedelta(seconds=widest),
            limit_per_mint=settings.SCORING_FEATURE_WINDOW,
        )

    def _evaluate(
        self,
        token: DiscoveredToken,
        snapshots: Sequence[TokenMarketSnapshot],
        *,
        history: Sequence[TokenScoreHistory],
        now: datetime,
    ) -> ScoreResult:
        features = build_feature_set(
            token,
            snapshots,
            now=now,
            policy=self.policy,
            prior_elite_streak=_elite_streak_from(history, self.model.elite_gate),
        )
        return evaluate(
            features,
            self.model,
            min_observations=settings.SCORING_MIN_OBSERVATIONS,
        )

    @staticmethod
    def _to_score_row(
        token: DiscoveredToken,
        result: ScoreResult,
        snapshot: TokenMarketSnapshot | None,
        evaluated_at: datetime,
    ) -> dict[str, Any]:
        return {
            "token_id": token.id,
            "mint_address": token.mint_address,
            "model_version": result.model_version,
            "score": result.score,
            "evidence": result.evidence,
            "coverage": result.coverage,
            "market_risk": result.market_risk,
            "opportunity_raw": result.opportunity_raw,
            "observations": result.observations,
            "grade": result.grade,
            "is_elite": result.is_elite,
            "has_veto": result.has_veto,
            "latest_snapshot_at": snapshot.captured_at if snapshot else None,
            "evaluated_at": evaluated_at,
            "source_snapshot_captured_at": snapshot.captured_at if snapshot else None,
        }

    @staticmethod
    def _to_history_row(
        token: DiscoveredToken,
        result: ScoreResult,
        snapshot: TokenMarketSnapshot | None,
        evaluated_at: datetime,
        trigger: ScoreTrigger,
        delta: Decimal | None,
    ) -> dict[str, Any]:
        return {
            "token_id": token.id,
            "mint_address": token.mint_address,
            "model_version": result.model_version,
            "score": result.score,
            "evidence": result.evidence,
            "coverage": result.coverage,
            "market_risk": result.market_risk,
            "opportunity_raw": result.opportunity_raw,
            "observations": result.observations,
            "grade": result.grade,
            "is_elite": result.is_elite,
            "has_veto": result.has_veto,
            "components": _components_of(result),
            "reasons": [str(code) for code in result.reasons],
            "delta": delta,
            "trigger": str(trigger),
            "latest_snapshot_at": snapshot.captured_at if snapshot else None,
            "evaluated_at": evaluated_at,
            "source_snapshot_captured_at": snapshot.captured_at if snapshot else None,
        }


# --- Module helpers -----------------------------------------------------------


def _previous_of(history: Sequence[TokenScoreHistory]) -> PreviousScore | None:
    """The newest history row, as the value object materiality expects."""
    if not history:
        return None
    row = history[0]
    return PreviousScore(
        score=row.score,
        grade=row.grade,
        is_elite=row.is_elite,
        has_veto=row.has_veto,
        evaluated_at=row.evaluated_at,
    )


def _elite_streak_from(history: Sequence[TokenScoreHistory], gate: EliteGate) -> int:
    """Consecutive recent history rows that met the Elite bar.

    Replayed from stored rows rather than incremented in a column - that is what
    keeps the streak reproducible under concurrent writers and recomputable
    during a rescore.

    Note what "consecutive" means here: consecutive *recorded observations*, not
    consecutive evaluations. History is written on material change plus a
    five-minute heartbeat, so intermediate evaluations are deliberately absent.
    Sustaining across three recorded observations is a stronger bar than three
    consecutive refreshes of a fast-tier token would be, which is the behaviour
    worth having for a certification the design bible reserves for gold.

    Liquidity is not part of the replayed check because history does not store
    it; the live evaluation still enforces the full gate, so this can only ever
    be more conservative than the gate itself.
    """
    streak = 0
    for row in history:
        qualifies = (
            not row.has_veto
            and row.score >= gate.min_score
            and row.evidence >= gate.min_evidence
            and row.market_risk <= gate.max_risk_penalty * HUNDRED
        )
        if not qualifies:
            break
        streak += 1
    return streak


def _components_of(result: ScoreResult) -> list[dict[str, Any]]:
    """The explanation payload, JSON-ready.

    Decimals are serialised as strings, matching how the market schemas already
    carry money: a float would silently round exactly the numbers the waterfall
    has to reconcile.
    """
    return [
        {
            "id": str(entry.id),
            "agent": entry.agent,
            "available": entry.available,
            "score": str(entry.score) if entry.score is not None else None,
            "declared_weight": str(entry.declared_weight),
            "effective_weight": str(entry.effective_weight),
            "contribution": str(entry.contribution),
            "raw": {
                key: (str(value) if value is not None else None)
                for key, value in entry.raw.items()
            },
            "reasons": [str(code) for code in entry.reasons],
        }
        for entry in result.components
    ]


def _event_of(
    result: ScoreResult,
    delta: Decimal | None,
    evaluated_at: datetime,
    trigger: ScoreTrigger,
) -> dict[str, Any]:
    """The `score_changed` payload.

    Carries `evidence` - time-invariant - rather than confidence, so a queued or
    replayed event can never assert a freshness that has since expired.
    """
    previous = None if delta is None else result.score - delta
    return {
        "type": "score_changed",
        "mint_address": result.mint_address,
        "score": str(result.score),
        "previous_score": str(previous) if previous is not None else None,
        "evidence": str(result.evidence),
        "grade": str(result.grade),
        "is_elite": result.is_elite,
        "has_veto": result.has_veto,
        "primary_reason": (
            str(result.explanation.primary) if result.explanation.primary else None
        ),
        "primary_agent": (
            str(result.explanation.primary_agent) if result.explanation.primary_agent else None
        ),
        "trigger": str(trigger),
        "model_version": result.model_version,
        "evaluated_at": evaluated_at.isoformat(),
    }
