"""Every candidate decided on, and what happened to it afterwards.

`FINDINGS.md` item 3: "Log rejected candidates, not just entered ones. Every
statistic above is conditioned on trades you took. You cannot evaluate a
filter against a population you never recorded."

These tests hold the properties that make the recorded population usable:
rejections are recorded with a reason, an entry supersedes an earlier
rejection of the same mint, a repeated rejection does not overwrite the first,
and the forward window is strictly after the decision.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.labs.rafiq import outcomes, registry
from app.labs.rafiq.models import RafiqCandidate, RafiqLabPosition
from app.labs.rafiq.service import RafiqLabService
from app.labs.rafiq.tests.test_full_cycle import seed_candidate
from app.models.market import TokenMarketSnapshot
from app.models.token import DiscoveredToken

pytestmark = pytest.mark.integration


async def _rows(session, mint: str | None = None) -> list[RafiqCandidate]:
    stmt = select(RafiqCandidate).order_by(RafiqCandidate.decided_at)
    if mint:
        stmt = stmt.where(RafiqCandidate.mint_address == mint)
    return list((await session.execute(stmt)).scalars())


async def test_an_entry_is_recorded_with_its_feature_snapshot(
    lab_session, monkeypatch
) -> None:
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    now = datetime.now(UTC)
    mint = await seed_candidate(lab_session, now, tag="filedentry")
    service = RafiqLabService(lab_session)
    await service.activate(now=now - timedelta(hours=1))
    await service.tick(now=now)

    rows = await _rows(lab_session, mint)
    assert len(rows) == 1
    row = rows[0]
    assert row.outcome == "entered"
    assert row.reject_reason is None
    # The market the decision saw, not a re-read of it later.
    assert row.liquidity_usd == Decimal("250000.0000")
    assert row.market_cap_usd == Decimal("2000000.0000")
    assert row.price_usd == Decimal("0.001000000000000000")
    assert row.opportunity_score == Decimal("85.0000")
    assert row.notional_usd is not None and row.notional_usd > 0
    assert row.entry_impact_pct is not None
    # And it points at the position it actually opened.
    position = (await lab_session.execute(
        select(RafiqLabPosition).where(RafiqLabPosition.id == row.position_id)
    )).scalars().first()
    assert position is not None and position.mint_address == mint


async def test_a_refusal_is_recorded_with_the_condition_that_refused_it(
    lab_session, monkeypatch
) -> None:
    """A $12k pool clears nothing F2 asks for. The row has to say which
    condition stopped it, or the population is unusable."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    now = datetime.now(UTC)
    mint = await seed_candidate(lab_session, now, tag="thinpool")
    await lab_session.execute(
        TokenMarketSnapshot.__table__.update()
        .where(TokenMarketSnapshot.mint_address == mint)
        .values(liquidity_usd=Decimal(12_000))
    )
    service = RafiqLabService(lab_session)
    await service.activate(now=now - timedelta(hours=1))
    await service.tick(now=now)

    rows = await _rows(lab_session, mint)
    assert rows, "a refused candidate left no record"
    assert {r.outcome for r in rows} == {"rejected"}
    assert rows[0].reject_reason == "liquidity_too_low"
    # The features are still captured. A refusal with no snapshot cannot be
    # compared against the entries.
    assert rows[0].liquidity_usd == Decimal("12000.0000")
    assert rows[0].price_usd is not None


async def test_a_repeated_refusal_does_not_overwrite_the_first(
    lab_session, monkeypatch
) -> None:
    """The first rejection is the one whose snapshot is point-in-time with
    respect to the forward window measured from it."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    now = datetime.now(UTC)
    mint = await seed_candidate(lab_session, now, tag="repeated")
    await lab_session.execute(
        TokenMarketSnapshot.__table__.update()
        .where(TokenMarketSnapshot.mint_address == mint)
        .values(liquidity_usd=Decimal(12_000))
    )
    service = RafiqLabService(lab_session)
    await service.activate(now=now - timedelta(hours=1))
    await service.tick(now=now)
    first = (await _rows(lab_session, mint))[0]
    decided, reason = first.decided_at, first.reject_reason

    for minute in (1, 2, 3):
        await service.tick(now=now + timedelta(minutes=minute))

    rows = await _rows(lab_session, mint)
    assert len(rows) == 1, "one row per candidate per book"
    assert rows[0].decided_at == decided
    assert rows[0].reject_reason == reason


async def test_an_entry_supersedes_an_earlier_refusal(
    lab_session, monkeypatch
) -> None:
    """Refused at 09:00 for a thin pool, bought at 09:02 when the pool
    deepened: one decision matters, and it is the entry."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    now = datetime.now(UTC)
    mint = await seed_candidate(lab_session, now, tag="supersede")
    await lab_session.execute(
        TokenMarketSnapshot.__table__.update()
        .where(TokenMarketSnapshot.mint_address == mint)
        .values(liquidity_usd=Decimal(12_000))
    )
    service = RafiqLabService(lab_session)
    await service.activate(now=now - timedelta(hours=1))
    await service.tick(now=now)
    assert (await _rows(lab_session, mint))[0].outcome == "rejected"

    token_id = (await lab_session.execute(
        select(DiscoveredToken.id).where(DiscoveredToken.mint_address == mint)
    )).scalar_one()
    later = now + timedelta(minutes=2)
    lab_session.add(TokenMarketSnapshot(
        token_id=token_id, mint_address=mint, captured_at=later,
        price_usd=Decimal("0.001"), liquidity_usd=Decimal(250_000),
        market_cap=Decimal(2_000_000), volume_5m=Decimal(5_000),
        volume_1h=Decimal(50_000), buy_count_24h=800, sell_count_24h=400,
        provider="test"))
    await lab_session.flush()
    await service.tick(now=later)

    rows = await _rows(lab_session, mint)
    assert len(rows) == 1
    assert rows[0].outcome == "entered"
    assert rows[0].reject_reason is None
    assert rows[0].position_id is not None
    assert rows[0].liquidity_usd == Decimal("250000.0000")


async def test_the_forward_window_starts_after_the_decision(
    lab_session, monkeypatch
) -> None:
    """A price printed before the decision must not appear in its forward
    return, and a horizon that has not closed must not be written at all."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    now = datetime.now(UTC) - timedelta(hours=2)
    mint = await seed_candidate(lab_session, now, tag="forward")
    service = RafiqLabService(lab_session)
    await service.activate(now=now - timedelta(hours=1))
    await service.tick(now=now)
    row = (await _rows(lab_session, mint))[0]
    assert row.price_usd == Decimal("0.001000000000000000")

    token_id = (await lab_session.execute(
        select(DiscoveredToken.id).where(DiscoveredToken.mint_address == mint)
    )).scalar_one()
    # Inside the hour: a 3x peak, ending at 0.5x on a dead pool.
    for minutes, price, liq in ((10, Decimal("0.003"), Decimal(250_000)),
                                (30, Decimal("0.002"), Decimal(200_000)),
                                (55, Decimal("0.0005"), Decimal(400))):
        lab_session.add(TokenMarketSnapshot(
            token_id=token_id, mint_address=mint,
            captured_at=now + timedelta(minutes=minutes),
            price_usd=price, liquidity_usd=liq, market_cap=Decimal(1_000_000),
            volume_5m=Decimal(100), volume_1h=Decimal(1_000),
            buy_count_24h=1, sell_count_24h=1, provider="test"))
    await lab_session.flush()

    result = await outcomes.record(lab_session, now=now + timedelta(hours=1))
    assert result["recorded"]["1h"] >= 1
    await lab_session.refresh(row)

    assert row.max_return_1h == Decimal("2.000000")      # 0.003 / 0.001 - 1
    assert row.final_return_1h == Decimal("-0.500000")   # 0.0005 / 0.001 - 1
    assert row.dead_1h is True                            # $400 < $1,000
    # +6h and +24h have not closed, so nothing was written for them.
    assert row.max_return_6h is None
    assert row.max_return_24h is None
    assert set(row.outcomes_attempted) == {"1h"}


async def test_a_horizon_with_no_prints_is_attempted_once_and_left_null(
    lab_session, monkeypatch
) -> None:
    """A token that stops printing has a legitimately null return. Without
    the attempt record it would be re-queried on every pass for ever."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    now = datetime.now(UTC) - timedelta(hours=2)
    mint = await seed_candidate(lab_session, now, tag="silentfwd")
    service = RafiqLabService(lab_session)
    await service.activate(now=now - timedelta(hours=1))
    await service.tick(now=now)
    row = (await _rows(lab_session, mint))[0]

    at = now + timedelta(hours=1)
    assert (await outcomes.record(lab_session, now=at))["recorded"]["1h"] >= 1
    await lab_session.refresh(row)
    assert row.max_return_1h is None
    assert row.outcomes_attempted == {"1h": None}

    # Second pass: this row is no longer selected.
    before = await outcomes.record(lab_session, now=at)
    assert before["recorded"]["1h"] == 0


async def test_coverage_reports_the_non_null_rate(lab_session, monkeypatch) -> None:
    """The number that says whether the instrument is working, as opposed to
    merely wired."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    now = datetime.now(UTC)
    await seed_candidate(lab_session, now, tag="coverage")
    service = RafiqLabService(lab_session)
    await service.activate(now=now - timedelta(hours=1))
    await service.tick(now=now)

    report = await outcomes.coverage(lab_session)
    assert report["candidates"] >= 1
    assert report["non_null_pct"]["liquidity_usd"] == 100.0
    # Both instrumented features are structurally absent on this platform
    # today; the report has to say so rather than omit them.
    assert report["non_null_pct"]["top10_holder_pct"] == 0.0
    assert report["non_null_pct"]["lp_status"] == 0.0


def test_only_f2_files_candidates() -> None:
    """One book enters, so one book's decisions are the population. If a
    second book were ever re-armed this test says the sample changed."""
    entering = [s.code for s in registry.STRATEGIES if s.enters]
    assert entering == ["F2"]


def test_every_reject_reason_is_short_enough_to_store() -> None:
    """The column is 48 characters. A truncated reason is a silent data loss
    in the one field the whole table is grouped by."""
    from app.labs.rafiq import entry_gate

    ours = {"candidate_too_old", "score_below_threshold", "no_observation",
            "not_priceable", "observation_stale", "consensus_refused",
            "no_stop_available", "size_is_zero", "insufficient_cash",
            "unquantifiable"}
    for reason in ours | set(entry_gate.REASONS):
        assert len(reason) <= 48, reason


def test_the_outcome_pass_reaches_no_external_endpoint() -> None:
    """Forward outcomes come from the platform's own snapshots. Nothing here
    can be rate-limited and no metered API is reachable."""
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path(outcomes.__file__).read_text())
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree) if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert not imported & {"httpx", "requests", "aiohttp", "urllib"}


async def test_the_chained_outcome_pass_actually_runs(lab_session, monkeypatch) -> None:
    """The forward pass rides the lab's beat task instead of taking a beat
    entry of its own. That is a branch that can silently never fire, so it
    gets a test that drives the scheduler rather than `outcomes.record`.
    """
    import contextlib

    from app.labs.rafiq import scheduler

    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")

    @contextlib.asynccontextmanager
    async def _factory():
        yield lab_session

    monkeypatch.setattr(scheduler, "SessionFactory", _factory)
    # The session is inside the fixture's transaction, which is rolled back;
    # a commit here would end it and detach everything after.
    monkeypatch.setattr(lab_session, "commit", lab_session.flush)

    on = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    monkeypatch.setattr(scheduler, "datetime",
                        type("C", (), {"now": staticmethod(lambda tz=None: on)}))
    assert on.minute % scheduler.OUTCOMES_EVERY_MINUTES == 0
    assert "outcomes" in await scheduler.tick()

    off = on.replace(minute=scheduler.OUTCOMES_EVERY_MINUTES // 2)
    monkeypatch.setattr(scheduler, "datetime",
                        type("C", (), {"now": staticmethod(lambda tz=None: off)}))
    assert "outcomes" not in await scheduler.tick()


def test_the_outcome_cadence_fires_every_hour() -> None:
    """A cadence that did not divide 60 would skip hours unpredictably."""
    from app.labs.rafiq import scheduler

    assert 60 % scheduler.OUTCOMES_EVERY_MINUTES == 0
