"""V6 Strategy Lab accounting: one scanner, sequential capital, PIT, snapshots.

V4/V5/V6 all measured the same thing — freeing capital into a negative-
expectancy population destroys a wallet faster than holding it. So capital has
to be modelled as it actually behaves: a position ties up its own size until
its own frozen exit fires. These tests hold the Lab to that, and to the
executable-value accounting the mission requires, rather than to a sum of
independent trades.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.lab import leaderboard, spec
from app.lab.service import LabService
from app.models.lab import (
    LabDecision,
    LabPosition,
    LabSnapshot,
    LabStrategy,
    LabTournament,
)
from app.models.market import TokenMarketSnapshot, TradingStatus
from app.models.radar import RadarToken
from app.models.research_data import ResearchQuote, WalletFlowSnapshot
from app.models.token import DiscoveredToken

pytestmark = pytest.mark.integration

D = Decimal
NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
VALID_FROM = NOW - timedelta(days=1)


async def _radar_token(session, *, mint: str, detected: datetime, liq: D,
                       price: D = D("0.001"), pool: str | None = None,
                       wallets: int = 40, buy_ok: bool = True, sell_ok: bool = True,
                       flow_key_is_pool: bool = False, minutes: int = 70):
    """A token engineered to satisfy the depth-gated strategies at any checkpoint."""
    tok = DiscoveredToken(mint_address=mint, signature=f"sig-{uuid.uuid4()}", slot=1,
                          discovered_at=detected, source_program="pumpfun")
    session.add(tok)
    await session.flush()
    session.add(RadarToken(token_id=tok.id, mint_address=mint,
                           first_detected_at=detected, first_price=price,
                           first_liquidity=liq, category="watch", current_category="watch",
                           first_opportunity_score=D("70"), first_confidence=D("70"),
                           current_opportunity_score=D("70"), current_confidence=D("70"),
                           current_price=price, current_liquidity=liq, model_version="test"))
    for i in range(minutes):
        session.add(TokenMarketSnapshot(
            token_id=tok.id, mint_address=mint,
            captured_at=detected + timedelta(minutes=i),
            price_usd=price, liquidity_usd=liq, market_cap=liq * 10,
            volume_1h=D("100000"), volume_5m=D("10000"),
            buy_count_24h=100 + i * 3, sell_count_24h=50 + i,
            trading_status=TradingStatus.TRADING, provider="test", suspect=False,
            pool_address=pool,
        ))
    session.add(WalletFlowSnapshot(
        key=(pool if flow_key_is_pool and pool else mint),
        key_kind=("pool" if flow_key_is_pool and pool else "mint"),
        captured_at=detected + timedelta(minutes=25),
        w1h_unique_wallets=wallets, w1h_unique_buyers=wallets // 2 + 5,
        w1h_unique_sellers=wallets // 2 - 5, w1h_top10_tx_share=D("0.4"),
        w1h_quality="exact",
    ))
    for side, ok in (("buy", buy_ok), ("sell", sell_ok)):
        session.add(ResearchQuote(
            mint_address=mint, token_id=tok.id,
            requested_at=detected + timedelta(minutes=30), side=side,
            size_usd=D("10"), ok=ok,
            price_impact_pct=D("0.5") if ok else None,
            context="checkpoint", checkpoint_minutes=30,
        ))
    await session.flush()
    return tok


# ---------------------------------------------------------------- activation

async def test_twenty_wallets_each_start_at_exactly_one_thousand(db_session):
    await LabService(db_session).activate(valid_from=VALID_FROM)
    rows = list((await db_session.execute(select(LabStrategy))).scalars())
    assert len(rows) == 20
    assert all(r.starting_equity == D("1000.00") for r in rows)
    assert all(r.cash == D("1000.00") for r in rows)
    assert {r.strategy_id for r in rows} == {s.id for s in spec.STRATEGIES}
    assert sum(r.starting_equity for r in rows) == D("20000.00")


async def test_activation_is_idempotent_and_valid_from_never_moves(db_session):
    svc = LabService(db_session)
    first = await svc.activate(valid_from=VALID_FROM)
    second = await svc.activate(valid_from=NOW)          # a restart, later clock
    assert first.id == second.id
    assert second.valid_from == VALID_FROM
    assert second.snapshot_at == VALID_FROM + timedelta(hours=24)
    assert (await db_session.scalar(select(func.count()).select_from(LabStrategy))) == 20


async def test_spec_hash_is_stamped_on_every_strategy(db_session):
    await LabService(db_session).activate(valid_from=VALID_FROM)
    rows = list((await db_session.execute(select(LabStrategy))).scalars())
    assert all(r.spec_hash == spec.SPEC_HASH for r in rows)


async def test_a_drifted_spec_halts_scoring_rather_than_using_new_rules(db_session,
                                                                       monkeypatch):
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    monkeypatch.setattr(spec, "SPEC_HASH", "deadbeef" * 8)
    assert await svc.evaluate_due(now=NOW) == {"halted": "spec_hash_drift"}


# ---------------------------------------------------------------- one scanner

async def test_one_token_is_judged_by_every_strategy_at_its_checkpoint(db_session):
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    await _radar_token(db_session, mint="M" + "1" * 20,
                       detected=NOW - timedelta(hours=2), liq=D("600000"), pool="POOL1")
    await svc.evaluate_due(now=NOW)
    rows = list((await db_session.execute(select(LabDecision))).scalars())
    # nineteen trading strategies, one decision each; the cash control has none
    assert len({r.strategy_id for r in rows}) == 19
    assert "V6-01" not in {r.strategy_id for r in rows}
    assert {r.checkpoint_minutes for r in rows} == {0, 30, 60}


async def test_the_same_token_may_be_bought_by_several_strategies(db_session):
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    await _radar_token(db_session, mint="M" + "2" * 20,
                       detected=NOW - timedelta(hours=2), liq=D("600000"), pool="POOL2")
    await svc.evaluate_due(now=NOW)
    holders = {p.strategy_id for p in
               (await db_session.execute(select(LabPosition))).scalars()}
    # every depth gate up to $500k is satisfied by a $600k pool
    assert {"V6-04", "V6-05", "V6-06", "V6-07"} <= holders


async def test_one_position_per_mint_per_strategy_ever(db_session):
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    await _radar_token(db_session, mint="M" + "3" * 20,
                       detected=NOW - timedelta(hours=2), liq=D("600000"), pool="POOL3")
    await svc.evaluate_due(now=NOW)
    await svc.evaluate_due(now=NOW + timedelta(minutes=5))   # a second tick
    counts = list((await db_session.execute(
        select(LabPosition.strategy_id, func.count())
        .group_by(LabPosition.strategy_id)
    )).all())
    assert all(n == 1 for _, n in counts)


async def test_decisions_are_written_once_and_include_skips(db_session):
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    # a shallow pool: every depth gate must SKIP, and say why
    await _radar_token(db_session, mint="M" + "4" * 20,
                       detected=NOW - timedelta(hours=2), liq=D("5000"), pool="POOL4")
    await svc.evaluate_due(now=NOW)
    skips = list((await db_session.execute(
        select(LabDecision).where(LabDecision.eligible.is_(False))
    )).scalars())
    assert skips, "a refusal is evidence and must be recorded"
    assert any(r.skip_reason == "liq_below_400k" for r in skips)
    # Only the two unconditional controls buy a $5k pool; every gate refuses it.
    holders = {p.strategy_id for p in
               (await db_session.execute(select(LabPosition))).scalars()}
    assert holders == {"V6-02", "V6-03"}


# ---------------------------------------------------------------- PIT

async def test_a_later_observation_cannot_reach_an_earlier_decision(db_session):
    """The gate must see the checkpoint's depth, not the depth that came after."""
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    detected = NOW - timedelta(hours=2)
    tok = await _radar_token(db_session, mint="M" + "5" * 20, detected=detected,
                             liq=D("50000"), pool="POOL5")
    # depth explodes an hour AFTER the 30-minute checkpoint
    db_session.add(TokenMarketSnapshot(
        token_id=tok.id, mint_address="M" + "5" * 20,
        captured_at=detected + timedelta(minutes=90),
        price_usd=D("0.001"), liquidity_usd=D("5000000"), market_cap=D("10000000"),
        trading_status=TradingStatus.TRADING, provider="test", suspect=False,
    ))
    await db_session.flush()
    await svc.evaluate_due(now=NOW)
    v606 = (await db_session.execute(
        select(LabDecision).where(LabDecision.strategy_id == "V6-06")
    )).scalars().first()
    assert v606.eligible is False
    assert v606.skip_reason == "liq_below_400k"


async def test_tokens_before_valid_from_are_never_scored(db_session):
    svc = LabService(db_session)
    await svc.activate(valid_from=NOW - timedelta(minutes=30))
    await _radar_token(db_session, mint="M" + "6" * 20,
                       detected=NOW - timedelta(days=3), liq=D("600000"), pool="POOL6")
    await svc.evaluate_due(now=NOW)
    assert (await db_session.scalar(
        select(func.count()).select_from(LabDecision))) == 0


async def test_suspect_rows_never_enter_a_decision(db_session):
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    detected = NOW - timedelta(hours=2)
    tok = await _radar_token(db_session, mint="M" + "7" * 20, detected=detected,
                             liq=D("50000"), pool="POOL7")
    db_session.add(TokenMarketSnapshot(
        token_id=tok.id, mint_address="M" + "7" * 20,
        captured_at=detected + timedelta(minutes=29),
        price_usd=D("0.001"), liquidity_usd=D("9000000"), market_cap=D("10000000"),
        trading_status=TradingStatus.TRADING, provider="test", suspect=True,
    ))
    await db_session.flush()
    await svc.evaluate_due(now=NOW)
    v606 = (await db_session.execute(
        select(LabDecision).where(LabDecision.strategy_id == "V6-06")
    )).scalars().first()
    assert v606.eligible is False


# ---------------------------------------------------------------- capital

async def test_capital_is_sequential_and_concurrency_is_enforced(db_session):
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    for i in range(12):
        await _radar_token(db_session, mint=f"C{i:02d}" + "x" * 18,
                           detected=NOW - timedelta(hours=2, minutes=i),
                           liq=D("600000"), pool=f"CP{i}")
    await svc.evaluate_due(now=NOW)
    # V6-06 caps at 8 concurrent / $80 exposure
    row = (await db_session.execute(
        select(LabStrategy).where(LabStrategy.strategy_id == "V6-06")
    )).scalars().first()
    n, deployed = await svc._open_book(row)
    assert n == 8
    assert deployed == D("80")
    assert row.cash == D("920")
    skips = {r.skip_reason for r in (await db_session.execute(
        select(LabDecision).where(LabDecision.strategy_id == "V6-06",
                                  LabDecision.eligible.is_(True))
    )).scalars()}
    assert "max_concurrent" in skips or "max_exposure" in skips


async def test_max_exposure_is_respected_independently_of_concurrency(db_session):
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    for i in range(8):
        await _radar_token(db_session, mint=f"E{i:02d}" + "x" * 18,
                           detected=NOW - timedelta(hours=2, minutes=i),
                           liq=D("600000"), pool=f"EP{i}")
    await svc.evaluate_due(now=NOW)
    row = (await db_session.execute(
        select(LabStrategy).where(LabStrategy.strategy_id == "V6-18")
    )).scalars().first()
    n, deployed = await svc._open_book(row)
    assert deployed <= row.max_exposure_usd
    assert n <= row.max_concurrent


async def test_cash_control_never_opens_anything(db_session):
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    for i in range(4):
        await _radar_token(db_session, mint=f"Z{i:02d}" + "x" * 18,
                           detected=NOW - timedelta(hours=2, minutes=i),
                           liq=D("900000"), pool=f"ZP{i}")
    await svc.evaluate_due(now=NOW)
    await svc.settle(now=NOW)
    cash = (await db_session.execute(
        select(LabStrategy).where(LabStrategy.strategy_id == "V6-01")
    )).scalars().first()
    assert cash.cash == D("1000.00")
    assert (await db_session.scalar(select(func.count()).select_from(LabPosition)
                                    .where(LabPosition.strategy_id == "V6-01"))) == 0
    assert await svc.equity(cash) == D("1000.00")


# ---------------------------------------------------------------- settlement

async def _open_one(db_session, svc, *, mint: str, liq: D, price: D = D("0.001")):
    await _radar_token(db_session, mint=mint, detected=NOW - timedelta(hours=2),
                       liq=liq, price=price, pool=f"P{mint[:4]}")
    await svc.evaluate_due(now=NOW)


async def test_take_profit_closes_at_the_executable_multiple(db_session):
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    await _open_one(db_session, svc, mint="T" + "1" * 20, liq=D("600000"))
    pos = (await db_session.execute(
        select(LabPosition).where(LabPosition.strategy_id == "V6-06")
    )).scalars().first()
    assert pos is not None
    db_session.add(TokenMarketSnapshot(
        token_id=pos.token_id, mint_address=pos.mint_address,
        captured_at=NOW + timedelta(minutes=1), price_usd=D("0.0014"),
        liquidity_usd=D("600000"), market_cap=D("6000000"),
        trading_status=TradingStatus.TRADING, provider="test", suspect=False,
    ))
    await db_session.flush()
    await svc.settle(now=NOW + timedelta(minutes=2))
    await db_session.refresh(pos)
    assert pos.status == "closed"
    assert pos.exit_reason.startswith("target")
    assert pos.exit_proceeds_usd > D("12")


async def test_a_dead_pool_settles_at_zero_not_at_its_last_healthy_print(db_session):
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    await _open_one(db_session, svc, mint="T" + "2" * 20, liq=D("600000"))
    pos = (await db_session.execute(
        select(LabPosition).where(LabPosition.strategy_id == "V6-06")
    )).scalars().first()
    db_session.add(TokenMarketSnapshot(
        token_id=pos.token_id, mint_address=pos.mint_address,
        captured_at=NOW + timedelta(minutes=1), price_usd=D("0.005"),
        liquidity_usd=D("600000"), trading_status=TradingStatus.INACTIVE,
        provider="test", suspect=False,
    ))
    await db_session.flush()
    await svc.settle(now=NOW + timedelta(minutes=2))
    await db_session.refresh(pos)
    assert pos.status == "closed"
    assert pos.exit_reason == "dead_zero"
    assert pos.exit_proceeds_usd == 0


async def test_a_stale_print_is_not_acted_on(db_session):
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    await _open_one(db_session, svc, mint="T" + "3" * 20, liq=D("600000"))
    pos = (await db_session.execute(
        select(LabPosition).where(LabPosition.strategy_id == "V6-06")
    )).scalars().first()
    # nothing new for hours: holding is the honest response to not knowing
    out = await svc.settle(now=NOW + timedelta(hours=5))
    await db_session.refresh(pos)
    assert pos.status == "open"
    assert out["stale"] >= 1


async def test_a_glitch_print_never_closes_a_position(db_session):
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    await _open_one(db_session, svc, mint="T" + "4" * 20, liq=D("600000"))
    pos = (await db_session.execute(
        select(LabPosition).where(LabPosition.strategy_id == "V6-06")
    )).scalars().first()
    for i in (1, 2, 3):
        db_session.add(TokenMarketSnapshot(
            token_id=pos.token_id, mint_address=pos.mint_address,
            captured_at=NOW + timedelta(seconds=i * 20), price_usd=D("0.001"),
            liquidity_usd=D("600000"), trading_status=TradingStatus.TRADING,
            provider="test", suspect=False,
        ))
    db_session.add(TokenMarketSnapshot(
        token_id=pos.token_id, mint_address=pos.mint_address,
        captured_at=NOW + timedelta(seconds=90), price_usd=D("50"),   # x50,000
        liquidity_usd=D("600000"), trading_status=TradingStatus.TRADING,
        provider="test", suspect=False,
    ))
    await db_session.flush()
    await svc.settle(now=NOW + timedelta(minutes=2))
    await db_session.refresh(pos)
    assert pos.status == "open", "an off-band print is not a market you can sell into"


async def test_partial_banks_cash_and_the_runner_keeps_going(db_session):
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    await _open_one(db_session, svc, mint="T" + "5" * 20, liq=D("900000"))
    pos = (await db_session.execute(
        select(LabPosition).where(LabPosition.strategy_id == "V6-19")
    )).scalars().first()
    assert pos is not None
    row = (await db_session.execute(
        select(LabStrategy).where(LabStrategy.strategy_id == "V6-19")
    )).scalars().first()
    cash_before = row.cash
    db_session.add(TokenMarketSnapshot(
        token_id=pos.token_id, mint_address=pos.mint_address,
        captured_at=NOW + timedelta(minutes=1), price_usd=D("0.0013"),
        liquidity_usd=D("900000"), trading_status=TradingStatus.TRADING,
        provider="test", suspect=False,
    ))
    await db_session.flush()
    await svc.settle(now=NOW + timedelta(minutes=2))
    await db_session.refresh(pos)
    await db_session.refresh(row)
    assert pos.status == "open"
    assert pos.partial_done is True
    assert pos.banked_proceeds_usd > D("6")
    assert pos.quantity_remaining < pos.quantity
    assert row.cash > cash_before, "banked proceeds must reach the wallet"


async def test_liquidity_collapse_exits_the_strategies_that_declared_it(db_session):
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    await _open_one(db_session, svc, mint="T" + "6" * 20, liq=D("600000"))
    pos = (await db_session.execute(
        select(LabPosition).where(LabPosition.strategy_id == "V6-08")
    )).scalars().first()
    assert pos is not None
    db_session.add(TokenMarketSnapshot(
        token_id=pos.token_id, mint_address=pos.mint_address,
        captured_at=NOW + timedelta(minutes=1), price_usd=D("0.001"),
        liquidity_usd=D("100000"),     # depth cut to a sixth of entry
        trading_status=TradingStatus.TRADING, provider="test", suspect=False,
    ))
    await db_session.flush()
    await svc.settle(now=NOW + timedelta(minutes=2))
    await db_session.refresh(pos)
    assert pos.status == "closed"
    assert pos.exit_reason == "liquidity_decay"


async def test_time_exit_fires_at_its_own_horizon(db_session):
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    await _open_one(db_session, svc, mint="T" + "7" * 20, liq=D("600000"))
    pos = (await db_session.execute(
        select(LabPosition).where(LabPosition.strategy_id == "V6-15")   # 2h exit
    )).scalars().first()
    assert pos is not None
    later = pos.opened_at + timedelta(hours=2, minutes=1)
    db_session.add(TokenMarketSnapshot(
        token_id=pos.token_id, mint_address=pos.mint_address,
        captured_at=later - timedelta(minutes=1), price_usd=D("0.001"),
        liquidity_usd=D("600000"), trading_status=TradingStatus.TRADING,
        provider="test", suspect=False,
    ))
    await db_session.flush()
    await svc.settle(now=later)
    await db_session.refresh(pos)
    assert pos.status == "closed"
    assert pos.exit_reason == "time_2h"


# ---------------------------------------------------------------- accounting

async def test_equity_is_cash_plus_executable_value_never_plus_cost(db_session):
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    await _open_one(db_session, svc, mint="T" + "8" * 20, liq=D("600000"))
    pos = (await db_session.execute(
        select(LabPosition).where(LabPosition.strategy_id == "V6-06")
    )).scalars().first()
    row = (await db_session.execute(
        select(LabStrategy).where(LabStrategy.strategy_id == "V6-06")
    )).scalars().first()
    # the token halves: $10 of cost is now ~$5 of executable value
    db_session.add(TokenMarketSnapshot(
        token_id=pos.token_id, mint_address=pos.mint_address,
        captured_at=NOW + timedelta(minutes=1), price_usd=D("0.0005"),
        liquidity_usd=D("600000"), trading_status=TradingStatus.TRADING,
        provider="test", suspect=False,
    ))
    await db_session.flush()
    await svc.settle(now=NOW + timedelta(minutes=2))
    await db_session.refresh(pos)
    await db_session.refresh(row)
    assert pos.status == "open"
    assert D("4") < pos.last_open_value_usd < D("6")
    equity = await svc.equity(row)
    assert equity < D("996"), "a halved position must not be carried at its cost"


async def test_circuit_breaker_stops_new_entries_below_800(db_session):
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    row = (await db_session.execute(
        select(LabStrategy).where(LabStrategy.strategy_id == "V6-06")
    )).scalars().first()
    row.cash = D("790")
    await db_session.flush()
    await svc._apply_breaker(row, NOW)
    assert row.status == "failed"
    assert row.failed_reason == "drawdown_below_800"
    await _open_one(db_session, svc, mint="T" + "9" * 20, liq=D("600000"))
    opened = (await db_session.scalar(
        select(func.count()).select_from(LabPosition)
        .where(LabPosition.strategy_id == "V6-06")))
    assert opened == 0
    d = (await db_session.execute(
        select(LabDecision).where(LabDecision.strategy_id == "V6-06")
    )).scalars().first()
    assert d.skip_reason == "candidate_failed"


# ---------------------------------------------------------------- flow keying

async def test_wallet_flow_resolves_mint_to_its_active_pool(db_session):
    """The table is keyed by pool. V6-12 must still find its own token's flow."""
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    await _radar_token(db_session, mint="F" + "1" * 20,
                       detected=NOW - timedelta(hours=2), liq=D("600000"),
                       pool="POOLFLOW1", flow_key_is_pool=True)
    await svc.evaluate_due(now=NOW)
    d = (await db_session.execute(
        select(LabDecision).where(LabDecision.strategy_id == "V6-12")
    )).scalars().first()
    assert d.eligible is True, d.skip_reason
    assert d.snapshot_ids["flow_source"] == "pool"


async def test_an_unrelated_pool_is_never_joined(db_session):
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    # flow exists, but only for a DIFFERENT pool
    db_session.add(WalletFlowSnapshot(
        key="SOMEONEELSESPOOL", key_kind="pool", captured_at=NOW - timedelta(hours=1),
        w1h_unique_wallets=500, w1h_unique_buyers=400, w1h_unique_sellers=100,
        w1h_top10_tx_share=D("0.1"), w1h_quality="exact",
    ))
    tok = DiscoveredToken(mint_address="F" + "2" * 20, signature=f"sig-{uuid.uuid4()}",
                          slot=1, discovered_at=NOW - timedelta(hours=2),
                          source_program="pumpfun")
    db_session.add(tok)
    await db_session.flush()
    db_session.add(RadarToken(token_id=tok.id, mint_address="F" + "2" * 20,
                              first_detected_at=NOW - timedelta(hours=2),
                              first_price=D("0.001"), first_liquidity=D("600000"),
                              category="watch", current_category="watch",
                              first_opportunity_score=D("70"), first_confidence=D("70"),
                              current_opportunity_score=D("70"),
                              current_confidence=D("70"),
                              current_price=D("0.001"), current_liquidity=D("600000"),
                              model_version="test"))
    for i in range(40):
        db_session.add(TokenMarketSnapshot(
            token_id=tok.id, mint_address="F" + "2" * 20,
            captured_at=NOW - timedelta(hours=2) + timedelta(minutes=i),
            price_usd=D("0.001"), liquidity_usd=D("600000"), market_cap=D("6000000"),
            trading_status=TradingStatus.TRADING, provider="test", suspect=False,
            pool_address="MYOWNPOOL",
        ))
    await db_session.flush()
    await svc.evaluate_due(now=NOW)
    d = (await db_session.execute(
        select(LabDecision).where(LabDecision.strategy_id == "V6-12",
                                  LabDecision.mint_address == "F" + "2" * 20)
    )).scalars().first()
    assert d.eligible is False
    assert d.skip_reason == "unknown_flow_quality"


# ---------------------------------------------------------------- snapshots

async def test_24h_snapshot_marks_open_positions_without_closing_them(db_session):
    svc = LabService(db_session)
    t = await svc.activate(valid_from=VALID_FROM)
    await _open_one(db_session, svc, mint="S" + "1" * 20, liq=D("600000"))
    await svc.settle(now=NOW)
    boundary = VALID_FROM + timedelta(hours=24)
    payload = await leaderboard.build_snapshot(
        db_session, tournament=t, label="24H", boundary=boundary, now=NOW
    )
    assert payload["label"] == "24H"
    assert len(payload["strategies"]) == 20
    assert payload["leaders"]["profit"]["strategy_id"]
    open_positions = list((await db_session.execute(
        select(LabPosition).where(LabPosition.status == "open")
    )).scalars())
    assert open_positions, "the snapshot must not force-close the book"
    assert all(p.snapshot_value_usd is not None for p in open_positions)


async def test_snapshot_boundary_marking_is_written_once(db_session):
    svc = LabService(db_session)
    t = await svc.activate(valid_from=VALID_FROM)
    await _open_one(db_session, svc, mint="S" + "2" * 20, liq=D("600000"))
    await svc.settle(now=NOW)
    boundary = VALID_FROM + timedelta(hours=24)
    first = await leaderboard.mark_open_at_boundary(db_session, boundary=boundary)
    again = await leaderboard.mark_open_at_boundary(db_session, boundary=boundary)
    assert first >= 1
    assert again == 0, "a re-run must not restamp a frozen boundary value"


async def test_leaderboard_shows_twenty_rows_and_three_independent_badges(db_session):
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    rows = await leaderboard.strategy_rows(db_session)
    assert len(rows) == 20
    badges = leaderboard.leaders(rows)
    assert set(badges) == {"profit", "risk_adjusted", "executable_2x"}
    cash = next(r for r in rows if r["strategy_id"] == "V6-01")
    assert cash["equity"] == D("1000.00")
    assert cash["confidence"] == "INSUFFICIENT_SAMPLE"


async def test_equity_points_are_recorded_for_every_strategy(db_session):
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    assert await svc.record_equity(now=NOW) == 20


# --- the tournament outlives its own snapshot --------------------------------
# The 24-hour mark is a photograph, not a finish line. These hold the system to
# that, because "it keeps running" is the kind of claim that is easy to assert
# and easy to get silently wrong.

async def test_trading_continues_after_the_24h_snapshot(db_session):
    svc = LabService(db_session)
    t = await svc.activate(valid_from=VALID_FROM)
    boundary = t.snapshot_at
    after = boundary + timedelta(hours=2)

    await leaderboard.build_snapshot(
        db_session, tournament=t, label="24H", boundary=boundary, now=boundary
    )
    t.snapshot_taken_at = boundary
    await db_session.flush()

    # a token admitted AFTER the snapshot must still be judged and bought
    await _radar_token(db_session, mint="A" + "1" * 20,
                       detected=after - timedelta(hours=2), liq=D("600000"),
                       pool="POOLAFTER1")
    out = await svc.evaluate_due(now=after)
    assert out["decided"] > 0, "judging must not stop at the snapshot"
    assert out["opened"] > 0, "buying must not stop at the snapshot"

    live = list((await db_session.execute(
        select(LabPosition).where(LabPosition.opened_at > boundary)
    )).scalars())
    assert live, "positions opened after the boundary must exist"


async def test_no_strategy_is_deactivated_by_the_snapshot(db_session):
    svc = LabService(db_session)
    t = await svc.activate(valid_from=VALID_FROM)
    await leaderboard.build_snapshot(
        db_session, tournament=t, label="24H", boundary=t.snapshot_at, now=t.snapshot_at
    )
    rows = list((await db_session.execute(select(LabStrategy))).scalars())
    assert len(rows) == 20
    assert all(r.status == "active" for r in rows)
    assert t.status == "active"


async def test_a_snapshot_is_written_once_however_often_the_tick_runs(db_session):
    """A restart at the wrong moment must not produce a second, different 24h
    leaderboard, and a boundary crossed during downtime is still captured."""
    from app.lab import scheduler

    svc = LabService(db_session)
    t = await svc.activate(valid_from=VALID_FROM)
    late = t.snapshot_at + timedelta(hours=9)          # tick returns after downtime

    first = await scheduler._snapshots(db_session, t, late)
    second = await scheduler._snapshots(db_session, t, late)
    assert "24H" in first
    assert second == [], "a re-run must not rewrite a frozen snapshot"

    rows = list((await db_session.execute(
        select(LabSnapshot).where(LabSnapshot.label == "24H")
    )).scalars())
    assert len(rows) == 1
    # the boundary is the frozen instant, never the clock that happened to notice
    assert rows[0].boundary_at == t.snapshot_at
    assert rows[0].elapsed_hours == 24


async def test_the_thirty_day_boundary_is_scheduled(db_session):
    """The 30-day mark the operator cares about must exist as a real boundary."""
    from app.lab.scheduler import CALENDAR_SNAPSHOTS

    labels = dict(CALENDAR_SNAPSHOTS)
    assert labels["30D"] == 720
    assert labels["24H"] == 24
    assert "90D" in labels

    svc = LabService(db_session)
    t = await svc.activate(valid_from=VALID_FROM)
    from app.lab import scheduler
    written = await scheduler._snapshots(
        db_session, t, t.valid_from + timedelta(days=30, minutes=1)
    )
    assert "30D" in written and "24H" in written


# --- the trades view ---------------------------------------------------------
# This view exists so a reader can copy a contract address and check the token
# against the market. An abbreviated address would defeat the whole feature.

async def test_trades_return_the_full_untruncated_mint(db_session):
    from app.lab.api import trades

    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    mint = "T" + "r" * 20
    await _radar_token(db_session, mint=mint, detected=NOW - timedelta(hours=2),
                       liq=D("600000"), pool="POOLTRADE")
    await svc.evaluate_due(now=NOW)

    got = await trades(db_session, strategy_id=None, status=None, limit=500)
    assert got["trades"], "an opened position must appear in the trades view"
    for t in got["trades"]:
        assert t["mint"] == mint
        assert len(t["mint"]) == len(mint)
        assert "…" not in t["mint"] and "..." not in t["mint"]


async def test_trades_filter_by_strategy_and_status(db_session):
    from app.lab.api import trades

    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    await _radar_token(db_session, mint="T" + "f" * 20, detected=NOW - timedelta(hours=2),
                       liq=D("600000"), pool="POOLFILTER")
    await svc.evaluate_due(now=NOW)

    everything = await trades(db_session, strategy_id=None, status=None, limit=500)
    assert everything["total"] == everything["open"] + everything["closed"]

    one = await trades(db_session, strategy_id="v6-06", status=None, limit=500)
    assert one["trades"]
    assert {t["strategy_id"] for t in one["trades"]} == {"V6-06"}

    opens = await trades(db_session, strategy_id=None, status="open", limit=500)
    assert {t["status"] for t in opens["trades"]} == {"open"}
    closed = await trades(db_session, strategy_id=None, status="closed", limit=500)
    assert closed["trades"] == []


async def test_trades_report_sellable_value_not_cost(db_session):
    """An open position must be shown at what it could be sold for."""
    from app.lab.api import trades

    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    await _radar_token(db_session, mint="T" + "v" * 20, detected=NOW - timedelta(hours=2),
                       liq=D("600000"), pool="POOLVALUE")
    await svc.evaluate_due(now=NOW)
    # A fresh print, so the mark is allowed: the fixture's own series ends more
    # than 15 minutes back, and a stale print is deliberately not acted on.
    pos = (await db_session.execute(
        select(LabPosition).where(LabPosition.strategy_id == "V6-06")
    )).scalars().first()
    db_session.add(TokenMarketSnapshot(
        token_id=pos.token_id, mint_address=pos.mint_address,
        captured_at=NOW + timedelta(seconds=30), price_usd=D("0.001"),
        liquidity_usd=D("600000"), trading_status=TradingStatus.TRADING,
        provider="test", suspect=False,
    ))
    await db_session.flush()
    await svc.settle(now=NOW + timedelta(minutes=1))

    got = await trades(db_session, strategy_id="V6-06", status=None, limit=500)
    row = got["trades"][0]
    assert row["current_value_usd"] < row["size_usd"], (
        "a fresh position is worth less than it cost, because of impact and fees"
    )
    assert row["unrealised_pnl"] is not None
    assert row["realised_pnl"] is None
