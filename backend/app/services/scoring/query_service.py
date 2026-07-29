"""Read-side scoring use cases.

Kept separate from `TokenScoringService`, which is the write path owned by the
enrichment worker - the same split as `MarketQueryService` versus
`MarketEnrichmentService`, and for the same reason: the API must have no route
that can trigger an evaluation.

Nothing here computes a score. It reads stored rows, derives the two values that
are deliberately *not* stored (freshness, and the confidence built from it), and
maps persistence models onto response DTOs. Both derivations delegate to the
scoring package's pure functions rather than reimplementing them, so there is
exactly one definition of each in the codebase.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError, ValidationError
from app.models.score import ScoreGrade, TokenScore, TokenScoreHistory
from app.repositories.market import MarketSnapshotRepository
from app.repositories.score import ScoreHistoryRepository, ScoreRepository
from app.repositories.token import TokenRepository
from app.schemas.score import (
    AppliedFilters,
    EliteGateRead,
    EvidenceSummary,
    GradeBandRead,
    ModelComponentRead,
    ModelMetadataRead,
    RiskSummary,
    ScoreComponentRead,
    ScoreHistoryEntry,
    ScoreHistoryPage,
    ScoreReasonRead,
    ScoreStatus,
    TokenScoreEnvelope,
    TokenScoreRead,
    TokenSummary,
    TopScoreEntry,
    TopScorePage,
)
from app.services.market.scheduler import SchedulePolicy
from app.services.scoring.components import COMPONENT_REGISTRY
from app.services.scoring.components.base import NotYetImplemented
from app.services.scoring.explain import REASON_META, ReasonCode
from app.services.scoring.features import window_seconds_for
from app.services.scoring.freshness import confidence_of, freshness_of
from app.services.scoring.grading import GradeBands
from app.services.scoring.models.base import ModelConfig
from app.services.scoring.models.registry import get_model

SECONDS_PER_MINUTE = Decimal(60)

#: Scores are stored as NUMERIC(5,2); read-time derivations match them.
SCORE_QUANTUM = Decimal("0.01")
#: Freshness is a 0-1 ratio, so it earns two more places than a score does.
FRESHNESS_QUANTUM = Decimal("0.0001")


class ScoreQueryService:
    """Everything the read API needs. Routers call this and nothing else."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        model: ModelConfig | None = None,
        policy: SchedulePolicy | None = None,
    ) -> None:
        self.session = session
        self.scores = ScoreRepository(session)
        self.history = ScoreHistoryRepository(session)
        self.tokens = TokenRepository(session)
        self.snapshots = MarketSnapshotRepository(session)
        self.policy = policy or SchedulePolicy.from_settings()
        self._model = model

    @property
    def model(self) -> ModelConfig:
        """Resolved lazily so an unknown version fails the request, not import."""
        if self._model is None:
            self._model = get_model()
        return self._model

    # --- Per-token ------------------------------------------------------------

    async def current(self, mint_address: str, *, now: datetime) -> TokenScoreEnvelope:
        """The token's current score, or the reason there isn't one.

        A token that exists but has no score is a 200 with a null body: the
        absence is meaningful state the client should render, not an error.
        """
        mint = mint_address.strip()

        row = await self.scores.with_token(mint)
        if row is None:
            # Distinguish "we have never heard of this mint" (404) from "we know
            # it but have not scored it" (200 with a status).
            token = await self.tokens.get_by_mint(mint)
            if token is None:
                raise NotFoundError(f"No discovered token with mint {mint_address}.")
            return TokenScoreEnvelope(
                mint_address=token.mint_address,
                status=await self._absent_status(mint),
                score=None,
            )

        # Two rows: the newest carries the breakdown, the one below it gives the
        # previous score. One query, and the delta needs no stored column.
        recent = await self.history.recent_for_mint(mint, limit=2)
        return TokenScoreEnvelope(
            mint_address=mint,
            status="scored",
            score=self._to_score(row, recent, now=now),
        )

    async def history_page(
        self,
        mint_address: str,
        *,
        page: int = 1,
        page_size: int = 50,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> ScoreHistoryPage:
        """Recorded score changes, newest first.

        Offset pagination is correct here and only here: the table is
        append-only, so a page boundary cannot shift under a reader.
        """
        if since and until and since > until:
            raise ValidationError("`since` must be earlier than `until`.")

        mint = mint_address.strip()
        token = await self.tokens.get_by_mint(mint)
        if token is None:
            raise NotFoundError(f"No discovered token with mint {mint_address}.")

        rows, total = await self.history.history_for_mint(
            mint,
            offset=(page - 1) * page_size,
            limit=page_size,
            since=since,
            until=until,
        )
        return ScoreHistoryPage(
            mint_address=mint,
            items=[self._to_history_entry(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
            pages=(total + page_size - 1) // page_size if page_size else 0,
        )

    # --- Ranking --------------------------------------------------------------

    async def top(
        self,
        *,
        now: datetime,
        page: int = 1,
        page_size: int = 20,
        sort: str = "score",
        order: str = "desc",
        min_score: Decimal | None = None,
        min_confidence: Decimal | None = None,
        max_risk: Decimal | None = None,
        grade: str | None = None,
        trigger: str | None = None,
        model_version: str | None = None,
        elite_only: bool = False,
        include_vetoed: bool = False,
    ) -> TopScorePage:
        """Ranked scores, filtered and paginated in the database.

        `min_confidence` is applied to stored **evidence**. Confidence is
        `evidence x sqrt(freshness)` and therefore never exceeds evidence, so
        the predicate is an exact upper bound: it can drop no token that would
        have qualified. Filtering on true confidence would require the tier
        policy and the freshness curve to be reimplemented in SQL, duplicating
        scoring logic outside the engine.
        """
        rows, matched, candidates = await self.scores.ranked_page(
            offset=(page - 1) * page_size,
            limit=page_size,
            sort_by=sort,
            order=order,
            min_score=min_score,
            min_evidence=min_confidence,
            max_risk=max_risk,
            grade=grade,
            model_version=model_version,
            trigger=trigger,
            elite_only=elite_only,
            include_vetoed=include_vetoed,
        )

        # The breakdown is deliberately omitted from list rows: it is kilobytes
        # per token, and a ranking is scanned rather than read in detail.
        items = [
            TopScoreEntry(
                token=TokenSummary(
                    mint_address=row[0].mint_address, name=row[1], symbol=row[2]
                ),
                score=self._to_score(row, (), now=now, include_detail=False),
            )
            for row in rows
        ]

        return TopScorePage(
            items=items,
            total=matched,
            candidate_total=candidates,
            page=page,
            page_size=page_size,
            pages=(matched + page_size - 1) // page_size if page_size else 0,
            applied_filters=AppliedFilters(
                min_score=min_score,
                min_confidence=min_confidence,
                max_risk=max_risk,
                grade=ScoreGrade(grade) if grade else None,
                trigger=trigger,
                model_version=model_version,
                elite_only=elite_only,
                sort=sort,
                order=order,
            ),
        )

    # --- Model metadata -------------------------------------------------------

    def model_metadata(self) -> ModelMetadataRead:
        """The active model, as configuration rather than as a claim.

        Needs no database: the model is code, resolved through the registry.
        """
        model = self.model
        components: list[ModelComponentRead] = []
        available_total = Decimal(0)

        for entry in model.components:
            component = COMPONENT_REGISTRY[entry.id]
            available = not isinstance(component, NotYetImplemented)
            if available:
                available_total += entry.weight
            components.append(
                ModelComponentRead(
                    id=str(entry.id),
                    agent=str(component.agent),
                    weight=entry.weight,
                    available=available,
                )
            )

        declared_total = sum((entry.weight for entry in model.components), start=Decimal(0))
        max_evidence = available_total * Decimal(100)

        return ModelMetadataRead(
            version=model.version,
            risk_lambda=model.risk_lambda,
            veto_ceiling=model.veto_ceiling,
            max_single_contribution=model.max_single_contribution,
            min_scorable_weight=model.min_scorable_weight,
            declared_weight_total=declared_total,
            available_weight_total=available_total,
            components=components,
            grade_bands=_grade_bands(model.grade_bands),
            elite_gate=EliteGateRead(
                min_score=model.elite_gate.min_score,
                min_evidence=model.elite_gate.min_evidence,
                max_risk_penalty=model.elite_gate.max_risk_penalty,
                min_liquidity_usd=model.elite_gate.min_liquidity_usd,
                sustain_evaluations=model.elite_gate.sustain_evaluations,
                reachable=max_evidence >= model.elite_gate.min_evidence,
            ),
            scoring_enabled=settings.FEATURE_AI_SCORING_ENABLED,
        )

    # --- Internals ------------------------------------------------------------

    async def _absent_status(self, mint_address: str) -> ScoreStatus:
        """Why a known token has no score.

        Only reached on a miss, so the extra existence check never touches the
        happy path.
        """
        if not settings.FEATURE_AI_SCORING_ENABLED:
            return "scoring_disabled"
        if await self.snapshots.latest_for_mint(mint_address) is None:
            return "awaiting_market"
        return "not_scored"

    def _tier_interval_seconds(
        self, block_time: datetime | None, discovered_at: datetime, *, now: datetime
    ) -> int:
        """The token's refresh cadence, from the enrichment scheduler's policy.

        Freshness is relative to this rather than to an absolute clock: two
        minutes of silence is nothing for a six-hourly token and a missed beat
        for one refreshing every thirty seconds.
        """
        origin = block_time or discovered_at
        age = Decimal(max(0.0, (now - origin).total_seconds())) / SECONDS_PER_MINUTE
        _, interval, _ = window_seconds_for(age, policy=self.policy)
        return interval

    def _to_score(
        self,
        row: Row[Any],
        recent: Sequence[TokenScoreHistory],
        *,
        now: datetime,
        include_detail: bool = True,
    ) -> TokenScoreRead:
        score: TokenScore = row[0]
        interval = self._tier_interval_seconds(row[3], row[4], now=now)

        # Quantised before serialising. These two are derived per request rather
        # than read from a NUMERIC(5,2) column, so without this they would go out
        # at full Decimal precision - 28 significant digits of false accuracy
        # beside stored values rounded to the cent.
        raw_freshness = freshness_of(
            score.latest_snapshot_at, now=now, tier_interval_seconds=interval
        )
        confidence = confidence_of(score.evidence, raw_freshness).quantize(SCORE_QUANTUM)
        freshness = raw_freshness.quantize(FRESHNESS_QUANTUM)

        latest = recent[0] if recent else None
        previous = recent[1] if len(recent) > 1 else None

        return TokenScoreRead(
            mint_address=score.mint_address,
            score=score.score,
            opportunity_raw=score.opportunity_raw,
            grade=score.grade,
            is_elite=score.is_elite,
            evidence=EvidenceSummary(
                evidence=score.evidence,
                coverage=score.coverage,
                observations=score.observations,
                freshness=freshness,
                confidence=confidence,
            ),
            risk=RiskSummary(
                market_risk=score.market_risk,
                has_veto=score.has_veto,
                # Defined as the residual, exactly as the engine defines it, so
                # the waterfall reconciles rather than being rounded twice.
                deduction=score.opportunity_raw - score.score,
            ),
            model_version=score.model_version,
            evaluated_at=score.evaluated_at,
            latest_snapshot_at=score.latest_snapshot_at,
            previous_score=previous.score if previous else None,
            last_trigger=latest.trigger if latest else None,
            components=(
                [_to_component(entry) for entry in (latest.components if latest else [])]
                if include_detail
                else []
            ),
            reasons=(_to_reasons(latest.reasons if latest else []) if include_detail else []),
        )

    @staticmethod
    def _to_history_entry(row: TokenScoreHistory) -> ScoreHistoryEntry:
        return ScoreHistoryEntry(
            evaluated_at=row.evaluated_at,
            score=row.score,
            delta=row.delta,
            trigger=row.trigger,
            grade=row.grade,
            is_elite=row.is_elite,
            has_veto=row.has_veto,
            evidence=row.evidence,
            coverage=row.coverage,
            market_risk=row.market_risk,
            opportunity_raw=row.opportunity_raw,
            observations=row.observations,
            model_version=row.model_version,
            reasons=_to_reasons(row.reasons),
        )


# --- Module helpers -----------------------------------------------------------


def _grade_bands(bands: GradeBands) -> list[GradeBandRead]:
    """Turn the model's thresholds into explicit, renderable ranges."""
    boundaries = [
        (ScoreGrade.CRITICAL, Decimal(0), bands.weak_from),
        (ScoreGrade.WEAK, bands.weak_from, bands.watch_from),
        (ScoreGrade.WATCH, bands.watch_from, bands.strong_from),
        (ScoreGrade.STRONG, bands.strong_from, bands.high_conviction_from),
        (ScoreGrade.HIGH_CONVICTION, bands.high_conviction_from, None),
    ]
    return [
        GradeBandRead(grade=grade, lower_bound=lower, upper_bound=upper)
        for grade, lower, upper in boundaries
    ]


def _to_component(entry: dict[str, Any]) -> ScoreComponentRead:
    return ScoreComponentRead(
        id=entry["id"],
        agent=entry["agent"],
        available=entry["available"],
        score=Decimal(entry["score"]) if entry.get("score") is not None else None,
        declared_weight=Decimal(entry["declared_weight"]),
        effective_weight=Decimal(entry["effective_weight"]),
        contribution=Decimal(entry["contribution"]),
        raw=entry.get("raw", {}),
        reasons=entry.get("reasons", []),
    )


def _to_reasons(codes: Sequence[str]) -> list[ScoreReasonRead]:
    """Attach severity, owning agent, and prose to each stored code.

    An unrecognised code is passed through rather than raising. Codes are
    append-only by contract, so this should never fire - but history outliving a
    code is a bad reason to fail a read request.
    """
    rendered: list[ScoreReasonRead] = []
    for code in codes:
        try:
            meta = REASON_META[ReasonCode(code)]
        except (KeyError, ValueError):
            rendered.append(
                ScoreReasonRead(code=code, severity="info", agent="oracle", message=code)
            )
            continue
        rendered.append(
            ScoreReasonRead(
                code=code,
                severity=str(meta.severity),
                agent=str(meta.agent),
                message=meta.template,
            )
        )
    return rendered
