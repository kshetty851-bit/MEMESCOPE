"""F2's two capital rules, as behaviour in the runner rather than in Rafiq's
module alone.

His own tests cover `EquityFloor` and `DailyTradeCap` as objects. These cover
the thing that was actually missing: whether the service consults them. It did
not — `_breaker` was gated on Strategy E's daily loss policy only, so F2's
$900 floor and its 20-trades-a-day cap existed in the file and bound nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.labs.rafiq import registry
from app.labs.rafiq.models import (
    RafiqCandidate,
    RafiqLabPosition,
    RafiqLabStrategy,
)
from app.labs.rafiq.service import RafiqLabService
from app.labs.rafiq.strategies import strategy_f2
from app.labs.rafiq.tests.test_full_cycle import seed_candidate

pytestmark = pytest.mark.integration


def test_the_floor_is_nine_hundred_not_a_thousand() -> None:
    """Karthik's explicit instruction. At $1,000 on a $1,000 book the first
    losing trade halts F2 for ever and the sample is one trade."""
    f2 = registry.BY_CODE["F2"]
    assert f2.equity_floor == Decimal(900)
    assert f2.equity_floor == strategy_f2.FLOOR_WITH_ROOM.floor_usd
    assert f2.equity_floor != strategy_f2.FLOOR_AT_START.floor_usd
    assert f2.max_trades_per_day == 20


def test_the_floor_and_the_cap_are_inside_f2s_digest() -> None:
    """Changing either must be a new record, not an edit to an old one."""
    import dataclasses

    f2 = registry.BY_CODE["F2"]
    assert dataclasses.replace(f2, equity_floor=Decimal(800)).digest != f2.digest
    assert dataclasses.replace(f2, max_trades_per_day=50).digest != f2.digest


def test_the_other_books_digests_are_untouched_by_those_fields() -> None:
    """A2-E2 carry neither, so their hashes must be what their records were
    opened under. These are the values committed in 8e8d47d."""
    assert {c: registry.BY_CODE[c].digest[:8]
            for c in ("A2", "B2", "C2", "D2", "E2")} == {
        "A2": "bba07d8c", "B2": "068d3a0e", "C2": "9809be8c",
        "D2": "5fa3c4e2", "E2": "6c42fd38"}


async def _f2(session) -> RafiqLabStrategy:
    return (await session.execute(
        select(RafiqLabStrategy).where(RafiqLabStrategy.code == "F2")
    )).scalars().one()


async def test_the_breaker_trips_at_nine_hundred(lab_session, monkeypatch) -> None:
    """$900.00 halts, $900.01 does not. The boundary is Rafiq's `<=`."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    now = datetime.now(UTC)
    service = RafiqLabService(lab_session)
    await service.activate(now=now - timedelta(hours=1))
    row = await _f2(lab_session)

    # A realised loss taking the book to exactly the floor. Booked as a closed
    # position, which is the only thing the runner counts as cash movement.
    for cost, proceeds in ((Decimal(100), Decimal(0)),):
        lab_session.add(RafiqLabPosition(
            strategy_id=row.id, mint_address="Floor".ljust(44, "1"), leg=1,
            opened_at=now - timedelta(hours=2), entry_price=Decimal(1),
            entry_observed_price=Decimal(1), quantity=Decimal(100),
            cost_basis=cost, stop_price=Decimal("0.88"), stop_pct=Decimal(12),
            max_hold_seconds=28800, status="closed", peak_price=Decimal(1),
            last_evaluated_at=now, closed_at=now - timedelta(hours=1),
            exit_price=Decimal(0), exit_observed_price=Decimal(0),
            exit_proceeds_usd=proceeds, exit_reason="stop"))
    await lab_session.flush()

    positions = list((await lab_session.execute(
        select(RafiqLabPosition).where(RafiqLabPosition.strategy_id == row.id)
    )).scalars())
    assert service.cash(row, positions) == Decimal(900)

    halted, reason = await service._breaker(
        registry.BY_CODE["F2"], row, positions, now=now)
    assert halted is True
    assert "hard floor" in reason

    # One cent above it, and the book still trades.
    positions[0].exit_proceeds_usd = Decimal("0.01")
    await lab_session.flush()
    fresh = await _f2(lab_session)
    halted, _ = await service._breaker(
        registry.BY_CODE["F2"], fresh, positions, now=now + timedelta(days=1))
    assert halted is False


async def test_a_halted_book_opens_nothing_and_closes_nothing(
    lab_session, monkeypatch
) -> None:
    """The floor stops entries. It must never force-close — selling into a
    drained pool is what produces the 0.0003x fills."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    now = datetime.now(UTC)
    service = RafiqLabService(lab_session)
    await service.activate(now=now - timedelta(hours=1))
    row = await _f2(lab_session)
    lab_session.add(RafiqLabPosition(
        strategy_id=row.id, mint_address="Drained".ljust(44, "2"), leg=1,
        opened_at=now - timedelta(hours=2), entry_price=Decimal(1),
        entry_observed_price=Decimal(1), quantity=Decimal(150),
        cost_basis=Decimal(150), stop_price=Decimal("0.88"),
        stop_pct=Decimal(12), max_hold_seconds=28800, status="closed",
        peak_price=Decimal(1), last_evaluated_at=now,
        closed_at=now - timedelta(hours=1), exit_price=Decimal(0),
        exit_observed_price=Decimal(0), exit_proceeds_usd=Decimal(0),
        exit_reason="stop"))
    await seed_candidate(lab_session, now, tag="halted")
    await lab_session.flush()

    await service.tick(now=now)
    opened = list((await lab_session.execute(
        select(RafiqLabPosition)
        .where(RafiqLabPosition.strategy_id == row.id,
               RafiqLabPosition.status == "open")
    )).scalars())
    assert opened == [], "a halted book opened a position"
    assert not hasattr(strategy_f2.FLOOR_WITH_ROOM, "force_close")


async def test_the_daily_cap_binds_against_what_was_opened(
    lab_session, monkeypatch
) -> None:
    """Twenty mints already opened today, so the twenty-first is refused —
    and the refusal is recorded, because how much of the stream the cap
    discarded is part of what F2 exists to measure."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    now = datetime.now(UTC)
    service = RafiqLabService(lab_session)
    await service.activate(now=now - timedelta(hours=1))
    row = await _f2(lab_session)

    for index in range(20):
        lab_session.add(RafiqLabPosition(
            strategy_id=row.id,
            mint_address=f"Cap{index:02d}".ljust(44, "3"), leg=1,
            opened_at=now - timedelta(minutes=30), entry_price=Decimal(1),
            entry_observed_price=Decimal(1), quantity=Decimal(10),
            cost_basis=Decimal(10), stop_price=Decimal("0.88"),
            stop_pct=Decimal(12), max_hold_seconds=28800, status="open",
            peak_price=Decimal(1), last_mark_price=Decimal(1),
            last_evaluated_at=now))
    mint = await seed_candidate(lab_session, now, tag="capped")
    await lab_session.flush()

    await service.tick(now=now)

    assert (await lab_session.execute(
        select(RafiqLabPosition).where(RafiqLabPosition.strategy_id == row.id,
                                       RafiqLabPosition.mint_address == mint)
    )).scalars().first() is None, "the cap did not bind"
    filed = (await lab_session.execute(
        select(RafiqCandidate).where(RafiqCandidate.mint_address == mint,
                                     RafiqCandidate.strategy_id == row.id)
    )).scalars().first()
    assert filed is not None and filed.reject_reason == "daily_trade_cap"
    # And it was evaluated all the way through first, so the row carries the
    # snapshot rather than a bare "cap" with no features. The cap is checked
    # last on purpose: checked first it would be the recorded reason for
    # nearly the whole stream and every one of those rows would lose the
    # reason it would actually have failed for.
    assert filed.liquidity_usd == Decimal("250000.0000")
    assert filed.notional_usd is not None
    assert filed.entry_impact_pct is not None


async def test_the_cap_resets_on_a_new_day(lab_session, monkeypatch) -> None:
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    now = datetime.now(UTC)
    service = RafiqLabService(lab_session)
    await service.activate(now=now - timedelta(hours=1))
    row = await _f2(lab_session)
    for index in range(20):
        lab_session.add(RafiqLabPosition(
            strategy_id=row.id,
            mint_address=f"Yday{index:02d}".ljust(44, "4"), leg=1,
            opened_at=now - timedelta(days=1), entry_price=Decimal(1),
            entry_observed_price=Decimal(1), quantity=Decimal(10),
            cost_basis=Decimal(10), stop_price=Decimal("0.88"),
            stop_pct=Decimal(12), max_hold_seconds=28800, status="closed",
            peak_price=Decimal(1), last_evaluated_at=now,
            closed_at=now - timedelta(days=1) + timedelta(hours=1),
            exit_price=Decimal(1), exit_observed_price=Decimal(1),
            exit_proceeds_usd=Decimal(10), exit_reason="max_hold"))
    mint = await seed_candidate(lab_session, now, tag="newday")
    await lab_session.flush()

    await service.tick(now=now)
    assert (await lab_session.execute(
        select(RafiqLabPosition).where(RafiqLabPosition.strategy_id == row.id,
                                       RafiqLabPosition.mint_address == mint)
    )).scalars().first() is not None, "yesterday's trades held today's cap down"
