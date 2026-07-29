"""TokenScoringService against a real database.

Covers the contract the enrichment worker depends on: what gets written, what
does not, what survives a failure, and what the caller is handed to publish.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import TradingStatus
from app.models.score import ScoreGrade, ScoreTrigger, TokenScore, TokenScoreHistory
from app.repositories.market import MarketSnapshotRepository
from app.repositories.score import ScoreHistoryRepository, ScoreRepository
from app.repositories.token import TokenRepository
from app.services.scoring.components.base import ComponentId
from app.services.scoring.models.base import ComponentWeight, ModelConfig
from app.services.scoring.service import TokenScoringService

pytestmark = pytest.mark.integration

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


async def _token(
    session: AsyncSession,
    mint: str,
    *,
    block_time: datetime | None = None,
    metadata_status: str = "resolved",
) -> Any:
    return await TokenRepository(session).insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}",
            "slot": 1,
            "discovered_at": block_time or NOW - timedelta(hours=3),
            "block_time": block_time or NOW - timedelta(hours=3),
            "metadata_status": metadata_status,
        }
    )


async def _snapshots(
    session: AsyncSession,
    token: Any,
    *,
    count: int = 6,
    spacing_seconds: int = 300,
    liquidity: str = "50000",
    now: datetime = NOW,
    **overrides: Any,
) -> None:
    repo = MarketSnapshotRepository(session)
    for index in range(count):
        values: dict[str, Any] = {
            "token_id": token.id,
            "mint_address": token.mint_address,
            "captured_at": now - timedelta(seconds=spacing_seconds * index),
            "price_usd": Decimal("0.001"),
            "liquidity_usd": Decimal(liquidity),
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
        values.update(overrides)
        await repo.add_snapshot(values)
    await session.flush()


# --- The happy path -----------------------------------------------------------


async def test_scoring_writes_a_current_score_and_first_history_row(
    db_session: AsyncSession,
) -> None:
    token = await _token(db_session, "MintScored")
    await _snapshots(db_session, token)

    outcome = await TokenScoringService(db_session).score_mints(["MintScored"], now=NOW)

    assert outcome.scored == 1
    assert outcome.history_written == 1

    score = await ScoreRepository(db_session).get_by_mint("MintScored")
    assert score is not None
    assert score.model_version == "v1"
    assert Decimal(0) < score.score <= Decimal(100)
    assert score.evaluated_at == NOW
    assert score.observations == 6

    history = await ScoreHistoryRepository(db_session).latest_for_mint("MintScored")
    assert history is not None
    assert history.trigger == str(ScoreTrigger.FIRST)
    assert history.delta is None


async def test_the_component_breakdown_is_persisted_and_reconciles(
    db_session: AsyncSession,
) -> None:
    """The waterfall the UI renders must add up in the row it is read from."""
    token = await _token(db_session, "MintBreakdown")
    await _snapshots(db_session, token)

    await TokenScoringService(db_session).score_mints(["MintBreakdown"], now=NOW)
    history = await ScoreHistoryRepository(db_session).latest_for_mint("MintBreakdown")

    assert history is not None
    assert len(history.components) == 9  # every declared component, available or not
    assert history.reasons

    contributions = sum(Decimal(entry["contribution"]) for entry in history.components)
    assert contributions == history.opportunity_raw

    unavailable = [entry for entry in history.components if not entry["available"]]
    assert {entry["id"] for entry in unavailable} == {
        "contract_safety",
        "holder_distribution",
        "smart_money",
        "narrative",
    }


async def test_evidence_reflects_v1_coverage(db_session: AsyncSession) -> None:
    """0.65 of declared weight exists, so nothing can read as fully evidenced."""
    token = await _token(db_session, "MintEvidence")
    await _snapshots(db_session, token)

    await TokenScoringService(db_session).score_mints(["MintEvidence"], now=NOW)
    score = await ScoreRepository(db_session).get_by_mint("MintEvidence")

    assert score is not None
    assert score.coverage == Decimal("65.00")
    assert score.evidence <= Decimal("65.00")
    assert score.is_elite is False


async def test_a_batch_is_scored_in_one_pass(db_session: AsyncSession) -> None:
    mints = [f"MintBatch{index}" for index in range(5)]
    for mint in mints:
        await _snapshots(db_session, await _token(db_session, mint))

    outcome = await TokenScoringService(db_session).score_mints(mints, now=NOW)

    assert outcome.scored == 5
    stored = await ScoreRepository(db_session).get_many_by_mints(mints)
    assert set(stored) == set(mints)


# --- Not scoring is also an outcome -------------------------------------------


async def test_a_token_with_no_snapshots_is_skipped_not_failed(
    db_session: AsyncSession,
) -> None:
    """No market data is a normal state, not an error."""
    await _token(db_session, "MintNoMarket")

    outcome = await TokenScoringService(db_session).score_mints(["MintNoMarket"], now=NOW)

    assert outcome.skipped == 1
    assert outcome.scored == 0
    assert outcome.failed == 0
    assert await ScoreRepository(db_session).get_by_mint("MintNoMarket") is None


async def test_an_undiscovered_mint_is_reported_not_raised(
    db_session: AsyncSession,
) -> None:
    outcome = await TokenScoringService(db_session).score_mints(["MintGhost"], now=NOW)
    assert outcome.unknown == 1
    assert outcome.scored == 0


async def test_an_empty_batch_is_a_no_op(db_session: AsyncSession) -> None:
    outcome = await TokenScoringService(db_session).score_mints([], now=NOW)
    assert outcome.requested == 0


async def test_batched_history_lookup_handles_an_empty_request(
    db_session: AsyncSession,
) -> None:
    assert await ScoreHistoryRepository(db_session).recent_for_mints([]) == {}


async def test_duplicate_mints_in_a_batch_are_scored_once(
    db_session: AsyncSession,
) -> None:
    token = await _token(db_session, "MintDup")
    await _snapshots(db_session, token)

    outcome = await TokenScoringService(db_session).score_mints(
        ["MintDup", "MintDup"], now=NOW
    )

    assert outcome.scored == 1
    rows = (await db_session.execute(select(TokenScoreHistory))).scalars().all()
    assert len(rows) == 1


# --- Materiality --------------------------------------------------------------


async def test_an_unchanged_score_does_not_append_history(
    db_session: AsyncSession,
) -> None:
    """The property that keeps a 30-second tier from writing 2,880 rows a day."""
    token = await _token(db_session, "MintFlat")
    await _snapshots(db_session, token)
    service = TokenScoringService(db_session)

    await service.score_mints(["MintFlat"], now=NOW)
    second = await service.score_mints(["MintFlat"], now=NOW + timedelta(seconds=30))

    assert second.scored == 1
    assert second.history_written == 0
    assert await ScoreHistoryRepository(db_session).count_for_mint("MintFlat") == 1


async def test_the_current_score_is_updated_even_when_history_is_not(
    db_session: AsyncSession,
) -> None:
    token = await _token(db_session, "MintUpdated")
    await _snapshots(db_session, token)
    service = TokenScoringService(db_session)

    await service.score_mints(["MintUpdated"], now=NOW)
    later = NOW + timedelta(seconds=30)
    await service.score_mints(["MintUpdated"], now=later)

    score = await ScoreRepository(db_session).get_by_mint("MintUpdated")
    assert score is not None
    assert score.evaluated_at == later


async def test_the_heartbeat_appends_after_the_interval(
    db_session: AsyncSession,
) -> None:
    token = await _token(db_session, "MintHeartbeat")
    await _snapshots(db_session, token)
    service = TokenScoringService(db_session)

    await service.score_mints(["MintHeartbeat"], now=NOW)
    outcome = await service.score_mints(["MintHeartbeat"], now=NOW + timedelta(seconds=400))

    assert outcome.history_written == 1
    latest = await ScoreHistoryRepository(db_session).latest_for_mint("MintHeartbeat")
    assert latest is not None
    assert latest.trigger == str(ScoreTrigger.HEARTBEAT)


async def test_a_collapsing_pool_appends_with_a_veto_trigger(
    db_session: AsyncSession,
) -> None:
    """The case the whole risk gate exists for, end to end."""
    token = await _token(db_session, "MintRug")
    await _snapshots(db_session, token, liquidity="80000")
    service = TokenScoringService(db_session)
    await service.score_mints(["MintRug"], now=NOW)

    # The pool drains twenty minutes later.
    later = NOW + timedelta(minutes=20)
    await _snapshots(db_session, token, count=1, liquidity="8000", now=later)
    outcome = await service.score_mints(["MintRug"], now=later)

    assert outcome.history_written == 1
    score = await ScoreRepository(db_session).get_by_mint("MintRug")
    assert score is not None
    assert score.has_veto is True
    assert score.grade is ScoreGrade.CRITICAL
    assert score.score <= Decimal("35.00")

    latest = await ScoreHistoryRepository(db_session).latest_for_mint("MintRug")
    assert latest is not None
    assert latest.trigger == str(ScoreTrigger.VETO_CHANGE)
    assert latest.delta is not None and latest.delta < Decimal(0)


# --- Events -------------------------------------------------------------------


async def test_events_are_returned_for_the_caller_to_publish(
    db_session: AsyncSession,
) -> None:
    """The service never publishes; publishing before commit could lie."""
    token = await _token(db_session, "MintEvent")
    await _snapshots(db_session, token)

    outcome = await TokenScoringService(db_session).score_mints(["MintEvent"], now=NOW)

    assert len(outcome.events) == 1
    event = outcome.events[0]
    assert event["type"] == "score_changed"
    assert event["mint_address"] == "MintEvent"
    assert event["model_version"] == "v1"
    assert event["trigger"] == str(ScoreTrigger.FIRST)
    # Evidence, not confidence: a replayed event must not assert a freshness
    # that has since expired.
    assert "evidence" in event
    assert "confidence" not in event


async def test_no_event_when_nothing_material_changed(
    db_session: AsyncSession,
) -> None:
    token = await _token(db_session, "MintQuiet")
    await _snapshots(db_session, token)
    service = TokenScoringService(db_session)

    await service.score_mints(["MintQuiet"], now=NOW)
    second = await service.score_mints(["MintQuiet"], now=NOW + timedelta(seconds=30))

    assert second.events == ()


async def test_the_event_payload_is_json_serialisable(
    db_session: AsyncSession,
) -> None:
    import json

    token = await _token(db_session, "MintJson")
    await _snapshots(db_session, token)

    outcome = await TokenScoringService(db_session).score_mints(["MintJson"], now=NOW)
    assert json.loads(json.dumps(outcome.events[0]))


# --- Concurrency and retries --------------------------------------------------


async def test_a_stale_evaluation_cannot_overwrite_a_fresher_one(
    db_session: AsyncSession,
) -> None:
    """Three writers touch this table; only the newest evaluation may win."""
    token = await _token(db_session, "MintRace")
    await _snapshots(db_session, token)
    service = TokenScoringService(db_session)

    later = NOW + timedelta(minutes=10)
    await service.score_mints(["MintRace"], now=later)
    fresh = await ScoreRepository(db_session).get_by_mint("MintRace")
    assert fresh is not None
    fresh_score = fresh.score

    # A sweep or rescore that read older data lands afterwards.
    await service.score_mints(["MintRace"], now=NOW)

    stored = await ScoreRepository(db_session).get_by_mint("MintRace")
    assert stored is not None
    assert stored.evaluated_at == later
    assert stored.score == fresh_score


async def test_no_event_is_emitted_for_a_rejected_stale_write(
    db_session: AsyncSession,
) -> None:
    """Announcing it would tell subscribers the score moved backwards."""
    token = await _token(db_session, "MintRaceEvent")
    await _snapshots(db_session, token)
    service = TokenScoringService(db_session)

    await service.score_mints(["MintRaceEvent"], now=NOW + timedelta(minutes=10))
    outcome = await service.score_mints(["MintRaceEvent"], now=NOW)

    assert outcome.events == ()


async def test_scoring_is_idempotent_on_retry(db_session: AsyncSession) -> None:
    """A retried batch must not double-write history or change the score."""
    token = await _token(db_session, "MintRetry")
    await _snapshots(db_session, token)
    service = TokenScoringService(db_session)

    first = await service.score_mints(["MintRetry"], now=NOW)
    again = await service.score_mints(["MintRetry"], now=NOW)

    assert first.history_written == 1
    assert again.history_written == 0
    assert await ScoreHistoryRepository(db_session).count_for_mint("MintRetry") == 1


async def test_one_bad_token_does_not_cost_the_batch(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Isolation: the sweep retries the failure, the rest of the batch lands."""
    good = await _token(db_session, "MintGood")
    bad = await _token(db_session, "MintBad")
    await _snapshots(db_session, good)
    await _snapshots(db_session, bad)

    service = TokenScoringService(db_session)
    original = service._evaluate

    def _explode(token: Any, snapshots: Any, **kwargs: Any) -> Any:
        if token.mint_address == "MintBad":
            raise RuntimeError("feature extraction blew up")
        return original(token, snapshots, **kwargs)

    monkeypatch.setattr(service, "_evaluate", _explode)
    outcome = await service.score_mints(["MintGood", "MintBad"], now=NOW)

    assert outcome.scored == 1
    assert outcome.failed == 1
    assert await ScoreRepository(db_session).get_by_mint("MintGood") is not None
    assert await ScoreRepository(db_session).get_by_mint("MintBad") is None


# --- Model versions -----------------------------------------------------------


async def test_a_promotion_replaces_scores_from_another_version(
    db_session: AsyncSession,
) -> None:
    token = await _token(db_session, "MintPromote")
    await _snapshots(db_session, token)

    await TokenScoringService(db_session).score_mints(["MintPromote"], now=NOW)

    candidate = ModelConfig(
        version="test-promote",
        components=(
            ComponentWeight(ComponentId.LIQUIDITY_DEPTH, Decimal("0.6")),
            ComponentWeight(ComponentId.SURVIVAL_AGE, Decimal("0.4")),
        ),
    )
    # Deliberately *older* than the current row: a promotion is the one case
    # where an earlier evaluation is allowed to win.
    await TokenScoringService(db_session, model=candidate).score_mints(
        ["MintPromote"], now=NOW - timedelta(hours=1)
    )

    score = await ScoreRepository(db_session).get_by_mint("MintPromote")
    assert score is not None
    assert score.model_version == "test-promote"


async def test_the_model_version_travels_with_every_row(
    db_session: AsyncSession,
) -> None:
    token = await _token(db_session, "MintVersioned")
    await _snapshots(db_session, token)

    await TokenScoringService(db_session).score_mints(["MintVersioned"], now=NOW)

    score = await ScoreRepository(db_session).get_by_mint("MintVersioned")
    history = await ScoreHistoryRepository(db_session).latest_for_mint("MintVersioned")
    assert score is not None and history is not None
    assert score.model_version == history.model_version == "v1"


# --- Staleness ----------------------------------------------------------------


async def test_find_stale_uses_each_token_s_own_tier(
    db_session: AsyncSession,
) -> None:
    """Two minutes is nothing for a six-hourly token, a missed beat for a fresh one."""
    fresh = await _token(db_session, "MintFreshTier", block_time=NOW - timedelta(minutes=2))
    old = await _token(db_session, "MintOldTier", block_time=NOW - timedelta(days=5))
    await _snapshots(db_session, fresh, count=2, spacing_seconds=30)
    await _snapshots(db_session, old, count=2, spacing_seconds=30)

    service = TokenScoringService(db_session)
    await service.score_mints(["MintFreshTier", "MintOldTier"], now=NOW)

    # Ten minutes later: 20 intervals for the fresh tier, a fraction of one for
    # the old tier.
    stale = await service.find_stale(now=NOW + timedelta(minutes=10), limit=50)

    assert "MintFreshTier" in stale
    assert "MintOldTier" not in stale


async def test_a_recently_scored_token_is_not_stale(db_session: AsyncSession) -> None:
    token = await _token(db_session, "MintRecent", block_time=NOW - timedelta(minutes=2))
    await _snapshots(db_session, token, count=2, spacing_seconds=30)

    service = TokenScoringService(db_session)
    await service.score_mints(["MintRecent"], now=NOW)

    assert await service.find_stale(now=NOW + timedelta(seconds=30), limit=50) == []


async def test_mints_without_scores_finds_only_tokens_with_market_data(
    db_session: AsyncSession,
) -> None:
    with_market = await _token(db_session, "MintPending")
    await _snapshots(db_session, with_market, count=1)
    await _token(db_session, "MintNothing")

    pending = set(await ScoreRepository(db_session).mints_without_scores(limit=50))

    assert "MintPending" in pending
    assert "MintNothing" not in pending


async def test_outdated_model_mints_finds_the_backlog(
    db_session: AsyncSession,
) -> None:
    token = await _token(db_session, "MintOutdated")
    await _snapshots(db_session, token)
    await TokenScoringService(db_session).score_mints(["MintOutdated"], now=NOW)

    outdated = await ScoreRepository(db_session).outdated_model_mints(
        model_version="v2", limit=50
    )
    assert "MintOutdated" in set(outdated)

    current = await ScoreRepository(db_session).outdated_model_mints(
        model_version="v1", limit=50
    )
    assert "MintOutdated" not in set(current)


# --- History maintenance ------------------------------------------------------


async def test_pruning_thins_old_history_to_hourly_samples(
    db_session: AsyncSession,
) -> None:
    token = await _token(db_session, "MintPrune")
    repo = ScoreHistoryRepository(db_session)
    # Top of the hour: all six rows must land in one bucket for the thinning
    # to leave exactly one survivor.
    old = (NOW - timedelta(days=60)).replace(minute=0, second=0, microsecond=0)

    for index in range(6):
        await repo.add_many(
            [
                {
                    "token_id": token.id,
                    "mint_address": token.mint_address,
                    "model_version": "v1",
                    "score": Decimal("50.00"),
                    "evidence": Decimal("50.00"),
                    "coverage": Decimal("65.00"),
                    "market_risk": Decimal("0.00"),
                    "opportunity_raw": Decimal("50.00"),
                    "observations": 3,
                    "grade": ScoreGrade.WATCH,
                    "trigger": str(ScoreTrigger.HEARTBEAT),
                    "evaluated_at": old + timedelta(minutes=10 * index),
                }
            ]
        )

    deleted = await repo.prune_before(cutoff=NOW - timedelta(days=30))

    assert deleted == 5  # one hour bucket, one survivor
    assert await repo.count_for_mint("MintPrune") == 1


async def test_pruning_leaves_recent_history_alone(db_session: AsyncSession) -> None:
    token = await _token(db_session, "MintKeep")
    await _snapshots(db_session, token)
    await TokenScoringService(db_session).score_mints(["MintKeep"], now=NOW)

    deleted = await ScoreHistoryRepository(db_session).prune_before(
        cutoff=NOW - timedelta(days=30)
    )

    assert deleted == 0
    assert await ScoreHistoryRepository(db_session).count_for_mint("MintKeep") == 1


async def test_scores_survive_only_as_long_as_their_token(
    db_session: AsyncSession,
) -> None:
    token = await _token(db_session, "MintCascade2")
    await _snapshots(db_session, token)
    await TokenScoringService(db_session).score_mints(["MintCascade2"], now=NOW)

    await db_session.delete(token)
    await db_session.flush()

    assert (await db_session.execute(select(TokenScore))).scalars().first() is None
