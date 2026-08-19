"""Forward Radar-quality ledger guarantees against the real test database."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import TokenMarketSnapshot
from app.models.radar import RadarToken
from app.models.radar_quality import (
    RadarDecisionOutcome,
    RadarDecisionSnapshot,
    RadarRankEvent,
)
from app.models.token import DiscoveredToken
from app.radar.models import Observation, RadarSeries
from app.radar.quality import RadarQualityRecorder, _predecision_features
from app.radar.repository import RadarRepository
from app.radar.service import RadarService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


async def _token(
    session: AsyncSession, mint: str, *, discovered_at: datetime = NOW - timedelta(hours=24)
) -> DiscoveredToken:
    token = DiscoveredToken(
        mint_address=mint,
        name="Forward Radar Probe",
        symbol="FRP",
        decimals=6,
        signature=f"sig-{uuid.uuid4()}",
        slot=1,
        discovered_at=discovered_at,
    )
    session.add(token)
    await session.flush()
    return token


async def _series(
    session: AsyncSession,
    token: DiscoveredToken,
    *,
    price_step: Decimal = Decimal("0.00004"),
) -> None:
    for index in range(48):
        session.add(
            TokenMarketSnapshot(
                token_id=token.id,
                mint_address=token.mint_address,
                captured_at=NOW - timedelta(minutes=(48 - index) * 30),
                price_usd=Decimal("0.001") + price_step * Decimal(index),
                market_cap=Decimal(150_000),
                liquidity_usd=Decimal(25_000) + Decimal(index) * 300,
                volume_5m=Decimal(700) + Decimal(index) * 10,
                volume_1h=Decimal(2_000) + Decimal(index) * 20,
                volume_24h=Decimal(30_000) + Decimal(index) * 400,
                buy_count_24h=180 + index,
                sell_count_24h=70 + index,
                dex_name="pumpfun",
                pool_address="PoolForwardQuality00000000000000000000001",
                provider="test",
                provider_latency_ms=12,
            )
        )
    await session.flush()


async def _capture(service: RadarService, session: AsyncSession) -> tuple[int, int]:
    """Persist the service's pending rows in the same test transaction."""

    await session.flush()
    recorder = RadarQualityRecorder(session)
    rows, events = await recorder.prepare(tuple(service._pending_quality))
    inserted = await recorder.persist(rows, events)
    await session.flush()
    return inserted


async def test_freezes_complete_decision_market_and_component_state(
    db_session: AsyncSession,
) -> None:
    token = await _token(db_session, "ForwardQualityFreeze000000000000000000000001")
    await _series(db_session, token)
    service = RadarService(db_session)

    outcome = await service.refresh_mints([token.mint_address], now=NOW)
    assert outcome.tracked == 1
    decisions, events = await _capture(service, db_session)
    assert decisions == 1
    assert events >= 1

    snapshot = await db_session.scalar(select(RadarDecisionSnapshot))
    assert snapshot is not None
    assert snapshot.market_snapshot_id is not None
    assert snapshot.radar_rank == 1
    assert snapshot.radar_score > 0
    assert snapshot.confidence_score > 0
    assert snapshot.component_state["momentum"]["declared_weight"] == "0.28"
    assert snapshot.component_state["momentum"]["weighted_contribution"] is not None
    assert snapshot.market_state["volume_5m"] is not None
    assert snapshot.market_state["volume_1h"] is not None
    assert snapshot.market_state["volume_24h"] is not None
    assert (
        snapshot.availability["market"]["volume_6h"]["state"] == "NOT_AVAILABLE_FROM_PROVIDER"
    )
    assert snapshot.derived_features["volume_5m_to_liquidity"] is not None
    assert snapshot.derived_features["snapshot_count_since_discovery"] == 48
    assert snapshot.token_identity["symbol"] == "FRP"

    # A later market observation cannot mutate the frozen decision record.
    db_session.add(
        TokenMarketSnapshot(
            token_id=token.id,
            mint_address=token.mint_address,
            captured_at=NOW + timedelta(hours=1),
            price_usd=Decimal("1"),
            liquidity_usd=Decimal(1),
            volume_24h=Decimal(1),
            provider="test",
        )
    )
    await db_session.flush()
    frozen = await db_session.scalar(
        select(RadarDecisionSnapshot).where(RadarDecisionSnapshot.id == snapshot.id)
    )
    assert frozen is not None
    assert frozen.market_state == snapshot.market_state
    assert frozen.component_state == snapshot.component_state


async def test_rank_history_is_append_only_and_retries_are_idempotent(
    db_session: AsyncSession,
) -> None:
    first = await _token(db_session, "ForwardQualityRank00000000000000000000000001")
    second = await _token(db_session, "ForwardQualityRank00000000000000000000000002")
    await _series(db_session, first, price_step=Decimal("0.00002"))
    await _series(db_session, second, price_step=Decimal("0.00008"))
    service = RadarService(db_session)

    await service.refresh_mints([first.mint_address, second.mint_address], now=NOW)
    rows, events = await _capture(service, db_session)
    assert rows == 2
    assert events >= 2

    # Persisting the exact same prepared evaluations is a technical retry, not
    # a second canonical observation.
    recorder = RadarQualityRecorder(db_session)
    retry_rows, retry_events = await recorder.prepare(tuple(service._pending_quality))
    assert await recorder.persist(retry_rows, retry_events) == (0, 0)

    # A genuine later evaluation creates another rank event rather than
    # overwriting the first one.
    db_session.add(
        TokenMarketSnapshot(
            token_id=first.id,
            mint_address=first.mint_address,
            captured_at=NOW + timedelta(hours=1),
            price_usd=Decimal("2"),
            liquidity_usd=Decimal(100_000),
            volume_24h=Decimal(500_000),
            buy_count_24h=700,
            sell_count_24h=50,
            provider="test",
        )
    )
    await db_session.flush()
    await service.refresh_mints([first.mint_address], now=NOW + timedelta(hours=1))
    rows, _ = await _capture(service, db_session)
    assert rows == 1

    events = (
        await db_session.scalars(
            select(RadarRankEvent)
            .where(RadarRankEvent.mint_address == first.mint_address)
            .order_by(RadarRankEvent.observed_at.asc())
        )
    ).all()
    assert len(events) >= 2
    assert {event.radar_rank for event in events}.issubset({1, 2})


async def test_derived_features_exclude_future_observations() -> None:
    future = NOW + timedelta(minutes=5)
    series = RadarSeries(
        mint_address="ForwardQualityNoLookahead",
        observations=(
            Observation(
                captured_at=NOW - timedelta(minutes=2),
                price_usd=Decimal("1"),
                market_cap=None,
                liquidity_usd=Decimal("10"),
                volume_24h=Decimal("20"),
                volume_1h=Decimal("4"),
                buy_count_24h=4,
                sell_count_24h=2,
                volume_5m=Decimal("2"),
            ),
            Observation(
                captured_at=NOW - timedelta(minutes=1),
                price_usd=Decimal("2"),
                market_cap=None,
                liquidity_usd=Decimal("20"),
                volume_24h=Decimal("30"),
                volume_1h=Decimal("6"),
                buy_count_24h=6,
                sell_count_24h=3,
                volume_5m=Decimal("3"),
            ),
            Observation(
                captured_at=future,
                price_usd=Decimal("100"),
                market_cap=None,
                liquidity_usd=Decimal("1"),
                volume_24h=Decimal("1_000"),
                volume_1h=Decimal("999"),
                buy_count_24h=999,
                sell_count_24h=1,
                volume_5m=Decimal("500"),
            ),
        ),
    )
    features, availability = _predecision_features(series, NOW)
    assert features["radar_input_snapshot_count"] == 2
    assert features["volume_5m_to_liquidity"] == "0.15"
    assert availability["volume_5m_to_liquidity"]["state"] == "AVAILABLE"


async def test_outcomes_are_separate_labels_and_include_24h_path_metrics(
    db_session: AsyncSession,
) -> None:
    token = await _token(db_session, "ForwardQualityOutcome00000000000000000000001")
    await _series(db_session, token)
    service = RadarService(db_session)
    await service.refresh_mints([token.mint_address], now=NOW)
    await _capture(service, db_session)
    decision = await db_session.scalar(select(RadarDecisionSnapshot))
    assert decision is not None

    for captured_at, price, liquidity in (
        (NOW + timedelta(minutes=5), Decimal("0.10"), Decimal(30_000)),
        (NOW + timedelta(hours=24), Decimal("0.01"), Decimal(3_000)),
    ):
        db_session.add(
            TokenMarketSnapshot(
                token_id=token.id,
                mint_address=token.mint_address,
                captured_at=captured_at,
                price_usd=price,
                liquidity_usd=liquidity,
                volume_24h=Decimal(100_000),
                provider="test",
            )
        )
    await db_session.flush()

    summary = await RadarQualityRecorder(db_session).capture_outcomes(
        now=NOW + timedelta(hours=24), limit=10
    )
    assert summary["horizons_written"] >= 1
    assert summary["paths_written"] == 1
    outcomes = (
        await db_session.scalars(
            select(RadarDecisionOutcome).where(RadarDecisionOutcome.decision_id == decision.id)
        )
    ).all()
    path = next(outcome for outcome in outcomes if outcome.outcome_kind == "PATH_SUMMARY")
    assert path.payload["maximum_future_multiple"] is not None
    assert "time_to_2x_seconds" in path.payload
    # Outcome collection adds labels only; it never rewrites the decision row.
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(RadarDecisionSnapshot)
            .where(RadarDecisionSnapshot.id == decision.id)
        )
        == 1
    )


async def test_instrumentation_failure_cannot_change_radar_result(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = await _token(db_session, "ForwardQualityFailure00000000000000000000001")
    await _series(db_session, token)
    service = RadarService(db_session)
    outcome = await service.refresh_mints([token.mint_address], now=NOW)
    await db_session.commit()
    before = await db_session.scalar(
        select(RadarToken).where(RadarToken.mint_address == token.mint_address)
    )
    assert before is not None
    before_state = (
        before.current_opportunity_score,
        before.current_confidence,
        before.current_category,
        before.is_active,
    )
    before_ranking = await RadarRepository(db_session).top_mints()

    async def _fail(_decisions: object) -> None:
        raise RuntimeError("injected research persistence failure")

    monkeypatch.setattr("app.radar.service.capture_pending", _fail)
    await service.capture_forward_quality()
    after = await db_session.scalar(
        select(RadarToken).where(RadarToken.mint_address == token.mint_address)
    )
    assert after is not None
    after_state = (
        after.current_opportunity_score,
        after.current_confidence,
        after.current_category,
        after.is_active,
    )
    after_ranking = await RadarRepository(db_session).top_mints()
    assert outcome.tracked == 1
    assert after_state == before_state
    assert after_ranking == before_ranking
