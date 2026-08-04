"""Radar HTTP endpoints.

Mounted under `/api/v1/radar`. Entirely additive — no existing route changes
shape, and the launch scanner's endpoints are untouched.

Routes are declared literal-first (`/performance`, `/leaderboard`, …) before
`/{mint}`, for the same reason `scores.py` does: otherwise `/performance` is
matched as a mint address.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.core.exceptions import NotFoundError
from app.models.radar import RadarToken
from app.radar import achievements as achievement_tiers
from app.radar import detector, explain, scorer
from app.radar.models import RadarCategory, RadarDimension, RadarReason
from app.radar.repository import RadarRepository
from app.radar.schemas import (
    AchievementOut,
    CategoryOut,
    DimensionOut,
    ModelOut,
    PerformanceOut,
    RadarDetailOut,
    RadarDiscoveredCandidateOut,
    RadarDiscoveredPage,
    RadarEntryOut,
    RadarHistoryOut,
    RadarPage,
    RadarSnapshotOut,
    ReasonOut,
    TierCount,
)
from app.services.pumpfun_radar import PumpfunRadarScanner

router = APIRouter(prefix="/radar", tags=["radar"])

_SECONDS_PER_DAY = Decimal(86_400)

CATEGORY_COPY: dict[RadarCategory, tuple[str, str]] = {
    RadarCategory.EARLY_MOMENTUM: (
        "Early Momentum",
        "Beginning to gain traction: liquidity, volume or price improving "
        "against its own baseline.",
    ),
    RadarCategory.BREAKOUT: (
        "Breakout",
        "Price has moved above its prior observed high with volume behind it.",
    ),
    RadarCategory.STRONG_COMMUNITY: (
        "Strong Community",
        "Sustained engagement across social channels and development activity.",
    ),
    RadarCategory.UNDERVALUED: (
        "Undervalued",
        "On-chain structure is sound while the market has not yet moved.",
    ),
    RadarCategory.ELITE: (
        "Elite",
        "Several independent dimensions agree at a high level. Rare by construction.",
    ),
}


def _days_since(moment: datetime, now: datetime) -> Decimal:
    return Decimal(max((now - moment).total_seconds(), 0)) / _SECONDS_PER_DAY


def _to_entry(
    entry: RadarToken,
    now: datetime,
    names: dict[str, tuple[str | None, str | None]] | None = None,
    tiers: dict[str, list[str]] | None = None,
) -> RadarEntryOut:
    """Assemble one Radar entry.

    `names` maps mint -> (name, symbol). It is optional so the signature stays
    usable without a lookup, but omitting it renders every entry nameless: the
    schema declares both fields and `RadarToken` stores neither, so they were
    previously always null on every Radar surface.
    """
    name, symbol = (names or {}).get(entry.mint_address, (None, None))
    return RadarEntryOut(
        mint_address=entry.mint_address,
        name=name,
        symbol=symbol,
        category=entry.current_category,
        original_category=entry.category,
        opportunity_score=entry.current_opportunity_score,
        confidence=entry.current_confidence,
        first_detected_at=entry.first_detected_at,
        first_price=entry.first_price,
        first_market_cap=entry.first_market_cap,
        first_liquidity=entry.first_liquidity,
        first_opportunity_score=entry.first_opportunity_score,
        current_price=entry.current_price,
        current_market_cap=entry.current_market_cap,
        current_liquidity=entry.current_liquidity,
        current_multiple=entry.current_multiple,
        peak_multiple=entry.peak_multiple,
        peak_price=entry.peak_price,
        peak_market_cap=entry.peak_market_cap,
        peak_at=entry.peak_at,
        days_since_detection=_days_since(entry.first_detected_at, now),
        is_active=entry.is_active,
        detection_reason=list(entry.detection_reason or []),
        model_version=entry.model_version,
        last_evaluated_at=entry.last_evaluated_at,
        achieved_tiers=(tiers or {}).get(entry.mint_address, []),
    )


@router.get("/categories", response_model=ModelOut, summary="The published Radar model")
async def get_model() -> ModelOut:
    """Weights, gates and categories, verbatim.

    Published so the platform's claims about its own model are checkable rather
    than asserted — the same reason `/scores/model` exists. `reachable: false`
    marks a category the current model can never award.
    """
    declared = sum(scorer.WEIGHTS.values(), Decimal(0))
    available = sum(
        weight
        for dimension, weight in scorer.WEIGHTS.items()
        if dimension is not RadarDimension.COMMUNITY
    )

    return ModelOut(
        version=scorer.MODEL_VERSION,
        dimensions=[
            {
                "id": dimension.value,
                "label": explain.DIMENSION_LABEL[dimension],
                "weight": str(weight),
                "available": dimension is not RadarDimension.COMMUNITY,
            }
            for dimension, weight in scorer.WEIGHTS.items()
        ],
        declared_weight_total=declared,
        available_weight_total=available,
        min_radar_score=detector.MIN_RADAR_SCORE,
        min_radar_confidence=detector.MIN_RADAR_CONFIDENCE,
        min_risk_floor=detector.MIN_RISK_FLOOR,
        categories=[
            CategoryOut(
                id=category.value,
                label=CATEGORY_COPY[category][0],
                description=CATEGORY_COPY[category][1],
                reachable=detector.category_is_reachable(category),
                reachable_note=(
                    None
                    if detector.category_is_reachable(category)
                    else "Community signals are declared but not yet collected, so this "
                    "category cannot currently be awarded."
                ),
            )
            for category in RadarCategory
        ],
        achievement_tiers=[tier.label for tier in achievement_tiers.TIERS],
    )


@router.get("/performance", response_model=PerformanceOut, summary="Platform track record")
async def get_performance(session: DbSession) -> PerformanceOut:
    """Aggregate performance across every opportunity ever detected.

    Includes failures. A success rate computed only over the entries that
    worked is not a success rate, and hiding the losers would make the whole
    record worthless as evidence.
    """
    summary = await RadarRepository(session).performance_summary()

    reached_2x = summary.tier_counts.get("2x", 0)
    success_rate = Decimal(reached_2x) / Decimal(summary.total) if summary.total else None

    return PerformanceOut(
        total_opportunities=summary.total,
        active_opportunities=summary.active,
        average_peak_multiple=summary.average_peak_multiple,
        median_current_multiple=summary.median_current_multiple,
        best_peak_multiple=summary.best_peak_multiple,
        worst_current_multiple=summary.worst_current_multiple,
        tiers=[
            TierCount(tier=tier.label, count=summary.tier_counts.get(tier.label, 0))
            for tier in achievement_tiers.TIERS
        ],
        success_rate=success_rate,
        # Nothing currently marks an entry inactive, so this reads 0 today. It
        # is reported as a measured count rather than omitted: a zero the reader
        # can see is honest, and a missing field looks like an oversight.
        expired_opportunities=summary.total - summary.active,
        median_peak_multiple=summary.median_peak_multiple,
        average_drawdown=summary.average_drawdown,
        average_days_to_2x=summary.average_days_to_2x,
        average_days_tracked=summary.average_days_tracked,
        average_detection_market_cap=summary.average_detection_market_cap,
        average_peak_market_cap=summary.average_peak_market_cap,
        largest_peak_market_cap=summary.largest_peak_market_cap,
        observed_at=datetime.now(UTC),
    )


@router.get("/leaderboard", response_model=list[RadarEntryOut], summary="Best performers")
async def get_leaderboard(
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[RadarEntryOut]:
    now = datetime.now(UTC)
    repository = RadarRepository(session)
    entries = await repository.leaderboard(limit=limit)
    names = await repository.names_for([entry.mint_address for entry in entries])
    tiers = await repository.tiers_for([entry.mint_address for entry in entries])
    return [_to_entry(entry, now, names, tiers) for entry in entries]


@router.get("/achievements", response_model=list[AchievementOut], summary="Recent milestones")
async def get_achievements(
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AchievementOut]:
    rows = await RadarRepository(session).achievements(limit=limit)
    return [
        AchievementOut(
            tier=row.tier,
            multiple=row.multiple,
            achieved_at=row.achieved_at,
            price_at_achievement=row.price_at_achievement,
            market_cap_at_achievement=row.market_cap_at_achievement,
            days_to_achieve=row.days_to_achieve,
        )
        for row in rows
    ]


@router.get("", response_model=RadarPage, summary="Current Radar")
async def list_radar(
    session: DbSession,
    category: Annotated[str | None, Query()] = None,
    include_inactive: Annotated[bool, Query()] = False,
    sort: Annotated[str, Query(pattern="^(score|detected|peak|current)$")] = "score",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> RadarPage:
    """Opportunities currently on the Radar.

    Filters are echoed so an empty page caused by a strict filter is
    distinguishable from an empty Radar — the same convention `/scores/top`
    follows.
    """
    repository = RadarRepository(session)
    now = datetime.now(UTC)
    active_only = not include_inactive

    entries = await repository.list_entries(
        category=category,
        active_only=active_only,
        sort=sort,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    total = await repository.count_entries(category=category, active_only=active_only)

    mints = [entry.mint_address for entry in entries]
    names = await repository.names_for(mints)
    tiers = await repository.tiers_for(mints)

    return RadarPage(
        items=[_to_entry(entry, now, names, tiers) for entry in entries],
        total=total,
        page=page,
        page_size=page_size,
        applied_filters={
            "category": category,
            "include_inactive": include_inactive,
            "sort": sort,
        },
    )


@router.get(
    "/discovered",
    response_model=RadarDiscoveredPage,
    summary="Eligible Pump.fun discovery candidates",
)
async def list_discovered(
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> RadarDiscoveredPage:
    """List the configured Pump.fun age and market window.

    This route is intentionally separate from ``GET /radar``: an admission
    candidate has not passed the Opportunity Radar's technical, community or
    AI scoring stages and must not be represented as if it has.
    """
    now = datetime.now(UTC)
    scanner = PumpfunRadarScanner(session)
    candidates = await scanner.candidates(
        limit=page_size,
        offset=(page - 1) * page_size,
        now=now,
    )
    total = await scanner.count(now=now)
    return RadarDiscoveredPage(
        items=[
            RadarDiscoveredCandidateOut(
                token=candidate.token_address,
                name=candidate.name,
                symbol=candidate.symbol,
                creation_time=candidate.creation_time,
                age_days=candidate.age_days,
                market_cap=candidate.market_cap,
                liquidity=candidate.liquidity,
                volume=candidate.volume_24h,
                holder_count=candidate.holder_count,
                last_scan_time=candidate.last_scan_time,
            )
            for candidate in candidates
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{mint}/history", response_model=RadarHistoryOut, summary="Score timeline")
async def get_history(
    session: DbSession,
    mint: str,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> RadarHistoryOut:
    repository = RadarRepository(session)
    if await repository.get(mint) is None:
        raise NotFoundError(f"{mint} is not on the Radar.")

    rows = await repository.snapshots(mint, limit=limit)
    return RadarHistoryOut(
        mint_address=mint,
        total=len(rows),
        items=[
            RadarSnapshotOut(
                captured_at=row.captured_at,
                price=row.price,
                market_cap=row.market_cap,
                liquidity=row.liquidity,
                opportunity_score=row.opportunity_score,
                confidence=row.confidence,
                coverage=row.coverage,
                category=row.category,
                reasons=list(row.reasons or []),
            )
            for row in rows
        ],
    )


@router.get("/{mint}", response_model=RadarDetailOut, summary="One opportunity in full")
async def get_entry(session: DbSession, mint: str) -> RadarDetailOut:
    """A single opportunity, with the dimensions and reasons behind it.

    The dimension breakdown is recomputed from the stored series rather than
    read from the last snapshot, so it always describes the current state. That
    it *can* be recomputed exactly is the engine's purity guarantee in use.
    """
    repository = RadarRepository(session)
    entry = await repository.get(mint)
    if entry is None:
        raise NotFoundError(f"{mint} is not on the Radar.")

    now = datetime.now(UTC)
    base = _to_entry(
        entry,
        now,
        await repository.names_for([entry.mint_address]),
        await repository.tiers_for([entry.mint_address]),
    )

    dimensions: list[DimensionOut] = []
    reasons: list[ReasonOut] = []

    series = await repository.load_series(mint)
    if series is not None:
        result = scorer.evaluate(series, now=now)
        if result is not None:
            weights = scorer.effective_weights(result.dimensions)
            dimensions = [
                DimensionOut(
                    id=dimension.id.value,
                    label=explain.DIMENSION_LABEL[dimension.id],
                    available=dimension.available,
                    score=dimension.score,
                    effective_weight=weights.get(dimension.id),
                    reasons=[reason.value for reason in dimension.reasons],
                )
                for dimension in result.dimensions
            ]
            # De-duplicated, preserving order: a reason raised by two dimensions
            # should be stated once.
            seen: set[RadarReason] = set()
            for reason in result.reasons:
                if reason not in seen:
                    seen.add(reason)
                    reasons.append(ReasonOut(**explain.render(reason)))

    rows = await repository.achievements(mint_address=mint)

    return RadarDetailOut(
        **base.model_dump(),
        dimensions=dimensions,
        reasons=reasons,
        achievements=[
            AchievementOut(
                tier=row.tier,
                multiple=row.multiple,
                achieved_at=row.achieved_at,
                price_at_achievement=row.price_at_achievement,
                market_cap_at_achievement=row.market_cap_at_achievement,
                days_to_achieve=row.days_to_achieve,
            )
            for row in rows
        ],
    )
