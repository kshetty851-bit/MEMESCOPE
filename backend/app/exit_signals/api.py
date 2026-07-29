"""Exit Watch, Hall of Fame, Hall of Lessons and leaderboards.

All additive. No existing route changes shape.

The three record views are one query family over `radar_tokens`, which Phase 8
already populates with everything needed: first detection, peak, current, and
nothing ever deleted. That the Hall of Lessons is possible at all is a
consequence of that design decision, not a new feature.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.sql.elements import ColumnElement

from app.api.deps import DbSession
from app.core.exceptions import NotFoundError
from app.exit_signals import detector, explain, smart_money
from app.exit_signals.models import ExitSeverity
from app.exit_signals.schemas import (
    ExitAssessmentOut,
    ExitModelOut,
    ExitSignalOut,
    ExitWatchPage,
    HallEntryOut,
    LeaderboardBoard,
    LeaderboardOut,
    SmartMoneyBlock,
)
from app.models.radar import RadarToken
from app.radar.api import _days_since
from app.radar.models import RadarSeries
from app.radar.repository import RadarRepository

router = APIRouter(tags=["intelligence"])

_SECONDS_PER_DAY = Decimal(86_400)


def _live_multiple(series: RadarSeries, first_price: Decimal | None) -> Decimal | None:
    """Current multiple from the **live** series, not the stored column.

    `radar_tokens.current_multiple` only moves on a Radar sweep. Exit Watch
    recomputes from the latest observation, so reading the stored value here
    produced a visible contradiction: a token flagged `price_below_detection`
    while displaying 1.00x, because the signal saw the live price and the
    number did not. Both now come from the same observation.
    """
    latest = series.latest
    if latest is None or latest.price_usd is None:
        return None
    if first_price is None or first_price <= 0:
        return None
    return latest.price_usd / first_price


def _hall_entry(entry: RadarToken, now: datetime) -> HallEntryOut:
    days_to_peak: Decimal | None = None
    if entry.peak_at is not None:
        days_to_peak = (
            Decimal(max((entry.peak_at - entry.first_detected_at).total_seconds(), 0))
            / _SECONDS_PER_DAY
        )

    return HallEntryOut(
        mint_address=entry.mint_address,
        category=entry.current_category,
        original_category=entry.category,
        first_detected_at=entry.first_detected_at,
        first_market_cap=entry.first_market_cap,
        first_price=entry.first_price,
        peak_market_cap=entry.peak_market_cap,
        peak_price=entry.peak_price,
        peak_multiple=entry.peak_multiple,
        peak_at=entry.peak_at,
        current_market_cap=entry.current_market_cap,
        current_price=entry.current_price,
        current_multiple=entry.current_multiple,
        days_since_detection=_days_since(entry.first_detected_at, now),
        days_to_peak=days_to_peak,
        opportunity_score=entry.current_opportunity_score,
        confidence=entry.current_confidence,
        is_active=entry.is_active,
    )


# --- Exit Watch ---------------------------------------------------------------


@router.get(
    "/exit-watch/model", response_model=ExitModelOut, summary="Published Exit Watch model"
)
async def get_exit_model() -> ExitModelOut:
    """Thresholds and signals, verbatim.

    Published for the same reason `/scores/model` and `/radar/categories` are:
    a platform that warns you about something should be checkable on how it
    decided to.
    """
    return ExitModelOut(
        signals=[
            {
                **explain.render(signal),
                "available": signal not in smart_money.DECLARED_SIGNALS,
            }
            for signal in explain.SIGNAL_LABEL
        ],
        thresholds={
            "volume_collapse_ratio": str(detector.VOLUME_COLLAPSE_RATIO),
            "liquidity_exit_ratio": str(detector.LIQUIDITY_EXIT_RATIO),
            "technical_breakdown_ratio": str(detector.TECHNICAL_BREAKDOWN_RATIO),
            "momentum_rollover_drop": str(detector.MOMENTUM_ROLLOVER_DROP),
            "confidence_drop": str(detector.CONFIDENCE_DROP),
            "sell_pressure_share": str(detector.SELL_PRESSURE_SHARE),
        },
        signals_for_watch=detector.WATCH_SIGNALS,
        signals_for_elevated=detector.ELEVATED_SIGNALS,
        disclaimer=explain.DISCLAIMER,
    )


@router.get("/exit-watch", response_model=ExitWatchPage, summary="Weakening opportunities")
async def list_exit_watch(
    session: DbSession,
    severity: Annotated[Literal["watch", "elevated"] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ExitWatchPage:
    """Radar entries whose supporting evidence is deteriorating.

    Assessed live from the stored series rather than read from a cached verdict.
    The engine is pure, so recomputing is exact — and a stale warning would be
    worse than none.
    """
    repository = RadarRepository(session)
    now = datetime.now(UTC)

    entries = await repository.list_entries(active_only=True, limit=limit, sort="score")

    assessments: list[ExitAssessmentOut] = []
    for entry in entries:
        series = await repository.load_series(entry.mint_address)
        if series is None:
            continue

        assessment = detector.assess(
            series,
            now=now,
            current_score=entry.current_opportunity_score,
            peak_score=entry.first_opportunity_score,
            current_confidence=entry.current_confidence,
            peak_confidence=entry.first_confidence,
            first_price=entry.first_price,
        )
        if assessment.severity is ExitSeverity.CLEAR:
            continue
        if severity is not None and assessment.severity.value != severity:
            continue

        assessments.append(
            ExitAssessmentOut(
                mint_address=entry.mint_address,
                severity=assessment.severity.value,
                coverage=assessment.coverage,
                summary=explain.SEVERITY_MESSAGE[assessment.severity],
                signals=[
                    ExitSignalOut(
                        **explain.render(signal.id),
                        triggered=signal.triggered,
                        available=signal.available,
                        magnitude=signal.magnitude,
                    )
                    for signal in assessment.signals
                    if signal.triggered
                ],
                current_multiple=_live_multiple(series, entry.first_price),
                peak_multiple=entry.peak_multiple,
                evaluated_at=now,
            )
        )

    # Most deteriorated first: elevated before watch, then by how many signals.
    assessments.sort(key=lambda a: (a.severity == "elevated", len(a.signals)), reverse=True)

    return ExitWatchPage(
        items=assessments,
        total=len(assessments),
        disclaimer=explain.DISCLAIMER,
    )


@router.get(
    "/exit-watch/{mint}", response_model=ExitAssessmentOut, summary="One token's assessment"
)
async def get_exit_assessment(session: DbSession, mint: str) -> ExitAssessmentOut:
    repository = RadarRepository(session)
    entry = await repository.get(mint)
    if entry is None:
        raise NotFoundError(f"{mint} is not on the Radar.")

    series = await repository.load_series(mint)
    if series is None:
        raise NotFoundError(f"No market history for {mint}.")

    now = datetime.now(UTC)
    assessment = detector.assess(
        series,
        now=now,
        current_score=entry.current_opportunity_score,
        peak_score=entry.first_opportunity_score,
        current_confidence=entry.current_confidence,
        peak_confidence=entry.first_confidence,
        first_price=entry.first_price,
    )

    return ExitAssessmentOut(
        mint_address=mint,
        severity=assessment.severity.value,
        coverage=assessment.coverage,
        summary=explain.SEVERITY_MESSAGE[assessment.severity],
        # Every signal here, not only the fired ones: on a single token the
        # checks that passed are as informative as the ones that did not.
        signals=[
            ExitSignalOut(
                **explain.render(signal.id),
                triggered=signal.triggered,
                available=signal.available,
                magnitude=signal.magnitude,
            )
            for signal in assessment.signals
        ],
        current_multiple=_live_multiple(series, entry.first_price),
        peak_multiple=entry.peak_multiple,
        evaluated_at=now,
    )


# --- Smart money --------------------------------------------------------------


@router.get(
    "/smart-money/{mint}", response_model=SmartMoneyBlock, summary="Wallet intelligence"
)
async def get_smart_money(mint: str) -> SmartMoneyBlock:
    """Always unavailable, with the reason attached.

    The endpoint exists rather than 404ing so that clients can render "not
    collected" honestly and so the gap is discoverable in the API surface
    instead of being an undocumented absence.
    """
    block = smart_money.token_intelligence()
    return SmartMoneyBlock(mint_address=mint, **block)


# --- Hall of Fame / Hall of Lessons ------------------------------------------


@router.get("/hall-of-fame", response_model=list[HallEntryOut], summary="Best calls")
async def get_hall_of_fame(
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[HallEntryOut]:
    """Highest peak return since detection.

    Ranked by **peak**, not current: what the call was worth at its best is the
    honest measure of the detection, and judging it by today's price would
    credit or punish the platform for time it never claimed to predict.
    """
    now = datetime.now(UTC)
    rows = (
        await session.scalars(
            select(RadarToken)
            .where(RadarToken.peak_multiple.is_not(None))
            .order_by(RadarToken.peak_multiple.desc(), RadarToken.mint_address)
            .limit(limit)
        )
    ).all()
    return [_hall_entry(row, now) for row in rows]


@router.get("/hall-of-lessons", response_model=list[HallEntryOut], summary="Calls that failed")
async def get_hall_of_lessons(
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[HallEntryOut]:
    """Worst current return since detection.

    This endpoint is the point of the whole record. Nothing is filtered, hidden
    or softened: the entries here are detections that did not work, ranked by
    how badly, and they are counted in exactly the same denominator as the Hall
    of Fame. A platform that publishes only its winners has published nothing.
    """
    now = datetime.now(UTC)
    rows = (
        await session.scalars(
            select(RadarToken)
            .where(RadarToken.current_multiple.is_not(None))
            .order_by(RadarToken.current_multiple.asc(), RadarToken.mint_address)
            .limit(limit)
        )
    ).all()
    return [_hall_entry(row, now) for row in rows]


# --- Leaderboard --------------------------------------------------------------


@router.get("/leaderboard", response_model=LeaderboardOut, summary="Ranked boards")
async def get_leaderboard(
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> LeaderboardOut:
    """Several boards in one response.

    One request rather than six: the page shows them together, and six round
    trips to render one screen is the pattern §8 already had to undo once.
    """
    now = datetime.now(UTC)

    async def board(
        order: ColumnElement[Any], where: ColumnElement[bool] | None = None
    ) -> list[HallEntryOut]:
        statement = select(RadarToken)
        if where is not None:
            statement = statement.where(where)
        statement = statement.order_by(order, RadarToken.mint_address).limit(limit)
        rows = (await session.scalars(statement)).all()
        return [_hall_entry(row, now) for row in rows]

    improving = func.coalesce(RadarToken.current_opportunity_score, 0) - func.coalesce(
        RadarToken.first_opportunity_score, 0
    )

    return LeaderboardOut(
        boards=[
            LeaderboardBoard(
                id="top_momentum",
                label="Top momentum",
                description="Highest opportunity score right now.",
                entries=await board(RadarToken.current_opportunity_score.desc()),
            ),
            LeaderboardBoard(
                id="highest_confidence",
                label="Highest confidence",
                description="Most of the model applied, with the most history behind it.",
                entries=await board(RadarToken.current_confidence.desc()),
            ),
            LeaderboardBoard(
                id="fastest_improving",
                label="Fastest improving",
                description="Largest score gain since first detection.",
                entries=await board(improving.desc()),
            ),
            LeaderboardBoard(
                id="most_undervalued",
                label="Most undervalued",
                description="Sound structure the market has not yet moved on.",
                entries=await board(
                    RadarToken.current_opportunity_score.desc(),
                    RadarToken.current_category == "undervalued",
                ),
            ),
            LeaderboardBoard(
                id="top_accumulation",
                label="Top accumulation",
                description=(
                    "Requires wallet-level data, which is not collected. "
                    "Empty by construction, not by absence of activity."
                ),
                entries=[],
            ),
            LeaderboardBoard(
                id="top_smart_money",
                label="Top smart money",
                description=(
                    "Requires wallet-level data, which is not collected. "
                    "Empty by construction, not by absence of activity."
                ),
                entries=[],
            ),
        ],
        smart_money_available=False,
        smart_money_note=smart_money.UNAVAILABLE_REASON,
    )
