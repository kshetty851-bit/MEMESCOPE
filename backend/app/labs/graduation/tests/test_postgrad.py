"""The hour after graduation: parsing, windows, and the backfill's precondition."""

from __future__ import annotations

import json
import pathlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.labs.graduation import config
from app.labs.graduation.postgrad import (
    PostGradSampler,
    PostGradState,
    parse_candle,
    parse_pair,
)

D = Decimal
NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
MINT = "Bjsxb2QErbB4rhpSRsUgtNBPPri24R3AK58tQwjvpump"
PAIRS = [
    {k: v for k, v in p.items() if k != "_note"}
    for p in json.loads(
        (pathlib.Path(__file__).parent / "fixtures" / "dexscreener_pairs.json").read_text())
]


class FakeMarket:
    """Returns canned pairs and candles, and counts the calls."""

    def __init__(self, pairs=None, candles=None) -> None:
        self.pairs = pairs if pairs is not None else PAIRS
        self.candles = candles or []
        self.pair_calls: list[list[str]] = []
        self.ohlcv_calls: list[tuple[str, int]] = []

    async def dex_pairs(self, mints):
        self.pair_calls.append(list(mints))
        return [p for p in self.pairs
                if (p.get("baseToken") or {}).get("address") in set(mints)]

    async def gecko_minute_ohlcv(self, pool, *, limit):
        self.ohlcv_calls.append((pool, limit))
        return self.candles


# --- parsing ------------------------------------------------------------------

def test_a_live_pair_parses_every_column() -> None:
    row = parse_pair(PAIRS[0], ts=NOW)
    assert row is not None
    assert row["mint"] == MINT
    assert row["source"] == "dexscreener"
    assert row["pair_address"] == "8QKJHcXiVfo7jY9mY8kpoZgJMG4F9JM2mPY243VALjMB"
    assert row["dex_id"] == "pumpswap"
    assert row["price_usd"] == D("0.00006889")
    assert row["liquidity_usd"] == D("41230.55")
    assert row["volume_m5_usd"] == D("1204.50")
    assert row["volume_h1_usd"] == D("18903.25")
    assert row["txns_m5_buys"] == 14 and row["txns_m5_sells"] == 9
    assert row["txns_h1_buys"] == 231 and row["txns_h1_sells"] == 188


def test_a_pair_on_another_chain_is_refused() -> None:
    """A chain filter that is not applied is one that is not there."""
    assert parse_pair(PAIRS[1], ts=NOW) is None


def test_absent_liquidity_reads_as_null_not_zero() -> None:
    """DexScreener's documented gap on bonding-curve pairs. An unknown reserve
    is not a zero one."""
    row = parse_pair(PAIRS[2], ts=NOW)
    assert row is not None
    assert row["liquidity_usd"] is None
    assert row["volume_m5_usd"] is None      # only h1 was sent
    assert row["volume_h1_usd"] == D("55.00")


def test_a_backfilled_candle_fills_only_what_it_can_know() -> None:
    """`volume_m5_usd` is a rolling window DexScreener computes. A one-minute
    candle cannot produce it, and a zero there would be indistinguishable from
    a minute in which nothing traded."""
    state = PostGradState(mint=MINT, migrated_at=NOW, pair_address="pool1",
                          dex_id="pumpswap")
    row = parse_candle([1757606460, 1.0, 1.2, 0.9, 1.1, 4321.5],
                       mint=MINT, state=state)
    assert row is not None
    assert row["source"] == "geckoterminal"
    assert row["price_usd"] == D("1.10000000")
    assert row["volume_m1_usd"] == D("4321.50")
    assert row["volume_m5_usd"] is None and row["volume_h1_usd"] is None
    assert row["txns_m5_buys"] is None and row["txns_h1_buys"] is None
    assert row["pair_address"] == "pool1"


# --- the window ---------------------------------------------------------------

async def test_a_window_opens_on_migration_and_closes_an_hour_after_the_open() -> None:
    """It used to close an hour after the MIGRATION, which silently truncated
    every window by however long DexScreener took to answer — about nine
    minutes, and enough that no outcome could ever clear the coverage floor."""
    sampler = PostGradSampler(market=FakeMarket())
    sampler.start(MINT, NOW)
    assert len(sampler) == 1

    # With a pool open recorded, the hour runs from there.
    opened = NOW + timedelta(minutes=9)
    sampler.states[MINT].opened_at = opened
    assert sampler.expire(NOW + timedelta(minutes=61)) == []
    assert sampler.expire(opened + timedelta(minutes=61)) == [MINT]
    assert len(sampler) == 0


async def test_starting_the_same_window_twice_is_a_no_op() -> None:
    """The migration feed and the chain's own `complete` flag can both report
    the same graduation, and either may arrive first."""
    sampler = PostGradSampler(market=FakeMarket())
    sampler.start(MINT, NOW)
    sampler.start(MINT, NOW + timedelta(minutes=5))
    assert len(sampler) == 1
    assert sampler.states[MINT].migrated_at == NOW


async def test_a_poll_produces_one_row_and_learns_the_pool() -> None:
    market = FakeMarket()
    sampler = PostGradSampler(market=market)
    sampler.start(MINT, NOW)

    rows = await sampler.poll(NOW)
    assert len(rows) == 1 and rows[0]["mint"] == MINT
    # The pool address is learned HERE and nowhere else — it is what the
    # GeckoTerminal fallback addresses.
    assert sampler.states[MINT].pair_address == \
        "8QKJHcXiVfo7jY9mY8kpoZgJMG4F9JM2mPY243VALjMB"


async def test_a_token_is_not_resampled_inside_its_interval() -> None:
    market = FakeMarket()
    sampler = PostGradSampler(market=market)
    sampler.start(MINT, NOW)
    await sampler.poll(NOW)
    market.pair_calls.clear()

    assert await sampler.poll(NOW + timedelta(seconds=config.POSTGRAD_INTERVAL_S - 5)) == []
    assert market.pair_calls == []


# --- the backfill -------------------------------------------------------------

async def test_a_missed_poll_is_backfilled_from_minute_candles() -> None:
    market = FakeMarket(pairs=[])   # DexScreener answers nothing
    sampler = PostGradSampler(market=market)
    sampler.start(MINT, NOW)
    sampler.states[MINT].pair_address = "pool1"   # learned from an earlier poll
    sampler.states[MINT].last_sample_at = NOW
    market.candles = [[int((NOW + timedelta(minutes=m)).timestamp()),
                       1.0, 1.0, 1.0, 1.0 + m, 100.0 * m] for m in (1, 2, 3)]

    rows = await sampler.poll(NOW + timedelta(minutes=5))
    assert [r["source"] for r in rows] == ["geckoterminal"] * 3
    assert sampler.backfilled == 1
    assert market.ohlcv_calls and market.ohlcv_calls[0][0] == "pool1"


async def test_a_token_whose_first_poll_failed_can_never_be_backfilled() -> None:
    """GeckoTerminal addresses a POOL, and the pool address only ever comes
    from a DexScreener response. This gap is permanent, so it is counted rather
    than hidden."""
    market = FakeMarket(pairs=[])
    sampler = PostGradSampler(market=market)
    sampler.start(MINT, NOW)

    rows = await sampler.poll(NOW + timedelta(minutes=5))
    assert rows == []
    assert sampler.backfill_impossible == 1
    assert market.ohlcv_calls == []   # nothing to address


async def test_a_backfill_never_duplicates_a_live_sample() -> None:
    market = FakeMarket()
    sampler = PostGradSampler(market=market)
    sampler.start(MINT, NOW)
    await sampler.poll(NOW)
    # A candle at exactly the timestamp already written live.
    market.pairs = []
    market.candles = [[int(NOW.timestamp()), 1.0, 1.0, 1.0, 1.0, 10.0]]

    rows = await sampler.poll(NOW + timedelta(minutes=5))
    assert rows == []


async def test_candles_predating_the_graduation_are_dropped() -> None:
    """This table is the hour AFTER. A candle from before belongs to a
    different question."""
    market = FakeMarket(pairs=[])
    sampler = PostGradSampler(market=market)
    sampler.start(MINT, NOW)
    sampler.states[MINT].pair_address = "pool1"
    sampler.states[MINT].last_sample_at = NOW
    market.candles = [[int((NOW - timedelta(minutes=30)).timestamp()),
                       1.0, 1.0, 1.0, 1.0, 5.0]]

    assert await sampler.poll(NOW + timedelta(minutes=5)) == []


# --- the window runs from the open, not the migration -------------------------

async def test_the_window_runs_a_full_hour_from_the_pool_open() -> None:
    """The bug this closes, found in production.

    DexScreener first answers about nine minutes after the migration. Closing
    the window sixty minutes after the MIGRATION therefore collected only ~51
    minutes of prices — while the outcome floor needs 55 of 60 counted from
    the open. No outcome could ever qualify; every graduate was rejected.
    """
    sampler = PostGradSampler(market=FakeMarket())
    sampler.start(MINT, NOW)
    state = sampler.states[MINT]

    # The pool appears nine minutes late.
    opened = NOW + timedelta(minutes=9)
    state.opened_at = opened

    # An hour after the MIGRATION is no longer the end of the window.
    assert state.window_open(NOW + timedelta(minutes=61)) is True
    # An hour after the OPEN is.
    assert state.window_open(opened + timedelta(minutes=59)) is True
    assert state.window_open(opened + timedelta(minutes=61)) is False


async def test_a_graduate_whose_pair_never_appears_is_given_up_on() -> None:
    """Otherwise a token with no pool would be polled for ever, because the
    clock it runs on would never start."""
    sampler = PostGradSampler(market=FakeMarket())
    sampler.start(MINT, NOW)
    state = sampler.states[MINT]
    assert state.opened_at is None

    grace = config.POSTGRAD_OPEN_GRACE_SECONDS
    assert state.window_open(NOW + timedelta(seconds=grace - 60)) is True
    assert state.window_open(NOW + timedelta(seconds=grace + 60)) is False


async def test_the_open_is_recorded_from_the_first_accepted_sample() -> None:
    market = FakeMarket()
    sampler = PostGradSampler(market=market)
    sampler.start(MINT, NOW)
    late = NOW + timedelta(minutes=9)

    await sampler.poll(late)
    assert sampler.states[MINT].opened_at == late
    # And it does not move on later samples.
    await sampler.poll(late + timedelta(minutes=5))
    assert sampler.states[MINT].opened_at == late


# --- the pair is pinned -------------------------------------------------------

def _pair(address: str, *, price: str, liq: float) -> dict:
    return {"chainId": config.NETWORK, "pairAddress": address, "dexId": "pumpswap",
            "baseToken": {"address": MINT}, "priceNative": price,
            "priceUsd": price, "liquidity": {"usd": liq}}


async def test_a_second_pool_cannot_reprice_a_position() -> None:
    """`/tokens/v1` answers with EVERY pool a mint trades in and the order is
    not stable, so without a pin the series hops between them.

    Live on 2026-09-11 that turned ORE's marks from its SOL pair into a
    USD-quoted pair's — a 100x "gain" in one minute with no trade behind it —
    and did the same to a pump.fun token at 162x. Forty-five of 349 paper
    trades were priced across two pools and produced +$2,414 of a +$1,712
    book. A position is opened against one pool; marking it against another
    is not a price change, it is a change of instrument.
    """
    deep = _pair("POOL_DEEP", price="0.5617", liq=90_000)
    shallow = _pair("POOL_OTHER", price="59.99", liq=400)
    market = FakeMarket(pairs=[shallow, deep])
    sampler = PostGradSampler(market=market)
    sampler.start(MINT, NOW)

    # First poll: the DEEPEST pool wins, whatever order the API listed them.
    rows = await sampler.poll(NOW)
    assert [r["pair_address"] for r in rows] == ["POOL_DEEP"]
    assert sampler.states[MINT].pair_address == "POOL_DEEP"

    # Later polls take nothing from the other pool, even when it is listed
    # first and even though its timestamp is new.
    rows = await sampler.poll(NOW + timedelta(minutes=1))
    assert [r["pair_address"] for r in rows] == ["POOL_DEEP"]
    assert [r["price_native"] for r in rows] == [D("0.5617")]
    assert sampler.pair_rejected == 2
