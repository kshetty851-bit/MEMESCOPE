"""Regression tests for the score sweep livelock (MEMESCOPE_AUDIT.md §3.5).

`mints_without_scores` asked for tokens with *any* snapshot and applied `LIMIT`
with no `ORDER BY`. Neither half was right on its own:

  * the predicate did not match what the engine scores on — it needs an
    observation inside the token's history window, not merely somewhere in the
    table — so tokens last enriched days ago were selected, produced an empty
    window, and were skipped as unscorable;
  * without an `ORDER BY`, Postgres returned the same rows from the same heap
    positions every pass, so those same tokens were re-selected forever.

Together they starved the sweep completely: 2,880 permanently unscorable tokens
held the head of the queue and consumed the entire 200-row budget every 15
minutes, so the stale and outdated arms never got a turn and the sweep scored
nothing for days while reporting `scored: 0, skipped: 200` each cycle.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import TradingStatus
from app.repositories.market import MarketSnapshotRepository
from app.repositories.score import ScoreRepository
from app.repositories.token import TokenRepository
from app.services.scoring.service import TokenScoringService

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
#: Comfortably inside any tier's history window.
FRESH = NOW - timedelta(minutes=5)
#: Comfortably outside the widest window the engine can build (72 h).
ANCIENT = NOW - timedelta(days=10)
#: What the service would compute; used directly so these tests pin the
#: repository contract rather than the policy.
SINCE = NOW - timedelta(hours=72)


async def _token_with_snapshot(
    session: AsyncSession, mint: str, *, captured_at: datetime | None
) -> Any:
    """A discovered token, optionally with one market snapshot."""
    token = await TokenRepository(session).insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}",
            "slot": 1,
            "discovered_at": NOW - timedelta(days=1),
        }
    )
    assert token is not None
    if captured_at is not None:
        await MarketSnapshotRepository(session).add_snapshot(
            {
                "token_id": token.id,
                "mint_address": mint,
                "captured_at": captured_at,
                "price_usd": Decimal("0.001"),
                "liquidity_usd": Decimal("5000"),
                "trading_status": TradingStatus.TRADING,
                "provider": "test",
            }
        )
    await session.flush()
    return token


class TestStarvationPrevention:
    async def test_the_livelock_scenario(self, db_session: AsyncSession) -> None:
        """The exact production failure, reproduced at small scale.

        Many tokens whose newest observation is far outside any scoring window,
        plus one that can actually be scored. Before the fix the batch was
        filled with the unscorable ones and the scorable token was never
        reached; now it is the only thing returned.
        """
        for index in range(10):
            await _token_with_snapshot(db_session, f"MintStuck{index}", captured_at=ANCIENT)
        await _token_with_snapshot(db_session, "MintScorable", captured_at=FRESH)

        # A batch smaller than the stuck set: before the fix this could not
        # possibly reach the scorable token.
        selected = await ScoreRepository(db_session).mints_without_scores(
            since=SINCE, limit=5
        )

        assert list(selected) == ["MintScorable"]

    async def test_permanently_unscorable_tokens_are_never_selected(
        self, db_session: AsyncSession
    ) -> None:
        """A token whose data is too old to score must not consume budget.

        Selecting it can only ever produce a skip, and a skip that repeats
        every cycle is the livelock.
        """
        await _token_with_snapshot(db_session, "MintTooOld", captured_at=ANCIENT)

        selected = await ScoreRepository(db_session).mints_without_scores(
            since=SINCE, limit=200
        )

        assert "MintTooOld" not in selected

    async def test_a_stuck_token_returns_once_it_is_re_enriched(
        self, db_session: AsyncSession
    ) -> None:
        """Exclusion is a function of the data, not a permanent blacklist.

        Nothing is marked as failed anywhere, so a token the enrichment worker
        catches up on is eligible again on the very next sweep — without any
        bookkeeping to reset.
        """
        token = await _token_with_snapshot(db_session, "MintRevived", captured_at=ANCIENT)
        repo = ScoreRepository(db_session)
        assert "MintRevived" not in await repo.mints_without_scores(since=SINCE, limit=50)

        await MarketSnapshotRepository(db_session).add_snapshot(
            {
                "token_id": token.id,
                "mint_address": "MintRevived",
                "captured_at": FRESH,
                "price_usd": Decimal("0.002"),
                "trading_status": TradingStatus.TRADING,
                "provider": "test",
            }
        )
        await db_session.flush()

        assert "MintRevived" in await repo.mints_without_scores(since=SINCE, limit=50)


class TestOrdering:
    async def test_the_order_is_deterministic(self, db_session: AsyncSession) -> None:
        """Two identical calls must return an identical page.

        Without a total order Postgres is free to return rows in any order, and
        in practice returned the same *wrong* ones every time.
        """
        for index in range(6):
            await _token_with_snapshot(
                db_session, f"MintOrder{index}", captured_at=FRESH - timedelta(minutes=index)
            )

        repo = ScoreRepository(db_session)
        first = list(await repo.mints_without_scores(since=SINCE, limit=6))
        second = list(await repo.mints_without_scores(since=SINCE, limit=6))

        assert first == second
        assert len(first) == 6

    async def test_newest_observation_first(self, db_session: AsyncSession) -> None:
        """Priority *and* anti-starvation.

        The token whose data just landed is the one a score is most useful for,
        and ordering on a column that enrichment keeps rewriting means the head
        of the queue rotates on its own — so a token that cannot be scored for
        some reason the predicate does not capture drifts down it rather than
        blocking the batch.
        """
        await _token_with_snapshot(
            db_session, "MintOldest", captured_at=NOW - timedelta(hours=10)
        )
        await _token_with_snapshot(
            db_session, "MintNewest", captured_at=NOW - timedelta(minutes=1)
        )
        await _token_with_snapshot(
            db_session, "MintMiddle", captured_at=NOW - timedelta(hours=2)
        )

        selected = list(
            await ScoreRepository(db_session).mints_without_scores(since=SINCE, limit=10)
        )

        assert selected == ["MintNewest", "MintMiddle", "MintOldest"]

    async def test_ties_are_broken_by_mint_address(self, db_session: AsyncSession) -> None:
        """Identical timestamps must still yield a total order.

        Batch enrichment writes many snapshots with the same `captured_at`, so
        ties are common rather than theoretical.
        """
        for mint in ("MintC", "MintA", "MintB"):
            await _token_with_snapshot(db_session, mint, captured_at=FRESH)

        selected = list(
            await ScoreRepository(db_session).mints_without_scores(since=SINCE, limit=10)
        )

        assert selected == ["MintA", "MintB", "MintC"]


class TestBatchingContract:
    async def test_the_limit_is_respected(self, db_session: AsyncSession) -> None:
        for index in range(8):
            await _token_with_snapshot(
                db_session, f"MintBatch{index}", captured_at=FRESH - timedelta(seconds=index)
            )

        selected = await ScoreRepository(db_session).mints_without_scores(
            since=SINCE, limit=3
        )

        assert len(selected) == 3

    async def test_no_mint_is_returned_twice(self, db_session: AsyncSession) -> None:
        """A token with many snapshots is still one row.

        The lateral aggregates rather than joining row-per-snapshot; a plain
        join would return a token once per observation and the sweep would
        score it repeatedly in one batch.
        """
        token = await _token_with_snapshot(db_session, "MintMany", captured_at=FRESH)
        snapshots = MarketSnapshotRepository(db_session)
        for minute in range(1, 5):
            await snapshots.add_snapshot(
                {
                    "token_id": token.id,
                    "mint_address": "MintMany",
                    "captured_at": FRESH - timedelta(minutes=minute),
                    "price_usd": Decimal("0.001"),
                    "trading_status": TradingStatus.TRADING,
                    "provider": "test",
                }
            )
        await db_session.flush()

        selected = list(
            await ScoreRepository(db_session).mints_without_scores(since=SINCE, limit=50)
        )

        assert selected.count("MintMany") == 1

    async def test_tokens_with_no_market_data_are_still_excluded(
        self, db_session: AsyncSession
    ) -> None:
        """The original contract, preserved: nothing to score means not selected."""
        await _token_with_snapshot(db_session, "MintNoMarket", captured_at=None)

        selected = await ScoreRepository(db_session).mints_without_scores(
            since=SINCE, limit=50
        )

        assert "MintNoMarket" not in selected

    async def test_already_scored_tokens_are_excluded(
        self, db_session: AsyncSession
    ) -> None:
        """This arm is "missing", not "stale" — `find_stale` owns re-evaluation."""
        from app.models.score import ScoreGrade

        token = await _token_with_snapshot(db_session, "MintScored", captured_at=FRESH)
        await ScoreRepository(db_session).upsert_many(
            [
                {
                    "token_id": token.id,
                    "mint_address": "MintScored",
                    "model_version": "v1",
                    "score": Decimal("50.00"),
                    "evidence": Decimal("40.00"),
                    "coverage": Decimal("45.00"),
                    "market_risk": Decimal("20.00"),
                    "opportunity_raw": Decimal("60.00"),
                    "observations": 3,
                    "grade": ScoreGrade.WATCH,
                    "is_elite": False,
                    "has_veto": False,
                    "evaluated_at": NOW,
                }
            ]
        )
        await db_session.flush()

        selected = await ScoreRepository(db_session).mints_without_scores(
            since=SINCE, limit=50
        )

        assert "MintScored" not in selected


class TestCutoffDerivation:
    async def test_the_cutoff_comes_from_the_widest_possible_window(
        self, db_session: AsyncSession
    ) -> None:
        """72 hours today: 12 observations x the old tier's 6-hour interval.

        Asserted as a relationship rather than a constant so that raising
        `SCORING_FEATURE_WINDOW` widens the cutoff with it instead of silently
        leaving tokens the engine could now score outside the sweep.
        """
        service = TokenScoringService(db_session)
        cutoff = service.scorable_since(now=NOW)

        expected = NOW - timedelta(
            seconds=12 * service.policy.old_interval_seconds
        )
        assert cutoff == expected

    async def test_a_token_just_inside_the_cutoff_is_selected(
        self, db_session: AsyncSession
    ) -> None:
        """The boundary must not exclude a token the engine could still score."""
        service = TokenScoringService(db_session)
        cutoff = service.scorable_since(now=NOW)
        await _token_with_snapshot(
            db_session, "MintEdge", captured_at=cutoff + timedelta(minutes=1)
        )

        selected = await ScoreRepository(db_session).mints_without_scores(
            since=cutoff, limit=50
        )

        assert "MintEdge" in selected
