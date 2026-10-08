"""Meme Lifecycle Lab persistence: the guarantees the database has to keep.

The Lab's whole claim is "what was known at T". Every test here is one of the
ways a repository could quietly break that claim — a re-run that moves a
link's `linked_at`, a revised GDELT bucket that overwrites the first reading,
a missing reply counter read as zero, retention deleting the series a replay
will need — and pins the property rather than the mechanism.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.lifecycle_lab.domain import (
    AliasKind,
    CollectionRun,
    DataClass,
    EventType,
    LinkMethod,
    MarketPoint,
    MemeEvent,
    MemeTokenLink,
    Metric,
    Observation,
    ResearchMode,
    Source,
    SourceStatus,
    Timeliness,
    Unavailable,
    ValueKind,
)
from app.lifecycle_lab.repository import SOURCE_PROGRAM, LifecycleLabRepository
from app.models.lifecycle_lab import MllMeme, MllMemeEvent
from app.models.market import (
    LANE_NORMAL,
    EnrichmentStatus,
    TokenEnrichmentState,
    TokenMarketSnapshot,
    TradingStatus,
)
from app.models.social import PumpfunSocialSnapshot
from app.models.token import DiscoveredToken
from app.workers.retention_tasks import _prune_market_snapshots, _prune_pumpfun_social

pytestmark = pytest.mark.integration

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _mint(tag: str) -> str:
    # ≤ 44 chars: `discovered_tokens.mint_address` is String(44).
    return f"MLL{tag}{uuid.uuid4().hex}"[:44]


@pytest.fixture
def repo(db_session: AsyncSession) -> LifecycleLabRepository:
    return LifecycleLabRepository(db_session)


async def _meme(repo: LifecycleLabRepository, slug: str | None = None) -> str:
    meme = await repo.create_meme(
        slug=slug or f"mll-{uuid.uuid4().hex[:12]}",
        display_name="Pepe",
        tracking_started_at=T0,
        wikipedia_title="Pepe_the_Frog",
        gdelt_query='"pepe the frog"',
    )
    return meme.id


def _obs(meme_id: str, *, value: str = "10", **kw: object) -> Observation:
    base: dict[str, object] = {
        "source": Source.GDELT,
        "metric": Metric.MENTIONS,
        "value_kind": ValueKind.WINDOW_COUNT,
        "data_class": DataClass.FORWARD,
        "source_timestamp": T0,
        "observed_at": T0 + timedelta(minutes=15),
        "retrieved_at": T0 + timedelta(minutes=16),
        "raw_value": Decimal(value),
        "meme_id": meme_id,
        "window_start": T0,
        "window_end": T0 + timedelta(minutes=15),
        "query": "pepe",
    }
    base.update(kw)
    return Observation(**base)  # type: ignore[arg-type]


def _link(meme_id: str, mint: str, at: datetime, **kw: object) -> MemeTokenLink:
    base: dict[str, object] = {
        "meme_id": meme_id,
        "mint_address": mint,
        "method": LinkMethod.EXACT_SYMBOL,
        "confidence": Decimal("0.9"),
        "linked_at": at,
    }
    base.update(kw)
    return MemeTokenLink(**base)  # type: ignore[arg-type]


async def _token(
    session: AsyncSession, mint: str, *, discovered_at: datetime
) -> DiscoveredToken:
    token = DiscoveredToken(
        mint_address=mint,
        name="Pepe",
        symbol="PEPE",
        signature=f"sig-{mint}",
        slot=1,
        block_time=discovered_at - timedelta(minutes=1),
        discovered_at=discovered_at,
        creator_address="Creator1111",
    )
    session.add(token)
    await session.flush()
    return token


# --------------------------------------------------------------------------
# Observations
# --------------------------------------------------------------------------


class TestObservations:
    async def test_insert_is_idempotent_and_the_first_reading_wins(
        self, repo: LifecycleLabRepository
    ) -> None:
        """GDELT revises recent buckets. The revision is a later claim; the
        first value is what was known then, and must survive a re-collection."""
        meme_id = await _meme(repo)
        first = _obs(meme_id, value="10")
        revised = _obs(meme_id, value="14", retrieved_at=T0 + timedelta(hours=2))
        assert first.dedupe_key() == revised.dedupe_key()

        assert await repo.insert_observations([first, first]) == 1
        assert await repo.insert_observations([revised]) == 0

        rows = await repo.observations(
            meme_ids=[meme_id], mints=[], until=T0 + timedelta(days=1)
        )
        assert [o.raw_value for o in rows] == [Decimal("10")]
        assert rows[0] == first

    async def test_large_batches_are_chunked(self, repo: LifecycleLabRepository) -> None:
        meme_id = await _meme(repo)
        rows = [
            _obs(meme_id, observed_at=T0 + timedelta(minutes=i), retrieved_at=T0)
            for i in range(2500)
        ]
        assert await repo.insert_observations(rows) == 2500

    async def test_reads_over_fetch_backfill_and_gate_forward_on_retrieval(
        self, repo: LifecycleLabRepository
    ) -> None:
        """FORWARD rows are candidates once retrieved; BACKFILL rows once their
        source period has passed (EXPLORATORY may place them there). `pit`
        makes the exact cut — the repository must not drop either early."""
        meme_id = await _meme(repo)
        until = T0 + timedelta(hours=1)
        known = _obs(meme_id, query="known")
        late = _obs(meme_id, query="late", retrieved_at=until + timedelta(seconds=1))
        backfill = _obs(
            meme_id,
            query="backfill",
            data_class=DataClass.BACKFILL,
            retrieved_at=T0 + timedelta(days=20),
        )
        await repo.insert_observations([known, late, backfill])

        got = await repo.observations(meme_ids=[meme_id], mints=[], until=until)
        assert {o.query for o in got} == {"known", "backfill"}

    async def test_pumpfun_replies_are_read_in_place_and_null_is_not_zero(
        self, repo: LifecycleLabRepository, db_session: AsyncSession
    ) -> None:
        mint = _mint("pf")
        for minutes, count in ((0, 12), (10, None), (20, 30), (90, 99)):
            db_session.add(
                PumpfunSocialSnapshot(
                    mint_address=mint,
                    observed_at=T0 + timedelta(minutes=minutes),
                    reply_count=count,
                    source_sort="last_reply",
                )
            )
        await db_session.flush()

        got = await repo.observations(meme_ids=[], mints=[mint], until=T0 + timedelta(hours=1))

        assert [o.raw_value for o in got] == [Decimal(12), Decimal(30)]
        first = got[0]
        assert first.source is Source.PUMPFUN_REPLIES
        assert first.metric is Metric.REPLIES_TOTAL
        assert first.value_kind is ValueKind.CUMULATIVE
        assert first.data_class is DataClass.FORWARD
        assert first.source_timestamp == first.observed_at == first.retrieved_at == T0
        assert first.mint_address == mint and first.meme_id is None
        assert first.query == "last_reply"
        assert first.source_url == "https://frontend-api-v3.pump.fun/coins?sort=last_reply"
        assert await repo.pumpfun_social_latest_observed_at() is not None


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------


class TestLinks:
    async def test_linked_at_is_written_once(self, repo: LifecycleLabRepository) -> None:
        """A matcher re-finds an existing link on every pass. If that moved
        `linked_at`, the link would vanish from replays of the period it was
        already known in; if a re-link could move it earlier, it would
        fabricate foresight. Neither may happen."""
        meme_id = await _meme(repo)
        mint = _mint("lk")
        assert await repo.add_link(_link(meme_id, mint, T0), evidence={"a": 1}, linked_by="t")
        for at in (T0 + timedelta(days=3), T0 - timedelta(days=3)):
            again = _link(meme_id, mint, at, method=LinkMethod.MANUAL, confidence=Decimal(1))
            assert not await repo.add_link(again, evidence=None, linked_by="other")

        (link,) = await repo.links_for([meme_id])
        assert link.linked_at == T0
        assert link.method is LinkMethod.EXACT_SYMBOL
        assert link.confidence == Decimal("0.9")

    async def test_unlink_is_written_once_and_stays_visible(
        self, repo: LifecycleLabRepository
    ) -> None:
        meme_id = await _meme(repo)
        mint = _mint("ul")
        await repo.add_link(_link(meme_id, mint, T0), evidence=None, linked_by="t")

        assert await repo.unlink(meme_id, mint, T0 + timedelta(days=1))
        assert not await repo.unlink(meme_id, mint, T0 + timedelta(days=2))

        (link,) = await repo.links_for([meme_id])
        assert link.unlinked_at == T0 + timedelta(days=1)
        assert link.visible_at(T0 + timedelta(hours=1))
        assert not link.visible_at(T0 + timedelta(days=1))

    async def test_aliases_normalise_and_dedupe(self, repo: LifecycleLabRepository) -> None:
        meme_id = await _meme(repo)
        assert await repo.add_alias(meme_id, "$PEPE", AliasKind.SYMBOL, T0) is not None
        assert await repo.add_alias(meme_id, "  pepe ", AliasKind.SYMBOL, T0) is None
        assert await repo.add_alias(meme_id, "#Pepe", AliasKind.HASHTAG, T0) is not None
        assert await repo.add_alias(meme_id, "$ ", AliasKind.SYMBOL, T0) is None

        aliases = await repo.aliases_for([meme_id])
        # Same normalised text, ordered by kind: the order is total.
        assert [(a.alias, a.kind) for a in aliases] == [
            ("#Pepe", AliasKind.HASHTAG),
            ("$PEPE", AliasKind.SYMBOL),
        ]

    async def test_memes_and_tokens_round_trip(
        self, repo: LifecycleLabRepository, db_session: AsyncSession
    ) -> None:
        slug = f"mll-{uuid.uuid4().hex[:10]}"
        meme_id = await _meme(repo, slug)
        meme = await repo.get_meme_by_slug(slug)
        assert meme is not None and meme.id == meme_id
        assert meme.wikipedia_title == "Pepe_the_Frog"
        assert meme_id in {m.id for m in await repo.tracked_memes()}

        mint = _mint("tk")
        await _token(db_session, mint, discovered_at=T0)
        (info,) = await repo.tokens([mint, _mint("absent")])
        assert (info.name, info.symbol, info.creator_address) == (
            "Pepe",
            "PEPE",
            "Creator1111",
        )
        assert info.created_at == T0 - timedelta(minutes=1)
        assert info.discovered_at == T0


# --------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------


class TestRuns:
    async def test_runs_are_recorded_once_and_latest_is_per_scope(
        self, repo: LifecycleLabRepository
    ) -> None:
        meme_id = await _meme(repo)

        def run(minutes: int, **kw: object) -> CollectionRun:
            base: dict[str, object] = {
                "id": str(uuid.uuid4()),
                "source": Source.WIKIPEDIA,
                "status": SourceStatus.AVAILABLE,
                "started_at": T0 + timedelta(minutes=minutes),
                "finished_at": T0 + timedelta(minutes=minutes, seconds=5),
                "data_class": DataClass.FORWARD,
            }
            base.update(kw)
            return CollectionRun(**base)  # type: ignore[arg-type]

        old_global = run(0)
        new_global = run(10, status=SourceStatus.ERROR, reason="http_503")
        subject = run(5, meme_id=meme_id, observations_written=3, detail={"n": Decimal(1)})
        for r in (old_global, new_global, subject, subject):
            await repo.record_run(r)

        got = await repo.runs(meme_ids=[meme_id], since=None, until=T0 + timedelta(hours=1))
        assert [r.id for r in got] == [old_global.id, subject.id, new_global.id]
        assert got[1].detail == {"n": "1"}

        latest = [
            r
            for r in await repo.latest_runs_by_source()
            if r.id in {old_global.id, new_global.id, subject.id}
        ]
        assert [r.id for r in latest] == [new_global.id, subject.id]
        assert latest[0].reason == "http_503"


# --------------------------------------------------------------------------
# Market
# --------------------------------------------------------------------------


class TestMarket:
    async def test_candle_backfill_round_trip(self, repo: LifecycleLabRepository) -> None:
        """A bar is stored by its start and read back as a point at its close;
        re-fetching the same bars writes nothing."""
        mint = _mint("cd")
        points = [
            MarketPoint(
                mint_address=mint,
                observed_at=T0 + timedelta(minutes=i + 1),
                available_at=T0 + timedelta(minutes=i + 1),
                data_class=DataClass.BACKFILL,
                price_usd=Decimal("0.000001234") * (i + 1),
                bar_volume=Decimal("100.5"),
                bar_seconds=60,
                source="geckoterminal",
            )
            for i in range(3)
        ]
        retrieved = T0 + timedelta(days=10)
        assert (
            await repo.upsert_candles(points, source="geckoterminal", retrieved_at=retrieved)
            == 3
        )
        assert (
            await repo.upsert_candles(points, source="geckoterminal", retrieved_at=retrieved)
            == 0
        )

        got = await repo.market_points(
            [mint], since=None, until=T0 + timedelta(hours=1), include_backfill=True
        )
        assert got == points
        assert (
            await repo.market_points(
                [mint], since=None, until=T0 + timedelta(hours=1), include_backfill=False
            )
            == []
        )
        upto = await repo.market_points(
            [mint], since=None, until=T0 + timedelta(minutes=2), include_backfill=True
        )
        assert len(upto) == 2

    async def test_forward_points_come_from_snapshots_without_suspects(
        self, repo: LifecycleLabRepository, db_session: AsyncSession
    ) -> None:
        mint = _mint("fw")
        token = await _token(db_session, mint, discovered_at=T0)
        for minutes, suspect in ((0, False), (5, True), (10, False)):
            db_session.add(
                TokenMarketSnapshot(
                    token_id=token.id,
                    mint_address=mint,
                    captured_at=T0 + timedelta(minutes=minutes),
                    price_usd=Decimal("0.01"),
                    volume_5m=Decimal("12.5"),
                    buy_count_24h=7,
                    trading_status=TradingStatus.TRADING,
                    provider="test",
                    suspect=suspect,
                )
            )
        await db_session.flush()

        got = await repo.market_points(
            [mint], since=T0, until=T0 + timedelta(hours=1), include_backfill=True
        )
        assert [p.observed_at for p in got] == [T0, T0 + timedelta(minutes=10)]
        assert all(p.data_class is DataClass.FORWARD for p in got)
        assert got[0].available_at == got[0].observed_at
        assert (got[0].volume_5m, got[0].buy_count_24h) == (Decimal("12.5"), 7)


# --------------------------------------------------------------------------
# Enrolment and cadence
# --------------------------------------------------------------------------


class TestCoverage:
    async def test_linked_mints_are_enrolled_once(
        self, repo: LifecycleLabRepository, db_session: AsyncSession
    ) -> None:
        """Discovery is down; a linked coin may never have reached
        `discovered_tokens`, and nothing prices a mint that is not there."""
        meme_id = await _meme(repo)
        linked, unlinked = _mint("en"), _mint("un")
        await repo.add_link(_link(meme_id, linked, T0), evidence=None, linked_by="t")
        await repo.add_link(_link(meme_id, unlinked, T0), evidence=None, linked_by="t")
        await repo.unlink(meme_id, unlinked, T0 + timedelta(hours=1))

        now = T0 + timedelta(days=1)
        assert await repo.enrol_linked_mints(now=now, limit=10_000) >= 1
        assert await repo.enrol_linked_mints(now=now, limit=10_000) == 0

        token = await db_session.scalar(
            select(DiscoveredToken).where(DiscoveredToken.mint_address == linked)
        )
        assert token is not None
        assert token.source_program == SOURCE_PROGRAM
        assert token.block_time is None  # unknown stays unknown
        state = await db_session.scalar(
            select(TokenEnrichmentState).where(TokenEnrichmentState.mint_address == linked)
        )
        assert state is not None
        assert state.status == EnrichmentStatus.ACTIVE and state.priority == LANE_NORMAL
        assert (
            await db_session.scalar(
                select(DiscoveredToken.id).where(DiscoveredToken.mint_address == unlinked)
            )
            is None
        )

    async def test_archived_memes_are_not_covered(
        self, repo: LifecycleLabRepository, db_session: AsyncSession
    ) -> None:
        meme_id = await _meme(repo)
        mint = _mint("ar")
        await repo.add_link(_link(meme_id, mint, T0), evidence=None, linked_by="t")
        await db_session.execute(
            MllMeme.__table__.update()
            .where(MllMeme.id == uuid.UUID(meme_id))
            .values(status="archived")
        )
        assert mint not in await repo.current_linked_mints(limit=10_000)

    async def test_pacing_pulls_due_time_forward_and_never_back(
        self, repo: LifecycleLabRepository, db_session: AsyncSession, monkeypatch
    ) -> None:
        """The worker reschedules an old token six hours out; the Lab needs it
        every `MLL_MARKET_INTERVAL_SECONDS`. A clamp, never an assignment: a
        token due sooner keeps its cadence, a failing one keeps its backoff."""
        monkeypatch.setattr(settings, "MLL_MARKET_INTERVAL_SECONDS", 300)
        monkeypatch.setattr(settings, "MLL_MAX_TRACKED_TOKENS", 10_000)
        now = T0 + timedelta(days=1)
        meme_id = await _meme(repo)
        cases = {
            "slow": (now + timedelta(hours=6), 0),
            "soon": (now + timedelta(seconds=30), 0),
            "failing": (now + timedelta(hours=2), 3),
        }
        mints = {}
        for tag, (due, failures) in cases.items():
            mint = _mint(tag)
            mints[tag] = mint
            token = await _token(db_session, mint, discovered_at=T0 - timedelta(days=5))
            db_session.add(
                TokenEnrichmentState(
                    token_id=token.id,
                    mint_address=mint,
                    next_refresh_at=due,
                    consecutive_failures=failures,
                )
            )
            await repo.add_link(_link(meme_id, mint, T0), evidence=None, linked_by="t")
        await db_session.flush()

        assert await repo.pace_linked_mints(now=now) == 1
        assert await repo.pace_linked_mints(now=now) == 0  # an unchanged minute writes nothing

        due = {
            tag: await db_session.scalar(
                select(TokenEnrichmentState.next_refresh_at).where(
                    TokenEnrichmentState.mint_address == mint
                )
            )
            for tag, mint in mints.items()
        }
        assert due["slow"] == now + timedelta(seconds=300)
        assert due["soon"] == cases["soon"][0]
        assert due["failing"] == cases["failing"][0]


# --------------------------------------------------------------------------
# Research results
# --------------------------------------------------------------------------


class TestResults:
    async def test_meme_level_events_dedupe_and_outcomes_keep_reasons(
        self, repo: LifecycleLabRepository, db_session: AsyncSession
    ) -> None:
        """NULLs are distinct in a plain unique key, so without the coalesce
        expression a meme-level event (no mint) would be re-inserted by every
        replay."""
        meme_id = await _meme(repo)
        event = MemeEvent(
            meme_id=meme_id,
            event_type=EventType.ATTENTION_ACCELERATION,
            detected_at=T0,
            mode=ResearchMode.AUTHORITATIVE,
            detector_version="mll-events-v1",
            features={"velocity": Decimal("2.5"), "gone": Unavailable("no_source")},
        )
        with_mint = MemeEvent(**{**_fields(event), "mint_address": _mint("ev")})
        assert await repo.save_events([event, with_mint]) == 2
        assert await repo.save_events([event, with_mint]) == 0

        row = await db_session.scalar(
            select(MllMemeEvent).where(
                MllMemeEvent.meme_id == uuid.UUID(meme_id),
                MllMemeEvent.mint_address.is_not(None),
            )
        )
        assert row is not None
        assert row.features == {"velocity": "2.5", "gone": {"unavailable": "no_source"}}

        await repo.record_timeliness(
            str(row.id),
            Timeliness(
                detected_at=T0,
                mint_address=row.mint_address or "",
                price_before_detection=Decimal("0.001"),
                price_at_detection=Decimal("0.002"),
                returns={
                    timedelta(minutes=5): Decimal("0.1"),
                    timedelta(hours=24): Unavailable("no_market_data"),
                },
                run_up_before_detection=Unavailable("no_lookback"),
            ),
            complete_at=T0 + timedelta(days=2),
        )
        await db_session.refresh(row)
        assert row.return_5m == Decimal("0.1")
        assert row.return_24h is None and row.run_up_before_detection is None
        assert row.outcome_reasons == {
            "return_24h": "no_market_data",
            "run_up_before_detection": "no_lookback",
        }

    async def test_experiment_registry_and_trade_upsert(
        self, repo: LifecycleLabRepository
    ) -> None:
        meme_id = await _meme(repo)
        key = f"exp-{uuid.uuid4().hex[:8]}"
        spec = {
            "experiment_key": key,
            "hypothesis": "attention acceleration with market confirmation",
            "strategy_spec": {"size": Decimal("10")},
            "spec_hash": "a" * 64,
            "mode": "authoritative",
            "arm": "baseline_attention_acceleration_market_confirmation",
            "status": "registered",
        }
        exp_id = await repo.upsert_experiment(spec)
        assert await repo.upsert_experiment(spec) == exp_id
        with pytest.raises(ValueError, match="different spec"):
            await repo.upsert_experiment({**spec, "spec_hash": "b" * 64})

        run_id = await repo.save_run(
            {
                "experiment_id": exp_id,
                "mode": "authoritative",
                "segment": "all",
                "status": "running",
                "started_at": T0,
                "window_start": T0,
                "window_end": T0 + timedelta(days=1),
                "config_spec": {"x": Decimal("1")},
            }
        )
        mint = _mint("tr")
        trade = {
            "trade_key": "k1",
            "arm": "baseline_attention_acceleration_market_confirmation",
            "meme_id": meme_id,
            "mint_address": mint,
            "entry_at": T0,
            "entry_price": Decimal("0.001"),
            "size_usd": Decimal("10"),
            "quantity": Decimal("9970"),
            "entry_fees_usd": Decimal("0.03"),
            "age_bucket": "1-3d",
            "entry_reason": "attention_acceleration",
            "entry_features": {"v": Decimal("2")},
            "evidence_timeline": [],
            "cost_model": "flat",
            "status": "open",
        }
        assert await repo.save_trades(run_id, [trade]) == 1
        closed = {
            **trade,
            "entry_reason": "rewritten",  # must NOT stick
            "exit_at": T0 + timedelta(hours=2),
            "exit_price": Decimal("0.002"),
            "exit_reason": "take_profit",
            "pnl_usd": Decimal("9.9"),
            "status": "closed",
        }
        assert await repo.save_trades(run_id, [closed]) == 1
        (row,) = await repo.trades_for_run(run_id)
        assert row["status"] == "closed" and row["exit_reason"] == "take_profit"
        assert row["entry_reason"] == "attention_acceleration"

        snap = {
            "at": T0,
            "equity": Decimal("1000"),
            "cash": Decimal("990"),
            "deployed": Decimal("10"),
            "realized_pnl": Decimal("0"),
            "open_positions": 1,
        }
        assert await repo.save_snapshots(run_id, [snap, snap]) == 1
        await repo.update_run(
            run_id, {"status": "completed", "finished_at": T0, "trades_count": 1}
        )
        got = await repo.get_run(run_id)
        assert got is not None and got["status"] == "completed"
        assert got["config_spec"] == {"x": "1"}


def _fields(event: MemeEvent) -> dict[str, object]:
    return {name: getattr(event, name) for name in MemeEvent.__dataclass_fields__}


# --------------------------------------------------------------------------
# Retention
# --------------------------------------------------------------------------

RETENTION_PREFIX = "MLLRet"
RETENTION_SLUG = "mll-retention-test"
OLD = datetime.now(UTC) - timedelta(days=60)


@pytest.fixture
async def committed(test_session_factory):
    """Retention opens its own sessions, so fixture rows must be committed.
    Teardown removes only this module's rows, by prefix."""
    async with test_session_factory() as s:
        yield s
        await s.rollback()
        for table in ("token_market_snapshots", "pumpfun_social_snapshots"):
            await s.execute(
                text(f"DELETE FROM {table} WHERE mint_address LIKE :p"),  # noqa: S608
                {"p": f"{RETENTION_PREFIX}%"},
            )
        await s.execute(text("DELETE FROM mll_memes WHERE slug = :s"), {"s": RETENTION_SLUG})
        await s.execute(
            text("DELETE FROM discovered_tokens WHERE mint_address LIKE :p"),
            {"p": f"{RETENTION_PREFIX}%"},
        )
        await s.commit()


class TestRetentionProtectsLinkedMints:
    async def test_current_links_keep_their_series_and_unlinked_ones_do_not(
        self, committed: AsyncSession
    ) -> None:
        """The replay reads a linked coin's market and reply history weeks
        after the fact — after the ordinary window would have deleted it."""
        repo = LifecycleLabRepository(committed)
        meme_id = await _meme(repo, RETENTION_SLUG)
        mints = {
            "linked": f"{RETENTION_PREFIX}Linked{uuid.uuid4().hex[:20]}",
            "unlinked": f"{RETENTION_PREFIX}Unlinked{uuid.uuid4().hex[:20]}",
            "never": f"{RETENTION_PREFIX}Never{uuid.uuid4().hex[:20]}",
        }
        for tag, mint in mints.items():
            token = await _token(committed, mint, discovered_at=OLD)
            committed.add(
                TokenMarketSnapshot(
                    token_id=token.id,
                    mint_address=mint,
                    captured_at=OLD,
                    price_usd=Decimal("0.001"),
                    trading_status=TradingStatus.TRADING,
                    provider="test",
                )
            )
            committed.add(
                PumpfunSocialSnapshot(
                    mint_address=mint, observed_at=OLD, reply_count=5, source_sort="last_reply"
                )
            )
            if tag != "never":
                await repo.add_link(_link(meme_id, mint, OLD), evidence=None, linked_by="t")
        await repo.unlink(meme_id, mints["unlinked"], OLD + timedelta(days=1))
        await committed.commit()

        await _prune_market_snapshots(7)
        await _prune_pumpfun_social(7)

        async def count(model: type, mint: str) -> int:
            rows = await committed.scalars(select(model.id).where(model.mint_address == mint))
            return len(rows.all())

        assert await count(TokenMarketSnapshot, mints["linked"]) == 1
        assert await count(PumpfunSocialSnapshot, mints["linked"]) == 1
        for tag in ("unlinked", "never"):
            assert await count(TokenMarketSnapshot, mints[tag]) == 0, tag
            assert await count(PumpfunSocialSnapshot, mints[tag]) == 0, tag


class TestPriorityBeatHook:
    async def test_pacing_failure_never_costs_the_lanes_a_pass(
        self, test_session_factory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The Lab is research. If its pass raises, the beat still returns the
        display and nursery results, with the failure reported, not raised."""
        from app.workers import priority_tasks

        monkeypatch.setattr(priority_tasks, "SessionFactory", test_session_factory)
        monkeypatch.setattr(settings, "FEATURE_LIFECYCLE_LAB_ENABLED", True)
        monkeypatch.setattr(settings, "FEATURE_PRIORITY_ENRICHMENT_ENABLED", False)

        async def _boom(self: object, *, now: datetime, limit: int | None = None) -> int:
            raise RuntimeError("lab down")

        monkeypatch.setattr(LifecycleLabRepository, "enrol_linked_mints", _boom)
        result = await priority_tasks._refresh()
        assert "nursery" in result
        assert result["lifecycle_lab"] == {"failed": True}

    async def test_the_lab_pass_is_off_with_the_feature(
        self, test_session_factory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.workers import priority_tasks

        monkeypatch.setattr(priority_tasks, "SessionFactory", test_session_factory)
        monkeypatch.setattr(settings, "FEATURE_LIFECYCLE_LAB_ENABLED", False)
        monkeypatch.setattr(settings, "FEATURE_PRIORITY_ENRICHMENT_ENABLED", False)
        result = await priority_tasks._refresh()
        assert "lifecycle_lab" not in result
