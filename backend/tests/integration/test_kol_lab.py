"""The KOL Lab: the ranking is point-in-time, and the filter actually gates.

The property this file exists to protect is that a wallet is never scored on
the trades that selected it. Everything else here is scaffolding around that.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from app.compound.service import CompoundService
from app.kol import ranking
from app.kol import spec as kspec
from app.kol.scheduler import MIN_RANKED_WALLETS, freeze_ranking
from app.lab.service import LabService
from app.models.early_buyer import TokenEarlyBuyer
from app.models.kol import KolWalletRank
from app.models.lab import LabPosition, LabStrategy, LabTournament
from app.models.market import TokenMarketSnapshot, TradingStatus
from tests.integration.test_lab_accounting import NOW, _radar_token

pytestmark = pytest.mark.integration

PUMPFUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"


async def _coin(db_session, mint: str, *, detected, ran: bool):
    """A coin that either doubled after its early buy, or did not."""
    tok = await _radar_token(db_session, mint=mint, detected=detected,
                             liq=D("600000"), price=D("0.001"),
                             pool="P" + mint[:6])
    tok.source_program = PUMPFUN_PROGRAM
    if ran:
        db_session.add(TokenMarketSnapshot(
            token_id=tok.id, mint_address=mint,
            captured_at=detected + timedelta(minutes=20),
            price_usd=D("0.005"), liquidity_usd=D("600000"),
            market_cap=D("6000000"), volume_1h=D("100000"), volume_5m=D("10000"),
            buy_count_24h=200, sell_count_24h=90,
            trading_status=TradingStatus.TRADING, provider="test", suspect=False,
            pool_address="P" + mint[:6],
        ))
    await db_session.flush()
    return tok


async def _early(db_session, mint: str, wallet: str, *, at):
    db_session.add(TokenEarlyBuyer(mint_address=mint, wallet_address=wallet,
                                   bought_at=at, buy_rank=1))
    await db_session.flush()


async def test_the_ranking_reads_nothing_after_as_of(db_session):
    """THE property. A wallet scored on trades that happened after the cutoff
    is scored on the very evidence the lab is supposed to be testing, which is
    the selection trap that produced four false edges here."""
    old = NOW - timedelta(days=2)
    future = NOW + timedelta(days=1)

    # Five winners BEFORE the cutoff, all bought by `past`.
    for i in range(5):
        mint = f"KolPast{i:02d}" + "a" * 26
        await _coin(db_session, mint, detected=old, ran=True)
        await _early(db_session, mint, "past_wallet", at=old + timedelta(minutes=1))
    # Five winners AFTER it, all bought by `future`.
    for i in range(5):
        mint = f"KolFut{i:02d}" + "b" * 27
        await _coin(db_session, mint, detected=future, ran=True)
        await _early(db_session, mint, "future_wallet",
                     at=future + timedelta(minutes=1))

    ranked = await ranking.rank(db_session, as_of=NOW, min_buys=5)
    names = {r.wallet_address for r in ranked}

    assert "past_wallet" in names
    assert "future_wallet" not in names, (
        "a wallet whose entire record is after the cutoff must be invisible"
    )


async def test_a_wallet_below_the_sample_floor_is_not_ranked(db_session):
    """Two early buys that both ran is a 100% hit rate and means nothing;
    across thousands of wallets some will hit five in a row by chance."""
    old = NOW - timedelta(days=2)
    for i in range(2):
        mint = f"KolThin{i:02d}" + "c" * 26
        await _coin(db_session, mint, detected=old, ran=True)
        await _early(db_session, mint, "lucky", at=old + timedelta(minutes=1))

    ranked = await ranking.rank(db_session, as_of=NOW, min_buys=5)
    assert "lucky" not in {r.wallet_address for r in ranked}


async def test_a_coin_that_never_ran_is_not_a_hit(db_session):
    """And a coin we could never price is not one either — counting it would
    reward wallets for buying things that went dark."""
    old = NOW - timedelta(days=2)
    for i in range(6):
        mint = f"KolDud{i:02d}" + "d" * 27
        await _coin(db_session, mint, detected=old, ran=False)
        await _early(db_session, mint, "dud_wallet", at=old + timedelta(minutes=1))

    ranked = await ranking.rank(db_session, as_of=NOW, min_buys=5)
    row = next((r for r in ranked if r.wallet_address == "dud_wallet"), None)
    assert row is not None and row.hits == 0 and row.hit_rate == 0.0


async def test_it_refuses_to_open_a_tournament_without_enough_wallets(db_session):
    """Opening early would freeze `valid_from` — which can never move —
    against wallets chosen from an afternoon of data, spending the experiment
    to save a week."""
    written = await freeze_ranking(db_session, now=NOW)
    assert written == 0

    rows = list((await db_session.execute(select(KolWalletRank))).scalars())
    assert rows == []


async def test_a_frozen_ranking_is_never_recomputed(db_session):
    """The whole claim is that THESE wallets, chosen on THIS date, keep
    hitting. Refreshing the list would quietly restate the claim."""
    old = NOW - timedelta(days=2)
    for w in range(MIN_RANKED_WALLETS):
        for i in range(5):
            mint = f"K{w:02d}m{i:02d}" + "e" * 28
            await _coin(db_session, mint, detected=old, ran=True)
            await _early(db_session, mint, f"wallet{w:02d}",
                         at=old + timedelta(minutes=1))

    first = await freeze_ranking(db_session, now=NOW)
    assert first >= MIN_RANKED_WALLETS
    frozen_at = (await db_session.execute(
        select(KolWalletRank.computed_at).limit(1)
    )).scalar_one()

    again = await freeze_ranking(db_session, now=NOW + timedelta(days=1))
    assert again == 0, "a second freeze must be a no-op"
    still = (await db_session.execute(
        select(KolWalletRank.computed_at).limit(1)
    )).scalar_one()
    assert still == frozen_at


async def test_the_filter_gates_the_signal_arm_but_not_the_control(db_session):
    """Behaviour, not configuration: the control takes a coin no followed
    wallet touched, and the signal declines it by name."""
    svc = CompoundService(db_session, registry=kspec)
    await svc._lab.activate(valid_from=NOW - timedelta(minutes=15))
    # A ranking exists, but not for anyone who bought this coin.
    db_session.add(KolWalletRank(
        spec_version=kspec.SPEC_VERSION, computed_at=NOW - timedelta(days=1),
        wallet_address="someone_else", rank=1, early_buys=10, hits=7,
        hit_rate=0.7))
    await db_session.flush()

    await _coin(db_session, "KolUntouched" + "f" * 20,
                detected=NOW - timedelta(minutes=11), ran=False)
    await svc.tick(now=NOW)

    def rows(sid):
        return select(LabPosition).join(
            LabStrategy, LabStrategy.id == LabPosition.strategy_row_id
        ).join(LabTournament, LabTournament.id == LabStrategy.tournament_id).where(
            LabTournament.spec_version == kspec.SPEC_VERSION,
            LabPosition.strategy_id == sid)

    signal = list((await db_session.execute(rows("KOL-01"))).scalars())
    control = list((await db_session.execute(rows("KOL-02"))).scalars())
    assert control, "the control must take what the signal declines"
    assert not signal


async def test_the_signal_arm_takes_a_coin_a_followed_wallet_bought(db_session):
    """The mirror, without which the test above passes for the wrong reason."""
    svc = CompoundService(db_session, registry=kspec)
    await svc._lab.activate(valid_from=NOW - timedelta(minutes=15))
    mint = "KolFollowed" + "g" * 21
    db_session.add(KolWalletRank(
        spec_version=kspec.SPEC_VERSION, computed_at=NOW - timedelta(days=1),
        wallet_address="followed_one", rank=1, early_buys=10, hits=7,
        hit_rate=0.7))
    await _coin(db_session, mint, detected=NOW - timedelta(minutes=11), ran=False)
    await _early(db_session, mint, "followed_one", at=NOW - timedelta(minutes=11))

    await svc.tick(now=NOW)

    signal = list((await db_session.execute(
        select(LabPosition).join(
            LabStrategy, LabStrategy.id == LabPosition.strategy_row_id
        ).join(LabTournament, LabTournament.id == LabStrategy.tournament_id).where(
            LabTournament.spec_version == kspec.SPEC_VERSION,
            LabPosition.strategy_id == "KOL-01")
    )).scalars())
    assert signal, "a coin a followed wallet bought first must be taken"


async def test_the_feature_is_scoped_to_this_registry(db_session):
    """Two KOL tournaments with different frozen rankings must not read each
    other's wallets — the same scoping bug that once let one lab settle
    another's book."""
    mint = "KolScoped" + "h" * 23
    await _coin(db_session, mint, detected=NOW - timedelta(minutes=11), ran=False)
    await _early(db_session, mint, "other_labs_wallet", at=NOW - timedelta(minutes=11))
    db_session.add(KolWalletRank(
        spec_version="kol-9.9.9", computed_at=NOW - timedelta(days=1),
        wallet_address="other_labs_wallet", rank=1, early_buys=10, hits=9,
        hit_rate=0.9))
    await db_session.flush()

    svc = LabService(db_session, registry=kspec)
    assert await svc._kol_early_count(mint) == 0
