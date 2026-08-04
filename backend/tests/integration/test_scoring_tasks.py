"""Scoring maintenance jobs.

The async bodies are tested rather than the Celery-decorated wrappers: those
wrappers are one `asyncio.run` call each, and driving them from an async test
would nest event loops for no coverage gain.

Like the pipeline tests, these commit real rows because the jobs open their own
sessions. Everything shares the `Task` mint prefix and is removed by cascade.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import TradingStatus
from app.models.score import ScoreGrade, ScoreTrigger, TokenScoreHistory
from app.models.token import DiscoveredToken
from app.repositories.market import MarketSnapshotRepository
from app.repositories.score import ScoreHistoryRepository, ScoreRepository
from app.repositories.token import TokenRepository
from app.services.scoring.models.registry import UnknownModelError
from app.services.scoring.service import TokenScoringService
from app.workers.scoring_tasks import (
    _prune_score_history,
    _rescore_tokens,
    _score_sweep,
)

pytestmark = pytest.mark.integration

PREFIX = "Task"


class CapturingRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, payload: str) -> int:
        self.published.append((channel, payload))
        return 1


@pytest.fixture
async def sessions(test_session_factory: Any) -> AsyncIterator[Any]:
    yield test_session_factory
    async with test_session_factory() as session:
        await session.execute(
            delete(DiscoveredToken).where(DiscoveredToken.mint_address.like(f"{PREFIX}%"))
        )
        await session.commit()


@pytest.fixture(autouse=True)
def scoring_enabled(monkeypatch: pytest.MonkeyPatch) -> CapturingRedis:
    monkeypatch.setattr("app.workers.scoring_tasks.settings.FEATURE_AI_SCORING_ENABLED", True)
    redis = CapturingRedis()
    monkeypatch.setattr("app.core.events.get_redis", lambda: redis)
    return redis


async def _token_with_market(
    session: AsyncSession,
    mint: str,
    *,
    age_hours: int = 3,
    count: int = 4,
    now: datetime | None = None,
) -> Any:
    moment = now or datetime.now(UTC)
    token = await TokenRepository(session).insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}",
            "slot": 1,
            "discovered_at": moment - timedelta(hours=age_hours),
            "block_time": moment - timedelta(hours=age_hours),
            "metadata_status": "resolved",
        }
    )
    assert token is not None

    snapshots = MarketSnapshotRepository(session)
    for index in range(count):
        await snapshots.add_snapshot(
            {
                "token_id": token.id,
                "mint_address": mint,
                "captured_at": moment - timedelta(seconds=300 * index),
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
                "provider": "dexscreener",
            }
        )
    await session.commit()
    return token


# --- score_sweep --------------------------------------------------------------


async def test_the_sweep_scores_a_token_the_fast_path_missed(
    sessions: Any, scoring_enabled: CapturingRedis
) -> None:
    """The crash window between the enrichment commit and the scoring commit."""
    mint = f"{PREFIX}Missed"
    async with sessions() as session:
        await _token_with_market(session, mint)

    result = await _score_sweep()

    assert result["missing"] >= 1
    assert result["scored"] >= 1
    async with sessions() as session:
        assert await ScoreRepository(session).get_by_mint(mint) is not None


async def test_the_sweep_publishes_after_committing(
    sessions: Any, scoring_enabled: CapturingRedis
) -> None:
    mint = f"{PREFIX}SweepEvent"
    async with sessions() as session:
        await _token_with_market(session, mint)

    result = await _score_sweep()

    assert result["events"] >= 1
    assert scoring_enabled.published


async def test_the_sweep_ignores_tokens_with_no_market_data(
    sessions: Any, scoring_enabled: CapturingRedis
) -> None:
    """Nothing to score, so re-examining it every pass would be pure cost."""
    mint = f"{PREFIX}Barren"
    async with sessions() as session:
        await TokenRepository(session).insert_if_absent(
            {
                "mint_address": mint,
                "signature": f"sig-{mint}",
                "slot": 1,
                "discovered_at": datetime.now(UTC),
            }
        )
        await session.commit()

    await _score_sweep()

    async with sessions() as session:
        assert await ScoreRepository(session).get_by_mint(mint) is None


async def test_the_sweep_picks_up_a_stale_score(
    sessions: Any, scoring_enabled: CapturingRedis
) -> None:
    """The real shape of staleness: enrichment kept working, scoring did not.

    Fresh snapshots, an old score row - which is what a failed scoring
    transaction leaves behind. A fast-tier token is stale within a couple of
    minutes, and the sweep is what notices.
    """
    mint = f"{PREFIX}Stale"
    stale_moment = datetime.now(UTC) - timedelta(hours=2)

    async with sessions() as session:
        await _token_with_market(session, mint, age_hours=0)
        await TokenScoringService(session).score_mints([mint], now=stale_moment)
        await session.commit()

    await _score_sweep()

    async with sessions() as session:
        score = await ScoreRepository(session).get_by_mint(mint)
        assert score is not None
        assert score.evaluated_at > stale_moment


async def test_a_stale_score_with_no_fresh_data_stays_stale(
    sessions: Any, scoring_enabled: CapturingRedis
) -> None:
    """When enrichment itself has stalled, the sweep cannot invent a score.

    There is nothing inside the feature window to evaluate, so the row keeps its
    old `evaluated_at` rather than being refreshed against ancient data. This is
    the case read-time freshness exists for: the score is served discounted
    rather than silently restated as current.
    """
    mint = f"{PREFIX}NoFreshData"
    # Four hours old, so it sits in the young tier and carries a one-hour
    # window. Its newest snapshot is two hours old, and therefore outside it.
    two_hours_ago = datetime.now(UTC) - timedelta(hours=2)

    async with sessions() as session:
        await _token_with_market(session, mint, age_hours=2, now=two_hours_ago)
        await TokenScoringService(session).score_mints([mint], now=two_hours_ago)
        await session.commit()

    await _score_sweep()

    async with sessions() as session:
        score = await ScoreRepository(session).get_by_mint(mint)
        assert score is not None
        assert score.evaluated_at == two_hours_ago


async def test_the_sweep_rescores_an_outdated_model_version(
    sessions: Any, scoring_enabled: CapturingRedis
) -> None:
    """A mixed-version table makes every ranking meaningless."""
    from app.services.scoring.components.base import ComponentId
    from app.services.scoring.models.base import ComponentWeight, ModelConfig

    legacy = ModelConfig(
        version="test-legacy",
        components=(
            ComponentWeight(ComponentId.LIQUIDITY_DEPTH, Decimal("0.6")),
            ComponentWeight(ComponentId.SURVIVAL_AGE, Decimal("0.4")),
        ),
    )

    mint = f"{PREFIX}Outdated"
    async with sessions() as session:
        await _token_with_market(session, mint)
        await TokenScoringService(session, model=legacy).score_mints([mint])
        await session.commit()

    result = await _score_sweep()

    assert result["outdated"] >= 1
    async with sessions() as session:
        score = await ScoreRepository(session).get_by_mint(mint)
        assert score is not None
        assert score.model_version == "v1"


async def test_the_sweep_scores_a_token_once_even_if_it_matches_twice(
    sessions: Any, scoring_enabled: CapturingRedis
) -> None:
    """Stale and outdated at the same time must not write two history rows."""
    from app.services.scoring.components.base import ComponentId
    from app.services.scoring.models.base import ComponentWeight, ModelConfig

    legacy = ModelConfig(
        version="test-legacy-dup",
        components=(ComponentWeight(ComponentId.LIQUIDITY_DEPTH, Decimal("1.0")),),
    )
    mint = f"{PREFIX}Both"
    stale_moment = datetime.now(UTC) - timedelta(hours=2)

    async with sessions() as session:
        await _token_with_market(session, mint, age_hours=0)
        await TokenScoringService(session, model=legacy).score_mints([mint], now=stale_moment)
        await session.commit()

    await _score_sweep()

    async with sessions() as session:
        rows = (
            (
                await session.execute(
                    select(TokenScoreHistory).where(TokenScoreHistory.mint_address == mint)
                )
            )
            .scalars()
            .all()
        )
    # One from the legacy scoring, one from the sweep - not two from the sweep.
    assert len(rows) == 2


async def test_the_sweep_is_a_no_op_when_scoring_is_disabled(
    sessions: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.workers.scoring_tasks.settings.FEATURE_AI_SCORING_ENABLED", False)
    assert await _score_sweep() == {"skipped": "scoring_disabled"}


async def test_the_sweep_reports_an_empty_pass(
    sessions: Any, scoring_enabled: CapturingRedis
) -> None:
    result = await _score_sweep()
    assert result["scored"] == 0


async def test_a_token_whose_data_aged_out_does_not_consume_the_batch(
    sessions: Any, scoring_enabled: CapturingRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The livelock, at the level of the job that suffered it.

    A token last enriched well outside any scoring window can only ever be
    skipped. Before the fix the sweep selected exactly those tokens, filled its
    whole batch with them, and reported `scored: 0, skipped: 200` every cycle
    for days while a scorable token sat behind them.

    Asserted through the batch budget: with a batch of one, the scorable token
    is only reached if the aged-out one is no longer selected at all.
    """
    monkeypatch.setattr("app.workers.scoring_tasks.settings.SCORING_SWEEP_BATCH_LIMIT", 1)
    now = datetime.now(UTC)
    async with sessions() as session:
        # Enriched ten days ago: outside the widest window the engine can build.
        await _token_with_market(
            session, f"{PREFIX}AgedOut", now=now - timedelta(days=10), age_hours=240
        )
        await _token_with_market(session, f"{PREFIX}Current", now=now)

    result = await _score_sweep()

    assert result["missing"] == 1
    assert result["scored"] == 1
    assert result["skipped"] == 0
    async with sessions() as session:
        scores = ScoreRepository(session)
        assert await scores.get_by_mint(f"{PREFIX}Current") is not None
        assert await scores.get_by_mint(f"{PREFIX}AgedOut") is None


async def test_a_skipped_token_does_not_abort_the_batch(
    sessions: Any, scoring_enabled: CapturingRedis
) -> None:
    """Selection is a filter, not a guarantee.

    A token can pass the freshness predicate and still come back unscorable —
    the engine declines when too little component weight is available. That is
    a normal outcome and must cost only that token, leaving the rest of the
    batch scored.
    """
    now = datetime.now(UTC)
    async with sessions() as session:
        await _token_with_market(session, f"{PREFIX}Rich", now=now)
        # One observation, price only: not enough available weight to score.
        thin = await TokenRepository(session).insert_if_absent(
            {
                "mint_address": f"{PREFIX}Thin",
                "signature": f"sig-{PREFIX}Thin",
                "slot": 1,
                "discovered_at": now - timedelta(hours=3),
                "block_time": now - timedelta(hours=3),
            }
        )
        assert thin is not None
        await MarketSnapshotRepository(session).add_snapshot(
            {
                "token_id": thin.id,
                "mint_address": f"{PREFIX}Thin",
                "captured_at": now,
                "trading_status": TradingStatus.UNKNOWN,
                "provider": "dexscreener",
            }
        )
        await session.commit()

    result = await _score_sweep()

    assert result["scored"] >= 1
    async with sessions() as session:
        assert await ScoreRepository(session).get_by_mint(f"{PREFIX}Rich") is not None


# --- rescore_tokens -----------------------------------------------------------


async def test_rescoring_recomputes_an_existing_score(
    sessions: Any, scoring_enabled: CapturingRedis
) -> None:
    mint = f"{PREFIX}Rescore"
    async with sessions() as session:
        await _token_with_market(session, mint)
        await TokenScoringService(session).score_mints([mint])
        await session.commit()

    result = await _rescore_tokens(None, None, 100, False)

    assert result["model_version"] == "v1"
    assert result["scored"] >= 1


async def test_rescoring_is_silent_by_default(
    sessions: Any, scoring_enabled: CapturingRedis
) -> None:
    """A backfill is not news; announcing it would flood the Observatory Log."""
    mint = f"{PREFIX}Silent"
    async with sessions() as session:
        await _token_with_market(session, mint)
        await TokenScoringService(session).score_mints([mint])
        await session.commit()

    scoring_enabled.published.clear()
    await _rescore_tokens(None, None, 100, False)

    assert scoring_enabled.published == []


async def test_rescoring_can_publish_when_asked(
    sessions: Any, scoring_enabled: CapturingRedis
) -> None:
    mint = f"{PREFIX}Loud"
    async with sessions() as session:
        await _token_with_market(session, mint)
        # Old enough that the rescore trips the heartbeat and writes history.
        await TokenScoringService(session).score_mints(
            [mint], now=datetime.now(UTC) - timedelta(hours=1)
        )
        await session.commit()

    scoring_enabled.published.clear()
    await _rescore_tokens(None, None, 100, True)

    assert scoring_enabled.published


async def test_rescoring_pages_with_a_resumable_cursor(
    sessions: Any, scoring_enabled: CapturingRedis
) -> None:
    """Keyset, so a promotion drains the table without one giant transaction."""
    mints = [f"{PREFIX}Page{index}" for index in range(3)]
    async with sessions() as session:
        for mint in mints:
            await _token_with_market(session, mint)
        await TokenScoringService(session).score_mints(mints)
        await session.commit()

    first = await _rescore_tokens(None, None, 1, False)
    assert first["next_cursor"] is not None

    second = await _rescore_tokens(None, first["next_cursor"], 1, False)
    assert second["next_cursor"] != first["next_cursor"]


async def test_rescoring_reports_the_end_of_the_walk(
    sessions: Any, scoring_enabled: CapturingRedis
) -> None:
    result = await _rescore_tokens(None, "zzzzzzzz", 100, False)
    assert result["next_cursor"] is None
    assert result["scored"] == 0


async def test_rescoring_under_an_unknown_model_fails_loudly(
    sessions: Any, scoring_enabled: CapturingRedis
) -> None:
    """Never a silent fallback to the active model."""
    with pytest.raises(UnknownModelError):
        await _rescore_tokens("v99", None, 100, False)


async def test_rescoring_reproduces_the_same_score(
    sessions: Any, scoring_enabled: CapturingRedis
) -> None:
    """The reproducibility contract, exercised through the job that relies on it.

    Same stored snapshots and same model version must yield the same score; only
    `evaluated_at` moves.
    """
    mint = f"{PREFIX}Reproduce"
    moment = datetime.now(UTC)
    async with sessions() as session:
        await _token_with_market(session, mint, now=moment)
        await TokenScoringService(session).score_mints([mint], now=moment)
        await session.commit()

    async with sessions() as session:
        before = await ScoreRepository(session).get_by_mint(mint)
        assert before is not None
        original = before.score

    await _rescore_tokens(None, None, 100, False)

    async with sessions() as session:
        after = await ScoreRepository(session).get_by_mint(mint)
        assert after is not None
        assert after.score == original


# --- prune_score_history ------------------------------------------------------


async def test_pruning_thins_history_beyond_the_retention_window(
    sessions: Any, scoring_enabled: CapturingRedis
) -> None:
    mint = f"{PREFIX}Prune"
    # Anchored to the top of an hour. Deriving from the current minute would
    # let the rows straddle two hour buckets whenever the suite runs late in
    # an hour, leaving two survivors instead of one.
    old = (datetime.now(UTC) - timedelta(days=60)).replace(minute=0, second=0, microsecond=0)

    async with sessions() as session:
        token = await _token_with_market(session, mint)
        repo = ScoreHistoryRepository(session)
        for index in range(5):
            await repo.add_many(
                [
                    {
                        "token_id": token.id,
                        "mint_address": mint,
                        "model_version": "v1",
                        "score": Decimal("50.00"),
                        "evidence": Decimal("50.00"),
                        "coverage": Decimal("65.00"),
                        "market_risk": Decimal("0.00"),
                        "opportunity_raw": Decimal("50.00"),
                        "observations": 3,
                        "grade": ScoreGrade.WATCH,
                        "trigger": str(ScoreTrigger.HEARTBEAT),
                        "evaluated_at": old + timedelta(minutes=5 * index),
                    }
                ]
            )
        await session.commit()

    result = await _prune_score_history()

    assert result["deleted"] == 4
    async with sessions() as session:
        assert await ScoreHistoryRepository(session).count_for_mint(mint) == 1


async def test_pruning_leaves_recent_history_alone(
    sessions: Any, scoring_enabled: CapturingRedis
) -> None:
    mint = f"{PREFIX}Fresh"
    async with sessions() as session:
        await _token_with_market(session, mint)
        await TokenScoringService(session).score_mints([mint])
        await session.commit()

    await _prune_score_history()

    async with sessions() as session:
        assert await ScoreHistoryRepository(session).count_for_mint(mint) == 1
