"""The pure parts: candles, rules, fills, wallets. No database."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.labs.momentum import board, config
from app.labs.momentum.arms import (
    ARMS,
    BY_NAME,
    M5,
    Context,
    Rolling,
    Rule,
    coin,
    fires,
    fires_rolling,
)
from app.labs.momentum.candles import Bar, bucket, busy, features
from app.labs.momentum.lab import buy, sell
from app.labs.momentum.sources import PairRow, best_pair, parse_listed

T0 = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
FIVE = timedelta(minutes=5)
CTX = Context(liquidity=500_000, age_days=60, breadth=0.6)


def bar(i: int, o: float, c: float, *, hi: float | None = None, lo: float | None = None,
        vol: float = 1_000, buys: int = 10, sells: int = 10, h24: float = 288_000,
        change_h24: float = 5.0) -> Bar:
    return Bar(start=T0 + i * FIVE, open=o, high=hi if hi is not None else max(o, c),
               low=lo if lo is not None else min(o, c), close=c, volume=vol, buys=buys,
               sells=sells, volume_h24=h24, liquidity=500_000, change_h24=change_h24,
               samples=10)


def quiet(n: int = 48) -> list[Bar]:
    """n bars wobbling 0.2%, at exactly average volume (h24 / 288)."""
    out, price = [], 1.0
    for i in range(n):
        c = price * (1.002 if i % 2 else 0.998)
        out.append(bar(i, price, c))
        price = c
    return out


def impulse(i: int, o: float, pct: float = 0.05, **kw) -> Bar:
    return bar(i, o, o * (1 + pct), hi=o * (1 + pct), lo=o * 0.995,
               vol=kw.pop("vol", 5_000), buys=kw.pop("buys", 30),
               sells=kw.pop("sells", 10), **kw)


def test_bucket_is_the_utc_grid() -> None:
    assert bucket(T0 + timedelta(minutes=7, seconds=12), 300) == T0 + FIVE
    assert bucket(T0 + timedelta(minutes=59), 3600) == T0


def test_features_never_read_the_future() -> None:
    """A bar is measured against bars that closed BEFORE it; anything at or
    after its start is ignored, whatever the caller passes."""
    history = quiet()
    sig = impulse(48, history[-1].close)
    later = [impulse(49, sig.close, 0.5), impulse(50, sig.close, 0.9)]
    a = features(sig, history, 300, impulse_ret=0.02)
    b = features(sig, history + later, 300, impulse_ret=0.02)
    assert a == b


def test_features_measure_the_candle() -> None:
    history = quiet()
    f = features(impulse(48, history[-1].close), history, 300, impulse_ret=0.02)
    assert f.ret == pytest.approx(0.05)
    assert f.clv == pytest.approx(1.0)
    assert f.body_x == pytest.approx(0.05 / 0.002, rel=0.01)
    assert f.vol_x == pytest.approx(5.0)
    assert f.buy_ratio == pytest.approx(3.0)
    assert f.breakout and f.quiet and f.recent_impulses == 0
    assert f.history == config.LOOKBACK_BARS


def test_the_base_rule_takes_a_momentum_candle_and_nothing_less() -> None:
    history = quiet()
    o = history[-1].close
    f = lambda b: features(b, history, 300, impulse_ret=0.02)  # noqa: E731
    assert fires(M5, f(impulse(48, o)), CTX)
    assert not fires(M5, f(impulse(48, o, 0.015)), CTX), "under 2%"
    assert not fires(M5, f(impulse(48, o, vol=2_000)), CTX), "2x volume"
    wick = bar(48, o, o * 1.03, hi=o * 1.08, lo=o * 0.99, vol=5_000, buys=30, sells=10)
    assert not fires(M5, f(wick), CTX), "gave most of it back: closed low in its range"


def test_one_condition_changed_each() -> None:
    """Run 2: each arm is the base rule with ONE thing changed."""
    history = quiet()
    o = history[-1].close
    loud = features(impulse(48, o, 0.08, vol=20_000), history, 300, impulse_ret=0.02)
    small = features(impulse(48, o, 0.03), history, 300, impulse_ret=0.02)
    assert fires(BY_NAME["BASE_60"].rule, loud, CTX)
    # QUIET takes the small move and refuses the loud one, on size and volume.
    assert fires(BY_NAME["QUIET_60"].rule, small, CTX)
    assert not fires(BY_NAME["QUIET_60"].rule, loud, CTX), "8% is over the 5% ceiling"
    assert not fires(BY_NAME["QUIET_60"].rule,
                     features(impulse(48, o, 0.03, vol=20_000), history, 300,
                              impulse_ret=0.02), CTX), "20x volume is over the ceiling"
    # DEEP needs the pool, DOWN needs the coin to be down on the day.
    assert not fires(BY_NAME["DEEP_60"].rule, loud, CTX), "a $200k pool is not deep"
    assert fires(BY_NAME["DEEP_60"].rule, loud, replace(CTX, liquidity=2_000_000))
    assert not fires(BY_NAME["DOWN_60"].rule, loud, CTX), "up on the day"


def test_confirmation_needs_the_next_candle_green() -> None:
    history = quiet()
    o = history[-1].close
    sig = impulse(48, o)
    prev = features(sig, history, 300, impulse_ret=0.02)
    rule = replace(M5, confirm=True)
    up = features(bar(49, sig.close, sig.close * 1.001), [*history, sig], 300,
                  impulse_ret=0.02)
    down = features(bar(49, sig.close, sig.close * 0.999), [*history, sig], 300,
                    impulse_ret=0.02)
    assert fires(rule, up, CTX, prev=prev)
    assert not fires(rule, down, CTX, prev=prev)
    assert not fires(rule, up, CTX, prev=None)


def test_the_dip_rule_is_the_mirror() -> None:
    history = quiet()
    o = history[-1].close
    red = bar(48, o, o * 0.95, hi=o * 1.005, lo=o * 0.95, vol=5_000, buys=5, sells=30)
    f = features(red, history, 300, impulse_ret=0.02)
    assert fires(BY_NAME["SNAP_60"].rule, f, CTX)
    assert not fires(M5, f, CTX)


def test_the_rolling_rule_reads_the_feeds_own_window() -> None:
    rule = Rule(min_ret=0.04, min_vol_x=3.0, rolling=True)
    s = Rolling(change_m5=6.0, volume_m5=5_000, volume_h24=288_000, buys_m5=40, sells_m5=10)
    assert fires_rolling(rule, s, CTX)
    assert not fires_rolling(rule, replace(s, change_m5=3.0), CTX)
    assert not fires_rolling(rule, replace(s, volume_m5=2_000), CTX)
    assert fires_rolling(rule, replace(s, buys_m5=5), CTX), "counts hide size"


def test_the_book_is_thirteen_frozen_strategies_with_controls() -> None:
    assert len(ARMS) == 13
    controls = [a for a in ARMS if a.is_control]
    assert len(controls) == 3 and {a.control for a in controls} == {"time"}
    for arm in ARMS:
        assert arm.entry_words and arm.exit_words, arm.name
        assert arm.tf == "5m", f"{arm.name}: run 2 is 5m only"
        # Run 1 priced stops at -7.6% a trade; run 2 carries none.
        assert arm.stop is None and arm.target_r is None, arm.name
        if not arm.is_control:
            assert BY_NAME[arm.vs].tf in {arm.tf, "5m"}, arm.name
    # Every entry is the base rule with one thing changed.
    for arm in ARMS:
        if arm.rule and arm.rule != M5:
            changed = [f for f in M5.__slots__
                       if getattr(arm.rule, f) != getattr(M5, f)]
            assert changed, arm.name


def test_a_coin_is_the_same_every_time() -> None:
    assert coin("RND_60", "p:1") == coin("RND_60", "p:1")
    assert coin("RND_60", "p:1") != coin("RND_DOWN", "p:1")
    draws = [coin("RND_60", f"p:{i}") for i in range(4000)]
    assert 0.45 < sum(d < 0.5 for d in draws) / len(draws) < 0.55


def test_a_round_trip_pays_fees_and_impact_both_ways() -> None:
    price, liq = Decimal("1.0"), Decimal("200000")
    fill, tokens, moved = buy(price, liq, 30, Decimal(100))
    assert moved == Decimal("0.001")
    assert fill > price
    out, proceeds, _ = sell(price, liq, 30, tokens)
    assert out < price
    # Flat market: the loss is the toll, ~0.6% fees + 0.2% impact + $0.04.
    assert Decimal("-0.0090") < proceeds / 100 - 1 < Decimal("-0.0075")


def test_an_unfillable_buy_is_refused() -> None:
    assert buy(Decimal(1), Decimal(5_000), 30, Decimal(100)) is None, "4% impact"
    assert buy(Decimal(1), None, 30, Decimal(100)) is None


def test_pumpswap_charges_its_market_cap_tier() -> None:
    assert config.fee_bps("raydium", Decimal(10)) == config.FEE_BPS
    assert config.fee_bps("pumpswap", Decimal(100)) == 125 + 10
    assert config.fee_bps("pumpswap", Decimal(1_000_000)) == 30 + 10


def row(address: str, base: str, quote: str, liq: float, vol: float) -> PairRow:
    return PairRow(address, base, quote, "X", "raydium", Decimal(1), Decimal(1),
                   Decimal(liq), None, None, Decimal(vol), None, None, None, None,
                   None, None, None)


def test_the_pool_is_the_most_traded_quoted_in_sol_or_dollars() -> None:
    mint = "TOKEN"
    rows = [row("a", mint, config.WSOL_MINT, 900_000, 10),
            row("b", mint, config.USDC_MINT, 60_000, 500),
            row("c", mint, "SomeOtherToken", 5_000_000, 9_000),   # priced through a token
            row("d", "OTHER", config.WSOL_MINT, 5_000_000, 9_000),  # our token is the QUOTE
            row("e", mint, config.WSOL_MINT, 10_000, 99_000)]      # under the floor
    assert best_pair(rows, mint).pair_address == "b"
    assert best_pair(rows[2:4], mint) is None


def test_age_is_the_first_pool_not_the_mint() -> None:
    listed = parse_listed({"id": "M", "createdAt": "2026-08-01T00:00:00Z",
                           "firstPool": {"createdAt": "2026-09-18T00:00:00Z"}}, "x")
    assert listed.born_at == datetime(2026, 9, 18, tzinfo=UTC)


# --- wallets ------------------------------------------------------------------

def trade(minute: int, hold: int, ret: float, impact: float = 0.0) -> board.Trade:
    return board.Trade(T0 + timedelta(minutes=minute),
                       T0 + timedelta(minutes=minute + hold), ret, impact, impact)


START = float(config.START_USD)


def test_a_split_wallet_skips_what_it_cannot_fund() -> None:
    # Three trades open at once; a whole-wallet ticket can hold one of them.
    trades = [trade(0, 30, 0.10), trade(1, 30, 0.10), trade(2, 30, 0.10)]
    one = board.walk(trades, 1)
    assert (one.funded, one.skipped) == (1, 2)
    assert one.end == pytest.approx(START * 1.10)
    ten = board.walk(trades, 10)
    assert (ten.funded, ten.skipped) == (3, 0)
    assert ten.end == pytest.approx(START * 1.03)


def test_a_bigger_ticket_pays_more_impact() -> None:
    t = [trade(0, 5, 0.0, impact=0.002)]
    assert board.walk(t, 1).end < board.walk(t, 10).end == pytest.approx(START)


def test_the_wallet_low_counts_losses_as_they_close() -> None:
    w = board.walk([trade(0, 5, -0.5), trade(10, 5, 0.5)], 1)
    assert w.low == pytest.approx(START * 0.5)
    assert w.end == pytest.approx(START * 0.75)


def test_error_is_measured_between_hours() -> None:
    same_hour = [trade(i, 1, 0.01 * (1 if i % 2 else -1)) for i in range(40)]
    assert board.stats(same_hour).se is None, "one hour is one observation"
    spread = [trade(60 * i, 1, 0.01 * (1 if i % 2 else -1)) for i in range(40)]
    s = board.stats(spread)
    assert s.hours == 40 and s.se == pytest.approx(0.01 / 40 ** 0.5)


def test_a_verdict_never_claims_more_than_the_numbers() -> None:
    few = board.stats([trade(60 * i, 1, 0.05) for i in range(10)])
    assert board.verdict(few, 9.9, "RND_60", is_control=False).startswith("waiting")
    many = board.stats([trade(60 * i, 1, 0.01 + 0.001 * (i % 3)) for i in range(40)])
    verdict = lambda z: board.verdict(many, z, "RND_60", is_control=False)  # noqa: E731
    assert verdict(2.9) == "no different from RND_60 yet"
    assert verdict(3.1) == "beats RND_60 and makes money"
    assert board.verdict(many, 3.1, "RND_60", is_control=True).startswith("control")


def test_rule_words_are_the_rule() -> None:
    assert "3x normal volume" in M5.words()
    assert "$1M+" in BY_NAME["DEEP_60"].entry_words
    assert "up 2%-5%" in BY_NAME["QUIET_60"].entry_words
    assert "3-10x normal volume" in BY_NAME["QUIET_60"].entry_words
    assert "+15%" in BY_NAME["BASE_TP15"].exit_words
    assert "down 10%+ on the day" in BY_NAME["RND_DOWN"].entry_words
    rolling = Rule(min_ret=0.04, min_vol_x=3.0, rolling=True)
    assert rolling.words().startswith("the last 5 minutes")


def test_only_busy_candles_count() -> None:
    """Twenty trades per five minutes the bar spans: four a minute."""
    need = config.MIN_TRADES_PER_5M
    assert busy(bar(0, 1, 1.05, buys=need - 5, sells=5))
    assert not busy(bar(0, 1, 1.05, buys=2, sells=0)), "the first live trade: two buys"
    fifteen = replace(bar(0, 1, 1.05, buys=need, sells=need), parts=3)
    assert not busy(fifteen), "a 15m bar needs three times as many"
    assert busy(replace(fifteen, buys=2 * need))


def test_a_pump_with_more_sellers_is_still_momentum() -> None:
    """ANONCOIN, 08:15 UTC 2026-09-19: +11.2% on 16x volume, closing at its high,
    two buys and thirty sells — one big buyer among many small sellers. The
    first rule refused it on the count; run 2 asks about counts nowhere."""
    history = quiet()
    o = history[-1].close
    anoncoin = impulse(48, o, 0.112, vol=16_000, buys=2, sells=30)
    f = features(anoncoin, history, 300, impulse_ret=0.02)
    assert fires(M5, f, CTX)
    assert all(a.rule.min_buy_ratio is None for a in ARMS if a.rule)


def test_a_bad_print_is_refused_either_way() -> None:
    """ANTFUN, 19 Sep: DexScreener printed $0.0000005 for a coin at $0.083.
    A buy filled on that print books millions of percent, a stop fires on a
    pool that never moved. Refused both ways; a real level is taken after two
    minutes."""
    from datetime import UTC, datetime, timedelta

    from app.labs.momentum.lab import MomentumLab
    from app.labs.momentum.models import MomPair

    now = datetime(2026, 9, 19, 13, 0, tzinfo=UTC)
    pair = MomPair(pair_address="P", mint="M", quote_mint=config.WSOL_MINT,
                   born_at=now - timedelta(days=30), admitted_at=now, listed_at=now,
                   last_price=Decimal("0.083"), last_sample_at=now - timedelta(seconds=30),
                   glitches=0)

    def row(price: str, at: datetime) -> PairRow:
        return replace(PairRow("P", "M", config.WSOL_MINT, "X", "raydium", Decimal(price),
                               None, Decimal(1_000_000), None, None, None, None, None,
                               None, None, None, None, None),
                       fetched_at=at + timedelta(seconds=config.FEED_LAG_S))

    lab = MomentumLab(None, feeds=None, now=now)  # type: ignore[arg-type]
    assert lab._accept({"P": pair}, {"P": row("0.0000005", now)}) == {}
    assert lab._accept({"P": pair}, {"P": row("0.30", now)}) == {}
    assert pair.glitches == 2
    assert "P" in lab._accept({"P": pair}, {"P": row("0.084", now)})
    later = now + timedelta(minutes=3)
    crash = lab._accept({"P": pair}, {"P": row("0.02", later)})
    assert "P" in crash, "a real crash, taken late"
