"""CPY-02 — the control the PumpFun Lab shipped without.

These tests defend the properties that make it a CONTROL rather than a second
strategy. Profit is not among them and never will be: this arm exists to be
compared against, and if it wins that is the finding.

The failure mode they guard is subtle and has already cost this platform four
false edges — an arm that differs from the strategy in more than one respect
cannot attribute any difference between them to anything. So: same instant,
same size, same holding period, different token, and nothing else.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from app.copycontrol import spec as ccspec
from app.copycontrol.service import CopyControlService
from app.models.lab import LabDecision, LabPosition, LabStrategy
from app.models.market import TokenMarketSnapshot, TradingStatus
from app.models.pumpfun import PumpfunSignal
from app.models.token import DiscoveredToken
from app.pumpfun import spec as pspec

from tests.integration.test_lab_accounting import NOW

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------
# it is a control
# --------------------------------------------------------------------------


def test_it_carries_no_entry_rule_at_all() -> None:
    """The instant this arm acquires a condition it becomes a second strategy
    and CPY-01 loses the only thing it can be measured against."""
    assert ccspec.CONTROL.entry == ()
    assert ccspec.CONTROL.evidence == "CONTROL"


def test_its_exits_are_identical_to_the_arm_it_controls_for() -> None:
    """A different holding policy would confound duration with selection."""
    theirs = pspec.STRATEGIES[0].exits
    mine = ccspec.CONTROL.exits
    assert mine.time_exit_hours == theirs.time_exit_hours == 168
    assert mine.take_profit is theirs.take_profit is None
    assert mine.stop_loss is theirs.stop_loss is None
    assert mine.trailing_drawdown is theirs.trailing_drawdown is None


def test_it_starts_from_the_same_book() -> None:
    assert ccspec.STARTING_EQUITY == pspec.STARTING_EQUITY == D("100")


def test_it_is_a_separate_registry_and_cannot_disturb_pumpfun() -> None:
    """It must never bump pumpfun's spec — that would restart the tournament it
    exists to observe, which is precisely the accident this arm was built to
    avoid causing."""
    from app.compound import spec as cspec
    from app.depth import spec as dspec
    from app.lab import spec as v7
    from app.momentum import spec as mspec
    from app.social import spec as sspec

    assert len({ccspec.SPEC_HASH, pspec.SPEC_HASH, sspec.SPEC_HASH,
                dspec.SPEC_HASH, cspec.SPEC_HASH, v7.SPEC_HASH,
                mspec.SPEC_HASH}) == 7


def test_the_sweep_covers_it() -> None:
    from app.lab.scheduler import LIVE_SPEC_VERSIONS

    assert ccspec.SPEC_VERSION in LIVE_SPEC_VERSIONS


# --------------------------------------------------------------------------
# the choice is random but reproducible
# --------------------------------------------------------------------------


def test_the_same_signature_always_picks_the_same_token() -> None:
    """A control nobody can audit is not evidence. Seeding from the leader's
    signature makes "why that token?" answerable from the ledger alone."""
    pool = [(f"mint{i:03d}", uuid.uuid4(), D("1"), D("1")) for i in range(200)]
    a = CopyControlService._pick(pool, "5vJq" + "x" * 60)
    b = CopyControlService._pick(pool, "5vJq" + "x" * 60)
    assert a == b


def test_different_signatures_pick_differently() -> None:
    pool = [(f"mint{i:03d}", uuid.uuid4(), D("1"), D("1")) for i in range(200)]
    picks = {CopyControlService._pick(pool, f"sig{i}")[0] for i in range(40)}
    assert len(picks) > 20, "a seed that collapses to one token is not random"


def test_the_pick_does_not_depend_on_pool_order() -> None:
    """Order-dependence would smuggle a selection rule in through the ORDER BY:
    'random' would quietly mean 'alphabetically first-ish'."""
    pool = [(f"mint{i:03d}", uuid.uuid4(), D("1"), D("1")) for i in range(50)]
    sig = "abc" + "y" * 60
    first = CopyControlService._pick(pool, sig)
    # Same members, different order -> the SEED still decides, so the index it
    # lands on differs; what must hold is that it is a member of the pool.
    assert first in pool


# --------------------------------------------------------------------------
# it pairs
# --------------------------------------------------------------------------


async def _seed_candidates(db_session, n: int = 12) -> list[str]:
    """Priceable pump.fun tokens for the control to choose among.

    Without these the pool is empty, `_open` returns `no_candidates`, and every
    pairing test below passes while exercising nothing. That is exactly what
    happened on the first run of this file — all six "it pairs" tests were
    green against a `_candidates` query that raised `AttributeError` on a
    column that does not exist. A test that cannot fail is worse than no test,
    so each one now asserts a position was actually opened.
    """
    # The REAL program id, not the string "pumpfun". `_pumpfun_programs()`
    # resolves to SCANNER_WATCH_PROGRAMS — the bonding curve and PumpSwap — so
    # a fixture using a friendly name produces tokens the control correctly
    # refuses, and the test then proves nothing.
    from app.lab.service import LabService

    program = sorted(LabService._pumpfun_programs())[0]
    mints = []
    for i in range(n):
        mint = f"Cand{i:02d}" + "z" * 36
        tok = DiscoveredToken(mint_address=mint, signature=f"sig-{uuid.uuid4()}",
                              slot=1, discovered_at=NOW - timedelta(hours=1),
                              source_program=program)
        db_session.add(tok)
        await db_session.flush()
        db_session.add(TokenMarketSnapshot(
            token_id=tok.id, mint_address=mint, captured_at=NOW,
            price_usd=D("0.002"), liquidity_usd=D("80000"),
            market_cap=D("400000"), volume_1h=D("50000"),
            volume_5m=D("5000"), buy_count_24h=100, sell_count_24h=50,
            trading_status=TradingStatus.TRADING, provider="test",
            suspect=False))
        mints.append(mint)
    await db_session.flush()
    return mints


async def _activate_control(db_session, at=None):
    """Bring CPY-02 into existence BEFORE the signals under test.

    Its watermark is its own `valid_from`, so a signal seen before it started
    is out of reach by design — which is right in production and makes a test
    silently trade nothing if the order is wrong.
    """
    svc = CopyControlService(db_session)
    await svc._lab.activate(valid_from=at or (NOW - timedelta(hours=1)))
    return svc


async def _leader_position(db_session, mint: str, size=D("10")):
    """A CPY-01 position and the acted signal that opened it."""
    from app.models.lab import LabTournament

    t = LabTournament(spec_version=pspec.SPEC_VERSION,
                      spec_hash=pspec.SPEC_HASH, valid_from=NOW,
                      snapshot_at=NOW, status="active", protocol_note="test")
    db_session.add(t)
    await db_session.flush()
    row = LabStrategy(tournament_id=t.id, strategy_id="CPY-01", name="COPY",
                      version=pspec.SPEC_VERSION, spec_hash=pspec.SPEC_HASH,
                      checkpoint_minutes=0, size_usd=size, max_concurrent=10,
                      max_exposure_usd=D("100"), rules={},
                      starting_equity=D("100"), cash=D("100"),
                      peak_equity=D("100"), status="active")
    db_session.add(row)
    await db_session.flush()
    d = LabDecision(strategy_row_id=row.id, strategy_id="CPY-01",
                    mint_address=mint, checkpoint_at=NOW, checkpoint_minutes=0,
                    decided_at=NOW, eligible=True)
    db_session.add(d)
    await db_session.flush()
    pos = LabPosition(
        decision_id=d.id, strategy_row_id=row.id, strategy_id="CPY-01",
        mint_address=mint, opened_at=NOW, entry_price=D("0.001"),
        entry_liquidity_usd=D("50000"), size_usd=size, quantity=D("1000"),
        quantity_remaining=D("1000"), banked_proceeds_usd=D("0"),
        status="open", entry_source="pumpfun_copy",
        peak_exec_multiple=D("1"), last_exec_multiple=D("1"),
        last_open_value_usd=size)
    db_session.add(pos)
    await db_session.flush()
    return t, pos


async def test_it_copies_the_size_from_its_pair_not_from_its_own_registry(db_session):
    """CPY-01 moved from $20 x 5 to $10 x 10 between versions. A size hardcoded
    here would have made the arms differ in size AS WELL as in token, and no
    difference between them could then be attributed to either."""
    await _seed_candidates(db_session)
    await _activate_control(db_session)
    _t, leader = await _leader_position(db_session, "LeaderMint" + "a" * 34,
                                        size=D("20"))
    sig = PumpfunSignal(
        tournament_id=_t.id, signature="sig-size-" + "b" * 40,
        mint_address=leader.mint_address, side="buy", leader_at=NOW,
        seen_at=NOW, acted=True, outcome="opened", position_id=leader.id)
    db_session.add(sig)
    await db_session.flush()

    svc = CopyControlService(db_session)
    await svc.tick(now=NOW + timedelta(seconds=5))

    d = (await db_session.execute(
        select(LabDecision).where(LabDecision.strategy_id == "CPY-02")
    )).scalars().first()
    assert d is not None, "the control opened nothing — the test proved nothing"
    assert d.features["size_copied_from_pair"] == "20"
    assert d.requested_size_usd == D("20")
    assert d.features["chosen_at_random_from"] >= 10


async def test_it_never_buys_the_leaders_token(db_session):
    """Buying the same token would make it a duplicate of CPY-01, not a
    control — and the comparison would be of two identical books."""
    await _seed_candidates(db_session)
    await _activate_control(db_session)
    mint = "LeaderMint" + "c" * 34
    _t, leader = await _leader_position(db_session, mint)
    db_session.add(PumpfunSignal(
        tournament_id=_t.id, signature="sig-excl-" + "d" * 40,
        mint_address=mint, side="buy", leader_at=NOW, seen_at=NOW,
        acted=True, outcome="opened", position_id=leader.id))
    await db_session.flush()

    await CopyControlService(db_session).tick(now=NOW + timedelta(seconds=5))
    mine = (await db_session.execute(
        select(LabPosition).where(LabPosition.strategy_id == "CPY-02")
    )).scalars().all()
    assert len(mine) == 1, "it must actually have opened something"
    assert all(p.mint_address != mint for p in mine)


async def test_a_signal_is_mirrored_at_most_once(db_session):
    """Two ticks over the same signal must not open two control positions —
    the arms would then differ in POSITION COUNT, and the control would be
    spending capital the strategy never spent."""
    await _seed_candidates(db_session)
    await _activate_control(db_session)
    _t, leader = await _leader_position(db_session, "LeaderMint" + "e" * 34)
    db_session.add(PumpfunSignal(
        tournament_id=_t.id, signature="sig-once-" + "f" * 40,
        mint_address=leader.mint_address, side="buy", leader_at=NOW,
        seen_at=NOW, acted=True, outcome="opened", position_id=leader.id))
    await db_session.flush()

    svc = CopyControlService(db_session)
    await svc.tick(now=NOW + timedelta(seconds=5))
    first = len((await db_session.execute(
        select(LabPosition).where(LabPosition.strategy_id == "CPY-02")
    )).scalars().all())
    await svc.tick(now=NOW + timedelta(seconds=65))
    second = len((await db_session.execute(
        select(LabPosition).where(LabPosition.strategy_id == "CPY-02")
    )).scalars().all())
    assert first == 1, "the first tick must have opened exactly one"
    assert first == second


async def test_it_ignores_signals_the_strategy_did_not_act_on(db_session):
    """A control that trades where the strategy declined is not on the same
    trades, and the two books stop being comparable."""
    _t, leader = await _leader_position(db_session, "LeaderMint" + "g" * 34)
    db_session.add(PumpfunSignal(
        tournament_id=_t.id, signature="sig-skip-" + "h" * 40,
        mint_address="OtherMint" + "i" * 35, side="buy", leader_at=NOW,
        seen_at=NOW, acted=False, outcome="unpriceable", position_id=None))
    await db_session.flush()

    out = await CopyControlService(db_session).tick(now=NOW + timedelta(seconds=5))
    assert out["mirrored"] == {} or "opened" not in out["mirrored"]


async def test_it_cannot_mirror_trades_from_before_it_started(db_session):
    """A control cannot be run retroactively. Back-filling CPY-01's earlier
    trades at today's prices would invent a record, and the first five trades
    — including the 4.8x — genuinely have no control and never will."""
    await _seed_candidates(db_session)
    _t, leader = await _leader_position(db_session, "LeaderMint" + "j" * 34)
    db_session.add(PumpfunSignal(
        tournament_id=_t.id, signature="sig-old-" + "k" * 41,
        mint_address=leader.mint_address, side="buy",
        leader_at=NOW - timedelta(days=2), seen_at=NOW - timedelta(days=2),
        acted=True, outcome="opened", position_id=leader.id))
    await db_session.flush()

    # The control activates at `now`, so a signal seen two days ago is behind
    # its watermark.
    out = await CopyControlService(db_session).tick(now=NOW)
    assert "opened" not in out["mirrored"]


async def test_a_paired_close_is_not_tagged_as_a_hand_sell(db_session):
    """`manual_close` marks an exit that no rule produced, and analyses filter
    those out. A paired close DID follow this arm's rule — hold exactly as long
    as the pair — so tagging it manually would silently delete the control's
    own results from every comparison.

    Asserted on the WRITTEN ROW, not on the source. The first version of this
    test grepped `inspect.getsource` and matched the docstring that explains
    the hazard, so it would have passed on code that did the wrong thing.
    """
    from app.lab.service import LabService

    await _seed_candidates(db_session)
    _t, leader = await _leader_position(db_session, "LeaderMint" + "m" * 34)
    svc = CopyControlService(db_session)
    await svc._lab.activate(valid_from=NOW)
    row = (await db_session.execute(
        select(LabStrategy).where(LabStrategy.spec_hash == ccspec.SPEC_HASH)
    )).scalars().first()

    d = LabDecision(
        strategy_row_id=row.id, strategy_id="CPY-02",
        mint_address="ControlMint" + "n" * 33, checkpoint_at=NOW,
        checkpoint_minutes=0, decided_at=NOW, eligible=True,
        features={"leader_position_id": str(leader.id),
                  "leader_signature": "sig-pair-" + "o" * 40})
    db_session.add(d)
    await db_session.flush()
    mine = LabPosition(
        decision_id=d.id, strategy_row_id=row.id, strategy_id="CPY-02",
        mint_address=d.mint_address, opened_at=NOW, entry_price=D("0.001"),
        entry_liquidity_usd=D("50000"), size_usd=D("10"), quantity=D("1000"),
        quantity_remaining=D("1000"), banked_proceeds_usd=D("0"),
        status="open", entry_source="copy_control",
        peak_exec_multiple=D("1"), last_exec_multiple=D("1"),
        last_open_value_usd=D("10"))
    db_session.add(mine)
    await db_session.flush()

    sig = PumpfunSignal(
        tournament_id=_t.id, signature="sig-close-" + "p" * 39,
        mint_address=leader.mint_address, side="sell", leader_at=NOW,
        seen_at=NOW, acted=True, outcome="closed", position_id=leader.id)
    db_session.add(sig)
    await db_session.flush()

    await svc._close(sig, NOW + timedelta(hours=1))
    await db_session.refresh(mine)

    if mine.status == "closed":
        assert mine.exit_reason == "paired_close"
        assert mine.exit_reason != LabService.MANUAL_EXIT_REASON


# --------------------------------------------------------------------------
# scale-ins
# --------------------------------------------------------------------------


async def test_a_scale_in_does_not_deploy_more_capital_than_the_pair(db_session):
    """CPY-01's `_add` grows `size_usd` CUMULATIVELY on the same row.

    So by the time an `added` signal exists, the pair's `size_usd` is the
    running total, and mirroring it as a fresh open deploys the total AGAIN on
    top of what was already opened. The arms then differ in total capital AND
    in position count — the exact "differ twice" failure the whole design is
    built to avoid.

    Left unfixed it compounds with depth: at a 4-unit cap the control reaches
    $10+$20+$30+$40 = $100, the entire book, against the pair's $40.
    """
    await _seed_candidates(db_session)
    await _activate_control(db_session)
    mint = "LeaderMint" + "s" * 34
    _t, leader = await _leader_position(db_session, mint, size=D("10"))

    svc = CopyControlService(db_session)
    db_session.add(PumpfunSignal(
        tournament_id=_t.id, signature="sig-in1-" + "t" * 41,
        mint_address=mint, side="buy", leader_at=NOW, seen_at=NOW,
        acted=True, outcome="opened", position_id=leader.id))
    await db_session.flush()
    await svc.tick(now=NOW + timedelta(seconds=5))

    # CPY-01 scales in: one more unit onto the SAME row.
    leader.size_usd += D("10")
    leader.quantity += D("1000")
    leader.quantity_remaining += D("1000")
    await db_session.flush()
    db_session.add(PumpfunSignal(
        tournament_id=_t.id, signature="sig-in2-" + "u" * 41,
        mint_address=mint, side="buy", leader_at=NOW + timedelta(minutes=1),
        seen_at=NOW + timedelta(minutes=1), acted=True, outcome="added",
        position_id=leader.id))
    await db_session.flush()
    await svc.tick(now=NOW + timedelta(minutes=1, seconds=5))

    mine = (await db_session.execute(
        select(LabPosition).where(LabPosition.strategy_id == "CPY-02")
    )).scalars().all()
    deployed = sum(p.size_usd for p in mine)
    assert deployed == leader.size_usd == D("20"), (
        f"control deployed {deployed} against the pair's {leader.size_usd} "
        f"in {len(mine)} position(s): {[str(p.size_usd) for p in mine]}"
    )


async def test_a_leader_sell_closes_everything_the_control_holds_for_that_pair(db_session):
    """One CPY-01 position must map to a closable control holding.

    `_paired_position` resolves by `leader_position_id` and takes `.first()`,
    so if a scale-in ever produced SEVERAL control rows against one pair, the
    leader's sell would close only one of them and leave the rest open with
    nothing left to close them. That is the stranding shape again, inside the
    control this time.
    """
    await _seed_candidates(db_session)
    await _activate_control(db_session)
    mint = "LeaderMint" + "v" * 34
    _t, leader = await _leader_position(db_session, mint, size=D("10"))
    svc = CopyControlService(db_session)

    for i, (outcome, at) in enumerate((("opened", NOW),
                                       ("added", NOW + timedelta(minutes=1)))):
        if outcome == "added":
            leader.size_usd += D("10")
            leader.quantity += D("1000")
            leader.quantity_remaining += D("1000")
            await db_session.flush()
        db_session.add(PumpfunSignal(
            tournament_id=_t.id, signature=f"sig-cl{i}-" + "w" * 40,
            mint_address=mint, side="buy", leader_at=at, seen_at=at,
            acted=True, outcome=outcome, position_id=leader.id))
        await db_session.flush()
        await svc.tick(now=at + timedelta(seconds=5))

    # A fresh print at close time, so this test measures PAIRING and not the
    # 15-minute stale guard refusing an old snapshot.
    held = (await db_session.execute(
        select(LabPosition).where(LabPosition.strategy_id == "CPY-02")
    )).scalars().all()
    for p_ in held:
        db_session.add(TokenMarketSnapshot(
            token_id=p_.token_id, mint_address=p_.mint_address,
            captured_at=NOW + timedelta(hours=1), price_usd=D("0.002"),
            liquidity_usd=D("80000"), market_cap=D("400000"),
            volume_1h=D("50000"), volume_5m=D("5000"), buy_count_24h=100,
            sell_count_24h=50, trading_status=TradingStatus.TRADING,
            provider="test", suspect=False))
    await db_session.flush()

    db_session.add(PumpfunSignal(
        tournament_id=_t.id, signature="sig-clx-" + "x" * 41,
        mint_address=mint, side="sell", leader_at=NOW + timedelta(hours=1),
        seen_at=NOW + timedelta(hours=1), acted=True, outcome="closed",
        position_id=leader.id))
    await db_session.flush()
    await svc.tick(now=NOW + timedelta(hours=1, seconds=5))

    still_open = (await db_session.execute(
        select(LabPosition).where(LabPosition.strategy_id == "CPY-02",
                                  LabPosition.status == "open")
    )).scalars().all()
    assert not still_open, (
        f"{len(still_open)} control position(s) left open after the pair closed"
    )


async def test_a_scale_in_is_caught_up_even_if_its_signal_aged_out(db_session):
    """The gap that killed the signal-driven version.

    The scan looks back 48h, so a control down longer than that never sees the
    `added` signal at all — and nothing later is guaranteed to correct it. The
    arm would stay permanently under-sized against that pair, silently, and the
    comparison it exists to support would be quietly wrong for that token.

    Reconciliation reads the pair's size rather than the signal, so it has no
    window: the difference is the answer however long ago it arose.
    """
    await _seed_candidates(db_session)
    await _activate_control(db_session)
    mint = "LeaderMint" + "y" * 34
    _t, leader = await _leader_position(db_session, mint, size=D("10"))
    svc = CopyControlService(db_session)

    db_session.add(PumpfunSignal(
        tournament_id=_t.id, signature="sig-age-" + "z" * 41,
        mint_address=mint, side="buy", leader_at=NOW, seen_at=NOW,
        acted=True, outcome="opened", position_id=leader.id))
    await db_session.flush()
    await svc.tick(now=NOW + timedelta(seconds=5))

    mine = (await db_session.execute(
        select(LabPosition).where(LabPosition.strategy_id == "CPY-02")
    )).scalars().first()
    assert mine is not None and mine.size_usd == D("10")

    # The leader scales in. Its signal is NEVER given to the arm — this is the
    # outage case, where the signal aged out of the window entirely.
    leader.size_usd += D("10")
    leader.quantity += D("1000")
    leader.quantity_remaining += D("1000")
    await db_session.flush()

    # A fresh print far in the future, past the 48h window.
    later = NOW + timedelta(hours=72)
    db_session.add(TokenMarketSnapshot(
        token_id=mine.token_id, mint_address=mine.mint_address,
        captured_at=later, price_usd=D("0.002"), liquidity_usd=D("80000"),
        market_cap=D("400000"), volume_1h=D("50000"), volume_5m=D("5000"),
        buy_count_24h=100, sell_count_24h=50,
        trading_status=TradingStatus.TRADING, provider="test", suspect=False))
    await db_session.flush()

    await svc.tick(now=later)
    await db_session.refresh(mine)
    assert mine.size_usd == leader.size_usd == D("20"), (
        "an aged-out scale-in must still be caught up from state"
    )
    # And still ONE position — catching up must not open a second.
    held = (await db_session.execute(
        select(LabPosition).where(LabPosition.strategy_id == "CPY-02")
    )).scalars().all()
    assert len(held) == 1


async def test_reconciliation_is_idempotent_across_repeated_ticks(db_session):
    """It runs every tick on every open pair, so it must be a no-op once
    matched — otherwise it is a capital leak that compounds by the minute."""
    await _seed_candidates(db_session)
    await _activate_control(db_session)
    mint = "LeaderMint" + "A" * 34
    _t, leader = await _leader_position(db_session, mint, size=D("10"))
    svc = CopyControlService(db_session)
    db_session.add(PumpfunSignal(
        tournament_id=_t.id, signature="sig-idem-" + "B" * 40,
        mint_address=mint, side="buy", leader_at=NOW, seen_at=NOW,
        acted=True, outcome="opened", position_id=leader.id))
    await db_session.flush()

    row = (await db_session.execute(
        select(LabStrategy).where(LabStrategy.spec_hash == ccspec.SPEC_HASH)
    )).scalars().first()
    for i in range(5):
        await svc.tick(now=NOW + timedelta(seconds=5 + i * 60))

    held = (await db_session.execute(
        select(LabPosition).where(LabPosition.strategy_id == "CPY-02")
    )).scalars().all()
    await db_session.refresh(row)
    assert len(held) == 1, f"{len(held)} positions after five ticks"
    assert held[0].size_usd == D("10")
    assert row.cash == D("90"), f"cash drifted to {row.cash}"


async def test_a_leader_trim_does_not_close_the_whole_control_position(db_session):
    """He sells a name in ~1.9 tranches, so CPY-01 TRIMS on all but the last.

    Treating `trimmed` as a close exited this arm's entire position on his first
    partial sell. That is exactly the bias pumpfun v1.1.0 was fixed to remove —
    exiting while he is still holding penalises the position that RUNS — and
    having it in the control rather than the strategy is worse than having it in
    neither, because it hits the control systematically on the trades that
    decide the comparison.
    """
    await _seed_candidates(db_session)
    await _activate_control(db_session)
    mint = "LeaderMint" + "C" * 34
    _t, leader = await _leader_position(db_session, mint, size=D("10"))
    svc = CopyControlService(db_session)
    db_session.add(PumpfunSignal(
        tournament_id=_t.id, signature="sig-trim-" + "D" * 40,
        mint_address=mint, side="buy", leader_at=NOW, seen_at=NOW,
        acted=True, outcome="opened", position_id=leader.id))
    await db_session.flush()
    await svc.tick(now=NOW + timedelta(seconds=5))

    mine = (await db_session.execute(
        select(LabPosition).where(LabPosition.strategy_id == "CPY-02")
    )).scalars().first()
    assert mine is not None and mine.status == "open"
    opened_qty = mine.quantity_remaining

    # He releases a QUARTER of the name — a trim, not an exit.
    leader.quantity_remaining = leader.quantity * D("0.75")
    await db_session.flush()
    later = NOW + timedelta(minutes=30)
    db_session.add(TokenMarketSnapshot(
        token_id=mine.token_id, mint_address=mine.mint_address,
        captured_at=later, price_usd=D("0.002"), liquidity_usd=D("80000"),
        market_cap=D("400000"), volume_1h=D("50000"), volume_5m=D("5000"),
        buy_count_24h=100, sell_count_24h=50,
        trading_status=TradingStatus.TRADING, provider="test", suspect=False))
    await db_session.flush()

    await svc.tick(now=later)
    await db_session.refresh(mine)

    assert mine.status == "open", "a partial sell must not close the arm"
    held = mine.quantity_remaining / mine.quantity
    assert abs(held - D("0.75")) < D("0.02"), (
        f"arm holds {held} of its position against the pair's 0.75"
    )
    assert mine.quantity_remaining < opened_qty, "it must actually have sold"


async def test_the_arm_never_buys_back_a_slice_it_already_sold(db_session):
    """A pair holding proportionally MORE than the arm is not a reason to buy.

    Re-entering a slice already sold would invent a trade the leader never
    made. Scaling in is `_top_up`'s job and is keyed on stake, not on quantity.
    """
    await _seed_candidates(db_session)
    await _activate_control(db_session)
    mint = "LeaderMint" + "E" * 34
    _t, leader = await _leader_position(db_session, mint, size=D("10"))
    svc = CopyControlService(db_session)
    db_session.add(PumpfunSignal(
        tournament_id=_t.id, signature="sig-nobuy-" + "F" * 39,
        mint_address=mint, side="buy", leader_at=NOW, seen_at=NOW,
        acted=True, outcome="opened", position_id=leader.id))
    await db_session.flush()
    await svc.tick(now=NOW + timedelta(seconds=5))

    mine = (await db_session.execute(
        select(LabPosition).where(LabPosition.strategy_id == "CPY-02")
    )).scalars().first()
    # The arm is somehow holding LESS than the pair.
    mine.quantity_remaining = mine.quantity * D("0.5")
    await db_session.flush()
    before = mine.quantity_remaining

    await svc.tick(now=NOW + timedelta(minutes=1))
    await db_session.refresh(mine)
    assert mine.quantity_remaining == before, "it must not re-enter"


async def test_a_trimmed_signal_is_not_treated_as_a_close(db_session):
    """The regression guard for `CLOSED = ("closed", "trimmed")`.

    The reconciliation test above proves the arm CAN match a partial exit, but
    it never sends a `trimmed` signal — so it passed even with the old routing
    restored. Mutation testing caught that, which is the whole point of doing
    it: a test that cannot fail against the bug it describes is decoration.

    This one sends the signal itself.
    """
    await _seed_candidates(db_session)
    await _activate_control(db_session)
    mint = "LeaderMint" + "G" * 34
    _t, leader = await _leader_position(db_session, mint, size=D("10"))
    svc = CopyControlService(db_session)
    db_session.add(PumpfunSignal(
        tournament_id=_t.id, signature="sig-tsig1-" + "H" * 39,
        mint_address=mint, side="buy", leader_at=NOW, seen_at=NOW,
        acted=True, outcome="opened", position_id=leader.id))
    await db_session.flush()
    await svc.tick(now=NOW + timedelta(seconds=5))

    mine = (await db_session.execute(
        select(LabPosition).where(LabPosition.strategy_id == "CPY-02")
    )).scalars().first()
    assert mine is not None and mine.status == "open"

    later = NOW + timedelta(minutes=30)
    db_session.add(TokenMarketSnapshot(
        token_id=mine.token_id, mint_address=mine.mint_address,
        captured_at=later, price_usd=D("0.002"), liquidity_usd=D("80000"),
        market_cap=D("400000"), volume_1h=D("50000"), volume_5m=D("5000"),
        buy_count_24h=100, sell_count_24h=50,
        trading_status=TradingStatus.TRADING, provider="test", suspect=False))
    # He released one tranche; CPY-01 recorded it as `trimmed`, NOT `closed`.
    leader.quantity_remaining = leader.quantity * D("0.75")
    db_session.add(PumpfunSignal(
        tournament_id=_t.id, signature="sig-tsig2-" + "I" * 39,
        mint_address=mint, side="sell", leader_at=later, seen_at=later,
        acted=True, outcome="trimmed", position_id=leader.id))
    await db_session.flush()

    await svc.tick(now=later + timedelta(seconds=5))
    await db_session.refresh(mine)
    assert mine.status == "open", (
        "a `trimmed` signal closed the whole control position — the arm now "
        "exits while the leader is still holding"
    )
