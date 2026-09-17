"""Every exit is valued against the pool as it stands at the exit. Nothing else.

THE BUG THIS PINS
-----------------
`engine.evaluate` closed a position whose token had stopped printing at
`last_mark_price` — the last price anyone saw, often hours earlier — and
`service._settle` then priced that sale against `entry_liquidity_usd` whenever
the exit observation carried no depth. A pool nobody could observe was sold
into at its old price and its entry-day depth.

In the A2-E2 archive 180 of 559 closed trades took that path, with exit
prices 95 to 630 minutes old on average. C2 booked +13.8% and D2 +23.6% on
them while every stop in the same books lost ~87%.

These tests drive the real settle path (`RafiqLabService.tick`), not the pure
evaluator, because the fictional half of the valuation lived in the service.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.labs.rafiq.adapters import costs
from app.labs.rafiq.api import _execution_cost
from app.labs.rafiq.models import RafiqLabPosition, RafiqLabStrategy
from app.labs.rafiq.service import RafiqLabService
from app.models.market import TokenEnrichmentState, TokenMarketSnapshot, TradingStatus
from app.models.radar import RadarToken
from app.models.token import DiscoveredToken

#: Mechanisms of the archived A2-F2 run, driven as that run traded.
pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("v2_run")]

ENTRY = Decimal("0.001")
QTY = Decimal(50_000)
DEEP = Decimal(250_000)
HOLD = timedelta(hours=4)


async def _token(session, tag: str, prints: list[tuple[datetime, Decimal | None,
                                                         Decimal | None, TradingStatus]],
                 delisted_at: datetime | None = None) -> str:
    """A Radar-admitted token with exactly the snapshots given."""
    mint = ("Val" + tag).ljust(44, "7")[:44]
    token = DiscoveredToken(
        id=uuid.uuid4(), mint_address=mint, symbol="VAL", name="Valuation",
        signature=("sig" + uuid.uuid4().hex).ljust(64, "4")[:64], slot=1,
        discovered_at=prints[0][0] - timedelta(minutes=1))
    session.add(token)
    await session.flush()
    session.add(RadarToken(
        token_id=token.id, mint_address=mint,
        first_detected_at=prints[0][0] - timedelta(minutes=1),
        first_opportunity_score=Decimal(80), first_confidence=Decimal(80),
        detection_reason=["test"], category="admission",
        current_opportunity_score=Decimal(80), current_confidence=Decimal(80),
        current_category="admission", is_active=True, model_version="test",
        last_evaluated_at=prints[-1][0]))
    for at, price, liquidity, status in prints:
        session.add(TokenMarketSnapshot(
            token_id=token.id, mint_address=mint, captured_at=at,
            price_usd=price, liquidity_usd=liquidity, market_cap=Decimal(2_000_000),
            volume_5m=Decimal(1_000), trading_status=status, provider="test",
            pool_address=("Pool" + tag).ljust(44, "3")[:44]))
    session.add(TokenEnrichmentState(token_id=token.id, mint_address=mint,
                                     total_snapshots=len(prints),
                                     delisted_at=delisted_at))
    await session.flush()
    return mint


async def _open(session, strategy: RafiqLabStrategy, mint: str, *, opened_at: datetime,
                peak: Decimal = ENTRY) -> RafiqLabPosition:
    """An open position frozen as the runner writes one: no target, a 25% trail."""
    pos = RafiqLabPosition(
        strategy_id=strategy.id, lab_run_id=strategy.lab_run_id, mint_address=mint,
        leg=1, opened_at=opened_at,
        entry_price=ENTRY, entry_observed_price=ENTRY, quantity=QTY,
        cost_basis=Decimal(50), entry_liquidity_usd=DEEP,
        stop_price=ENTRY * Decimal("0.88"), target_price=None,
        stop_pct=Decimal(12), trailing_frac=Decimal("0.25"),
        max_hold_seconds=int(HOLD.total_seconds()), status="open",
        peak_price=peak, last_mark_price=ENTRY,
        last_evaluated_at=opened_at + timedelta(minutes=1))
    session.add(pos)
    await session.flush()
    return pos


async def _book(session, service, now) -> RafiqLabStrategy:
    await service.activate(now=now - timedelta(days=1))
    return (await session.execute(
        select(RafiqLabStrategy).order_by(RafiqLabStrategy.code).limit(1)
    )).scalars().one()


async def _settled(session, pos_id) -> RafiqLabPosition:
    return (await session.execute(
        select(RafiqLabPosition).where(RafiqLabPosition.id == pos_id)
        .execution_options(populate_existing=True)
    )).scalars().one()


async def test_a_pool_that_stopped_printing_is_not_sold_at_its_last_price(
    lab_session, monkeypatch
) -> None:
    """The archive's shape: healthy at entry, then silence for hours.

    Before the fix this booked $49.61 of a $50 stake — the last price seen
    three hours earlier, sold into the pool's depth on entry day.
    """
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    now = datetime.now(UTC)
    opened = now - HOLD - timedelta(minutes=5)
    service = RafiqLabService(lab_session)
    book = await _book(lab_session, service, now)
    mint = await _token(lab_session, "silent", [
        (opened, ENTRY, DEEP, TradingStatus.TRADING),
        (opened + timedelta(minutes=1), ENTRY, DEEP, TradingStatus.TRADING),
    ])
    pos = await _open(lab_session, book, mint, opened_at=opened)

    await service.tick(now=now)

    row = await _settled(lab_session, pos.id)
    assert row.status == "closed" and row.exit_reason == "max_hold"
    assert row.exit_proceeds_usd == Decimal(0), (
        f"booked ${row.exit_proceeds_usd} from a pool nobody has seen since "
        f"{opened + timedelta(minutes=1):%H:%M}")
    assert "no tradeable pool" in row.exit_evidence


async def test_a_drained_pool_is_not_sold_into_the_depth_it_had_at_entry(
    lab_session, monkeypatch
) -> None:
    """DexScreener's dead-pool print: `inactive`, zero depth, and a price that
    is still UP. Before the fix `_settle` fell back to `entry_liquidity_usd`
    and booked a +19% exit from it."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    now = datetime.now(UTC)
    opened = now - HOLD - timedelta(minutes=5)
    service = RafiqLabService(lab_session)
    book = await _book(lab_session, service, now)
    up = ENTRY * Decimal("1.2")
    mint = await _token(lab_session, "drained", [
        (now - timedelta(minutes=30), ENTRY, DEEP, TradingStatus.TRADING),
        (now - timedelta(seconds=40), up, Decimal(0), TradingStatus.INACTIVE),
        (now - timedelta(seconds=20), up, Decimal(0), TradingStatus.INACTIVE),
    ])
    pos = await _open(lab_session, book, mint, opened_at=opened, peak=up)

    await service.tick(now=now)

    row = await _settled(lab_session, pos.id)
    assert row.status == "closed" and row.exit_reason == "max_hold"
    assert row.exit_proceeds_usd == Decimal(0), (
        f"booked ${row.exit_proceeds_usd} from a pool reporting zero liquidity")


async def test_a_delisted_pool_is_not_sold_at_its_last_print(
    lab_session, monkeypatch
) -> None:
    """The platform stamped a delisting after the last print: the provider
    stopped returning the pool. That print is still inside the feed's two-hour
    lookback, so the old code sold into it at full value."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    now = datetime.now(UTC)
    opened = now - HOLD - timedelta(minutes=5)
    service = RafiqLabService(lab_session)
    book = await _book(lab_session, service, now)
    mint = await _token(lab_session, "delisted", [
        (now - timedelta(minutes=61), ENTRY, DEEP, TradingStatus.TRADING),
        (now - timedelta(minutes=60), ENTRY, DEEP, TradingStatus.TRADING),
    ], delisted_at=now - timedelta(minutes=55))
    pos = await _open(lab_session, book, mint, opened_at=opened)

    await service.tick(now=now)

    row = await _settled(lab_session, pos.id)
    assert row.status == "closed" and row.exit_reason == "max_hold"
    assert row.exit_proceeds_usd == Decimal(0)


async def test_a_slowly_polled_live_pool_is_still_a_market(
    lab_session, monkeypatch
) -> None:
    """The platform re-prices a token past six hours old every thirty minutes,
    and this lab's positions are not in its priority lane. A 40-minute-old
    print with no death signal is the pool's last state, not a death — and it
    is sold into ITS depth, not the entry's."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    now = datetime.now(UTC)
    opened = now - HOLD - timedelta(minutes=5)
    service = RafiqLabService(lab_session)
    book = await _book(lab_session, service, now)
    thin = Decimal(90_000)
    mint = await _token(lab_session, "slow", [
        (now - timedelta(minutes=70), ENTRY, thin, TradingStatus.TRADING),
        (now - timedelta(minutes=40), ENTRY, thin, TradingStatus.TRADING),
    ])
    pos = await _open(lab_session, book, mint, opened_at=opened)

    await service.tick(now=now)

    row = await _settled(lab_session, pos.id)
    assert row.exit_reason == "max_hold"
    assert row.exit_proceeds_usd == costs.sell_proceeds(QTY, ENTRY, thin).quantize(
        Decimal("0.0001"))


async def test_a_live_pool_is_valued_by_the_same_model_on_every_path(
    lab_session, monkeypatch
) -> None:
    """The control. A fresh, funded print: the time-box exit is priced exactly
    as a stop or a target would be — the print, sold into THIS reading's depth."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    now = datetime.now(UTC)
    opened = now - HOLD - timedelta(minutes=5)
    service = RafiqLabService(lab_session)
    book = await _book(lab_session, service, now)
    thin = Decimal(120_000)          # NOT the entry depth, on purpose
    mint = await _token(lab_session, "live", [
        (now - timedelta(minutes=2), ENTRY, thin, TradingStatus.TRADING),
        (now - timedelta(minutes=1), ENTRY, thin, TradingStatus.TRADING),
        (now - timedelta(seconds=10), ENTRY, thin, TradingStatus.TRADING),
    ])
    pos = await _open(lab_session, book, mint, opened_at=opened)

    await service.tick(now=now)

    row = await _settled(lab_session, pos.id)
    assert row.exit_reason == "max_hold"
    assert row.exit_proceeds_usd == costs.sell_proceeds(QTY, ENTRY, thin).quantize(
        Decimal("0.0001"))
    assert row.exit_price == ENTRY


async def test_an_inactive_reading_alone_is_not_a_death(lab_session, monkeypatch) -> None:
    """One `inactive` poll is not a dead pool — 6.9% of the platform's
    dead_zero exits were tokens still trading. A trading print inside the
    confirmation window is what the exit is valued against."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    now = datetime.now(UTC)
    opened = now - HOLD - timedelta(minutes=5)
    service = RafiqLabService(lab_session)
    book = await _book(lab_session, service, now)
    depth = Decimal(180_000)
    mint = await _token(lab_session, "blip", [
        (now - timedelta(seconds=50), ENTRY, depth, TradingStatus.TRADING),
        (now - timedelta(seconds=10), ENTRY, Decimal(0), TradingStatus.INACTIVE),
    ])
    pos = await _open(lab_session, book, mint, opened_at=opened)

    await service.tick(now=now)

    row = await _settled(lab_session, pos.id)
    assert row.exit_reason == "max_hold"
    assert row.exit_proceeds_usd == costs.sell_proceeds(QTY, ENTRY, depth).quantize(
        Decimal("0.0001"))


def test_friction_is_fee_and_impact_only() -> None:
    """Execution cost is measured from the FILL. From the print it also counted
    the take-profit cap and a dead pool's leftover price as friction."""
    liquidity = Decimal(250_000)
    fill, printed = Decimal("0.0015"), Decimal("0.004")   # a capped target
    proceeds = costs.sell_proceeds(QTY, fill, liquidity)
    pos = RafiqLabPosition(status="closed", cost_basis=Decimal(50), quantity=QTY,
                           fraction_open=Decimal(1), scaled_out=False,
                           realised_usd=Decimal(0),
                           entry_observed_price=Decimal(50) / QTY,
                           exit_price=fill, exit_observed_price=printed,
                           exit_proceeds_usd=proceeds)
    assert _execution_cost([pos]) == QTY * fill - proceeds


def test_the_dead_pool_rule_on_its_own() -> None:
    """`pool_reading` without a database: which print, if any, an exit may use."""
    from types import SimpleNamespace

    from app.labs.rafiq.feed import pool_reading

    now = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)

    def row(ago_s, status=TradingStatus.TRADING, price=ENTRY, liquidity=DEEP):
        return SimpleNamespace(captured_at=now - timedelta(seconds=ago_s),
                               trading_status=status, price_usd=price,
                               liquidity_usd=liquidity)

    dead, gap = TradingStatus.INACTIVE, {"price": ENTRY, "liquidity": None}
    live = row(600)
    # A provider gap after the death does not resurrect the pool.
    assert pool_reading([live, row(300, dead), row(60, **gap)], now, None) is None
    # A pool that died and came back is live again.
    back = row(30)
    assert pool_reading([row(600), row(300, dead), back], now, None) is back
    # One inactive poll right after a trading print is a blip, not a death.
    fresh = row(90)
    assert pool_reading([fresh, row(10, dead)], now, None) is fresh
    # A delisting after the last print kills it; one before it does not.
    assert pool_reading([live], now, now - timedelta(seconds=300)) is None
    assert pool_reading([live], now, now - timedelta(seconds=900)) is live
    # Nothing tradeable at all is no reading.
    assert pool_reading([row(60, dead, price=None, liquidity=None)], now, None) is None
