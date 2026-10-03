"""The validation-phase endpoints: data quality, per-meme audit, research status.

What is pinned is what a reader of the page would be misled by if it broke:
forward and backfill counts blurred together, a source the operator switched
off scored as a failure, a meme with no data hidden instead of listed, a token
without market history reported as healthy, a research state that claims more
than the evidence supports — and a JSON shape that drifts from the contract
the frontend codes against.

(A refused request rolls the test's outer transaction back — see
``tests/conftest.py`` — so each refusal is its own test.)
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.lifecycle_lab import api as lab_api
from app.lifecycle_lab.domain import (
    AliasKind,
    Arm,
    CollectionRun,
    DataClass,
    EventType,
    LinkMethod,
    MemeEvent,
    MemeTokenLink,
    Metric,
    Observation,
    ResearchMode,
    Source,
    SourceStatus,
    ValueKind,
)
from app.lifecycle_lab.repository import LifecycleLabRepository
from app.lifecycle_lab.service import FORWARD_SEGMENT, LifecycleLabService
from app.models import User
from app.models.market import TokenMarketCandle, TokenMarketSnapshot, TradingStatus
from app.models.social import PumpfunSocialSnapshot
from app.models.token import DiscoveredToken
from app.models.user import UserRole

pytestmark = pytest.mark.integration

API = f"{settings.API_V1_PREFIX}/lifecycle-lab"
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
MIDNIGHT = datetime(2026, 9, 10, tzinfo=UTC)


def mint() -> str:
    return "".join(random.choice(B58) for _ in range(44))


@pytest.fixture(autouse=True)
def lab(monkeypatch: pytest.MonkeyPatch) -> None:
    """A lab that is on, with a fixed clock for every endpoint under test."""
    monkeypatch.setattr(settings, "FEATURE_LIFECYCLE_LAB_ENABLED", True)
    monkeypatch.setattr(settings, "MLL_REDDIT_ENABLED", False)
    monkeypatch.setattr(settings, "MLL_X_ENABLED", False)
    monkeypatch.setattr(settings, "MLL_FORWARD_START", "")
    monkeypatch.setattr(lab_api, "_now", lambda: NOW)


@pytest.fixture
async def admin_headers(
    auth_headers: dict[str, str], user: User, db_session: AsyncSession
) -> dict[str, str]:
    user.role = UserRole.ADMIN
    await db_session.flush()
    return auth_headers


@pytest.fixture
def svc(db_session: AsyncSession) -> LifecycleLabService:
    return LifecycleLabService(db_session)


async def make_meme(
    svc: LifecycleLabService, *, at: datetime = NOW - timedelta(days=10)
) -> Any:
    slug = f"mll-{uuid.uuid4().hex[:10]}"
    await svc.create_meme(
        slug=slug,
        display_name=f"Meme {slug[-4:]}",
        now=at,
        aliases=[("$FROG", AliasKind.SYMBOL)],
    )
    meme = await svc.get_meme(slug)
    assert meme is not None
    return meme


async def add_token(session: AsyncSession, mint_address: str) -> DiscoveredToken:
    token = DiscoveredToken(
        mint_address=mint_address,
        name="Frog",
        symbol="FROG",
        signature=f"sig-{mint_address}",
        slot=1,
        block_time=NOW - timedelta(days=5),
        discovered_at=NOW - timedelta(days=5),
    )
    session.add(token)
    await session.flush()
    return token


async def snapshot(
    session: AsyncSession, token: DiscoveredToken, at: datetime, **missing: bool
) -> None:
    """A snapshot with every market field present, minus those named."""
    fields: dict[str, Decimal | None] = {
        "price_usd": Decimal("0.01"),
        "market_cap": Decimal("50000"),
        "liquidity_usd": Decimal("20000"),
        "volume_1h": Decimal("1000"),
    }
    for name in missing:
        fields[name] = None
    session.add(
        TokenMarketSnapshot(
            token_id=token.id,
            mint_address=token.mint_address,
            captured_at=at,
            trading_status=TradingStatus.TRADING,
            provider="test",
            **fields,
        )
    )
    await session.flush()


def observation(
    meme_id: str,
    *,
    retrieved_at: datetime,
    data_class: DataClass = DataClass.FORWARD,
    source: Source = Source.GDELT,
) -> Observation:
    observed = retrieved_at - timedelta(minutes=1)
    return Observation(
        source=source,
        metric=Metric.MENTIONS,
        value_kind=ValueKind.WINDOW_COUNT,
        data_class=data_class,
        source_timestamp=observed - timedelta(minutes=14),
        observed_at=observed,
        retrieved_at=retrieved_at,
        raw_value=Decimal(3),
        meme_id=meme_id,
        window_start=observed - timedelta(minutes=14),
        window_end=observed,
        query="frog",
    )


async def run_row(
    repo: LifecycleLabRepository,
    source: Source,
    status: SourceStatus,
    *,
    finished_at: datetime = NOW - timedelta(hours=1),
    reason: str | None = None,
) -> None:
    await repo.record_run(
        CollectionRun(
            id=str(uuid.uuid4()),
            source=source,
            status=status,
            started_at=finished_at - timedelta(seconds=5),
            finished_at=finished_at,
            data_class=DataClass.FORWARD,
            reason=reason,
        )
    )


# --------------------------------------------------------------------------
# GET /quality
# --------------------------------------------------------------------------


async def test_forward_and_backfill_observations_are_counted_separately(
    client: AsyncClient, svc: LifecycleLabService, db_session: AsyncSession
) -> None:
    """Backfill can never reach the verdict, so it must never inflate the
    forward figure. 'Today' is since UTC midnight; 'week' is the last 7 days;
    both by retrieved_at. pump.fun replies are read in place and count as forward."""
    meme = await make_meme(svc)
    m = mint()
    await add_token(db_session, m)
    await svc.repo.add_link(
        MemeTokenLink(
            meme_id=meme.id,
            mint_address=m,
            method=LinkMethod.MANUAL,
            confidence=Decimal("0.9"),
            linked_at=NOW - timedelta(days=3),
        ),
        evidence={"actor": "t"},
        linked_by="manual:t",
    )
    rows = [
        # today (>= 00:00 UTC): 3 forward, 2 backfill
        *[
            observation(meme.id, retrieved_at=MIDNIGHT + timedelta(hours=1, minutes=i))
            for i in range(3)
        ],
        *[
            observation(
                meme.id,
                retrieved_at=MIDNIGHT + timedelta(hours=2, minutes=i),
                data_class=DataClass.BACKFILL,
            )
            for i in range(2)
        ],
        # earlier this week: 4 forward, 5 backfill
        *[
            observation(meme.id, retrieved_at=NOW - timedelta(days=2, minutes=i))
            for i in range(4)
        ],
        *[
            observation(
                meme.id,
                retrieved_at=NOW - timedelta(days=3, minutes=i),
                data_class=DataClass.BACKFILL,
            )
            for i in range(5)
        ],
        # older than a week: counted nowhere
        observation(meme.id, retrieved_at=NOW - timedelta(days=9)),
        observation(
            meme.id,
            retrieved_at=NOW - timedelta(days=9, minutes=1),
            data_class=DataClass.BACKFILL,
        ),
        # after `now`: the report does not look ahead
        observation(meme.id, retrieved_at=NOW + timedelta(minutes=5)),
    ]
    await svc.repo.insert_observations(rows)
    for i in range(2):  # pump.fun replies today, one yesterday
        db_session.add(
            PumpfunSocialSnapshot(
                mint_address=m,
                observed_at=MIDNIGHT + timedelta(hours=3, minutes=i),
                reply_count=10 + i,
                source_sort="last_reply",
            )
        )
    db_session.add(
        PumpfunSocialSnapshot(
            mint_address=m,
            observed_at=NOW - timedelta(days=1),
            reply_count=5,
            source_sort="last_reply",
        )
    )
    await db_session.flush()

    body = (await client.get(f"{API}/quality")).json()
    assert body["observations_today"] == {"forward": 3 + 2, "backfill": 2}
    assert body["observations_week"] == {"forward": 3 + 4 + 3, "backfill": 2 + 5}
    assert body["tracked_memes"] == 1 and body["tracked_tokens"] == 1
    assert body["newest_forward_observation_at"].startswith("2026-09-10T03:01")
    assert body["oldest_forward_observation_at"].startswith("2026-09-01")


async def test_disabled_sources_are_not_failures(
    client: AsyncClient, svc: LifecycleLabService
) -> None:
    """DISABLED is a configuration state. It leaves both the numerator and the
    denominator of the success rate, and is not counted as a failure."""
    repo = svc.repo
    for _ in range(3):
        await run_row(repo, Source.REDDIT, SourceStatus.DISABLED, reason="disabled_by_config")
    for _ in range(3):
        await run_row(repo, Source.GDELT, SourceStatus.AVAILABLE)
    await run_row(repo, Source.WIKIPEDIA, SourceStatus.UNAVAILABLE, reason="http_429")
    # Outside the 24h window: not counted.
    await run_row(
        repo,
        Source.GDELT,
        SourceStatus.ERROR,
        finished_at=NOW - timedelta(hours=30),
        reason="boom",
    )

    body = (await client.get(f"{API}/quality")).json()
    collection = body["collection"]
    assert collection["runs_24h"] == 7
    assert collection["failures_24h"] == 1
    # 3 available / (7 runs - 3 disabled)
    assert collection["success_rate_24h"] == "0.750"
    by = {s["source"]: s for s in collection["by_source"]}
    assert by["reddit"]["disabled"] == 3 and by["reddit"]["runs_24h"] == 3
    assert by["reddit"]["success_rate_24h"] is None  # nothing could have succeeded
    assert by["gdelt"]["success_rate_24h"] == "1.000"
    assert by["gdelt"]["error"] == 0
    assert (
        by["wikipedia"]["unavailable"] == 1 and by["wikipedia"]["success_rate_24h"] == "0.000"
    )
    assert by["wikipedia"]["last_reason"] == "http_429"
    assert by["gdelt"]["last_success_at"] is not None
    assert by["x"]["runs_24h"] == 0 and by["x"]["last_status"] is None
    # Reddit and X are switched off; they are listed as unable to deliver.
    assert {"reddit", "x"} <= set(body["unavailable_sources"])
    assert "gdelt" not in body["unavailable_sources"]


async def test_memes_without_observations_are_listed(
    client: AsyncClient, svc: LifecycleLabService, db_session: AsyncSession
) -> None:
    """An empty meme is a finding, not an omission."""
    seen = await make_meme(svc)
    silent = await make_meme(svc)
    replies_only = await make_meme(svc)
    m = mint()
    await svc.repo.insert_observations(
        [observation(seen.id, retrieved_at=NOW - timedelta(hours=1))]
    )
    await svc.repo.add_link(
        MemeTokenLink(
            meme_id=replies_only.id,
            mint_address=m,
            method=LinkMethod.MANUAL,
            confidence=Decimal("0.9"),
            linked_at=NOW - timedelta(days=1),
        ),
        evidence=None,
        linked_by="manual:t",
    )
    db_session.add(
        PumpfunSocialSnapshot(
            mint_address=m,
            observed_at=NOW - timedelta(hours=2),
            reply_count=3,
            source_sort="last_reply",
        )
    )
    await db_session.flush()

    body = (await client.get(f"{API}/quality")).json()
    assert [x["slug"] for x in body["memes_without_observations"]] == [silent.slug]
    assert set(body["memes_without_observations"][0]) == {"slug", "display_name"}


async def test_tokens_without_history_or_with_incomplete_data_are_listed(
    client: AsyncClient, svc: LifecycleLabService, db_session: AsyncSession
) -> None:
    """A token nobody has a price for is not 'fine'; and completeness is judged
    on the LATEST forward snapshot, so an old gap that was filled is not a gap."""
    meme = await make_meme(svc)
    complete, gappy, empty = mint(), mint(), mint()
    for m in (complete, gappy, empty):
        await svc.repo.add_link(
            MemeTokenLink(
                meme_id=meme.id,
                mint_address=m,
                method=LinkMethod.MANUAL,
                confidence=Decimal("0.9"),
                linked_at=NOW - timedelta(days=2),
            ),
            evidence=None,
            linked_by="manual:t",
        )
    t_complete = await add_token(db_session, complete)
    t_gappy = await add_token(db_session, gappy)
    await add_token(db_session, empty)
    # Old gap, later filled: complete.
    await snapshot(db_session, t_complete, NOW - timedelta(hours=3), liquidity_usd=True)
    await snapshot(db_session, t_complete, NOW - timedelta(hours=1))
    # Fine, then a gap: incomplete.
    await snapshot(db_session, t_gappy, NOW - timedelta(hours=3))
    await snapshot(
        db_session, t_gappy, NOW - timedelta(hours=1), liquidity_usd=True, volume_1h=True
    )

    body = (await client.get(f"{API}/quality")).json()
    assert body["tokens_without_market_history"] == [{"mint": empty, "meme_slug": meme.slug}]
    assert body["tokens_with_incomplete_market_data"] == [
        {"mint": gappy, "meme_slug": meme.slug, "missing": ["liquidity_usd", "volume_1h"]}
    ]


# --------------------------------------------------------------------------
# GET /memes/{slug}/quality
# --------------------------------------------------------------------------


async def test_meme_audit_shows_link_provenance_and_per_source_counts(
    client: AsyncClient, svc: LifecycleLabService, db_session: AsyncSession
) -> None:
    meme = await make_meme(svc)
    m = mint()
    token = await add_token(db_session, m)
    linked_at = NOW - timedelta(days=2)
    await svc.add_manual_link(meme.slug, m, Decimal("0.9"), "kshetty", linked_at)
    # A link made after `now` is not a fact yet.
    await svc.add_manual_link(
        meme.slug, mint(), Decimal("0.5"), "future", NOW + timedelta(hours=1)
    )
    await svc.repo.insert_observations(
        [
            observation(meme.id, retrieved_at=NOW - timedelta(hours=2)),
            observation(meme.id, retrieved_at=NOW - timedelta(hours=1)),
            observation(
                meme.id, retrieved_at=NOW - timedelta(days=1), data_class=DataClass.BACKFILL
            ),
        ]
    )
    db_session.add(
        PumpfunSocialSnapshot(
            mint_address=m,
            observed_at=NOW - timedelta(hours=1),
            reply_count=7,
            source_sort="last_reply",
        )
    )
    db_session.add(
        TokenMarketCandle(
            mint_address=m,
            resolution_s=3600,
            source="geckoterminal",
            bucket=NOW - timedelta(days=4),
            close_price=Decimal("0.01"),
            data_class="backfill",
            retrieved_at=NOW - timedelta(hours=5),
        )
    )
    await snapshot(db_session, token, NOW - timedelta(hours=2), liquidity_usd=True)
    await snapshot(db_session, token, NOW - timedelta(hours=1), liquidity_usd=True)
    await run_row(svc.repo, Source.GDELT, SourceStatus.AVAILABLE)

    response = await client.get(f"{API}/memes/{meme.slug}/quality")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["meme"]["slug"] == meme.slug
    assert [a["alias"] for a in body["aliases"]] == ["$FROG"]

    assert len(body["links"]) == 1
    link = body["links"][0]
    assert link["mint"] == m and link["method"] == "manual" and link["confidence"] == "0.9"
    assert link["linked_at"].startswith("2026-09-08T12:00")
    assert link["unlinked_at"] is None
    assert link["linked_by"] == "manual:kshetty"
    assert link["evidence"] == {"url": None, "note": None, "submitted_by": "kshetty"}

    by = {s["source"]: s for s in body["sources"]}
    assert set(by) == {s.value for s in Source}
    assert (by["gdelt"]["forward_count"], by["gdelt"]["backfill_count"]) == (2, 1)
    assert by["gdelt"]["observation_count"] == 3
    assert by["gdelt"]["status"] == "available"
    assert by["gdelt"]["first_observation_at"] < by["gdelt"]["latest_observation_at"]
    assert (
        by["pumpfun_replies"]["forward_count"],
        by["pumpfun_replies"]["backfill_count"],
    ) == (1, 0)
    assert (by["geckoterminal"]["forward_count"], by["geckoterminal"]["backfill_count"]) == (
        0,
        1,
    )
    assert by["wikipedia"]["observation_count"] == 0
    assert by["wikipedia"]["first_observation_at"] is None
    assert by["reddit"]["status"] == "disabled"

    (market,) = body["market"]
    assert market["mint"] == m
    assert market["observation_count"] == 3  # two forward snapshots + one backfill candle
    assert market["missing_fields"] == ["liquidity_usd"]


async def test_meme_audit_evaluates_the_engines_without_inventing_values(
    client: AsyncClient, svc: LifecycleLabService
) -> None:
    """No data: lifecycle 'unknown', attention Unavailable with reasons (never 0),
    divergence 'none'."""
    meme = await make_meme(svc)
    body = (await client.get(f"{API}/memes/{meme.slug}/quality")).json()
    assert body["links"] == [] and body["market"] == []
    assert body["lifecycle_state"] == "unknown"
    assert body["divergence_case"] == "none"
    for name in ("mentions_1h", "velocity", "acceleration", "baseline_multiple"):
        assert body["attention"][name]["value"] is None
        assert body["attention"][name]["unavailable_reason"]
    # Nothing observed and nothing recent: collected least often, and says why.
    assert body["collection_priority"] == {
        "level": "low",
        "interval_seconds": 6 * 3600,
        "reason": (
            "Lifecycle state is unknown and no reading arrived within the last 24 hours."
        ),
    }


async def test_meme_audit_for_an_unknown_slug_is_404(client: AsyncClient) -> None:
    assert (await client.get(f"{API}/memes/nope/quality")).status_code == 404


# --------------------------------------------------------------------------
# GET /research-status and overview.research_status
# --------------------------------------------------------------------------


async def test_research_status_not_started_when_forward_start_is_unset(
    client: AsyncClient,
) -> None:
    body = (await client.get(f"{API}/research-status")).json()
    assert body["state"] == "NOT_STARTED"
    assert body["verdict"] == "UNCERTAIN" and body["verdict_engine_available"] is False
    assert body["forward_start"] is None and body["forward_days"] is None
    assert len(body["requirements"]) == 8
    assert all(r["met"] is False and r["observed"] is None for r in body["requirements"])


async def test_research_status_not_started_when_the_lab_is_off(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "FEATURE_LIFECYCLE_LAB_ENABLED", False)
    monkeypatch.setattr(settings, "MLL_FORWARD_START", (NOW - timedelta(days=30)).isoformat())
    assert (await client.get(f"{API}/research-status")).json()["state"] == "NOT_STARTED"


async def test_research_status_collecting_early_then_insufficient_after_seven_days(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "MLL_FORWARD_START", (NOW - timedelta(days=2)).isoformat())
    early = (await client.get(f"{API}/research-status")).json()
    assert early["state"] == "COLLECTING"
    assert early["forward_days"] == 2.0
    monkeypatch.setattr(settings, "MLL_FORWARD_START", (NOW - timedelta(days=8)).isoformat())
    later = (await client.get(f"{API}/research-status")).json()
    assert later["state"] == "INSUFFICIENT_DATA"
    assert later["verdict"] == "UNCERTAIN"
    # Nothing measured yet means unmet with a reason, never met.
    assert not any(r["met"] for r in later["requirements"])
    assert all(r["reason"] for r in later["requirements"])


async def test_overview_carries_the_same_research_status(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "MLL_FORWARD_START", (NOW - timedelta(days=8)).isoformat())
    overview = (await client.get(f"{API}/overview")).json()
    assert overview["research_status"] == (await client.get(f"{API}/research-status")).json()


def trade_row(
    meme_id: str,
    entry_at: datetime,
    *,
    exit_at: datetime | None,
    status: str,
) -> dict[str, Any]:
    key = uuid.uuid4().hex
    return {
        "trade_key": key,
        "arm": Arm.BASELINE.value,
        "meme_id": meme_id,
        "mint_address": mint(),
        "entry_at": entry_at,
        "entry_price": Decimal("0.01"),
        "size_usd": Decimal("10"),
        "quantity": Decimal("1000"),
        "entry_fees_usd": Decimal("0.03"),
        "age_bucket": "unknown",
        "entry_reason": "conditions_met",
        "entry_features": {},
        "evidence_timeline": [],
        "cost_model": "flat",
        "exit_at": exit_at,
        "status": status,
    }


async def test_research_facts_come_from_the_database_and_never_look_past_now(
    client: AsyncClient,
    svc: LifecycleLabService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fs = NOW - timedelta(days=20)
    monkeypatch.setattr(settings, "MLL_FORWARD_START", fs.isoformat())
    m1 = await make_meme(svc, at=fs)
    m2 = await make_meme(svc, at=fs)
    ids = await svc.ensure_baseline_experiment(NOW)

    async def forward_run(arm: Arm, *, window_end: datetime = NOW) -> str:
        return await svc.repo.save_run(
            {
                "experiment_id": ids[arm],
                "mode": "authoritative",
                "segment": FORWARD_SEGMENT,
                "status": "completed",
                "started_at": NOW,
                "finished_at": NOW,
                "window_start": fs,
                "window_end": window_end,
                "config_spec": {},
            }
        )

    base = await forward_run(Arm.BASELINE)
    await forward_run(Arm.CONTROL_B_MARKET_ONLY)
    await forward_run(Arm.CONTROL_C_ATTENTION_ONLY)
    # D ran over a shorter window: not "the same window".
    await forward_run(Arm.CONTROL_D_COMBINED, window_end=NOW - timedelta(hours=6))

    day = timedelta(days=1)
    trades = [
        *[
            trade_row(
                m1.id,
                fs + day * (i + 1),
                exit_at=fs + day * (i + 1) + timedelta(hours=2),
                status="closed",
            )
            for i in range(3)
        ],
        *[
            trade_row(
                m2.id,
                fs + day * (i + 5),
                exit_at=fs + day * (i + 5) + timedelta(hours=2),
                status="closed",
            )
            for i in range(2)
        ],
        trade_row(m2.id, fs + day * 9, exit_at=None, status="open"),
        # Closed only after `now`: not closed yet as far as this report knows.
        trade_row(
            m1.id, NOW - timedelta(hours=1), exit_at=NOW + timedelta(hours=1), status="closed"
        ),
    ]
    await svc.repo.save_trades(base, trades)

    def event(meme_id: str, kind: EventType, at: datetime, **over: Any) -> MemeEvent:
        args: dict[str, Any] = {
            "meme_id": meme_id,
            "event_type": kind,
            "detected_at": at,
            "mode": ResearchMode.AUTHORITATIVE,
            "detector_version": "t",
        }
        args.update(over)
        return MemeEvent(**args)

    t = fs + day * 2
    await svc.repo.save_events(
        [
            event(m1.id, EventType.NEW_ATTENTION_WAVE, t),
            event(m1.id, EventType.MEME_REVIVAL, t + timedelta(hours=2)),  # same episode
            event(m1.id, EventType.SECOND_WAVE, t + day * 3),
            event(m2.id, EventType.MEME_REVIVAL, t),  # stands alone
            # None of these count:
            event(m2.id, EventType.NEW_ATTENTION_WAVE, t + day, contains_backfill=True),
            event(m2.id, EventType.THIRD_WAVE, t + day * 4, mode=ResearchMode.EXPLORATORY),
            event(m2.id, EventType.NEW_ATTENTION_WAVE, fs - day),
            event(m2.id, EventType.NEW_ATTENTION_WAVE, NOW + timedelta(hours=1)),
            event(m2.id, EventType.ATTENTION_INCREASE, t + day * 5),
        ]
    )

    body = (await client.get(f"{API}/research-status")).json()
    by = {r["key"]: r for r in body["requirements"]}
    assert body["experiment_key"].endswith("-baseline")
    assert by["independent_events"]["observed"] == "3"  # wave, second wave, lone revival
    assert by["revival_events"]["observed"] == "3"  # 2 revivals + second wave
    assert by["baseline_trades"]["observed"] == "5"
    assert by["distinct_memes"]["observed"] == "2"
    assert by["concentration"]["observed"] == "60.0%"
    assert by["oos_trades"]["observed"] == "0"
    assert by["control_arms"]["observed"] == "B, C"
    assert "D" in by["control_arms"]["reason"]
    assert by["forward_period"]["observed"] == "20.0 days"
    assert body["state"] == "INSUFFICIENT_DATA"
    assert not any(r["met"] for r in body["requirements"])


async def test_baseline_trades_are_unmeasured_not_zero_before_a_run_exists(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "MLL_FORWARD_START", (NOW - timedelta(days=10)).isoformat())
    by = {
        r["key"]: r
        for r in (await client.get(f"{API}/research-status")).json()["requirements"]
    }
    for key in (
        "baseline_trades",
        "oos_trades",
        "distinct_memes",
        "concentration",
        "control_arms",
    ):
        assert by[key]["observed"] is None and by[key]["met"] is False and by[key]["reason"]
    # Events are measurable (there are none): zero, not unknown.
    assert by["independent_events"]["observed"] == "0"


# --------------------------------------------------------------------------
# Reserved slugs
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "slug", ["quality", "research-status", "health", "overview", "experiments", "runs"]
)
async def test_reserved_slugs_are_refused(
    client: AsyncClient, admin_headers: dict[str, str], slug: str
) -> None:
    """The frontend serves /lifecycle-lab/<page> statically; a meme with that
    slug would be shadowed by the page."""
    response = await client.post(
        f"{API}/memes", json={"slug": slug, "display_name": "x"}, headers=admin_headers
    )
    assert response.status_code == 422, response.text


async def test_an_ordinary_slug_is_still_accepted(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await client.post(
        f"{API}/memes",
        json={"slug": "quality-frog", "display_name": "Quality Frog"},
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text


# --------------------------------------------------------------------------
# API -> frontend contract
# --------------------------------------------------------------------------

SOURCE_STATS_KEYS = {
    "source", "label", "runs_24h", "available", "unavailable", "disabled", "error",
    "stale", "partial", "success_rate_24h", "last_success_at", "last_status", "last_reason",
}  # fmt: skip
RESEARCH_KEYS = {
    "state", "verdict", "verdict_engine_available", "forward_start", "forward_days",
    "experiment_key", "requirements", "explanation",
}  # fmt: skip
REQUIREMENT_KEYS = {"key", "label", "threshold", "observed", "met", "reason"}
MEASURED_KEYS = {"value", "unavailable_reason"}


async def test_json_keys_match_the_documented_contract(
    client: AsyncClient,
    svc: LifecycleLabService,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """docs/MEME_LIFECYCLE_LAB.md, "NEW API CONTRACT". The frontend codes
    against these names; a rename here breaks a page, so it breaks a test first.
    Data is seeded so every nested object appears at least once."""
    monkeypatch.setattr(settings, "MLL_FORWARD_START", (NOW - timedelta(days=8)).isoformat())
    meme = await make_meme(svc)
    silent = await make_meme(svc)
    m, bare = mint(), mint()
    for target, mm in ((meme, m), (silent, bare)):
        await svc.repo.add_link(
            MemeTokenLink(
                meme_id=target.id,
                mint_address=mm,
                method=LinkMethod.MANUAL,
                confidence=Decimal("0.9"),
                linked_at=NOW - timedelta(days=2),
            ),
            evidence={"actor": "t"},
            linked_by="manual:t",
        )
    token = await add_token(db_session, m)
    await add_token(db_session, bare)
    await snapshot(db_session, token, NOW - timedelta(hours=1), liquidity_usd=True)
    await svc.repo.insert_observations(
        [observation(meme.id, retrieved_at=NOW - timedelta(hours=1))]
    )
    await run_row(svc.repo, Source.GDELT, SourceStatus.AVAILABLE)

    quality = (await client.get(f"{API}/quality")).json()
    assert set(quality) == {
        "generated_at", "tracked_memes", "tracked_tokens", "observations_today",
        "observations_week", "collection", "unavailable_sources", "stale_sources",
        "oldest_forward_observation_at", "newest_forward_observation_at",
        "memes_without_observations", "tokens_without_market_history",
        "tokens_with_incomplete_market_data",
    }  # fmt: skip
    assert set(quality["observations_today"]) == {"forward", "backfill"}
    assert set(quality["observations_week"]) == {"forward", "backfill"}
    assert set(quality["collection"]) == {
        "runs_24h",
        "failures_24h",
        "success_rate_24h",
        "by_source",
    }
    assert quality["collection"]["by_source"]
    for entry in quality["collection"]["by_source"]:
        assert set(entry) == SOURCE_STATS_KEYS
    (no_obs,) = quality["memes_without_observations"]
    assert set(no_obs) == {"slug", "display_name"}
    (no_hist,) = quality["tokens_without_market_history"]
    assert set(no_hist) == {"mint", "meme_slug"}
    (incomplete,) = quality["tokens_with_incomplete_market_data"]
    assert set(incomplete) == {"mint", "meme_slug", "missing"}

    audit = (await client.get(f"{API}/memes/{meme.slug}/quality")).json()
    assert set(audit) == {
        "meme", "aliases", "links", "sources", "market", "lifecycle_state", "attention",
        "divergence_case", "collection_priority",
    }  # fmt: skip
    assert set(audit["meme"]) == {
        "slug", "display_name", "description", "tracking_started_at", "wikipedia_title",
        "gdelt_query",
    }  # fmt: skip
    assert set(audit["aliases"][0]) == {"alias", "kind", "added_at"}
    assert set(audit["links"][0]) == {
        "mint", "method", "confidence", "linked_at", "unlinked_at", "linked_by", "evidence",
    }  # fmt: skip
    assert set(audit["sources"][0]) == {
        "source", "label", "status", "reason", "first_observation_at", "latest_observation_at",
        "observation_count", "forward_count", "backfill_count",
    }  # fmt: skip
    assert set(audit["market"][0]) == {
        "mint", "first_observation_at", "latest_observation_at", "observation_count",
        "missing_fields",
    }  # fmt: skip
    assert set(audit["attention"]) == {
        "mentions_1h", "velocity", "acceleration", "baseline_multiple",
    }  # fmt: skip
    for measured in audit["attention"].values():
        assert set(measured) == MEASURED_KEYS
    assert set(audit["collection_priority"]) == {"level", "interval_seconds", "reason"}

    research = (await client.get(f"{API}/research-status")).json()
    assert set(research) == RESEARCH_KEYS
    assert research["requirements"]
    for req in research["requirements"]:
        assert set(req) == REQUIREMENT_KEYS
    overview = (await client.get(f"{API}/overview")).json()
    assert set(overview["research_status"]) == RESEARCH_KEYS
