"""Meme Lifecycle Lab orchestration: the properties the API and the beat rely on.

Each test pins a promise the Lab makes to its reader rather than a mechanism:
an off switch reads as "disabled", not as an empty lab; a source nobody is
allowed to query reads as DISABLED, not as zero mentions; an hour nobody
observed is a gap in the chart, not a flat line; a link is dated by the
server; a forward replay over the same data says the same thing twice; and an
experiment's split is fixed the moment it is registered.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.lifecycle_lab.adapters import DexScreenerAdapter
from app.lifecycle_lab.domain import (
    AliasKind,
    CollectionRun,
    DataClass,
    EventType,
    MemeEvent,
    Metric,
    Observation,
    ResearchMode,
    Source,
    SourceStatus,
    TokenInfo,
    ValueKind,
)
from app.lifecycle_lab.repository import LifecycleLabRepository
from app.lifecycle_lab.service import (
    EXPERIMENT_ARMS,
    ExperimentSpecConflictError,
    LifecycleLabService,
    experiment_key,
)
from app.models.market import TokenMarketSnapshot, TradingStatus
from app.models.token import DiscoveredToken

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def mint() -> str:
    return "".join(random.choice(B58) for _ in range(44))


@pytest.fixture
def svc(db_session: AsyncSession) -> LifecycleLabService:
    return LifecycleLabService(db_session)


@pytest.fixture
def lab_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "FEATURE_LIFECYCLE_LAB_ENABLED", True)
    monkeypatch.setattr(settings, "MLL_REDDIT_ENABLED", False)
    monkeypatch.setattr(settings, "MLL_X_ENABLED", False)


async def make_meme(svc: LifecycleLabService, *, at: datetime, aliases=()) -> str:
    slug = f"mll-{uuid.uuid4().hex[:10]}"
    await svc.create_meme(slug=slug, display_name="Frog CEO", now=at, aliases=aliases)
    return slug


async def add_token(
    session: AsyncSession, mint_address: str, *, at: datetime
) -> DiscoveredToken:
    token = DiscoveredToken(
        mint_address=mint_address,
        name="Frog CEO",
        symbol="FROGCEO",
        signature=f"sig-{mint_address}",
        slot=1,
        block_time=at,
        discovered_at=at,
    )
    session.add(token)
    await session.flush()
    return token


async def add_snapshots(
    session: AsyncSession,
    token: DiscoveredToken,
    start: datetime,
    end: datetime,
    *,
    step: timedelta = timedelta(minutes=5),
    price: str = "0.01",
) -> None:
    t = start
    while t < end:
        session.add(
            TokenMarketSnapshot(
                token_id=token.id,
                mint_address=token.mint_address,
                captured_at=t,
                price_usd=Decimal(price),
                volume_1h=Decimal("1000"),
                market_cap=Decimal("50000"),
                trading_status=TradingStatus.TRADING,
                provider="test",
            )
        )
        t += step
    await session.flush()


async def add_gdelt(
    repo: LifecycleLabRepository,
    meme_id: str,
    start: datetime,
    end: datetime,
    *,
    value: int = 3,
) -> None:
    """Contiguous 15-minute GDELT buckets, each retrieved a minute after it
    closed, plus the AVAILABLE run that collected it."""
    rows = []
    t = start
    while t < end:
        close = t + timedelta(minutes=15)
        rows.append(
            Observation(
                source=Source.GDELT,
                metric=Metric.MENTIONS,
                value_kind=ValueKind.WINDOW_COUNT,
                data_class=DataClass.FORWARD,
                source_timestamp=t,
                observed_at=close,
                retrieved_at=close + timedelta(minutes=1),
                raw_value=Decimal(value),
                meme_id=meme_id,
                window_start=t,
                window_end=close,
                query="frog ceo",
            )
        )
        await repo.record_run(
            CollectionRun(
                id=str(uuid.uuid4()),
                source=Source.GDELT,
                status=SourceStatus.AVAILABLE,
                started_at=close,
                finished_at=close + timedelta(minutes=1),
                data_class=DataClass.FORWARD,
            )
        )
        t = close
    await repo.insert_observations(rows)


async def seeded_meme(svc: LifecycleLabService, session: AsyncSession) -> tuple[str, str, str]:
    """A meme tracked from NOW-8h, linked at NOW-7h, with GDELT and market
    readings throughout."""
    slug = await make_meme(svc, at=NOW - timedelta(hours=8))
    meme = await svc.get_meme(slug)
    assert meme is not None
    m = mint()
    token = await add_token(session, m, at=NOW - timedelta(days=4))
    await svc.add_manual_link(slug, m, Decimal("0.9"), "tester", NOW - timedelta(hours=7))
    await add_snapshots(session, token, NOW - timedelta(hours=8), NOW)
    await add_gdelt(svc.repo, meme.id, NOW - timedelta(hours=8), NOW)
    return slug, meme.id, m


# --------------------------------------------------------------------------


async def test_overview_with_the_flag_off_is_truthfully_disabled(
    svc: LifecycleLabService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Off is a state. Every source says DISABLED with the reason, and the
    portfolio says why it has no numbers — nothing reads as an empty lab."""
    monkeypatch.setattr(settings, "FEATURE_LIFECYCLE_LAB_ENABLED", False)
    monkeypatch.setattr(settings, "MLL_FORWARD_START", "")
    out = await svc.overview(NOW)
    assert out["lab_enabled"] is False
    assert out["real_trading"] is False
    assert out["mode"] == "authoritative"
    assert out["forward_start"] is None and out["forward_days"] is None
    assert out["experiment"] is None
    assert {s["status"] for s in out["sources"]} == {"disabled"}
    assert {s["reason"] for s in out["sources"]} == {"lab_disabled"}
    assert all(s["observations_24h"] is None for s in out["sources"])
    p = out["portfolio"]
    assert p["unavailable_reason"] == "forward_start_not_set"
    assert p["equity"] is None and p["roi"] is None
    assert p["starting_capital"] == "1000"
    assert p["sample_label"] == "insufficient (<25)"


async def test_health_reports_reddit_and_x_disabled_not_zero(
    svc: LifecycleLabService, db_session: AsyncSession, lab_on: None
) -> None:
    """Reddit and X have no authorised access: DISABLED with a reason and a
    null count — a zero would claim we looked and found nothing. A source that
    is on but never ran is `never_collected`, also with a null count."""
    out = await svc.health(NOW)
    by = {s["source"]: s for s in out["sources"]}
    for name in ("reddit", "x"):
        assert by[name]["status"] == "disabled"
        assert by[name]["reason"] == "disabled_by_config"
        assert by[name]["observations_24h"] is None
    assert by["gdelt"]["status"] == "never_collected"
    assert by["gdelt"]["observations_24h"] is None
    assert by["geckoterminal"]["data_class"] == "backfill"

    slug = await make_meme(svc, at=NOW - timedelta(hours=3))
    meme = await svc.get_meme(slug)
    assert meme is not None
    await add_gdelt(svc.repo, meme.id, NOW - timedelta(hours=2), NOW - timedelta(minutes=30))
    by = {s["source"]: s for s in (await svc.health(NOW))["sources"]}
    assert by["gdelt"]["status"] == "available"
    assert by["gdelt"]["observations_24h"] == 6
    # Three hours later the last run is outside the freshness budget.
    by = {s["source"]: s for s in (await svc.health(NOW + timedelta(hours=3)))["sources"]}
    assert by["gdelt"]["status"] == "stale"


async def test_meme_detail_series_is_null_where_nothing_was_observed(
    svc: LifecycleLabService, db_session: AsyncSession
) -> None:
    """An hour nobody observed is null, not 0, in every series."""
    slug = await make_meme(svc, at=NOW - timedelta(hours=6))
    meme = await svc.get_meme(slug)
    assert meme is not None
    m = mint()
    token = await add_token(db_session, m, at=NOW - timedelta(days=2))
    await svc.add_manual_link(slug, m, Decimal("1"), "tester", NOW - timedelta(hours=6))
    await add_gdelt(svc.repo, meme.id, NOW - timedelta(hours=3), NOW - timedelta(hours=1))
    await add_snapshots(db_session, token, NOW - timedelta(hours=2), NOW - timedelta(hours=1))

    detail = await svc.meme_detail(slug, NOW)
    assert detail is not None
    series = detail["series"]
    hours = [p["t"] for p in series["attention"]]
    assert hours[0] == NOW - timedelta(hours=6) and hours[-1] == NOW - timedelta(hours=1)
    assert hours == [p["t"] for p in series["price"]] == [p["t"] for p in series["volume"]]

    attention = {p["t"]: p["value"] for p in series["attention"]}
    assert attention[NOW - timedelta(hours=3)] == "12"  # 4 buckets x 3
    assert attention[NOW - timedelta(hours=2)] == "12"
    assert attention[NOW - timedelta(hours=1)] is None  # not observed
    assert attention[NOW - timedelta(hours=5)] is None  # before any source
    assert "0" not in attention.values()

    price = {p["t"]: p["value"] for p in series["price"]}
    assert price[NOW - timedelta(hours=2)] == "0.01"
    assert price[NOW - timedelta(hours=3)] is None
    assert price[NOW - timedelta(hours=1)] is None
    assert set(series["per_source"]) == {"gdelt"}
    assert series["backfill_before"] is None
    assert detail["data_label"] == "authoritative" and detail["contains_backfill"] is False
    assert {m_["kind"] for m_ in detail["markers"]} >= {"token_linked", "token_launch"}

    assert await svc.meme_detail("no-such-meme", NOW) is None


async def test_manual_link_is_dated_by_the_server_and_never_moves(
    svc: LifecycleLabService,
) -> None:
    """`linked_at` is the `now` the server passes in. Re-linking later keeps
    the original moment — moving it would hide what was already known."""
    slug = await make_meme(svc, at=NOW - timedelta(days=1))
    m = mint()
    first = await svc.add_manual_link(slug, m, Decimal("0.75"), "admin-1", NOW)
    assert first["created"] is True
    assert first["linked_at"] == NOW
    assert first["method"] == "manual"
    again = await svc.add_manual_link(
        slug, m, Decimal("1"), "admin-2", NOW + timedelta(hours=5)
    )
    assert again["created"] is False
    assert again["linked_at"] == NOW
    assert again["confidence"] == "0.75"


async def test_forward_replay_persists_a_run_and_is_deterministic(
    svc: LifecycleLabService, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One forward run row per arm, re-saved by each replay. Replaying the
    same data at the same instant changes nothing: same row, same
    fingerprint, same trades, same equity curve."""
    monkeypatch.setattr(settings, "MLL_FORWARD_START", (NOW - timedelta(hours=6)).isoformat())
    await seeded_meme(svc, db_session)

    first = await svc.run_forward_replay(NOW)
    assert set(first["runs"]) == {
        "baseline_attention_acceleration_market_confirmation",
        "control_b_market_only",
        "control_c_attention_only",
        "control_d_combined",
    }
    baseline_id = first["runs"]["baseline_attention_acceleration_market_confirmation"][
        "run_id"
    ]
    run = await svc.repo.get_run(baseline_id)
    assert run is not None
    assert run["status"] == "completed"
    assert run["mode"] == "authoritative"
    assert run["window_start"] == NOW - timedelta(hours=6)
    assert run["window_end"] == NOW
    assert run["summary"]["recompute"] == "full"
    assert run["summary"]["duration_seconds"] >= 0
    assert run["input_fingerprint"]
    snaps = await svc.repo.snapshots_for_run(baseline_id)
    trades = await svc.repo.trades_for_run(baseline_id)
    assert snaps, "an equity curve is always recorded"

    second = await svc.run_forward_replay(NOW)
    assert (
        second["runs"]["baseline_attention_acceleration_market_confirmation"]["run_id"]
        == baseline_id
    )
    again = await svc.repo.get_run(baseline_id)
    assert again is not None
    assert again["input_fingerprint"] == run["input_fingerprint"]
    assert again["trades_count"] == run["trades_count"]
    assert again["summary"]["metrics"] == run["summary"]["metrics"]

    def strip(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{k: v for k, v in r.items() if k not in ("updated_at",)} for r in rows]

    assert strip(await svc.repo.snapshots_for_run(baseline_id)) == strip(snaps)
    assert strip(await svc.repo.trades_for_run(baseline_id)) == strip(trades)

    overview = await svc.overview(NOW)
    assert overview["portfolio"]["run_id"] == baseline_id
    assert overview["portfolio"]["unavailable_reason"] is None
    assert overview["portfolio"]["equity"] is not None
    assert overview["forward_days"] == 0.25


async def test_replay_before_forward_start_does_nothing(
    svc: LifecycleLabService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "MLL_FORWARD_START", "")
    assert await svc.run_forward_replay(NOW) == {"skipped": "forward_start_not_set"}
    monkeypatch.setattr(settings, "MLL_FORWARD_START", (NOW + timedelta(days=1)).isoformat())
    assert await svc.run_forward_replay(NOW) == {"skipped": "forward_not_started"}


async def test_experiment_split_is_fixed_at_creation_and_a_changed_spec_is_refused(
    svc: LifecycleLabService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 70/15/15 split is computed once, at registration, over
    [forward_start, forward_start + horizon). Registering again later neither
    moves it nor flips it meaningful early; re-registering under a different
    horizon is a different spec and is refused."""
    fs = datetime(2026, 9, 1, tzinfo=UTC)
    monkeypatch.setattr(settings, "MLL_FORWARD_START", "2026-09-01")
    monkeypatch.setattr(settings, "MLL_EXPERIMENT_HORIZON_DAYS", 90)

    ids = await svc.ensure_baseline_experiment(NOW)
    assert set(ids) == set(EXPERIMENT_ARMS)
    rows = {r["experiment_key"]: r for r in (await svc.experiments())["items"]}
    base = rows[experiment_key(fs, EXPERIMENT_ARMS[0])]
    assert base["train"][0] == fs
    assert base["test"][1] == fs + timedelta(days=90) == base["data_cutoff"]
    assert base["train"][1] == base["validation"][0]
    assert base["split_meaningful"] is False
    assert "data cutoff" in base["split_note"]
    control_a = [r for r in rows.values() if r["arm"] == "control_a_existing"]
    assert control_a[0]["status"] == "not_wired"

    # Later, same spec: same ids, same boundaries, still not meaningful.
    later = await svc.ensure_baseline_experiment(NOW + timedelta(days=30))
    assert later == ids
    again = {r["experiment_key"]: r for r in (await svc.experiments())["items"]}
    assert again[base["experiment_key"]]["train"] == base["train"]
    assert again[base["experiment_key"]]["spec_hash"] == base["spec_hash"]
    assert again[base["experiment_key"]]["split_meaningful"] is False

    # Past the cutoff with no forward trades: still not meaningful, and says why.
    await svc.ensure_baseline_experiment(fs + timedelta(days=91))
    after = {r["experiment_key"]: r for r in (await svc.experiments())["items"]}
    assert after[base["experiment_key"]]["split_meaningful"] is False
    assert after[base["experiment_key"]]["split_note"] == "insufficient trades"

    monkeypatch.setattr(settings, "MLL_EXPERIMENT_HORIZON_DAYS", 60)
    with pytest.raises(ExperimentSpecConflictError):
        await svc.ensure_baseline_experiment(NOW)
    final = {r["experiment_key"]: r for r in (await svc.experiments())["items"]}
    assert final[base["experiment_key"]]["test"] == base["test"]


async def test_forward_detection_is_idempotent(
    svc: LifecycleLabService, db_session: AsyncSession
) -> None:
    """Detection runs at the replay's grid instant, so a second pass in the
    same five minutes re-detects the same rows and writes nothing."""
    await seeded_meme(svc, db_session)
    first = await svc.detect_and_store_events(NOW + timedelta(minutes=2))
    assert first["at"] == NOW.isoformat()
    second = await svc.detect_and_store_events(NOW + timedelta(minutes=4))
    assert second["new"] == 0
    assert second["detected"] == first["detected"]


async def test_timeliness_settles_once_with_reasons_not_zeros(
    svc: LifecycleLabService, db_session: AsyncSession
) -> None:
    """Outcomes are measured after the horizons settle. A horizon with no
    reading near it is NULL with its reason, never a 0% return."""
    slug = await make_meme(svc, at=NOW - timedelta(days=2))
    meme = await svc.get_meme(slug)
    assert meme is not None
    m = mint()
    token = await add_token(db_session, m, at=NOW - timedelta(days=3))
    await add_snapshots(db_session, token, NOW - timedelta(hours=1), NOW + timedelta(hours=2))
    event = MemeEvent(
        meme_id=meme.id,
        event_type=EventType.ATTENTION_INCREASE,
        detected_at=NOW,
        mode=ResearchMode.AUTHORITATIVE,
        detector_version="mll-events-v1",
        mint_address=m,
    )
    await svc.repo.save_events([event])

    assert (await svc.fill_timeliness(NOW + timedelta(hours=3)))["recorded"] == 0
    assert (await svc.fill_timeliness(NOW + timedelta(hours=27)))["recorded"] == 1
    row = (await svc.repo.events_for_meme(meme.id))[0]
    assert row["outcomes_complete_at"] == NOW + timedelta(hours=27)
    assert row["return_1h"] == Decimal("0")  # flat price: a measured zero
    assert row["return_24h"] is None
    assert row["outcome_reasons"]["return_24h"] == "no_point_near_horizon"
    out = svc._event_out(row)
    assert out["returns"]["24h"] == {
        "value": None,
        "unavailable_reason": "no_point_near_horizon",
    }
    assert (await svc.fill_timeliness(NOW + timedelta(hours=28)))["recorded"] == 0


class _FakeDex:
    def __init__(self, candidates: list[tuple[TokenInfo, dict[str, Any]]]) -> None:
        self.candidates = candidates
        self.terms: list[str] = []

    async def search_candidates(self, alias: str, *, now: datetime) -> list[Any]:
        self.terms.append(alias)
        return self.candidates


async def test_autolink_links_only_strong_evidence_at_server_time(
    svc: LifecycleLabService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """At the default 0.8 floor a website the token's own profile points at
    links; a bare ticker collision does not — many tokens share a ticker."""
    monkeypatch.setattr(settings, "MLL_AUTOLINK_MIN_CONFIDENCE", "0.8")
    slug = await make_meme(
        svc,
        at=NOW - timedelta(days=1),
        aliases=[("FROGCEO", AliasKind.SYMBOL), ("frogceo.xyz", AliasKind.DOMAIN)],
    )
    site, ticker = mint(), mint()
    dex = _FakeDex(
        [
            (
                TokenInfo(site, "Something", "XYZ", None, NOW),
                {"websites": ["https://www.frogceo.xyz/"], "socials": []},
            ),
            (
                TokenInfo(ticker, "Other", "FROGCEO", None, NOW),
                {"websites": [], "socials": []},
            ),
        ]
    )
    out = await svc.autolink(NOW, cast(DexScreenerAdapter, dex))
    assert out["links_created"] == 1
    meme = await svc.get_meme(slug)
    assert meme is not None
    links = await svc.repo.links_for([meme.id])
    assert [(k.mint_address, k.method.value, k.linked_at) for k in links] == [
        (site, "website_match", NOW)
    ]
    # A meme with no domain/handle alias cannot reach 0.8, so is not searched.
    await make_meme(svc, at=NOW - timedelta(days=1), aliases=[("PEPE", AliasKind.SYMBOL)])
    dex.terms.clear()
    await svc.autolink(NOW + timedelta(hours=1), cast(DexScreenerAdapter, dex))
    assert "PEPE" not in dex.terms
