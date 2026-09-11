"""The orchestrator: discovery in, polls folded, checkpoints owed, rows written.

No socket, no node, no database — `fakes.py` stands in for all four. What is
under test is the wiring between the three loops, which is where a poller can
be subtly wrong in a way that shows up as a missing checkpoint months later.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

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
