"""A full lab cycle, against a real database, with the flag ON.

THE CLAIM THIS EXISTS TO HOLD
-----------------------------
Turning the lab on changes nothing about the existing wallet. Not "we did not
mean to write to it" — the Karthik wallet's three tables are hashed before the
cycle and after it, and the hashes must match. The lab is required to actually
DO something in between, or the comparison proves only that an idle process
writes nothing.

The static tests in `test_isolation.py` prove the code to touch those tables
does not exist. This proves the behaviour of the code that does exist.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.labs.rafiq import config
from app.labs.rafiq.models import RafiqLabPosition, RafiqLabStrategy
from app.labs.rafiq.service import RafiqLabService
from app.models.karthik import KarthikPosition, KarthikWallet
from app.models.market import TokenMarketSnapshot, TradingStatus
from app.models.radar import RadarToken
from app.models.token import DiscoveredToken

pytestmark = pytest.mark.integration

WALLET_TABLES = ("karthik_wallets", "karthik_opportunities", "karthik_positions")


async def digest(session, tables=WALLET_TABLES) -> dict[str, str]:
    """A content hash per table. Ordered by primary key so row order in the
    heap cannot make an unchanged table look changed."""
    out = {}
    for table in tables:
        rows = (await session.execute(
            text(f"SELECT * FROM {table} ORDER BY id")  # noqa: S608 - fixed list
        )).all()
        blob = "\n".join(repr(tuple(r)) for r in rows).encode()
        out[table] = f"{len(rows)}:{hashlib.sha256(blob).hexdigest()}"
    return out


async def seed_existing_wallet(session, now) -> None:
    """A Karthik wallet with an open position, exactly as production has.

    The test database is reusable and may already hold one — `karthik_wallets`
    is a singleton by unique index — so an existing wallet is used as-is
    rather than duplicated. The hash comparison works on whatever is there;
    it does not need rows this test created.
    """
    existing = (await session.execute(select(KarthikWallet))).scalars().first()
    if existing is not None:
        return
    wallet = KarthikWallet(
        id=uuid.uuid4(), name="Karthik", starting_capital=Decimal(1000),
        trade_size=Decimal(10), take_profit_multiple=Decimal("1.25"),
        activated_at=now - timedelta(days=3))
    session.add(wallet)
    await session.flush()
    session.add(KarthikPosition(
        id=uuid.uuid4(), wallet_id=wallet.id, mint_address="Karthik" + "1" * 37,
        track_record_at=now - timedelta(days=2), opened_at=now - timedelta(days=2),
        entry_price=Decimal("0.001"), entry_observed_price=Decimal("0.001"),
        entry_observed_at=now - timedelta(days=2), cost_basis=Decimal(10),
        quantity=Decimal(10000), decimals=6, target_price=Decimal("0.00125"),
        status="open", peak_price=Decimal("0.0012"),
        last_evaluated_at=now - timedelta(hours=1)))
    await session.flush()


async def seed_candidate(session, now) -> str:
    """One fresh Radar admission with a deep, healthy market behind it, so
    every one of the five strategies can price and size it."""
    mint = "Rafiq" + "2" * 39
    token = DiscoveredToken(
        id=uuid.uuid4(), mint_address=mint, symbol="RFQ", name="Rafiq Test",
        signature="sig" + "4" * 60, slot=1,
        discovered_at=now - timedelta(minutes=5))
    session.add(token)
    await session.flush()
    session.add(RadarToken(
        token_id=token.id, mint_address=mint,
        first_detected_at=now - timedelta(minutes=5),
        first_opportunity_score=Decimal(85), first_confidence=Decimal(80),
        detection_reason=["test"], category="admission",
        current_opportunity_score=Decimal(85), current_confidence=Decimal(80),
        current_category="admission", is_active=True, model_version="test",
        last_evaluated_at=now))
    for minutes in (5, 4, 3, 2, 1, 0):
        session.add(TokenMarketSnapshot(
            token_id=token.id, mint_address=mint,
            captured_at=now - timedelta(minutes=minutes),
            price_usd=Decimal("0.001"), liquidity_usd=Decimal(250_000),
            market_cap=Decimal(2_000_000), volume_5m=Decimal(5_000),
            volume_1h=Decimal(50_000), buy_count_24h=800, sell_count_24h=400,
            trading_status=TradingStatus.TRADING, provider="test",
            pool_address="Pool" + "3" * 40))
    await session.flush()
    return mint


async def test_an_admission_older_than_activation_is_never_entered(
    lab_session, monkeypatch
) -> None:
    """The contamination boundary, as behaviour rather than as a comment."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    now = datetime.now(UTC)
    mint = await seed_candidate(lab_session, now)  # detected five minutes ago
    service = RafiqLabService(lab_session)
    await service.tick(now=now)                    # activates AT `now`
    # Scoped to the mint this test seeded: the database is reusable, so
    # "the table is empty" is not a claim this test is entitled to make.
    assert not list((await lab_session.execute(
        select(RafiqLabPosition).where(
            RafiqLabPosition.mint_address == mint))).scalars())


async def test_a_full_cycle_leaves_the_existing_wallet_byte_identical(
    lab_session, monkeypatch
) -> None:
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    assert config.enabled()
    now = datetime.now(UTC)

    await seed_existing_wallet(lab_session, now)
    service = RafiqLabService(lab_session)
    # Activate BEFORE the candidate is detected. `activated_at` is the whole
    # eligibility rule and it never moves, so a token admitted before the lab
    # existed can never be entered — the boundary that stops a backfill from
    # looking like a forward run.
    await service.activate(now=now - timedelta(hours=1))
    await seed_candidate(lab_session, now)
    before = await digest(lab_session)

    result = await service.tick(now=now)
    # ... and again, to prove a repeated tick is not a second entry either.
    await service.tick(now=now + timedelta(minutes=1))

    after = await digest(lab_session)
    assert after == before, "the lab changed the existing wallet's tables"

    # The cycle has to have DONE something, or the assertion above is vacuous.
    strategies = list((await lab_session.execute(
        select(RafiqLabStrategy))).scalars())
    assert len(strategies) == 5
    positions = list((await lab_session.execute(
        select(RafiqLabPosition))).scalars())
    assert positions, f"no strategy entered anything: {result}"
    # Exactly-once: the second tick did not double any book.
    assert len({(p.strategy_id, p.mint_address) for p in positions}) == len(positions)

    # E is absent from that list, and its absence is the gap, not a bug. With
    # no wallet-flow row and no security evaluation, only the DEX stream can
    # confirm — one stream, and not the mandatory one. E cannot trade a market
    # this platform can only half-observe, and it declines rather than
    # treating "unmeasured" as "fine".
    by_code = {r.id: r.code for r in strategies}
    entered = {by_code[p.strategy_id] for p in positions}
    assert entered == {"A", "B", "C", "D"}, entered


async def test_a_disabled_lab_writes_nothing_at_all(lab_session, monkeypatch) -> None:
    """The flag is the gate. Off, the scheduler returns before the service."""
    monkeypatch.delenv("RAFIQ_LAB_ENABLED", raising=False)
    now = datetime.now(UTC)
    await seed_candidate(lab_session, now)

    before = len(list((await lab_session.execute(
        select(RafiqLabStrategy))).scalars()))
    from app.labs.rafiq.scheduler import tick
    assert await tick() == {"skipped": "rafiq_lab_disabled"}
    after = len(list((await lab_session.execute(
        select(RafiqLabStrategy))).scalars()))
    assert after == before


async def test_the_lab_never_force_closes_on_a_halt(lab_session, monkeypatch) -> None:
    """Strategy D halts NEW entries. An open position keeps running under its
    own exit rules — panic-liquidating is a risk D's docstring refuses."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    now = datetime.now(UTC)
    service = RafiqLabService(lab_session)
    await service.activate(now=now - timedelta(hours=1))
    await seed_candidate(lab_session, now)
    await service.tick(now=now)

    rows = {r.code: r for r in (await lab_session.execute(
        select(RafiqLabStrategy))).scalars()}
    d_positions = list((await lab_session.execute(
        select(RafiqLabPosition).where(
            RafiqLabPosition.strategy_id == rows["D"].id))).scalars())
    if not d_positions:
        pytest.skip("D did not enter; nothing to hold open")

    # Force the halt by collapsing the day's baseline equity underneath it.
    state = (await lab_session.execute(text(
        "UPDATE rafiq_lab_daily_state SET day_open_equity = 100000 "
        "WHERE strategy_id = :sid RETURNING halted"),
        {"sid": rows["D"].id})).first()
    assert state is not None
    await service.tick(now=now + timedelta(minutes=1))

    still_open = list((await lab_session.execute(
        select(RafiqLabPosition).where(
            RafiqLabPosition.strategy_id == rows["D"].id,
            RafiqLabPosition.status == "open"))).scalars())
    assert len(still_open) == len(d_positions), "a halt force-closed a position"
