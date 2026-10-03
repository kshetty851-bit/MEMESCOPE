"""Meme Lifecycle Lab — the forward replay resumes from checkpoints, and only
when it may.

The service-level half of ``tests/unit/test_mll_incremental.py`` and
``tests/unit/test_mll_checkpoint.py``: a second forward replay resumes; what
it reports and what it stores is what a forced full replay would; and each
thing that could make the stored state stale — a retroactive row, a
backdated link, another engine or configuration — sends it back to a full
replay with the reason recorded. The SQL watermark is held to the pure
reference digest over rows loaded through the same repository.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.lifecycle_lab import checkpoint as cp
from app.lifecycle_lab import service as service_module
from app.lifecycle_lab.domain import (
    AliasKind,
    CollectionRun,
    DataClass,
    MarketPoint,
    Metric,
    Observation,
    ResearchMode,
    Source,
    SourceStatus,
    ValueKind,
)
from app.lifecycle_lab.replay import ReplayState
from app.lifecycle_lab.service import FORWARD_HISTORY_LOOKBACK, LifecycleLabService
from app.models.lifecycle_lab import MllReplayCheckpoint
from app.models.market import TokenMarketSnapshot, TradingStatus
from app.models.social import PumpfunSocialSnapshot
from tests.integration.test_mll_service import (
    NOW,
    add_gdelt,
    add_snapshots,
    add_token,
    make_meme,
    mint,
    seeded_meme,
)

pytestmark = pytest.mark.integration

BASELINE = "baseline_attention_acceleration_market_confirmation"
FS = NOW - timedelta(hours=6)
FIRST = NOW - timedelta(hours=1, minutes=2)
AUTH = ResearchMode.AUTHORITATIVE


@pytest.fixture
def svc(db_session: AsyncSession) -> LifecycleLabService:
    return LifecycleLabService(db_session)


@pytest.fixture
def forward(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MLL_FORWARD_START", FS.isoformat())
    monkeypatch.setattr(settings, "MLL_CHECKPOINT_SAFETY_LAG_SECONDS", 1800)


async def _first_run(svc: LifecycleLabService, session: AsyncSession) -> tuple[str, str]:
    slug, meme_id, _m = await seeded_meme(svc, session)
    first = await svc.run_forward_replay(FIRST)
    for arm, run in first["runs"].items():
        assert run["replay"] == "full", arm
        assert run["invalidation_reason"] == "no_checkpoint", arm
    return slug, meme_id


async def _checkpoint(session: AsyncSession, arm: str = BASELINE) -> dict[str, Any]:
    rows = (await session.execute(text("select * from mll_replay_checkpoints"))).mappings()
    found = [dict(r) for r in rows if r["arm"] == arm]
    assert len(found) == 1
    return found[0]


async def _stored(svc: LifecycleLabService, run_id: str) -> dict[str, Any]:
    """Everything a forward run row stands for, minus row identity."""
    svc.session.expire_all()
    drop = {"id", "created_at", "updated_at"}

    def strip(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{k: v for k, v in r.items() if k not in drop} for r in rows]

    run = await svc.repo.get_run(run_id)
    assert run is not None
    summary = dict(run["summary"])
    for volatile in ("replay", "recompute", "duration_seconds"):
        summary.pop(volatile)
    events = (
        await svc.session.execute(
            text(
                "select meme_id, event_type, detected_at, mint_address, features "
                "from mll_meme_events where source_run_id = :r order by 1, 2, 3, 4"
            ),
            {"r": uuid.UUID(run_id)},
        )
    ).all()
    return {
        "fingerprint": run["input_fingerprint"],
        "trades_count": run["trades_count"],
        "ending_equity": run["ending_equity"],
        "summary": summary,
        "trades": strip(await svc.repo.trades_for_run(run_id)),
        "snapshots": strip(await svc.repo.snapshots_for_run(run_id)),
        "events": [tuple(e) for e in events],
    }


# --------------------------------------------------------------------------
# Resume, and equality with a forced full replay
# --------------------------------------------------------------------------


async def test_the_second_run_resumes_and_stores_what_a_full_run_would(
    svc: LifecycleLabService, db_session: AsyncSession, forward: None
) -> None:
    await _first_run(svc, db_session)
    row = await _checkpoint(db_session)
    assert row["processed_until"] <= FIRST - timedelta(minutes=30)
    assert row["processed_until"] > FIRST - timedelta(minutes=40)
    assert row["state_bytes"] > 0
    assert ReplayState.from_json(row["state"]).processed_until == row["processed_until"]

    savepoint = await db_session.begin_nested()
    incremental = await svc.run_forward_replay(NOW)
    run_id = incremental["runs"][BASELINE]["run_id"]
    for arm, run in incremental["runs"].items():
        assert run["replay"] == "incremental", (arm, run["invalidation_reason"])
        assert run["invalidation_reason"] is None
        assert 0 < run["ticks_processed"] < run["ticks"]
    after_incremental = await _stored(svc, run_id)
    checkpoint_incremental = await _checkpoint(db_session)
    run = await svc.repo.get_run(run_id)
    assert run is not None
    replay_info = run["summary"]["replay"]
    assert replay_info["mode"] == "incremental" == run["summary"]["recompute"]
    assert replay_info["resumed_from"] == row["processed_until"].isoformat()
    assert replay_info["duration_ms"] >= 0
    assert (
        replay_info["checkpoint_at"] == checkpoint_incremental["processed_until"].isoformat()
    )
    await savepoint.rollback()
    db_session.expire_all()

    forced = await svc.run_forward_replay(NOW, force_full=True)
    assert forced["runs"][BASELINE]["run_id"] == run_id
    for run in forced["runs"].values():
        assert (run["replay"], run["invalidation_reason"]) == ("full", "forced")
    after_full = await _stored(svc, run_id)
    checkpoint_full = await _checkpoint(db_session)

    assert after_incremental == after_full
    assert checkpoint_incremental["state"] == checkpoint_full["state"]
    assert checkpoint_incremental["input_watermark"] == checkpoint_full["input_watermark"]
    assert checkpoint_incremental["processed_until"] == checkpoint_full["processed_until"]


async def test_a_run_at_the_same_instant_resumes_and_changes_nothing(
    svc: LifecycleLabService, db_session: AsyncSession, forward: None
) -> None:
    await _first_run(svc, db_session)
    run_id = (await _checkpoint(db_session))["backtest_run_id"]
    before = await _stored(svc, str(run_id))
    again = await svc.run_forward_replay(FIRST)
    assert again["runs"][BASELINE]["replay"] == "incremental"
    assert await _stored(svc, str(run_id)) == before


# --------------------------------------------------------------------------
# Invalidation
# --------------------------------------------------------------------------


async def _second_reason(svc: LifecycleLabService, arm: str = BASELINE) -> str | None:
    out = await svc.run_forward_replay(NOW)
    run = out["runs"][arm]
    if run["replay"] == "incremental":
        return None
    reason = run["invalidation_reason"]
    assert isinstance(reason, str)
    stored = await svc.repo.get_run(run["run_id"])
    assert stored is not None
    assert stored["summary"]["replay"]["invalidation_reason"] == reason
    assert stored["summary"]["recompute"] == "full"
    return reason


async def test_a_retroactive_observation_invalidates(
    svc: LifecycleLabService, db_session: AsyncSession, forward: None
) -> None:
    """Stamped before the checkpoint, inserted after it — the late row."""
    _slug, meme_id = await _first_run(svc, db_session)
    processed_until = (await _checkpoint(db_session))["processed_until"]
    window_end = processed_until - timedelta(minutes=20)
    await svc.repo.insert_observations(
        [
            Observation(
                source=Source.WIKIPEDIA,
                metric=Metric.PAGEVIEWS,
                value_kind=ValueKind.WINDOW_COUNT,
                data_class=DataClass.FORWARD,
                source_timestamp=window_end - timedelta(hours=1),
                observed_at=window_end,
                retrieved_at=processed_until - timedelta(minutes=1),
                raw_value=Decimal(900),
                meme_id=meme_id,
                window_start=window_end - timedelta(hours=1),
                window_end=window_end,
                query="late",
            )
        ]
    )
    assert await _second_reason(svc) == f"retroactive_data_changed:{meme_id}:obs"


async def test_an_observation_retrieved_after_the_checkpoint_does_not_invalidate(
    svc: LifecycleLabService, db_session: AsyncSession, forward: None
) -> None:
    _slug, meme_id = await _first_run(svc, db_session)
    processed_until = (await _checkpoint(db_session))["processed_until"]
    await svc.repo.insert_observations(
        [
            Observation(
                source=Source.WIKIPEDIA,
                metric=Metric.PAGEVIEWS,
                value_kind=ValueKind.WINDOW_COUNT,
                data_class=DataClass.FORWARD,
                source_timestamp=processed_until - timedelta(hours=2),
                observed_at=processed_until - timedelta(hours=1),
                retrieved_at=processed_until + timedelta(minutes=1),
                raw_value=Decimal(900),
                meme_id=meme_id,
                window_start=processed_until - timedelta(hours=2),
                window_end=processed_until - timedelta(hours=1),
                query="on time",
            )
        ]
    )
    assert await _second_reason(svc) is None


async def test_a_new_link_into_the_past_invalidates_and_one_made_now_does_not(
    svc: LifecycleLabService, db_session: AsyncSession, forward: None
) -> None:
    slug, meme_id = await _first_run(svc, db_session)
    processed_until = (await _checkpoint(db_session))["processed_until"]

    savepoint = await db_session.begin_nested()
    now_link = mint()
    await svc.add_manual_link(slug, now_link, Decimal("0.9"), "tester", NOW)
    assert await _second_reason(svc) is None
    await savepoint.rollback()
    db_session.expire_all()

    backdated = mint()
    token = await add_token(db_session, backdated, at=NOW - timedelta(days=3))
    await add_snapshots(db_session, token, NOW - timedelta(hours=8), NOW)
    await svc.add_manual_link(
        slug, backdated, Decimal("0.9"), "tester", processed_until - timedelta(hours=2)
    )
    reason = await _second_reason(svc)
    assert reason is not None and reason.startswith(f"link_changed:{meme_id}:")


async def test_a_new_meme_invalidates(
    svc: LifecycleLabService, db_session: AsyncSession, forward: None
) -> None:
    await _first_run(svc, db_session)
    await make_meme(svc, at=NOW - timedelta(minutes=10))
    assert await _second_reason(svc) == "meme_set_changed"


async def test_another_configuration_or_engine_invalidates(
    svc: LifecycleLabService,
    db_session: AsyncSession,
    forward: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed LabConfig is refused at the experiment registry before a
    replay runs, so the stored hash is what can disagree — a checkpoint left
    by a build with other defaults. An edited engine is the other case."""
    await _first_run(svc, db_session)
    savepoint = await db_session.begin_nested()
    await db_session.execute(update(MllReplayCheckpoint).values(config_hash="0" * 64))
    assert await _second_reason(svc) == "config_changed"
    await savepoint.rollback()
    db_session.expire_all()

    sources = dict(service_module._engine_sources())
    sources["app.lifecycle_lab.replay"] += b"\n# edited\n"
    monkeypatch.setattr(service_module, "_engine_sources", lambda: sources)
    assert await _second_reason(svc) == "engine_code_changed"


async def test_a_replaced_run_row_invalidates(
    svc: LifecycleLabService, db_session: AsyncSession, forward: None
) -> None:
    """The checkpoint cascades with its run; an incremental run must write
    into the run that holds the rows it builds on."""
    await _first_run(svc, db_session)
    row = await _checkpoint(db_session)
    await db_session.execute(
        text("delete from mll_backtest_runs where id = :r"), {"r": row["backtest_run_id"]}
    )
    assert (await db_session.scalar(text("select count(*) from mll_replay_checkpoints"))) == 3
    assert await _second_reason(svc) == "no_checkpoint"


# --------------------------------------------------------------------------
# The SQL watermark is the pure digest
# --------------------------------------------------------------------------


async def _rich_world(svc: LifecycleLabService, session: AsyncSession) -> list[str]:
    """Every row kind the watermark covers, with NULLs, odd scales, a suspect
    snapshot, an unlink, a mint-level observation, pump.fun replies, backfill
    rows and candles, and global / per-meme / per-mint collection runs."""
    slug_a, meme_a, mint_a = await seeded_meme(svc, session)
    slug_b = await make_meme(
        svc,
        at=NOW - timedelta(hours=9),
        aliases=(("Frog Boss", AliasKind.NAME), ("$FBOSS", AliasKind.SYMBOL)),
    )
    meme_b = await svc.get_meme(slug_b)
    assert meme_b is not None
    shared = mint()
    token = await add_token(session, shared, at=NOW - timedelta(days=6))
    await svc.add_manual_link(slug_b, shared, Decimal("0.75"), "t", NOW - timedelta(hours=5))
    await svc.add_manual_link(slug_a, shared, Decimal("0.6"), "t", NOW - timedelta(hours=2))
    await svc.repo.unlink(meme_a, shared, NOW - timedelta(hours=1, minutes=10))
    t = NOW - timedelta(hours=6)
    i = 0
    while t < NOW:
        session.add(
            TokenMarketSnapshot(
                token_id=token.id,
                mint_address=shared,
                captured_at=t,
                price_usd=Decimal("0.000000012300000000") if i % 3 else None,
                volume_1h=Decimal("1234.5000") if i % 2 else None,
                volume_5m=Decimal("0"),
                market_cap=Decimal("50000.1000"),
                liquidity_usd=None,
                buy_count_24h=i,
                trading_status=TradingStatus.TRADING,
                provider="test",
                suspect=(i == 7),
            )
        )
        session.add(
            PumpfunSocialSnapshot(
                mint_address=shared,
                observed_at=t + timedelta(seconds=17),
                reply_count=None if i == 3 else 100 + i,
                source_sort="last_reply",
            )
        )
        t += timedelta(minutes=10)
        i += 1
    await session.flush()
    await add_gdelt(svc.repo, meme_b.id, NOW - timedelta(hours=7), NOW, value=2)
    await svc.repo.insert_observations(
        [
            Observation(
                source=Source.DEXSCREENER,
                metric=Metric.PROFILE,
                value_kind=ValueKind.SNAPSHOT,
                data_class=DataClass.FORWARD,
                source_timestamp=NOW - timedelta(hours=3),
                observed_at=NOW - timedelta(hours=3),
                retrieved_at=NOW - timedelta(hours=3) + timedelta(seconds=5),
                raw_value=Decimal(1),
                mint_address=shared,
                confidence=Decimal("0.5"),
                normalized_value=Decimal("0.25"),
            ),
            *[
                Observation(
                    source=Source.WIKIPEDIA,
                    metric=Metric.PAGEVIEWS,
                    value_kind=ValueKind.WINDOW_COUNT,
                    data_class=DataClass.BACKFILL,
                    source_timestamp=NOW - timedelta(days=d),
                    observed_at=NOW - timedelta(days=d - 1),
                    retrieved_at=NOW - timedelta(minutes=30),
                    raw_value=Decimal(10 * d),
                    meme_id=meme_b.id,
                    window_start=NOW - timedelta(days=d),
                    window_end=NOW - timedelta(days=d - 1),
                    query="Frog_Boss",
                )
                for d in range(1, 4)
            ],
        ]
    )
    for run in (
        CollectionRun(
            id=str(uuid.uuid4()),
            source=Source.WIKIPEDIA,
            status=SourceStatus.ERROR,
            started_at=NOW - timedelta(hours=2, minutes=1),
            finished_at=NOW - timedelta(hours=2),
            data_class=DataClass.FORWARD,
            reason="http_503",
            meme_id=meme_b.id,
        ),
        CollectionRun(
            id=str(uuid.uuid4()),
            source=Source.DEXSCREENER,
            status=SourceStatus.AVAILABLE,
            started_at=NOW - timedelta(hours=3, minutes=1),
            finished_at=NOW - timedelta(hours=3),
            data_class=DataClass.FORWARD,
            mint_address=shared,
        ),
        CollectionRun(
            id=str(uuid.uuid4()),
            source=Source.WIKIPEDIA,
            status=SourceStatus.AVAILABLE,
            started_at=NOW - timedelta(minutes=31),
            finished_at=NOW - timedelta(minutes=30),
            data_class=DataClass.BACKFILL,
            meme_id=meme_b.id,
        ),
    ):
        await svc.repo.record_run(run)
    await svc.repo.upsert_candles(
        [
            MarketPoint(
                mint_address=mint_a,
                observed_at=NOW - timedelta(hours=h),
                available_at=NOW - timedelta(hours=h),
                data_class=DataClass.BACKFILL,
                price_usd=Decimal("0.0105"),
                market_cap=Decimal("49000"),
                bar_volume=Decimal("777.25"),
                bar_seconds=3600,
                source="geckoterminal",
            )
            for h in range(1, 10)
        ],
        source="geckoterminal",
        retrieved_at=NOW,
    )
    return [m.id for m in await svc.repo.tracked_memes()]


@pytest.mark.parametrize(
    ("mode", "hindsight"),
    [
        (ResearchMode.AUTHORITATIVE, False),
        (ResearchMode.EXPLORATORY, False),
        (ResearchMode.EXPLORATORY, True),
    ],
)
async def test_the_sql_watermark_equals_the_pure_digest(
    svc: LifecycleLabService,
    db_session: AsyncSession,
    mode: ResearchMode,
    hindsight: bool,
) -> None:
    """Byte-for-byte: the SQL key expressions and the pure ``*_key``
    functions, over the rows ``_load`` hands the replay. (This is the test
    that caught forward rows being admitted on the backfill timeline.)"""
    meme_ids = await _rich_world(svc, db_session)
    since = NOW - timedelta(hours=6) - FORWARD_HISTORY_LOOKBACK
    memes = [m for m in await svc.repo.tracked_memes() if m.id in set(meme_ids)]
    inputs = await svc._load(
        memes, until=NOW, since=since, include_backfill=mode is ResearchMode.EXPLORATORY
    )
    for at in (
        NOW - timedelta(hours=7),
        NOW - timedelta(hours=1, minutes=5),
        NOW - timedelta(minutes=20),
        NOW,
    ):
        sql = await svc.repo.input_watermarks(
            meme_ids=meme_ids, at=at, mode=mode, since=since, hindsight_links=hindsight
        )
        pure = cp.input_watermarks(
            inputs, at=at, mode=mode, since=since, hindsight_links=hindsight
        )
        diff = {
            m: {k: (v, pure[m].get(k)) for k, v in kinds.items() if v != pure[m].get(k)}
            for m, kinds in sql.items()
            if kinds != pure.get(m)
        }
        assert sql == pure, (at, diff)
    # Not vacuous: every kind the digest covers has rows by the end.
    final = await svc.repo.input_watermarks(
        meme_ids=meme_ids, at=NOW, mode=mode, since=since, hindsight_links=hindsight
    )
    for kind in cp.MEME_KINDS:
        assert any(final[m][kind] != "0:0" for m in meme_ids), kind
    assert final[cp.GLOBAL_KEY]["run"] != "0:0"
