"""The orchestrator: discovery in, polls folded, checkpoints owed, rows written.

No socket, no node, no database — `fakes.py` stands in for all four. What is
under test is the wiring between the three loops, which is where a poller can
be subtly wrong in a way that shows up as a missing checkpoint months later.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.labs.graduation import config
from app.labs.graduation.recorder import GraduationRecorder
from app.labs.graduation.tests.fakes import (
    Clock,
    FakeMarket,
    FakeRPC,
    FakeSessionFactory,
    curve_state,
)
from app.labs.graduation.tests.test_parse import MESSAGES, by_signature
from app.labs.graduation.tests.test_postgrad import PAIRS

D = Decimal
START = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
MINT = "Bjsxb2QErbB4rhpSRsUgtNBPPri24R3AK58tQwjvpump"
#: Real token reserves at each level, from `test_curve.EXACT`.
AT_70 = 237930000000000
AT_90 = 79310000000000
AT_FULL = 0


def build(readings=None, pairs=None, **kwargs):
    rpc = FakeRPC(readings or {})
    market = FakeMarket(pairs=pairs if pairs is not None else PAIRS)
    sessions, clock = FakeSessionFactory(), Clock(START)
    recorder = GraduationRecorder(
        stream=_NoStream(), rpc=rpc, market=market,
        session_factory=sessions, now=clock, **kwargs)
    return recorder, rpc, market, sessions, clock


class _NoStream:
    connected = True
    reconnects = 0
    messages_received = 0

    def stop(self) -> None:  # pragma: no cover - never driven here
        pass


def launch(recorder, prefix: str = "4D7BVU", at: datetime = START) -> None:
    recorder.handle(by_signature(prefix), at)


# --- discovery ----------------------------------------------------------------

async def test_a_launch_joins_the_watch_set_with_its_derived_curve() -> None:
    recorder, *_ = build()
    launch(recorder)
    state = recorder.watch.get(MINT)
    assert state is not None
    assert state.curve_address == f"curve-of-{MINT}"
    assert state.quote_currency == "SOL"


async def test_the_poller_uses_the_derived_pda_never_the_feeds_key() -> None:
    """The launch feed's `bondingCurveKey` is not trustworthy.

    Measured on 15 consecutive launches on 2026-09-11: three carried the SAME
    key — `BwWK17cbHxwWBKZkUYvzxLcNQ1YVyaFezduWbtm2de6s` — for three unrelated
    mints, and that address is a zero-length account owned by the System
    Program, not a curve. A lab that polled the reported key would read nothing
    for those tokens for ever and never know why.
    """
    recorder, rpc, *_ = build()
    launch(recorder)
    state = recorder.watch.get(MINT)
    assert state.bonding_curve_key == "3XWT7fTxe9xkKsGYjNZ3AVoaomUVpxw2hDyeo3Rupwfy"
    # Recorded, and NOT what is addressed.
    assert state.curve_address == f"curve-of-{MINT}"
    assert state.curve_address != state.bonding_curve_key

    rpc.readings[MINT] = curve_state()
    await recorder.poll_once(START)
    assert rpc.fetches == [[MINT]]   # addressed by mint, derived inside


async def test_a_bonk_launch_is_never_watched() -> None:
    recorder, *_ = build()
    launch(recorder, "La32Yc")
    assert len(recorder.watch) == 0


async def test_a_usdc_launch_carries_its_denomination_into_the_rows() -> None:
    recorder, rpc, *_ = build()
    launch(recorder, "sigUsdcCreate")
    usdc = "UsdcCurve11111111111111111111111111111pump"
    rpc.readings[usdc] = curve_state(real_token=AT_70)
    await recorder.poll_once(START)
    assert recorder.watch.get(usdc).quote_currency == "USDC"
    assert recorder._samples[0]["quote_currency"] == "USDC"
    assert recorder._checkpoints[0]["quote_currency"] == "USDC"


# --- polling ------------------------------------------------------------------

async def test_a_poll_writes_a_sample_and_computes_progress() -> None:
    recorder, rpc, *_ = build()
    launch(recorder)
    rpc.readings[MINT] = curve_state(real_token=AT_70)

    result = await recorder.poll_once(START)
    assert result["polled"] == 1 and result["moved"] == 1
    sample = recorder._samples[0]
    assert sample["mint"] == MINT
    assert sample["progress_pct"] == D("70.000")
    assert sample["real_token_reserves"] == D("237930000")   # whole tokens
    assert sample["complete"] is False
    assert sample["market_cap_quote"] is not None


async def test_an_unchanged_curve_writes_no_second_sample() -> None:
    """Storing every poll is ~2.88M rows a day, the majority identical to the
    row before. The gap between two rows means nothing happened — not that
    nothing was looked at."""
    recorder, rpc, *_ = build()
    launch(recorder)
    rpc.readings[MINT] = curve_state(real_token=AT_70)

    await recorder.poll_once(START)
    await recorder.poll_once(START + timedelta(seconds=15))
    await recorder.poll_once(START + timedelta(seconds=30))

    assert len(recorder._samples) == 1
    state = recorder.watch.get(MINT)
    assert state.sample_count == 3          # it WAS polled three times
    assert state.last_sample_at == START + timedelta(seconds=30)


async def test_a_read_that_did_not_happen_is_not_a_reading() -> None:
    """A mint absent from the result means the RPC call failed, which must not
    be folded in as "no movement" — that would let an outage look like silence
    and evict the whole watch set."""
    recorder, rpc, *_ = build()
    launch(recorder)
    rpc.unreadable = {MINT}

    await recorder.poll_once(START)
    state = recorder.watch.get(MINT)
    assert recorder._samples == []
    assert state.sample_count == 0
    assert state.last_progress_change_at is None


async def test_an_absent_account_is_not_an_error() -> None:
    """A launch is on the websocket before its curve account is queryable, so
    a null for the first poll or two is ordinary."""
    recorder, rpc, *_ = build()
    launch(recorder)
    rpc.readings[MINT] = None
    await recorder.poll_once(START)
    assert recorder._samples == []
    assert MINT in recorder.watch


# --- checkpoints --------------------------------------------------------------

async def test_one_poll_can_owe_three_checkpoints() -> None:
    """Fifteen seconds is long enough to go from 68% to 94%."""
    recorder, rpc, *_ = build()
    launch(recorder)
    rpc.readings[MINT] = curve_state(real_token=AT_90)

    await recorder.poll_once(START)
    assert [c["level_pct"] for c in recorder._checkpoints] == [D(70), D(80), D(90)]
    assert {c["progress_pct"] for c in recorder._checkpoints} == {D("90.000")}


async def test_a_level_is_checkpointed_once_even_if_recrossed() -> None:
    recorder, rpc, *_ = build()
    launch(recorder)
    for reserves, at in ((AT_70, 0), (AT_90, 15), (300000000000000, 30), (AT_90, 45)):
        rpc.readings[MINT] = curve_state(real_token=reserves)
        await recorder.poll_once(START + timedelta(seconds=at))

    levels = [c["level_pct"] for c in recorder._checkpoints]
    assert levels == [D(70), D(80), D(90)]
    assert len(levels) == len(set(levels))


async def test_a_checkpoint_carries_both_reserves_and_the_market_cap() -> None:
    recorder, rpc, *_ = build()
    launch(recorder)
    rpc.readings[MINT] = curve_state(real_token=AT_70)
    await recorder.poll_once(START)

    checkpoint = recorder._checkpoints[0]
    assert checkpoint["real_token_reserves"] == D("237930000")
    assert checkpoint["v_token_reserves"] == D("517830000")
    assert checkpoint["v_quote_reserves"] == D("30.000000006")
    assert checkpoint["market_cap_quote"] is not None


async def test_the_trade_derived_checkpoint_columns_are_absent_not_zero() -> None:
    """The chain reports reserves, not who moved them. A poller cannot count
    buyers at any price, so those columns are left to the table's defaults
    rather than written as a measured zero."""
    recorder, rpc, *_ = build()
    launch(recorder)
    rpc.readings[MINT] = curve_state(real_token=AT_70)
    await recorder.poll_once(START)

    written = set(recorder._checkpoints[0])
    assert not written & {"buy_count", "unique_buyers", "top10_holder_share"}


# --- graduation ---------------------------------------------------------------

async def test_the_chain_can_report_graduation_before_the_websocket() -> None:
    """`complete` on the account is independent of the migration feed, and
    either may arrive first."""
    recorder, rpc, *_ = build()
    launch(recorder)
    rpc.readings[MINT] = curve_state(real_token=AT_FULL, complete=True)

    await recorder.poll_once(START)
    state = recorder.watch.get(MINT)
    assert state.seen_complete_on_chain is True
    assert state.max_progress == D("100.000")
    assert MINT in recorder.postgrad.states          # the window opened anyway
    assert [c["level_pct"] for c in recorder._checkpoints] == \
        [D(70), D(80), D(90), D(95), D(100)]


async def test_a_migration_message_completes_the_levels_and_opens_the_window() -> None:
    recorder, rpc, *_ = build()
    launch(recorder)
    rpc.readings[MINT] = curve_state(real_token=AT_70)
    await recorder.poll_once(START)

    recorder.handle(by_signature("sigMigrate0"), START + timedelta(seconds=30))
    state = recorder.watch.get(MINT)
    assert state.migrated_at == START + timedelta(seconds=30)
    assert [c["level_pct"] for c in recorder._checkpoints] == \
        [D(70), D(80), D(90), D(95), D(100)]
    assert recorder._migrations[0]["progress_pct_before"] == D("70.000")
    assert MINT in recorder.postgrad.states

    # The level that was actually OBSERVED carries its reserves; the ones only
    # inferred from the migration event carry null. A graduated curve zeroes
    # every reserve, so there is nothing truthful to put in those columns, and
    # a zero would read as a measurement nobody made.
    observed, inferred = recorder._checkpoints[0], recorder._checkpoints[-1]
    assert observed["level_pct"] == D(70)
    assert observed["progress_pct"] == D("70.000")
    assert observed["real_token_reserves"] == D("237930000")
    assert inferred["level_pct"] == D(100)
    assert inferred["progress_pct"] == D("100.000")
    assert inferred["real_token_reserves"] is None


async def test_a_migration_of_an_unwatched_token_is_still_recorded() -> None:
    """The migration feed is global. A graduation nobody watched still
    happened, and the row says so with a null progress."""
    recorder, *_ = build()
    recorder.handle(by_signature("sigMigrate0"), START)
    assert recorder._migrations[0]["mint"] == MINT
    assert recorder._migrations[0]["progress_pct_before"] is None
    assert len(recorder.watch) == 0


async def test_post_graduation_sampling_produces_rows() -> None:
    recorder, *_ = build()
    launch(recorder)
    recorder.handle(by_signature("sigMigrate0"), START)

    rows = await recorder.postgrad.poll(START)
    assert len(rows) == 1
    assert rows[0]["source"] == "dexscreener"
    assert rows[0]["price_usd"] == D("0.00006889")


# --- the sweep ----------------------------------------------------------------

async def test_a_swept_token_is_retired_and_written_once() -> None:
    recorder, rpc, _, sessions, _ = build()
    launch(recorder)
    rpc.readings[MINT] = curve_state()

    await recorder.poll_once(START)
    later = START + timedelta(minutes=config.SILENT_MIN + 1)
    await recorder.poll_once(later)

    assert MINT not in recorder.watch
    written = await recorder.flush(now=later)
    assert written["tokens"] == 1
    assert sessions.table_names()[0] == "grad_tokens"


async def test_an_evicted_token_is_still_written() -> None:
    recorder, *_ = build(watch=_full_watch())
    launch(recorder, "2LmQny")
    assert recorder._retired
    _, reason = next(iter(recorder._retired.values()))
    assert reason == "evicted"


def _full_watch():
    from app.labs.graduation.watchset import TokenState, WatchSet

    watch = WatchSet(max_size=1)
    watch.admit(TokenState(mint="squatter", first_seen_at=START, launch_pool="pump"))
    return watch


# --- writing ------------------------------------------------------------------

async def test_flush_writes_tokens_before_the_rows_that_name_them() -> None:
    recorder, rpc, _, sessions, _ = build()
    launch(recorder)
    rpc.readings[MINT] = curve_state(real_token=AT_90)
    await recorder.poll_once(START)
    recorder.handle(by_signature("sigMigrate0"), START)
    for row in await recorder.postgrad.poll(START):
        recorder._buffer(recorder._postgrad_rows, row)

    written = await recorder.flush()
    assert written == {"tokens": 1, "samples": 1, "checkpoints": 5,
                       "migrations": 1, "postgrad": 1}
    assert sessions.table_names()[0] == "grad_tokens"
    assert sessions.sessions[0].commits == 1
    # The buffers are empty, so a second flush is a no-op, not a double write.
    assert await recorder.flush() == {}


async def test_a_full_buffer_drops_rows_and_counts_them() -> None:
    """A database outage must cost memory, not the process."""
    original = config.BUFFER_MAX_ROWS
    config.BUFFER_MAX_ROWS = 2
    try:
        recorder, rpc, *_ = build()
        launch(recorder)
        rpc.readings[MINT] = curve_state(real_token=AT_90)
        await recorder.poll_once(START)
        assert len(recorder._samples) + len(recorder._checkpoints) == 2
        assert recorder.dropped_rows > 0
    finally:
        config.BUFFER_MAX_ROWS = original


async def test_unknown_migration_fields_are_surfaced() -> None:
    recorder, *_ = build()
    recorder.handle(by_signature("sigMigrateNew"), START)
    assert recorder.unexpected_fields == {"blockTime"}


async def test_every_fixture_message_is_handled_without_raising() -> None:
    """The whole recorded file, in order, including the ack. One bad message
    must never end a run."""
    recorder, *_ = build()
    for message in MESSAGES:
        recorder.handle(message, START)
    assert len(recorder.watch) >= 1


async def test_a_batch_mixing_sources_keeps_every_column() -> None:
    """One multi-row INSERT takes the batch, and SQLAlchemy builds it from the
    FIRST row's keys. A socket row carries a price and a depth and nothing
    else, so at the head of a batch it silently dropped the volume and trade
    counts of every DexScreener row behind it — and behind one, it failed the
    whole flush."""
    from sqlalchemy.dialects import postgresql

    from app.labs.graduation.postgrad import parse_pair

    recorder, _, _, sessions, _ = build()
    socket_row = {"mint": MINT, "ts": START, "source": "held_ws",
                  "pair_address": "POOL", "dex_id": "pumpswap",
                  "price_native": D("0.000001"), "liquidity_usd": D("90000.00")}
    dex_row = parse_pair(PAIRS[0], ts=START + timedelta(seconds=1))
    assert dex_row is not None and dex_row["txns_m5_buys"] is not None
    for batch in ([socket_row, dex_row], [dex_row, socket_row]):
        for row in batch:
            recorder._buffer(recorder._postgrad_rows, dict(row))
        await recorder.flush()
        statement = sessions.statements[-1]
        compiled = statement.compile(dialect=postgresql.dialect())
        assert "txns_m5_buys" in str(compiled)
        buys = [v for k, v in compiled.params.items() if k.startswith("txns_m5_buys")]
        assert sorted(buys, key=lambda v: v is None) == [dex_row["txns_m5_buys"], None]


async def test_no_flush_ever_waits_on_the_network() -> None:
    """Holder reads wait on a spent RPC for seconds a mint. While they ran
    inside `flush()`, every loop that wrote waited with them — new positions
    reached the vault socket 84-136s late. Now a flush writes only what the
    holders loop has already read."""
    from app.labs.graduation.sources import Holders

    recorder, rpc, _, sessions, _ = build()
    recorder._owe_holders.add(MINT)
    rpc.holder_readings[MINT] = Holders(top1_share=D("0.2"), top10_share=D("0.5"),
                                        top_address="POOL", seen=20)
    recorder._buffer(recorder._postgrad_rows, {
        "mint": MINT, "ts": START, "source": "held_ws",
        "price_native": D("0.000001")})
    written = await recorder.flush()
    assert written["postgrad"] == 1
    assert rpc.holders_asked == []
    assert recorder._owe_holders == {MINT}

    await recorder._collect_holders()             # the holders loop's turn
    assert rpc.holders_asked == [MINT]
    assert not recorder._owe_holders
    before = len(sessions.statements)
    await recorder.flush()
    assert "grad_tokens" in sessions.table_names()[before:]
    assert not recorder._holders_ready


async def test_a_new_graduates_first_sample_is_written_before_the_backfill(
        monkeypatch) -> None:
    """The first sample is the paper book's entry. Behind a GeckoTerminal
    backfill that refuses bursts for tens of seconds, entries mirrored to the
    real wallet were a median 77s old when written."""
    import asyncio

    class StuckBackfill(FakeMarket):
        async def gecko_minute_ohlcv(self, pool, *, limit):
            await asyncio.Event().wait()

    monkeypatch.setattr(config, "POSTGRAD_INTERVAL_S", 0)
    recorder, *_ = build(pairs=PAIRS)
    recorder._market = recorder.postgrad._market = StuckBackfill(pairs=PAIRS)
    sessions = recorder._sessions
    recorder.postgrad.start(MINT, START)
    stale = "AnOlderGraduateWithAGap"
    recorder.postgrad.start(stale, START)
    recorder.postgrad.states[stale].pair_address = "pool1"
    recorder.postgrad.states[stale].last_sample_at = START - timedelta(minutes=5)
    task = asyncio.create_task(recorder._postgrad_loop())
    try:
        for _ in range(200):
            if "grad_postgrad_samples" in sessions.table_names():
                break
            await asyncio.sleep(0.01)
        assert "grad_postgrad_samples" in sessions.table_names()
        assert not task.done()                    # the backfill is still stuck
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


class _Scripted:
    """A session that answers each query with the next scripted row list."""

    def __init__(self, *answers) -> None:
        self.answers = list(answers)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, statement):
        from types import SimpleNamespace

        if not self.answers:
            raise RuntimeError("database down")
        rows = self.answers.pop(0)
        return SimpleNamespace(all=lambda: rows)


def _recorder_on(session) -> GraduationRecorder:
    return GraduationRecorder(stream=_NoStream(), rpc=FakeRPC({}),
                              market=FakeMarket(pairs=PAIRS),
                              session_factory=lambda: session, now=Clock(START))


async def test_a_restart_resumes_every_open_window_on_its_pinned_pair() -> None:
    """The windows lived only in memory: every deploy cut short the hour of
    every token that graduated before it, and left open positions with no
    DexScreener mark until they closed."""
    from types import SimpleNamespace

    fed = START - timedelta(minutes=20)
    chain_only = "ChainSawItFeedDidNot"
    recorder = _recorder_on(_Scripted(
        [SimpleNamespace(mint=MINT, ts=fed)],
        [SimpleNamespace(mint=MINT, opened_at=fed + timedelta(minutes=9),
                         last_at=START - timedelta(seconds=40)),
         SimpleNamespace(mint=chain_only, opened_at=START - timedelta(minutes=5),
                         last_at=START - timedelta(minutes=1))],
        [SimpleNamespace(mint=MINT, pair_address="PINNED", dex_id="pumpswap")]))
    await recorder._resume_windows()
    state = recorder.postgrad.states[MINT]
    assert (state.migrated_at, state.pair_address) == (fed, "PINNED")
    assert state.opened_at == fed + timedelta(minutes=9)
    assert state.gap_seconds(START) == 40      # the backfill fills the restart
    assert recorder.postgrad.states[chain_only].migrated_at == START - timedelta(minutes=5)
    # The pin survives: another pool is refused, the pinned one accepted.
    assert not recorder.postgrad._accept(
        {"mint": MINT, "pair_address": "ELSEWHERE", "ts": START})
    assert recorder.postgrad._accept(
        {"mint": MINT, "pair_address": "PINNED", "ts": START})


async def test_a_failed_resume_never_stops_the_recorder() -> None:
    recorder = _recorder_on(_Scripted())
    await recorder._resume_windows()
    assert not recorder.postgrad.states


async def test_the_socket_gets_its_set_before_anything_slow() -> None:
    """On its first day live the pass flushed — and read holder concentration
    over a spent RPC — before handing the socket its set: ten positions in a
    row waited 84-136s for a first fast mark, most of a two-minute hold. Here
    DexScreener never answers, and the socket must still have its set."""
    import asyncio
    from types import SimpleNamespace

    from app.labs.graduation.held_watch import MarkWriter

    class Silent(FakeMarket):
        async def dex_pairs(self, mints):
            await asyncio.Event().wait()

    class Resolver:
        async def resolve(self, mint, pool):
            return SimpleNamespace(mint=mint, pool=pool)

    row = SimpleNamespace(mint=MINT, pair_address="POOL",
                          price_native=D("0.000001"), price_usd=D("0.0002"))
    recorder = GraduationRecorder(
        stream=_NoStream(), rpc=FakeRPC({}), market=Silent(pairs=PAIRS),
        session_factory=lambda: _Scripted([row], []), now=Clock(START))
    recorder.postgrad.start(MINT, START)
    recorder._owe_holders.add("JustGraduated")
    wanted: dict = {}
    refs: dict = {}
    task = asyncio.create_task(recorder._held_pass(
        Resolver(), wanted, refs, MarkWriter(), {}, {}))
    for _ in range(200):
        if wanted:
            break
        await asyncio.sleep(0.01)
    try:
        assert set(wanted) == {MINT}
        assert refs[MINT] == (D("0.000001"), D("200"))
        assert not task.done()                    # still waiting on DexScreener
        assert recorder.rpc.holders_asked == []
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_a_pass_leaves_holder_reads_to_the_other_loops() -> None:
    from types import SimpleNamespace

    from app.labs.graduation.held_watch import MarkWriter

    class Resolver:
        async def resolve(self, mint, pool):
            return None

    row = SimpleNamespace(mint=MINT, pair_address="POOL",
                          price_native=D("0.000001"), price_usd=D("0.0002"))
    recorder = GraduationRecorder(
        stream=_NoStream(), rpc=FakeRPC({}), market=FakeMarket(pairs=PAIRS),
        session_factory=lambda: _Scripted([row], []), now=Clock(START))
    recorder._owe_holders.add("JustGraduated")
    await recorder._held_pass(Resolver(), {}, {}, MarkWriter(), {}, {})
    assert recorder.rpc.holders_asked == []
    assert recorder._owe_holders == {"JustGraduated"}


def test_a_pumpswap_graduation_is_watched_for_the_early_arm() -> None:
    from app.labs.graduation.parse import MigrationRow

    recorder, *_ = build()
    for mint, venue in (("PoolMint", "pump-amm"), ("CpmmMint", "raydium-cpmm")):
        recorder._on_migration(MigrationRow(
            mint=mint, ts=START, pool=venue, signature=f"sig-{mint}", raw={}))
    assert set(recorder.early.due) == {"PoolMint"}
    assert recorder.early.due["PoolMint"] == (START, "sig-PoolMint")


async def test_an_early_crossing_is_found_watched_and_written() -> None:
    """The whole early path through the recorder: the pass reads the pool off
    the migration transaction and hands it to the socket; the first reading at
    B3's depth becomes a `grad_early_opens` row."""
    import asyncio
    from dataclasses import replace
    from types import SimpleNamespace

    from app.labs.graduation.held_watch import Held, MarkWriter

    watched = Held(mint="EarlyMint", pool="POOL", base_vault="bv",
                   quote_vault="qv", base_decimals=6, quote_decimals=9,
                   quote_mint=config.WSOL_MINT)
    deep = replace(watched, base=17_000_000_000_000, quote=1_000_000_000_000)

    class Stream:
        updates = 0

        async def pool_from_migration(self, mint, signature):
            assert (mint, signature) == ("EarlyMint", "sig")
            return "POOL"

        async def resolve(self, mint, pool):
            assert pool == "POOL"
            return watched

        async def stream(self, wanted, on_price):
            assert "EarlyMint" in wanted()
            await on_price(deep, START + timedelta(seconds=40))
            raise asyncio.CancelledError

    writes = FakeSessionFactory()
    first = iter([_Scripted([], [SimpleNamespace(rate=D(100))])])
    recorder = GraduationRecorder(
        stream=_NoStream(), rpc=FakeRPC({}), market=FakeMarket(pairs=[]),
        session_factory=lambda: next(first, None) or writes(),
        now=Clock(START + timedelta(seconds=5)))
    recorder.early.add("EarlyMint", START, "sig")
    wanted: dict = {}
    early: dict = {}
    await recorder._held_pass(Stream(), wanted, {}, MarkWriter(), {}, {}, early)
    assert wanted == {"EarlyMint": watched}
    assert recorder._sol_usd == D(100)

    with pytest.raises(asyncio.CancelledError):
        await recorder._held_socket(Stream(), wanted, {}, MarkWriter())
    assert "grad_early_opens" in writes.table_names()
    assert not recorder.early.due


def test_every_graduation_is_owed_a_holder_read() -> None:
    """The feed is global: most graduates were no longer in the watch set when
    they migrated, and on 2026-09-17 three in four were never asked."""
    from app.labs.graduation.parse import MigrationRow

    recorder, *_ = build()
    recorder._on_migration(MigrationRow(
        mint="NeverWatched", ts=START, pool="pump-amm", signature="sig", raw={}))
    assert recorder._owe_holders == {"NeverWatched"}


async def test_a_refused_holder_read_is_retried_briefly_then_dropped() -> None:
    """The node refuses reads in bursts; a refusal gets a short second chance
    and no more, because a late read describes a different token."""
    from app.labs.graduation import config
    from app.labs.graduation.sources import Holders

    recorder, rpc, _, _, clock = build()
    recorder._owe_holders.add(MINT)
    assert await recorder._read_holders() == {}          # refused
    assert rpc.holders_asked == [MINT]
    assert await recorder._read_holders() == {}          # not due yet: no ask
    assert rpc.holders_asked == [MINT]

    clock.now = START + timedelta(seconds=config.HOLDER_RETRY_S[0])
    rpc.holder_readings[MINT] = Holders(top1_share=D("0.3"), top10_share=D("0.6"),
                                        top_address="POOL", seen=20)
    got = await recorder._read_holders()                 # second try answers
    assert set(got) == {MINT}
    assert not recorder._holder_retry

    # A mint that is refused every time is asked 1 + len(HOLDER_RETRY_S) times.
    recorder._owe_holders.add("Refused")
    for wait in (0, *config.HOLDER_RETRY_S):
        clock.now += timedelta(seconds=wait)
        await recorder._read_holders()
    assert rpc.holders_asked.count("Refused") == 1 + len(config.HOLDER_RETRY_S)
    assert not recorder._holder_retry and not recorder._owe_holders
