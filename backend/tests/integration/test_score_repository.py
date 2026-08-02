"""Model and repository tests for the AI scoring tables.

Phase 1 covers storage only - there is no engine yet, so every score here is a
hand-written value. What is under test is the *storage contract* the engine will
depend on: the monotonic write guard, append-only history, the bounds, and the
cascade.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import TradingStatus
from app.models.score import ScoreGrade, ScoreTrigger, TokenScore, TokenScoreHistory
from app.repositories.market import MarketSnapshotRepository
from app.repositories.score import ScoreHistoryRepository, ScoreRepository
from app.repositories.token import TokenRepository

pytestmark = pytest.mark.integration

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
MODEL = "v1"


async def _token(session: AsyncSession, mint: str) -> Any:
    return await TokenRepository(session).insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}",
            "slot": 1,
            "discovered_at": NOW,
        }
    )


def _score_row(token: Any, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "token_id": token.id,
        "mint_address": token.mint_address,
        "model_version": MODEL,
        "score": Decimal("71.40"),
        "evidence": Decimal("52.10"),
        "coverage": Decimal("65.00"),
        "market_risk": Decimal("18.00"),
        "opportunity_raw": Decimal("83.00"),
        "observations": 9,
        "grade": ScoreGrade.STRONG,
        "is_elite": False,
        "has_veto": False,
        "latest_snapshot_at": NOW,
        "evaluated_at": NOW,
        "source_snapshot_captured_at": NOW,
    }
    values.update(overrides)
    return values


def _history_row(token: Any, **overrides: Any) -> dict[str, Any]:
    values = _score_row(token)
    values.update(
        {
            "components": [
                {
                    "id": "liquidity_depth",
                    "available": True,
                    "score": "62.50",
                    "contribution": "19.24",
                    "raw": {"liquidity_usd": "48200.0000"},
                    "reasons": ["LIQUIDITY_ADEQUATE"],
                }
            ],
            "reasons": ["MOMENTUM_ACCELERATING"],
            "delta": None,
            "trigger": ScoreTrigger.FIRST.value,
        }
    )
    values.update(overrides)
    return values


# --- Model shape --------------------------------------------------------------


async def test_score_round_trips_with_exact_decimals(db_session: AsyncSession) -> None:
    """Numeric, not float: 71.40 must come back as 71.40, not 71.400000000001."""
    token = await _token(db_session, "MintExact")
    repo = ScoreRepository(db_session)

    await repo.upsert_many([_score_row(token, score=Decimal("71.40"))])
    await db_session.flush()

    stored = await repo.get_by_mint("MintExact")
    assert stored is not None
    assert stored.score == Decimal("71.40")
    assert stored.evidence == Decimal("52.10")
    assert stored.grade is ScoreGrade.STRONG


async def test_confidence_is_not_a_stored_column() -> None:
    """Freshness decays with wall-clock time, so a stored confidence is a lie.

    Guards the split directly: if someone reintroduces the column, the design's
    read-time freshness guarantee is silently gone.
    """
    stored = set(TokenScore.__table__.columns.keys())
    assert "confidence" not in stored
    assert "freshness" not in stored
    # Removed for the same reason: read-modify-write under three writers.
    assert "previous_score" not in stored
    assert "elite_streak" not in stored
    assert "evidence" in stored


async def test_no_foreign_key_into_snapshots() -> None:
    """An FK here would block snapshot partitioning and retention."""
    for table in (TokenScore.__table__, TokenScoreHistory.__table__):
        referenced = {fk.column.table.name for fk in table.foreign_keys}
        assert referenced == {"discovered_tokens"}
        assert "source_snapshot_captured_at" in table.columns


async def test_one_score_row_per_token(db_session: AsyncSession) -> None:
    token = await _token(db_session, "MintUniq")
    db_session.add(TokenScore(**_score_row(token)))
    await db_session.flush()

    # Savepoint rather than a bare flush: the violation aborts the transaction,
    # and without one the session is unusable for the rest of the test.
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(TokenScore(**_score_row(token, mint_address="MintUniqOther")))
            await db_session.flush()

    assert await ScoreRepository(db_session).get_by_mint("MintUniq") is not None


@pytest.mark.parametrize("column", ["score", "evidence", "coverage", "market_risk"])
async def test_out_of_range_scores_are_rejected(db_session: AsyncSession, column: str) -> None:
    """The engine bounds these too; the constraint catches everything else."""
    token = await _token(db_session, f"MintRange{column}")

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(TokenScore(**_score_row(token, **{column: Decimal("240.00")})))
            await db_session.flush()


async def test_deleting_a_token_removes_its_scores(db_session: AsyncSession) -> None:
    token = await _token(db_session, "MintCascade")
    db_session.add(TokenScore(**_score_row(token)))
    db_session.add(TokenScoreHistory(**_history_row(token)))
    await db_session.flush()

    await db_session.delete(token)
    await db_session.flush()

    assert await ScoreRepository(db_session).get_by_mint("MintCascade") is None
    assert await ScoreHistoryRepository(db_session).count_for_mint("MintCascade") == 0


# --- Monotonic upsert ---------------------------------------------------------


async def test_upsert_inserts_then_updates_in_place(db_session: AsyncSession) -> None:
    token = await _token(db_session, "MintUpsert")
    repo = ScoreRepository(db_session)

    assert await repo.upsert_many([_score_row(token)]) == ["MintUpsert"]
    written = await repo.upsert_many(
        [
            _score_row(
                token,
                score=Decimal("80.00"),
                evaluated_at=NOW + timedelta(seconds=30),
            )
        ]
    )
    assert written == ["MintUpsert"]

    rows = (await db_session.execute(select(TokenScore))).scalars().all()
    assert len(rows) == 1
    assert rows[0].score == Decimal("80.00")


async def test_stale_evaluation_cannot_overwrite_a_fresher_one(
    db_session: AsyncSession,
) -> None:
    """The core guard: a rescore reading old data must not reinstate old scores.

    Three writers touch this table and only one of them is serialised by the
    enrichment claim, so this is enforced in SQL rather than by convention.
    """
    token = await _token(db_session, "MintMono")
    repo = ScoreRepository(db_session)

    await repo.upsert_many([_score_row(token, score=Decimal("80.00"), evaluated_at=NOW)])

    written = await repo.upsert_many(
        [
            _score_row(
                token,
                score=Decimal("10.00"),
                evaluated_at=NOW - timedelta(minutes=5),
            )
        ]
    )

    assert written == []  # rejected, and that is a normal outcome
    stored = await repo.get_by_mint("MintMono")
    assert stored is not None
    assert stored.score == Decimal("80.00")


async def test_equal_timestamps_do_not_overwrite(db_session: AsyncSession) -> None:
    """Strictly-greater, not greater-or-equal: a replayed write is a no-op."""
    token = await _token(db_session, "MintEqual")
    repo = ScoreRepository(db_session)

    await repo.upsert_many([_score_row(token, score=Decimal("55.00"))])
    written = await repo.upsert_many([_score_row(token, score=Decimal("99.00"))])

    assert written == []
    stored = await repo.get_by_mint("MintEqual")
    assert stored is not None
    assert stored.score == Decimal("55.00")


async def test_model_promotion_overwrites_regardless_of_timestamp(
    db_session: AsyncSession,
) -> None:
    """The one case where an older write is intended: promoting a new model."""
    token = await _token(db_session, "MintPromote")
    repo = ScoreRepository(db_session)

    await repo.upsert_many([_score_row(token, evaluated_at=NOW)])
    written = await repo.upsert_many(
        [
            _score_row(
                token,
                model_version="v2",
                score=Decimal("42.00"),
                evaluated_at=NOW - timedelta(hours=1),
            )
        ]
    )

    assert written == ["MintPromote"]
    stored = await repo.get_by_mint("MintPromote")
    assert stored is not None
    assert stored.model_version == "v2"
    assert stored.score == Decimal("42.00")


async def test_same_version_older_write_still_rejected_after_promotion(
    db_session: AsyncSession,
) -> None:
    """Promotion must not become a general-purpose bypass of the guard."""
    token = await _token(db_session, "MintAfterPromo")
    repo = ScoreRepository(db_session)

    await repo.upsert_many([_score_row(token, model_version="v2", evaluated_at=NOW)])
    written = await repo.upsert_many(
        [
            _score_row(
                token,
                model_version="v2",
                score=Decimal("1.00"),
                evaluated_at=NOW - timedelta(minutes=1),
            )
        ]
    )

    assert written == []


async def test_duplicate_token_in_one_batch_collapses_to_newest(
    db_session: AsyncSession,
) -> None:
    """Postgres refuses to touch a conflict row twice in one statement.

    A batch can legitimately carry a duplicate, so the repository collapses it
    rather than leaving every caller to trip over the error.
    """
    token = await _token(db_session, "MintDupe")
    repo = ScoreRepository(db_session)

    written = await repo.upsert_many(
        [
            _score_row(token, score=Decimal("10.00"), evaluated_at=NOW),
            _score_row(
                token,
                score=Decimal("90.00"),
                evaluated_at=NOW + timedelta(seconds=5),
            ),
        ]
    )

    assert written == ["MintDupe"]
    stored = await repo.get_by_mint("MintDupe")
    assert stored is not None
    assert stored.score == Decimal("90.00")


async def test_upsert_touches_updated_at(db_session: AsyncSession) -> None:
    """`onupdate` does not fire for ON CONFLICT, so it is set by hand."""
    token = await _token(db_session, "MintTouched")
    repo = ScoreRepository(db_session)

    await repo.upsert_many([_score_row(token)])
    await db_session.flush()
    first = await repo.get_by_mint("MintTouched")
    assert first is not None
    before = first.updated_at

    await repo.upsert_many(
        [_score_row(token, score=Decimal("72.00"), evaluated_at=NOW + timedelta(minutes=1))]
    )
    await db_session.refresh(first)

    assert first.updated_at >= before


async def test_upsert_of_nothing_is_a_no_op(db_session: AsyncSession) -> None:
    assert await ScoreRepository(db_session).upsert_many([]) == []


# --- Batch reads --------------------------------------------------------------


async def test_get_many_by_mints_keys_by_mint(db_session: AsyncSession) -> None:
    repo = ScoreRepository(db_session)
    for mint in ("MintBatchA", "MintBatchB"):
        await repo.upsert_many([_score_row(await _token(db_session, mint))])

    found = await repo.get_many_by_mints(["MintBatchA", "MintBatchB", "MintMissing"])

    assert set(found) == {"MintBatchA", "MintBatchB"}
    assert found["MintBatchA"].mint_address == "MintBatchA"
    assert await repo.get_many_by_mints([]) == {}


async def test_mints_without_scores_requires_a_snapshot(
    db_session: AsyncSession,
) -> None:
    """A token with no market data has nothing to score, so the sweep skips it."""
    scored = await _token(db_session, "MintSwept")
    unscored = await _token(db_session, "MintUnswept")
    no_market = await _token(db_session, "MintNoMarket")

    snapshots = MarketSnapshotRepository(db_session)
    for token in (scored, unscored):
        await snapshots.add_snapshot(
            {
                "token_id": token.id,
                "mint_address": token.mint_address,
                "captured_at": NOW,
                "price_usd": Decimal("0.001"),
                "trading_status": TradingStatus.TRADING,
                "provider": "dexscreener",
            }
        )
    await ScoreRepository(db_session).upsert_many([_score_row(scored)])

    pending = set(
        await ScoreRepository(db_session).mints_without_scores(since=NOW - timedelta(days=3))
    )

    assert "MintUnswept" in pending
    assert "MintSwept" not in pending
    assert no_market.mint_address not in pending


async def test_stale_before_returns_oldest_first(db_session: AsyncSession) -> None:
    repo = ScoreRepository(db_session)
    for offset, mint in ((30, "MintStaleOld"), (5, "MintStaleNew")):
        await repo.upsert_many(
            [
                _score_row(
                    await _token(db_session, mint),
                    evaluated_at=NOW - timedelta(minutes=offset),
                )
            ]
        )
    await repo.upsert_many(
        [_score_row(await _token(db_session, "MintFresh"), evaluated_at=NOW)]
    )

    stale = await repo.stale_before(cutoff=NOW - timedelta(minutes=1))

    assert [row.mint_address for row in stale] == ["MintStaleOld", "MintStaleNew"]


async def test_counts_by_grade(db_session: AsyncSession) -> None:
    repo = ScoreRepository(db_session)
    grades = (ScoreGrade.STRONG, ScoreGrade.STRONG, ScoreGrade.CRITICAL)
    for index, grade in enumerate(grades):
        await repo.upsert_many(
            [_score_row(await _token(db_session, f"MintGrade{index}"), grade=grade)]
        )

    counts = await repo.counts_by_grade()

    assert counts["strong"] == 2
    assert counts["critical"] == 1


# --- History ------------------------------------------------------------------


async def test_history_appends_rather_than_overwrites(db_session: AsyncSession) -> None:
    """The property the Elite streak and score deltas both depend on."""
    token = await _token(db_session, "MintHistory")
    repo = ScoreHistoryRepository(db_session)

    for index in range(3):
        await repo.add_many(
            [
                _history_row(
                    token,
                    score=Decimal(f"{60 + index}.00"),
                    evaluated_at=NOW + timedelta(minutes=index),
                    trigger=ScoreTrigger.DELTA.value,
                )
            ]
        )

    assert await repo.count_for_mint("MintHistory") == 3
    latest = await repo.latest_for_mint("MintHistory")
    assert latest is not None
    assert latest.score == Decimal("62.00")


async def test_components_jsonb_survives_the_round_trip(
    db_session: AsyncSession,
) -> None:
    """The explanation payload is read as a unit; nested shape must be intact."""
    token = await _token(db_session, "MintJson")
    repo = ScoreHistoryRepository(db_session)

    await repo.add_many([_history_row(token)])
    stored = await repo.latest_for_mint("MintJson")

    assert stored is not None
    assert stored.components[0]["id"] == "liquidity_depth"
    assert stored.components[0]["raw"]["liquidity_usd"] == "48200.0000"
    assert stored.reasons == ["MOMENTUM_ACCELERATING"]


async def test_history_defaults_to_empty_payload(db_session: AsyncSession) -> None:
    token = await _token(db_session, "MintDefaults")
    row = _history_row(token)
    del row["components"]
    del row["reasons"]

    await ScoreHistoryRepository(db_session).add_many([row])
    stored = await ScoreHistoryRepository(db_session).latest_for_mint("MintDefaults")

    assert stored is not None
    assert stored.components == []
    assert stored.reasons == []


async def test_delta_accepts_negative_values(db_session: AsyncSession) -> None:
    """A collapsing score is the most important delta to record."""
    token = await _token(db_session, "MintDelta")
    repo = ScoreHistoryRepository(db_session)

    await repo.add_many([_history_row(token, delta=Decimal("-42.50"))])
    stored = await repo.latest_for_mint("MintDelta")

    assert stored is not None
    assert stored.delta == Decimal("-42.50")


async def test_latest_for_mints_returns_one_row_per_mint(
    db_session: AsyncSession,
) -> None:
    repo = ScoreHistoryRepository(db_session)
    for mint in ("MintLatestA", "MintLatestB"):
        token = await _token(db_session, mint)
        for index in range(3):
            await repo.add_many(
                [
                    _history_row(
                        token,
                        score=Decimal(f"{50 + index}.00"),
                        evaluated_at=NOW + timedelta(minutes=index),
                    )
                ]
            )

    latest = await repo.latest_for_mints(["MintLatestA", "MintLatestB", "MintNope"])

    assert set(latest) == {"MintLatestA", "MintLatestB"}
    assert latest["MintLatestA"].score == Decimal("52.00")
    assert await repo.latest_for_mints([]) == {}


async def test_recent_for_mint_is_newest_first_and_bounded(
    db_session: AsyncSession,
) -> None:
    """Backs the Elite streak, which replays rows instead of reading a counter."""
    token = await _token(db_session, "MintRecent")
    repo = ScoreHistoryRepository(db_session)
    for index in range(5):
        await repo.add_many([_history_row(token, evaluated_at=NOW + timedelta(minutes=index))])

    recent = await repo.recent_for_mint("MintRecent", limit=3)

    assert len(recent) == 3
    assert [row.evaluated_at for row in recent] == sorted(
        (row.evaluated_at for row in recent), reverse=True
    )


async def test_history_pagination_and_time_bounds(db_session: AsyncSession) -> None:
    token = await _token(db_session, "MintPaged")
    repo = ScoreHistoryRepository(db_session)
    for index in range(5):
        await repo.add_many([_history_row(token, evaluated_at=NOW + timedelta(minutes=index))])

    page, total = await repo.history_for_mint("MintPaged", offset=0, limit=2)
    assert total == 5
    assert len(page) == 2
    assert page[0].evaluated_at == NOW + timedelta(minutes=4)

    windowed, windowed_total = await repo.history_for_mint(
        "MintPaged",
        since=NOW + timedelta(minutes=1),
        until=NOW + timedelta(minutes=3),
    )
    assert windowed_total == 3
    assert len(windowed) == 3


async def test_history_rejects_out_of_range_scores(db_session: AsyncSession) -> None:
    token = await _token(db_session, "MintHistRange")

    with pytest.raises((IntegrityError, DBAPIError)):
        async with db_session.begin_nested():
            await ScoreHistoryRepository(db_session).add_many(
                [_history_row(token, score=Decimal("-1.00"))]
            )


async def test_add_many_of_nothing_is_a_no_op(db_session: AsyncSession) -> None:
    assert await ScoreHistoryRepository(db_session).add_many([]) == 0
