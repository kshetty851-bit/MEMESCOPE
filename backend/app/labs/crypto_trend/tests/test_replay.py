"""The replay on a synthetic three-coin market: one long, one short, one
coin that never trades, every fill reconciled from first principles — and
the hindsight test."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.labs.crypto_trend import config
from app.labs.crypto_trend.candles import INTERVAL_MS, from_ms, to_ms
from app.labs.crypto_trend.models import CtReplayRun
from app.labs.crypto_trend.replay import (
    FUNDING_INTERVAL_MS,
    Dataset,
    grid_combos,
    overrides,
    parse_grid,
    parse_params,
    run_replay,
    store_run,
    write_outputs,
)
from app.labs.crypto_trend.strategy import LONG, SHORT
from app.labs.crypto_trend.tests.fakes import sideways_closes, synthetic_candles
from app.labs.crypto_trend.trend import compute_trend_state, compute_trend_states

END = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)  # a 4h boundary
END_MS = to_ms(END)
N4 = 240
PARAMS = {"CHOP_BREADTH_MIN": 0.3}  # one of three coins on each side


def gentle(n: int, *, start: float, up: int = 9, down: int = 3,
           sign: float = 1.0) -> list[float]:
    """Nine bars of +1, three of -0.5: a trend whose pullbacks never reach a
    2-ATR stop. `sign` -1 mirrors it."""
    out, price = [], start
    for i in range(n):
        price += sign * (1.0 if i % (up + down) < up else -0.5)
        out.append(price)
    return out


def crash(closes: list[float], bars: int, step: float) -> list[float]:
    out, price = list(closes), closes[-1]
    for _ in range(bars):
        price += step
        out.append(price)
    return out


def continued(closes: list[float], extra: int) -> list[float]:
    """`closes`, then `extra` more bars wandering around the last price."""
    last = closes[-1]
    return list(closes) + [last + w for w in sideways_closes(extra, centre=0.0)]


def build(extra: int = 0) -> Dataset:
    """AAA trends up then crashes, BBB trends down then spikes, CCC chops.
    `extra` appends that many 4h bars (and their hours) AFTER `END`, leaving
    every candle inside the window byte-identical."""
    end_ms = END_MS + extra * INTERVAL_MS["4h"]
    paths4 = {
        "AAAUSDT": crash(gentle(N4 - 12, start=100.0), 12, -3.0),
        "BBBUSDT": crash(gentle(N4 - 12, start=400.0, sign=-1.0), 12, +3.0),
        "CCCUSDT": sideways_closes(N4),
    }
    paths1 = {
        "AAAUSDT": gentle(4 * N4, start=100.0),
        "BBBUSDT": gentle(4 * N4, start=400.0, sign=-1.0),
        "CCCUSDT": sideways_closes(4 * N4),
    }
    candles = {}
    for symbol in paths4:
        candles[(symbol, "4h")] = synthetic_candles(
            continued(paths4[symbol], extra), symbol=symbol, timeframe="4h", end_ms=end_ms)
        candles[(symbol, "1h")] = synthetic_candles(
            continued(paths1[symbol], 4 * extra), symbol=symbol, timeframe="1h", end_ms=end_ms)
    return Dataset(candles=candles, funding={}, universe=list(paths4))


START = END - timedelta(days=35)


@pytest.fixture(scope="module")
def result():
    return run_replay(build(), start=START, end=END, params=PARAMS)


# --- the trades ------------------------------------------------------------------------

def test_one_long_one_short_and_one_coin_never_traded(result) -> None:
    assert sorted((t.symbol, t.side) for t in result.trades) == [
        ("AAAUSDT", LONG), ("BBBUSDT", SHORT)]
    assert result.open_positions == []
    assert not any("CCCUSDT" in o for b in result.bars for o in b.orders)
    assert all(t.reason in ("trail_stop", "hard_stop") for t in result.trades)


def test_entries_fill_at_the_open_after_the_flip_bar(result) -> None:
    dataset = build()
    for t in result.trades:
        c4 = dataset.candles[(t.symbol, "4h")]
        entry = next(c for c in c4 if c.open_time == t.opened_at)
        slip = 1 + 5e-4 if t.side == LONG else 1 - 5e-4
        assert t.entry_price == pytest.approx(float(entry.open) * slip)
        bar = next(b for b in result.bars if to_ms(b.time) == to_ms(entry.open_time) - 1)
        before = result.bars[result.bars.index(bar) - 1]
        bias = "LONG_BIAS" if t.side == LONG else "SHORT_BIAS"
        assert bar.verdicts[t.symbol] == bias and before.verdicts[t.symbol] != bias
        exit_candle = next(c for c in c4 if c.open_time == t.closed_at)
        slip_out = 1 - 5e-4 if t.side == LONG else 1 + 5e-4
        assert t.exit_price == pytest.approx(float(exit_candle.open) * slip_out)


def test_every_trade_reconciles_from_first_principles(result) -> None:
    """fees on both fills, the fallback funding at every 8h boundary held
    across (at the close just before it), and P&L net of both."""
    dataset = build()
    for t in result.trades:
        c4 = dataset.candles[(t.symbol, "4h")]
        by_close = {to_ms(c.close_time): float(c.close) for c in c4}
        opened, closed = to_ms(t.opened_at), to_ms(t.closed_at)
        boundaries = range((opened // FUNDING_INTERVAL_MS + 1) * FUNDING_INTERVAL_MS,
                           closed + 1, FUNDING_INTERVAL_MS)
        sign = 1.0 if t.side == LONG else -1.0
        funding = sum(0.0001 * t.qty * by_close[b - 1] * sign for b in boundaries)
        fees = (t.entry_price + t.exit_price) * t.qty * 0.0005
        expected = (t.exit_price - t.entry_price) * t.qty * sign - fees - funding
        assert t.funding == pytest.approx(funding, abs=1e-9)
        assert t.fees == pytest.approx(fees, abs=1e-9)
        assert t.pnl_usd == pytest.approx(expected, abs=1e-9)
        assert t.pnl_r == pytest.approx(t.pnl_usd / t.risk_usd)
        assert t.implied_leverage <= 0.2 + 1e-9


def test_risk_per_trade_is_one_percent_of_equity_at_the_decision(result) -> None:
    for t in result.trades:
        bar = next(b for b in result.bars if to_ms(b.time) == to_ms(t.opened_at) - 1)
        assert t.risk_usd <= 0.01 * bar.equity + 1e-6


def test_the_summary_adds_up(result) -> None:
    s = result.summary
    assert s["trades"] == 2 and s["long"]["trades"] == 1 and s["short"]["trades"] == 1
    assert s["net_pnl"] == pytest.approx(sum(t.pnl_usd for t in result.trades), abs=0.01)
    assert s["final_equity"] == pytest.approx(1000 + s["net_pnl"], abs=0.01)
    assert s["fees_total"] == pytest.approx(sum(t.fees for t in result.trades), abs=0.01)
    assert s["funding_total"] == pytest.approx(sum(t.funding for t in result.trades), abs=0.01)
    assert sum(v["trades"] for v in s["pnl_by_exit_reason"].values()) == 2
    assert 0 < s["exposure_pct"] < 100 and s["max_drawdown_pct"] >= 0
    assert s["window"]["bars"] == len(result.bars) and s["params"] == PARAMS
    assert s["open_at_end"] == {"positions": 0, "unrealised": 0.0}


# --- no hindsight -----------------------------------------------------------------------

def test_the_future_changes_nothing(result) -> None:
    later = run_replay(build(extra=30), start=START, end=END, params=PARAMS)
    assert later.trades == result.trades
    assert later.equity_curve == result.equity_curve
    assert [b.verdicts for b in later.bars] == [b.verdicts for b in result.bars]
    assert later.summary == result.summary


def test_the_state_series_equals_a_fresh_computation_on_every_prefix() -> None:
    candles = build().candles[("AAAUSDT", "4h")]
    series = compute_trend_states("AAAUSDT", "4h", candles, computed_at=END)
    for i in range(0, len(candles), 7):
        fresh = compute_trend_state("AAAUSDT", "4h", candles[:i + 1], computed_at=END)
        assert fresh == series[i]


# --- parameters ---------------------------------------------------------------------------

def test_overrides_reach_the_engine_and_are_restored() -> None:
    before = (config.ADX_MIN, config.STOP_ATR, config.MAX_BARS)
    with overrides({"ADX_MIN": "25", "STOP_ATR": 3, "MAX_BARS": "12.0"}):
        assert (config.ADX_MIN, config.STOP_ATR, config.MAX_BARS) == (25.0, 3.0, 12)
    assert before == (config.ADX_MIN, config.STOP_ATR, config.MAX_BARS)
    with pytest.raises(ValueError), overrides({"NOT_A_PARAM": 1}):
        pass
    with pytest.raises(ValueError), overrides({"enabled": 1}):
        pass


def test_a_different_stop_changes_the_result() -> None:
    tight = run_replay(build(), start=START, end=END, params={**PARAMS, "STOP_ATR": 0.5})
    loose = run_replay(build(), start=START, end=END, params=PARAMS)
    assert tight.summary != loose.summary


def test_grid_parsing_and_the_cap() -> None:
    assert parse_params(["A=1", "B = x"]) == {"A": "1", "B": "x"}
    default = parse_grid([])
    assert len(grid_combos(default)) == 18
    assert grid_combos(parse_grid(["STOP_ATR=1,2", "ADX_MIN=20"])) == [
        {"STOP_ATR": "1", "ADX_MIN": "20"}, {"STOP_ATR": "2", "ADX_MIN": "20"}]
    with pytest.raises(ValueError, match="cap"):
        grid_combos({"A": list(range(51))})


# --- outputs ----------------------------------------------------------------------

def test_outputs_are_written(result, tmp_path) -> None:
    run_dir = write_outputs(result, tmp_path / "run")
    trades = (run_dir / "trades.csv").read_text().splitlines()
    assert len(trades) == 1 + len(result.trades)
    assert trades[0].startswith("symbol,side,qty")
    equity = (run_dir / "equity.csv").read_text().splitlines()
    assert len(equity) == 1 + len(result.equity_curve)
    assert json.loads((run_dir / "summary.json").read_text()) == result.summary


@pytest.mark.integration
async def test_a_run_is_stored(lab_session, result) -> None:
    row = await store_run(lab_session, result, "test")
    stored = (await lab_session.execute(
        select(CtReplayRun).where(CtReplayRun.id == row.id))).scalar_one()
    assert stored.params == PARAMS and stored.trades == 2
    assert stored.summary["net_pnl"] == result.summary["net_pnl"]
    assert stored.window_start == START and stored.label == "test"
    assert from_ms(to_ms(stored.window_end)) == END
