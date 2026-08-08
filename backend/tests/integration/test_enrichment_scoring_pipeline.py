"""Enrichment to scoring, end to end.

The seam this file covers is the one the design argued hardest about: scoring
runs in its own transaction, *after* enrichment commits. That ordering is what
guarantees a scoring failure can never cost a snapshot, and that an event can
never describe a score that did not land.

The worker opens its own sessions, so these tests commit real rows rather than
using the rolled-back `db_session` fixture - the same reason
`test_enrichment_worker.py` does. Everything created shares the `Pipe` mint
prefix and is removed by the `sessions` fixture, which relies on the cascade
from `discovered_tokens` to clear snapshots, state, scores, and history.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.market import TokenMarketSnapshot, TradingStatus
from app.models.score import TokenScore, TokenScoreHistory
from app.models.token import DiscoveredToken
from app.repositories.market import EnrichmentStateRepository
from app.repositories.score import ScoreRepository
from app.repositories.token import TokenRepository
from app.services.market.providers.base import (
    MarketData,
    MarketDataProvider,
    ProviderHealth,
)
from app.services.market.worker import MarketEnrichmentWorker
from app.services.scoring.service import TokenScoringService

pytestmark = pytest.mark.integration

PREFIX = "Pipe"


class FakeProvider(MarketDataProvider):
    name = "fake"
    batch_size = 30

    def __init__(self, data: dict[str, MarketData]) -> None:
        self.data = data

    async def fetch_many(self, mint_addresses: Sequence[str]) -> dict[str, MarketData]:
        return {mint: self.data[mint] for mint in mint_addresses if mint in self.data}

    async def health(self) -> ProviderHealth:
        return ProviderHealth(name=self.name, available=True, circuit_state="closed")


def _market(mint: str, **overrides: Any) -> MarketData:
    values: dict[str, Any] = {
        "mint_address": mint,
        "price_usd": Decimal("0.001"),
        "liquidity_usd": Decimal("50000"),
        "market_cap": Decimal("500000"),
        "fully_diluted_valuation": Decimal("550000"),
        "volume_24h": Decimal("20000"),
        "volume_1h": Decimal("2000"),
        "volume_5m": Decimal("200"),
        "buy_count_24h": 300,
        "sell_count_24h": 200,
        "trading_status": TradingStatus.TRADING,
        "provider": "fake",
    }
    values.update(overrides)
    return MarketData(**values)


class CapturingRedis:
    """Stands in for Redis, recording what was published."""

    def __init__(self, *, fail: bool = False) -> None:
        self.published: list[tuple[str, str]] = []
        self.fail = fail

    async def publish(self, channel: str, payload: str) -> int:
        if self.fail:
            raise ConnectionError("redis is down")
        self.published.append((channel, payload))
        return 1


@pytest.fixture
async def sessions(test_session_factory: Any) -> AsyncIterator[Any]:
    """Committed-data session factory, with prefix-scoped cleanup."""
    yield test_session_factory
    async with test_session_factory() as session:
        await session.execute(
            delete(DiscoveredToken).where(DiscoveredToken.mint_address.like(f"{PREFIX}%"))
        )
        await session.commit()


@pytest.fixture
def scoring_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.market.worker.settings.FEATURE_AI_SCORING_ENABLED", True)


@pytest.fixture
def captured_redis(monkeypatch: pytest.MonkeyPatch) -> CapturingRedis:
    redis = CapturingRedis()
    monkeypatch.setattr("app.core.events.get_redis", lambda: redis)
    return redis


async def _register(session: AsyncSession, mint: str, *, age_hours: int = 3) -> None:
    """Discover a token and enrol it for enrichment, due immediately."""
    now = datetime.now(UTC)
    token = await TokenRepository(session).insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}",
            "slot": 1,
            "discovered_at": now - timedelta(hours=age_hours),
            "block_time": now - timedelta(hours=age_hours),
            "metadata_status": "resolved",
        }
    )
    assert token is not None
    await EnrichmentStateRepository(session).ensure_state(
        token_id=token.id,
        mint_address=mint,
        next_refresh_at=now - timedelta(seconds=1),
    )
    await session.commit()


async def _score_of(sessions: Any, mint: str) -> TokenScore | None:
    async with sessions() as session:
        return await ScoreRepository(session).get_by_mint(mint)


# --- The pipeline -------------------------------------------------------------


async def test_one_cycle_enriches_then_scores(
    sessions: Any, scoring_enabled: None, captured_redis: CapturingRedis
) -> None:
    """The whole seam: claim, fetch, snapshot, commit, score, commit, publish."""
    mint = f"{PREFIX}Basic"
    async with sessions() as session:
        await _register(session, mint)

    worker = MarketEnrichmentWorker(provider=FakeProvider({mint: _market(mint)}))
    processed = await worker._run_cycle()

    assert processed == 1
    assert worker.stats.snapshots_written == 1
    assert worker.stats.tokens_scored == 1
    assert worker.stats.score_history_written == 1
    assert worker.stats.scoring_failures == 0

    score = await _score_of(sessions, mint)
    assert score is not None
    assert score.model_version == "v1"
    assert Decimal(0) < score.score <= Decimal(100)
    assert score.coverage == Decimal("65.00")


async def test_committed_changes_publish_to_their_existing_redis_topics(
    sessions: Any, scoring_enabled: None, captured_redis: CapturingRedis
) -> None:
    """Market invalidation and score evidence keep their distinct topic semantics."""
    mint = f"{PREFIX}Event"
    async with sessions() as session:
        await _register(session, mint)

    worker = MarketEnrichmentWorker(provider=FakeProvider({mint: _market(mint)}))
    await worker._run_cycle()

    channels = {channel for channel, _ in captured_redis.published}
    assert channels == {settings.score_channel, settings.live_channel}
    assert settings.token_channel not in channels

    payloads = {channel: json.loads(payload) for channel, payload in captured_redis.published}
    score = payloads[settings.score_channel]
    assert score["type"] == "score_changed"
    assert score["mint_address"] == mint
    assert score["model_version"] == "v1"
    # Evidence, not confidence: a replayed event must not assert a freshness
    # that has since expired.
    assert "evidence" in score
    assert "confidence" not in score
    assert payloads[settings.live_channel] == {
        "type": "market.changed",
        "mints": [mint],
    }
    assert worker.stats.score_events_published == 1


async def test_the_event_describes_a_score_that_is_already_committed(
    sessions: Any, scoring_enabled: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publish-after-commit, asserted rather than assumed.

    The fake Redis reads the database at publish time on its own connection. If
    the worker published from inside the transaction the row would not be
    visible, which is exactly the bug the ordering exists to prevent.
    """
    mint = f"{PREFIX}Ordering"
    visible: list[bool] = []

    class ReadingRedis:
        async def publish(self, channel: str, payload: str) -> int:
            async with sessions() as session:
                visible.append(await ScoreRepository(session).get_by_mint(mint) is not None)
            return 1

    monkeypatch.setattr("app.core.events.get_redis", ReadingRedis)

    async with sessions() as session:
        await _register(session, mint)

    worker = MarketEnrichmentWorker(provider=FakeProvider({mint: _market(mint)}))
    await worker._run_cycle()

    # The market invalidation is published after TX-1, before the separate
    # scoring transaction exists; the score event follows its own commit.
    assert visible == [False, True]


# --- Isolation ----------------------------------------------------------------


async def test_a_scoring_failure_leaves_the_snapshot_committed(
    sessions: Any,
    scoring_enabled: None,
    captured_redis: CapturingRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Snapshots are the durable asset; scores are derived and recomputable."""

    async def _explode(self: Any, mints: Any, **kwargs: Any) -> Any:
        raise RuntimeError("scoring exploded")

    monkeypatch.setattr(TokenScoringService, "score_mints", _explode)

    mint = f"{PREFIX}Resilient"
    async with sessions() as session:
        await _register(session, mint)

    worker = MarketEnrichmentWorker(provider=FakeProvider({mint: _market(mint)}))
    processed = await worker._run_cycle()

    assert processed == 1
    assert worker.stats.scoring_failures == 1
    assert worker.stats.snapshots_written == 1

    async with sessions() as session:
        snapshots = (
            (
                await session.execute(
                    select(TokenMarketSnapshot).where(TokenMarketSnapshot.mint_address == mint)
                )
            )
            .scalars()
            .all()
        )
    assert len(snapshots) == 1
    assert await _score_of(sessions, mint) is None
    assert captured_redis.published == [
        (
            settings.live_channel,
            json.dumps({"type": "market.changed", "mints": [mint]}),
        )
    ]


async def test_a_redis_outage_does_not_fail_the_cycle(
    sessions: Any, scoring_enabled: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Events are best-effort; the database is the source of truth."""
    monkeypatch.setattr("app.core.events.get_redis", lambda: CapturingRedis(fail=True))

    mint = f"{PREFIX}NoRedis"
    async with sessions() as session:
        await _register(session, mint)

    worker = MarketEnrichmentWorker(provider=FakeProvider({mint: _market(mint)}))
    processed = await worker._run_cycle()

    assert processed == 1
    assert worker.stats.tokens_scored == 1
    assert await _score_of(sessions, mint) is not None


async def test_scoring_is_skipped_when_the_flag_is_off(
    sessions: Any, captured_redis: CapturingRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The flag gates computation; enrichment carries on regardless."""
    monkeypatch.setattr(
        "app.services.market.worker.settings.FEATURE_AI_SCORING_ENABLED", False
    )

    mint = f"{PREFIX}FlagOff"
    async with sessions() as session:
        await _register(session, mint)

    worker = MarketEnrichmentWorker(provider=FakeProvider({mint: _market(mint)}))
    await worker._run_cycle()

    assert worker.stats.snapshots_written == 1
    assert worker.stats.tokens_scored == 0
    assert captured_redis.published == [
        (
            settings.live_channel,
            json.dumps({"type": "market.changed", "mints": [mint]}),
        )
    ]
    assert await _score_of(sessions, mint) is None


async def test_a_token_the_provider_cannot_index_is_not_scored(
    sessions: Any, scoring_enabled: None, captured_redis: CapturingRedis
) -> None:
    """No pool yet is a normal state for a new mint, not a failure."""
    mint = f"{PREFIX}Unindexed"
    async with sessions() as session:
        await _register(session, mint)

    worker = MarketEnrichmentWorker(provider=FakeProvider({}))
    processed = await worker._run_cycle()

    assert processed == 1
    assert worker.stats.snapshots_written == 0
    assert worker.stats.tokens_scored == 0
    assert worker.stats.scoring_failures == 0
    assert captured_redis.published == []


# --- Repeated cycles ----------------------------------------------------------


async def test_a_second_cycle_updates_without_appending_history(
    sessions: Any, scoring_enabled: None, captured_redis: CapturingRedis
) -> None:
    """Steady state: the score refreshes, the mission log stays quiet."""
    mint = f"{PREFIX}Steady"
    async with sessions() as session:
        await _register(session, mint)

    worker = MarketEnrichmentWorker(provider=FakeProvider({mint: _market(mint)}))
    await worker._run_cycle()

    # Make it due again immediately, as a fast tier would be.
    async with sessions() as session:
        state = await EnrichmentStateRepository(session).get_by_mint(mint)
        assert state is not None
        state.next_refresh_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    await worker._run_cycle()

    assert worker.stats.tokens_scored == 2
    assert worker.stats.score_history_written == 1  # the first evaluation only
    assert worker.stats.score_events_published == 1

    async with sessions() as session:
        history = (
            (
                await session.execute(
                    select(TokenScoreHistory).where(TokenScoreHistory.mint_address == mint)
                )
            )
            .scalars()
            .all()
        )
        scores = (
            (await session.execute(select(TokenScore).where(TokenScore.mint_address == mint)))
            .scalars()
            .all()
        )

    assert len(history) == 1
    assert len(scores) == 1


async def test_a_batch_of_tokens_is_scored_together(
    sessions: Any, scoring_enabled: None, captured_redis: CapturingRedis
) -> None:
    mints = [f"{PREFIX}Batch{index}" for index in range(4)]
    async with sessions() as session:
        for mint in mints:
            await _register(session, mint)

    worker = MarketEnrichmentWorker(
        provider=FakeProvider({mint: _market(mint) for mint in mints})
    )
    processed = await worker._run_cycle()

    assert processed == 4
    assert worker.stats.tokens_scored == 4
    assert len(captured_redis.published) == 5
    channel, payload = captured_redis.published[0]
    assert channel == settings.live_channel
    assert json.loads(payload)["type"] == "market.changed"
    assert set(json.loads(payload)["mints"]) == set(mints)
