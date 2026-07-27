"""Repository tests for snapshots and enrichment state."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import EnrichmentStatus, TradingStatus
from app.repositories.market import EnrichmentStateRepository, MarketSnapshotRepository
from app.repositories.token import TokenRepository

pytestmark = pytest.mark.integration

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


async def _token(
    session: AsyncSession, mint: str, *, discovered_at: datetime | None = None
) -> Any:
    return await TokenRepository(session).insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}",
            "slot": 1,
            "discovered_at": discovered_at or NOW,
        }
    )


def _snapshot(token: Any, *, captured_at: datetime, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "token_id": token.id,
        "mint_address": token.mint_address,
        "captured_at": captured_at,
        "price_usd": Decimal("0.000003155"),
        "liquidity_usd": Decimal("1000.00"),
        "market_cap": Decimal("50000.00"),
        "volume_24h": Decimal("2500.00"),
        "trading_status": TradingStatus.TRADING,
        "provider": "dexscreener",
    }
    values.update(overrides)
    return values


# --- Snapshots ---------------------------------------------------------------


async def test_snapshots_accumulate_rather_than_overwrite(db_session: AsyncSession) -> None:
    """The core historical guarantee: a refresh appends, never updates."""
    token = await _token(db_session, "MintHist")
    repo = MarketSnapshotRepository(db_session)

    for minute in range(3):
        await repo.add_snapshot(
            _snapshot(
                token,
                captured_at=NOW + timedelta(minutes=minute),
                price_usd=Decimal(f"0.00{minute + 1}"),
            )
        )

    assert await repo.count_for_mint("MintHist") == 3

    latest = await repo.latest_for_mint("MintHist")
    assert latest is not None
    assert latest.price_usd == Decimal("0.003")


async def test_decimal_precision_survives_the_round_trip(db_session: AsyncSession) -> None:
    """Meme coin prices run to 1e-12; float would silently destroy them."""
    token = await _token(db_session, "MintPrec")
    repo = MarketSnapshotRepository(db_session)
    tiny = Decimal("0.000000000123456789")

    await repo.add_snapshot(_snapshot(token, captured_at=NOW, price_usd=tiny))
    stored = await repo.latest_for_mint("MintPrec")

    assert stored is not None
    assert stored.price_usd == tiny


async def test_history_is_newest_first_and_paginated(db_session: AsyncSession) -> None:
    token = await _token(db_session, "MintPage")
    repo = MarketSnapshotRepository(db_session)
    for minute in range(5):
        await repo.add_snapshot(_snapshot(token, captured_at=NOW + timedelta(minutes=minute)))

    page_one, total = await repo.history_for_mint("MintPage", offset=0, limit=2)
    page_two, _ = await repo.history_for_mint("MintPage", offset=2, limit=2)

    assert total == 5
    assert page_one[0].captured_at > page_one[1].captured_at
    assert page_one[-1].captured_at > page_two[0].captured_at


async def test_history_filters_by_time_window(db_session: AsyncSession) -> None:
    token = await _token(db_session, "MintWindow")
    repo = MarketSnapshotRepository(db_session)
    for hour in range(4):
        await repo.add_snapshot(_snapshot(token, captured_at=NOW + timedelta(hours=hour)))

    rows, total = await repo.history_for_mint(
        "MintWindow", since=NOW + timedelta(hours=1), until=NOW + timedelta(hours=2)
    )
    assert total == 2
    assert len(rows) == 2


async def test_bulk_insert_writes_every_row(db_session: AsyncSession) -> None:
    token = await _token(db_session, "MintBulk")
    repo = MarketSnapshotRepository(db_session)

    written = await repo.add_many(
        [_snapshot(token, captured_at=NOW + timedelta(seconds=n)) for n in range(4)]
    )
    assert written == 4
    assert await repo.count_for_mint("MintBulk") == 4


async def test_bulk_insert_of_nothing_is_a_no_op(db_session: AsyncSession) -> None:
    assert await MarketSnapshotRepository(db_session).add_many([]) == 0


async def test_latest_per_token_returns_only_the_newest_each(
    db_session: AsyncSession,
) -> None:
    repo = MarketSnapshotRepository(db_session)
    first = await _token(db_session, "MintT1")
    second = await _token(db_session, "MintT2")

    await repo.add_snapshot(_snapshot(first, captured_at=NOW, volume_24h=Decimal("10")))
    await repo.add_snapshot(
        _snapshot(first, captured_at=NOW + timedelta(minutes=5), volume_24h=Decimal("900"))
    )
    await repo.add_snapshot(_snapshot(second, captured_at=NOW, volume_24h=Decimal("500")))

    rows, total = await repo.latest_per_token(order_by="volume_24h")

    assert total == 2, "one row per token, not one per snapshot"
    assert [snapshot.volume_24h for snapshot, _ in rows] == [Decimal("900"), Decimal("500")]


async def test_trending_filters_by_min_liquidity(db_session: AsyncSession) -> None:
    repo = MarketSnapshotRepository(db_session)
    rich = await _token(db_session, "MintRich")
    poor = await _token(db_session, "MintPoor")

    await repo.add_snapshot(_snapshot(rich, captured_at=NOW, liquidity_usd=Decimal("50000")))
    await repo.add_snapshot(_snapshot(poor, captured_at=NOW, liquidity_usd=Decimal("5")))

    rows, total = await repo.latest_per_token(min_liquidity=1000)
    assert total == 1
    assert rows[0][0].mint_address == "MintRich"


async def test_trending_sorts_nulls_last(db_session: AsyncSession) -> None:
    """A token with no volume must not outrank one that has volume."""
    repo = MarketSnapshotRepository(db_session)
    with_volume = await _token(db_session, "MintVol")
    without = await _token(db_session, "MintNoVol")

    await repo.add_snapshot(_snapshot(with_volume, captured_at=NOW, volume_24h=Decimal("42")))
    await repo.add_snapshot(_snapshot(without, captured_at=NOW, volume_24h=None))

    rows, _ = await repo.latest_per_token(order_by="volume_24h")
    assert rows[0][0].mint_address == "MintVol"


# --- Enrichment state --------------------------------------------------------


async def test_ensure_state_is_idempotent(db_session: AsyncSession) -> None:
    token = await _token(db_session, "MintState")
    repo = EnrichmentStateRepository(db_session)

    first = await repo.ensure_state(
        token_id=token.id, mint_address=token.mint_address, next_refresh_at=NOW
    )
    second = await repo.ensure_state(
        token_id=token.id, mint_address=token.mint_address, next_refresh_at=NOW
    )

    assert first is not None
    assert second is None, "a token must not be enrolled twice"
    assert await repo.count() == 1


async def test_claim_due_returns_only_due_active_tokens(db_session: AsyncSession) -> None:
    repo = EnrichmentStateRepository(db_session)
    due = await _token(db_session, "MintDue")
    later = await _token(db_session, "MintLater")

    await repo.ensure_state(
        token_id=due.id,
        mint_address=due.mint_address,
        next_refresh_at=NOW - timedelta(minutes=1),
    )
    await repo.ensure_state(
        token_id=later.id,
        mint_address=later.mint_address,
        next_refresh_at=NOW + timedelta(hours=1),
    )

    claimed = await repo.claim_due(now=NOW, limit=10)
    assert [state.mint_address for state in claimed] == ["MintDue"]


async def test_claiming_leases_a_token_so_it_is_not_claimed_twice(
    db_session: AsyncSession,
) -> None:
    """Prevents two worker replicas processing the same token."""
    repo = EnrichmentStateRepository(db_session)
    token = await _token(db_session, "MintLease")
    await repo.ensure_state(
        token_id=token.id, mint_address=token.mint_address, next_refresh_at=NOW
    )

    first = await repo.claim_due(now=NOW, limit=10, lease_seconds=120)
    second = await repo.claim_due(now=NOW, limit=10, lease_seconds=120)

    assert len(first) == 1
    assert second == [], "a leased token must not be immediately reclaimable"


async def test_record_result_success_resets_failures(db_session: AsyncSession) -> None:
    repo = EnrichmentStateRepository(db_session)
    token = await _token(db_session, "MintOk")
    state = await repo.ensure_state(
        token_id=token.id, mint_address=token.mint_address, next_refresh_at=NOW
    )
    assert state is not None
    state.consecutive_failures = 4

    await repo.record_result(
        state,
        now=NOW,
        next_refresh_at=NOW + timedelta(seconds=30),
        tier="fresh",
        succeeded=True,
        had_data=True,
    )

    assert state.consecutive_failures == 0
    assert state.total_snapshots == 1
    assert state.total_refreshes == 1
    assert state.last_success_at == NOW


async def test_record_result_tracks_empty_separately_from_failure(
    db_session: AsyncSession,
) -> None:
    """No pool yet is not an error and must not count towards dead-lettering."""
    repo = EnrichmentStateRepository(db_session)
    token = await _token(db_session, "MintEmpty")
    state = await repo.ensure_state(
        token_id=token.id, mint_address=token.mint_address, next_refresh_at=NOW
    )
    assert state is not None

    await repo.record_result(
        state,
        now=NOW,
        next_refresh_at=NOW + timedelta(seconds=60),
        tier="fresh",
        succeeded=True,
        had_data=False,
    )

    assert state.consecutive_empty == 1
    assert state.consecutive_failures == 0
    assert state.total_snapshots == 0


async def test_dead_letter_marks_the_state(db_session: AsyncSession) -> None:
    repo = EnrichmentStateRepository(db_session)
    token = await _token(db_session, "MintDead")
    state = await repo.ensure_state(
        token_id=token.id, mint_address=token.mint_address, next_refresh_at=NOW
    )
    assert state is not None

    await repo.record_result(
        state,
        now=NOW,
        next_refresh_at=NOW + timedelta(hours=6),
        tier="old",
        succeeded=False,
        had_data=False,
        error="provider exploded",
        dead_letter=True,
    )

    assert state.status is EnrichmentStatus.DEAD_LETTER
    assert state.last_error == "provider exploded"
    # Dead-lettered tokens drop out of the claim queue.
    assert await repo.claim_due(now=NOW + timedelta(days=1), limit=10) == []


async def test_dead_letters_can_be_requeued(db_session: AsyncSession) -> None:
    repo = EnrichmentStateRepository(db_session)
    token = await _token(db_session, "MintRequeue")
    state = await repo.ensure_state(
        token_id=token.id, mint_address=token.mint_address, next_refresh_at=NOW
    )
    assert state is not None
    state.status = EnrichmentStatus.DEAD_LETTER
    await db_session.flush()

    assert await repo.requeue_dead_letters(now=NOW) == 1
    assert len(await repo.claim_due(now=NOW, limit=10)) == 1


async def test_backfill_enrols_tokens_missing_state(db_session: AsyncSession) -> None:
    """Tokens discovered while the worker was down must not be orphaned."""
    await _token(db_session, "MintOrphan1")
    await _token(db_session, "MintOrphan2")
    repo = EnrichmentStateRepository(db_session)

    assert await repo.backfill_missing(limit=100) == 2
    assert await repo.backfill_missing(limit=100) == 0


async def test_counts_by_status(db_session: AsyncSession) -> None:
    repo = EnrichmentStateRepository(db_session)
    token = await _token(db_session, "MintCount")
    await repo.ensure_state(
        token_id=token.id, mint_address=token.mint_address, next_refresh_at=NOW
    )
    assert (await repo.counts_by_status()).get("active") == 1
