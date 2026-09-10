"""DEX — is a DexScreener top gainer visible before it is one?

The board is a rear-view mirror and DexScreener publishes no gainers endpoint,
so this lab rebuilds the board's input from our own record and asks whether the
input predicts the board. The tests below defend the four things that would
quietly ruin that experiment, and profit is none of them:

* the pair is a CONTROLLED comparison — one condition apart, nothing else;
* the rule cannot fire on a turnover it has not actually measured;
* the candidate stream is the population the rule was measured on — any venue,
  above the liquidity floor, freshly printed;
* nothing banks the wallet, because a +10% portfolio target is a take-profit
  and this cohort's return is in the tail.

The third is the subtle one. `DEEP_AMM_VENUES` would exclude pump.swap, which
is where most of the 619 tokens that reached $100k in the measurement actually
trade — inheriting another lab's venue list "to stay comparable" is exactly the
mistake the Graduation Hold Lab made, and it changes the population under test
without changing a single visible rule.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from app.compound.service import CompoundService
from app.dexlab import spec as dxspec
from app.lab.service import LabService
from app.models.lab import LabDecision, LabStrategy
from app.models.market import TokenMarketSnapshot, TradingStatus
from app.models.token import DiscoveredToken
from tests.integration.test_lab_accounting import NOW

pytestmark = pytest.mark.integration

VALID_FROM = NOW - timedelta(days=1)


async def _priced_token(session, *, mint: str, dex: str, liq: D, vol_1h: D,
                        last_print_at=None, price: D = D("0.001")):
    """A token DexScreener has indexed with a pool, printed once."""
    at = last_print_at or NOW
    tok = DiscoveredToken(mint_address=mint, signature=f"sig-{uuid.uuid4()}", slot=1,
                          discovered_at=at - timedelta(hours=3),
                          source_program="pumpfun")
    session.add(tok)
    await session.flush()
    session.add(TokenMarketSnapshot(
        token_id=tok.id, mint_address=mint, captured_at=at,
        price_usd=price, liquidity_usd=liq, market_cap=liq * 8,
        volume_1h=vol_1h, volume_5m=vol_1h / 12, volume_24h=vol_1h * 6,
        buy_count_24h=400, sell_count_24h=300,
        trading_status=TradingStatus.TRADING, provider="test", suspect=False,
        dex_name=dex, pool_address=f"pool-{mint[:8]}",
    ))
    await session.flush()
    return tok


async def _rows(session):
    """Activate the tournament and hand back (tournament, strategy rows)."""
    tournament = await LabService(session, registry=dxspec).activate(
        valid_from=VALID_FROM)
    rows = list((await session.execute(
        select(LabStrategy).where(LabStrategy.tournament_id == tournament.id)
    )).scalars())
    return tournament, rows


async def _due(session, *, now=NOW, source="dexboard", limit=50):
    tournament, rows = await _rows(session)
    return await LabService(session, registry=dxspec)._due_candidates(
        tournament, minutes=5, ids=[r.id for r in rows],
        cutoff=now, limit=limit, source=source, now=now,
    )


# --------------------------------------------------------------------------
# one condition apart
# --------------------------------------------------------------------------

def test_the_two_wallets_differ_by_exactly_one_condition() -> None:
    signal, control = dxspec.STRATEGIES
    a = {str(c) for c in signal.entry}
    b = {str(c) for c in control.entry}
    assert b < a, "the control must be the signal MINUS one condition"
    assert len(a - b) == 1
    assert next(iter(a - b)).startswith("Condition(feature='turnover_1h'")


def test_nothing_but_the_entry_rule_varies() -> None:
    fixed = {
        (s.size_usd, s.max_concurrent, s.max_exposure_usd, s.checkpoint_minutes,
         s.exits.time_exit_hours, s.exits.take_profit, s.exits.stop_loss,
         s.exits.trailing_drawdown, s.exits.partial_at)
        for s in dxspec.STRATEGIES
    }
    assert len(fixed) == 1, "sizing that differed would confound rule with stake"


def test_the_floor_sits_in_the_flat_region_not_on_the_cliff() -> None:
    """2.0 is a threshold, not a fitted optimum.

    The measured mean was 1.16 at a floor of 0.25 and then 1.51 / 1.47 / 1.50 /
    1.51 / 1.42 from 1.0 to 20.0 — a cliff below and no gradient above. A floor
    tuned to the best decile boundary would be reading a gradient that is not
    there.
    """
    assert dxspec.TURNOVER_FLOOR == D("2.0")
    cond = [c for s in dxspec.STRATEGIES for c in s.entry
            if c.feature == "turnover_1h"]
    assert len(cond) == 1 and cond[0].op == "gte"


def test_it_is_a_separate_registry_from_every_other_tournament() -> None:
    from app.compound import spec as cspec
    from app.lab import spec as v7
    from app.matrix import spec as mxspec
    from app.movers import spec as mvspec
    from app.social import spec as sspec

    hashes = {dxspec.SPEC_HASH, cspec.SPEC_HASH, v7.SPEC_HASH,
              mxspec.SPEC_HASH, mvspec.SPEC_HASH, sspec.SPEC_HASH}
    assert len(hashes) == 6


# --------------------------------------------------------------------------
# it cannot fire on a number it has not measured
# --------------------------------------------------------------------------

def test_an_unmeasured_turnover_fails_the_signal_but_not_the_control() -> None:
    """Absent must mean NO.

    If a missing feature ever passed, DEX-01 would collapse into DEX-02 and the
    two wallets would be one experiment reported twice.
    """
    pool = {"liq": D("250000")}
    assert not all(c.evaluate(pool) for c in dxspec.BY_ID["DEX-01"].entry)
    assert all(c.evaluate(pool) for c in dxspec.BY_ID["DEX-02"].entry), (
        "the control must still take the coin — that is the comparison"
    )
    assert all(c.evaluate({**pool, "turnover_1h": D("2.5")})
               for c in dxspec.BY_ID["DEX-01"].entry)


def test_a_thin_token_is_refused_by_both_arms() -> None:
    thin = {"liq": D("99999"), "turnover_1h": D("50")}
    for s in dxspec.STRATEGIES:
        assert not all(c.evaluate(thin) for c in s.entry), s.id


async def test_turnover_1h_is_hourly_volume_over_liquidity(db_session):
    tok = await _priced_token(db_session, mint="D" + "1" * 20, dex="pumpswap",
                              liq=D("200000"), vol_1h=D("600000"))
    f, _ = await LabService(db_session, registry=dxspec).observe(
        token_id=tok.id, mint="D" + "1" * 20,
        detected_at=NOW - timedelta(minutes=5), checkpoint_at=NOW)
    assert f["turnover_1h"] == D(3), "600k of volume over 200k of liquidity"


async def test_turnover_is_absent_when_the_provider_reported_no_volume(db_session):
    """A missing figure must not read as zero-and-passing, nor as zero-and-
    failing by accident — it must simply not be there."""
    tok = await _priced_token(db_session, mint="D" + "2" * 20, dex="pumpswap",
                              liq=D("200000"), vol_1h=D("0"))
    await db_session.execute(
        TokenMarketSnapshot.__table__.update()
        .where(TokenMarketSnapshot.token_id == tok.id)
        .values(volume_1h=None))
    f, _ = await LabService(db_session, registry=dxspec).observe(
        token_id=tok.id, mint="D" + "2" * 20,
        detected_at=NOW - timedelta(minutes=5), checkpoint_at=NOW)
    assert "turnover_1h" not in f
    assert not all(c.evaluate(f) for c in dxspec.BY_ID["DEX-01"].entry)


# --------------------------------------------------------------------------
# the candidate stream is the population the rule was measured on
# --------------------------------------------------------------------------

async def test_the_stream_takes_pumpswap_which_a_deep_amm_venue_list_would_drop(db_session):
    """The whole reason `dexboard` exists rather than reusing `deepamm`."""
    await _priced_token(db_session, mint="D" + "3" * 20, dex="pumpswap",
                        liq=D("300000"), vol_1h=D("900000"))
    got = await _due(db_session)
    assert [r[1] for r in got] == ["D" + "3" * 20]

    assert dxspec.DEEP_VENUES == (), "empty on purpose — see the spec docstring"
    from app.universe import rules as universe_rules
    assert "pumpswap" not in universe_rules.DEEP_AMM_VENUES, (
        "if pump.swap is ever added to the deep list this lab's reason for a "
        "separate source changes, and the docstring must change with it"
    )


async def test_a_token_below_the_liquidity_floor_is_never_offered(db_session):
    await _priced_token(db_session, mint="D" + "4" * 20, dex="pumpswap",
                        liq=D("99000"), vol_1h=D("900000"))
    assert await _due(db_session) == []


async def test_a_stale_print_is_not_offered(db_session):
    """The position opens at the sampled print plus the checkpoint.

    A token nobody has polled for three hours would open three hours in the
    past and every clock exit would fire on the next settle, against a
    three-hour move dressed as a six-hour hold.
    """
    await _priced_token(db_session, mint="D" + "5" * 20, dex="pumpswap",
                        liq=D("300000"), vol_1h=D("900000"),
                        last_print_at=NOW - timedelta(hours=3))
    assert await _due(db_session) == []


async def test_a_declined_token_may_be_judged_again_after_the_cooldown(db_session):
    """Load-bearing in both directions.

    Without a cooldown a token declined at a quiet moment could never be caught
    during its burst — which is the entire hypothesis. With a shorter one the
    SAME `volume_1h` reading would be judged twice and counted as two draws.
    """
    assert dxspec.REJUDGE_BY_SOURCE == {"dexboard": timedelta(hours=1)}
    from app.matrix import spec as mxspec
    assert "dexboard" not in mxspec.REJUDGE_BY_SOURCE, (
        "the cooldown is keyed by SOURCE; sharing a source name would couple "
        "this lab's hourly re-judge to the Matrix Lab's six-hourly one"
    )

    mint = "D" + "6" * 20
    tok = await _priced_token(db_session, mint=mint, dex="pumpswap",
                              liq=D("300000"), vol_1h=D("900000"))
    _, strategies = await _rows(db_session)
    db_session.add(LabDecision(
        strategy_row_id=strategies[0].id, strategy_id=strategies[0].strategy_id,
        token_id=tok.id, mint_address=mint, checkpoint_minutes=5,
        checkpoint_at=NOW - timedelta(minutes=30),
        decided_at=NOW - timedelta(minutes=30),
        eligible=False, skip_reason="turnover_1h_below_2",
    ))
    await db_session.flush()

    assert [r[1] for r in await _due(db_session, now=NOW)] == [], "inside the hour"

    # The SAME token, printing again after the cooldown, is offered again.
    later = NOW + timedelta(hours=1, minutes=1)
    db_session.add(TokenMarketSnapshot(
        token_id=tok.id, mint_address=mint, captured_at=later,
        price_usd=D("0.001"), liquidity_usd=D("300000"), market_cap=D("2400000"),
        volume_1h=D("900000"), volume_5m=D("75000"), volume_24h=D("5400000"),
        buy_count_24h=400, sell_count_24h=300,
        trading_status=TradingStatus.TRADING, provider="test", suspect=False,
        dex_name="pumpswap", pool_address=f"pool-{mint[:8]}",
    ))
    await db_session.flush()
    assert [r[1] for r in await _due(db_session, now=later)] == [mint], (
        "a token declined once must be judgeable again during its burst — "
        "that is the entire hypothesis"
    )


# --------------------------------------------------------------------------
# nothing banks the wallet
# --------------------------------------------------------------------------

def test_the_ratchet_is_off_and_that_is_a_rule() -> None:
    """A +10% portfolio target is a take-profit applied to the whole book.

    Capping the signal arm at 2x took its measured mean from 1.472 to 1.149,
    and a +10% wallet target bites long before 2x on any single position.
    """
    assert dxspec.CYCLE_ENABLED is False
    assert all(s.exits.take_profit is None for s in dxspec.STRATEGIES)
    assert all(s.exits.stop_loss is None for s in dxspec.STRATEGIES), (
        "a fifth of these positions go to zero and stops on such tokens fill "
        "at about three cents"
    )


async def test_a_wallet_up_more_than_ten_percent_does_not_bank(db_session):
    _, rows = await _rows(db_session)
    rows[0].cash = D("140")
    await db_session.flush()
    out = await CompoundService(db_session, registry=dxspec).tick(now=NOW)
    assert not out.get("banked"), "the clock is the only exit here"


def test_the_book_is_five_dollars_twenty_ways() -> None:
    assert dxspec.STARTING_EQUITY == D("100")
    assert dxspec.SIZE_USD == D("5") and dxspec.MAX_CONCURRENT == 20
    assert dxspec.SIZE_USD * dxspec.MAX_CONCURRENT == dxspec.STARTING_EQUITY
    assert dxspec.SIZING_SCALES is False
    assert dxspec.TIME_EXIT_HOURS == 6.0


# --------------------------------------------------------------------------
# end to end: the comparison actually happens
# --------------------------------------------------------------------------

async def test_the_signal_skips_a_quiet_coin_that_the_control_buys(db_session):
    """One tick, two tokens, and the whole point of the pair in one assertion.

    A liquid coin trading a twentieth of its liquidity is refused by DEX-01 and
    taken by DEX-02; a liquid coin trading three times its liquidity is taken by
    both. If this ever came out with both arms holding the same book, the
    experiment would be one wallet reported twice and nobody would see it on
    the board.
    """
    quiet = "D" + "8" * 20
    busy = "D" + "9" * 20
    # Judged at +5 min, so the print has to sit a checkpoint in the past.
    printed = NOW - timedelta(minutes=5)
    await _priced_token(db_session, mint=quiet, dex="pumpswap",
                        liq=D("400000"), vol_1h=D("20000"), last_print_at=printed)
    await _priced_token(db_session, mint=busy, dex="pumpswap",
                        liq=D("400000"), vol_1h=D("1200000"), last_print_at=printed)

    await LabService(db_session, registry=dxspec).activate(
        valid_from=NOW - timedelta(hours=1))
    out = await LabService(db_session, registry=dxspec).evaluate_due(now=NOW)
    assert out["decided"] == 4, "two tokens x two arms"

    decisions = list((await db_session.execute(select(LabDecision))).scalars())
    taken = {(d.strategy_id, d.mint_address) for d in decisions if d.eligible}
    assert ("DEX-01", busy) in taken
    assert ("DEX-02", busy) in taken
    assert ("DEX-02", quiet) in taken
    assert ("DEX-01", quiet) not in taken

    skipped = next(d for d in decisions
                   if d.strategy_id == "DEX-01" and d.mint_address == quiet)
    assert skipped.skip_reason == "turnover_1h_below_2", (
        "a skip must name the measured cause, not a vague one"
    )
    assert skipped.features["turnover_1h"] == "0.05"


async def test_the_hq_probe_can_read_this_lab(db_session):
    """`LAB_REGISTRIES` is one of the three places a lab must be registered.

    Missing here, the lab trades but HQ reports nothing about it — the failure
    mode is silence, which looks exactly like a quiet market.
    """
    from app.hq_ops.probe import LAB_REGISTRIES
    from app.lab.health import read

    assert ("Dex", "app.dexlab.spec", "FEATURE_DEX_LAB_ENABLED") in LAB_REGISTRIES

    await LabService(db_session, registry=dxspec).activate(valid_from=VALID_FROM)
    reading = await read(db_session, now=NOW, registry=dxspec)
    assert reading.as_dict()["spec_version"] == dxspec.SPEC_VERSION
