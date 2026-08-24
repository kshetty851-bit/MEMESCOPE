"""Arena accounting: sequential capital, immutable ledger, PIT, isolation.

V4 proved that freeing capital into a negative-expectancy population destroys a
wallet faster than holding. The Arena therefore has to model capital as it
actually behaves — a position ties up its $10 until its frozen exit fires — and
these tests hold it to that rather than to a sum of independent trades.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.arena import rules
from app.arena.service import ArenaService
from app.models.arena import ArenaCandidate, ArenaDecision, ArenaPosition
from app.models.market import TokenMarketSnapshot, TradingStatus
from app.models.research_data import NurseryAdmission, ResearchQuote, WalletFlowSnapshot
from app.models.token import DiscoveredToken

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
VALID_FROM = NOW - timedelta(days=1)


async def _token(session, *, mint: str) -> DiscoveredToken:
    t = DiscoveredToken(mint_address=mint, signature=f"sig-{uuid.uuid4()}", slot=1,
                        discovered_at=NOW - timedelta(hours=3), source_program="pumpfun")
    session.add(t)
    await session.flush()
    return t


async def _candidate_token(session, *, mint: str, entered: datetime, liq: Decimal,
                           wallets: int = 40, buy_ok: bool = True, sell_ok: bool = True):
    """A token engineered to satisfy every candidate at its checkpoint."""
    tok = await _token(session, mint=mint)
    session.add(NurseryAdmission(token_id=tok.id, mint_address=mint, entered_at=entered,
                                 status="observing", window_minutes=60))
    for i in range(30):
        session.add(TokenMarketSnapshot(
            token_id=tok.id, mint_address=mint,
            captured_at=entered + timedelta(minutes=i),
            price_usd=Decimal("0.001"), liquidity_usd=liq * (1 + Decimal(i) / 100),
            trading_status=TradingStatus.TRADING, provider="test", suspect=False,
        ))
    session.add(WalletFlowSnapshot(
        key=mint, key_kind="mint", captured_at=entered + timedelta(minutes=25),
        w1h_unique_wallets=wallets, w1h_unique_buyers=wallets // 2 + 5,
        w1h_unique_sellers=wallets // 2 - 5, w1h_top10_tx_share=Decimal("0.4"),
        w1h_quality="exact",
    ))
    ckpt = entered + timedelta(minutes=rules.CHECKPOINT_MINUTES)
    for side, ok in (("buy", buy_ok), ("sell", sell_ok)):
        session.add(ResearchQuote(
            mint_address=mint, token_id=tok.id, requested_at=ckpt, side=side, size_usd=Decimal("10"),
            ok=ok, price_impact_pct=Decimal("0.5") if ok else None, context="checkpoint",
            checkpoint_minutes=rules.CHECKPOINT_MINUTES,
        ))
    await session.flush()
    return tok


async def test_every_candidate_starts_at_exactly_one_thousand(db_session):
    made = await ArenaService(db_session).activate(valid_from=VALID_FROM)
    assert len(made) == 5
    assert {c.code for c in made} == {"A", "B", "C", "D", "E"}
    assert all(c.starting_equity == Decimal("1000.00") and c.cash == Decimal("1000.00")
               for c in made)
    assert all(c.version == rules.RULES_VERSION for c in made)


async def test_the_cash_control_never_receives_a_decision_or_a_position(db_session):
    svc = ArenaService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    await _candidate_token(db_session, mint="CASHPROBE1111111111111111111111111111111",
                           entered=NOW - timedelta(hours=1), liq=Decimal("50000"))
    await svc.evaluate_due(now=NOW)
    cash = (await db_session.execute(
        select(ArenaCandidate).where(ArenaCandidate.code == "A"))).scalar_one()
    decisions = (await db_session.execute(
        select(ArenaDecision).where(ArenaDecision.candidate_id == cash.id))).scalars().all()
    positions = (await db_session.execute(
        select(ArenaPosition).where(ArenaPosition.candidate_id == cash.id))).scalars().all()
    assert decisions == [] and positions == []
    assert cash.cash == Decimal("1000.00")


async def test_a_qualifying_token_opens_one_position_and_debits_exactly_ten(db_session):
    svc = ArenaService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    await _candidate_token(db_session, mint="GOODTOKEN111111111111111111111111111111",
                           entered=NOW - timedelta(hours=1), liq=Decimal("50000"))
    result = await svc.evaluate_due(now=NOW)
    assert result["opened"] >= 1
    b = (await db_session.execute(
        select(ArenaCandidate).where(ArenaCandidate.code == "B"))).scalar_one()
    pos = (await db_session.execute(
        select(ArenaPosition).where(ArenaPosition.candidate_id == b.id))).scalars().all()
    assert len(pos) == 1
    assert pos[0].size_usd == Decimal("10.00")
    assert b.cash == Decimal("990.00")
    assert pos[0].target_price == pos[0].entry_price * Decimal("1.5")


async def test_a_sell_route_failure_is_recorded_and_refused_by_tradeability(db_session):
    """The case the Arena exists to price: buyable, unsellable."""
    svc = ArenaService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    await _candidate_token(db_session, mint="NOSELL11111111111111111111111111111111",
                           entered=NOW - timedelta(hours=1), liq=Decimal("50000"), sell_ok=False)
    await svc.evaluate_due(now=NOW)
    b = (await db_session.execute(
        select(ArenaCandidate).where(ArenaCandidate.code == "B"))).scalar_one()
    d = (await db_session.execute(
        select(ArenaDecision).where(ArenaDecision.candidate_id == b.id))).scalar_one()
    assert d.eligible is False
    assert d.skip_reason == "sell_route_failed"
    assert d.route_state == "BUY_OK_SELL_FAILED"
    assert b.cash == Decimal("1000.00")  # nothing spent on an unsellable token


async def test_capital_is_sequential_not_a_sum_of_independent_trades(db_session):
    """Six qualifying tokens, five slots: the sixth must be refused for capital,
    not silently included."""
    svc = ArenaService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    for i in range(6):
        await _candidate_token(db_session, mint=f"SEQ{i}AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                               entered=NOW - timedelta(hours=2) + timedelta(minutes=i),
                               liq=Decimal("50000"))
    await svc.evaluate_due(now=NOW)
    b = (await db_session.execute(
        select(ArenaCandidate).where(ArenaCandidate.code == "B"))).scalar_one()
    opens = (await db_session.execute(select(ArenaPosition).where(
        ArenaPosition.candidate_id == b.id, ArenaPosition.status == "open"))).scalars().all()
    assert len(opens) == rules.MAX_CONCURRENT
    assert b.cash == Decimal("1000.00") - rules.POSITION_SIZE_USD * rules.MAX_CONCURRENT
    refused = (await db_session.execute(select(ArenaDecision).where(
        ArenaDecision.candidate_id == b.id,
        ArenaDecision.skip_reason == "max_concurrent"))).scalars().all()
    assert len(refused) == 1


async def test_a_decision_is_written_once_and_never_revisited(db_session):
    svc = ArenaService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    await _candidate_token(db_session, mint="ONCE111111111111111111111111111111111111",
                           entered=NOW - timedelta(hours=1), liq=Decimal("50000"))
    first = await svc.evaluate_due(now=NOW)
    second = await svc.evaluate_due(now=NOW + timedelta(minutes=5))
    assert first["decided"] == 4  # B, C, D, E — never A
    assert second["decided"] == 0
    rows = (await db_session.execute(select(ArenaDecision))).scalars().all()
    assert len({(r.candidate_id, r.mint_address) for r in rows}) == len(rows)


async def test_tokens_whose_checkpoint_precedes_the_freeze_are_never_scored(db_session):
    """Protocol §0: everything before the boundary is contaminated."""
    svc = ArenaService(db_session)
    await svc.activate(valid_from=NOW - timedelta(minutes=10))
    await _candidate_token(db_session, mint="OLD11111111111111111111111111111111111111",
                           entered=NOW - timedelta(hours=5), liq=Decimal("50000"))
    result = await svc.evaluate_due(now=NOW)
    assert result["decided"] == 0


async def test_a_dead_pool_settles_at_zero_not_at_the_last_healthy_print(db_session):
    svc = ArenaService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    tok = await _candidate_token(db_session, mint="DEAD1111111111111111111111111111111111",
                                 entered=NOW - timedelta(hours=1), liq=Decimal("50000"))
    await svc.evaluate_due(now=NOW)
    db_session.add(TokenMarketSnapshot(
        token_id=tok.id, mint_address="DEAD1111111111111111111111111111111111",
        captured_at=NOW + timedelta(minutes=1), price_usd=Decimal("0.05"),
        liquidity_usd=Decimal("0"), trading_status=TradingStatus.INACTIVE,
        provider="test", suspect=False))
    await db_session.flush()
    await svc.settle(now=NOW + timedelta(minutes=2))
    closed = (await db_session.execute(select(ArenaPosition).where(
        ArenaPosition.status == "closed"))).scalars().all()
    assert closed
    assert all(p.exit_reason == "dead_zero" and p.exit_proceeds_usd == Decimal(0)
               for p in closed)


async def test_arena_settlement_touches_no_production_wallet_table(db_session):
    """The isolation guarantee, exercised rather than asserted."""
    from app.models.karthik import KarthikPosition
    from app.models.paper import PaperPosition

    svc = ArenaService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    await _candidate_token(db_session, mint="ISO11111111111111111111111111111111111111",
                           entered=NOW - timedelta(hours=1), liq=Decimal("50000"))
    await svc.evaluate_due(now=NOW)
    await svc.settle(now=NOW + timedelta(minutes=1))
    assert (await db_session.execute(select(PaperPosition))).scalars().all() == []
    assert (await db_session.execute(select(KarthikPosition))).scalars().all() == []
