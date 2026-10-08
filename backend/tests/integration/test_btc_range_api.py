"""`/api/v1/labs/btc-range/*` against real rows.

The properties defended here:

* with the flag off `/status` says so and never touches the candle table -
  "off" must not read as "found nothing";
* the live book never contains a trade from before it started, however much
  warm-up history sits behind it;
* a backtest computes and writes nothing, and says why when it cannot run
  rather than estimating;
* the JSON keys match the page's `types.ts` exactly - the page is built against
  them and a rename breaks it with no build error.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.labs.btc_range import repository, service
from app.labs.btc_range.execution import run_backtest
from app.labs.btc_range.source import Kline
from app.labs.btc_range.types import (
    TIMEFRAME_SECONDS,
    Call,
    Candle,
    ExitReason,
    OpenPosition,
    StrategyConfig,
)
from app.models.btc_range import BtcCandle
from tests.unit.labs.btc_range.builders import oscillation

pytestmark = pytest.mark.integration

PREFIX = f"{settings.API_V1_PREFIX}/labs/btc-range"
STEP = timedelta(seconds=TIMEFRAME_SECONDS)


def _floor(moment: datetime) -> datetime:
    return moment - timedelta(
        minutes=moment.minute % 15, seconds=moment.second, microseconds=moment.microsecond
    )


#: The open time of the candle that is forming right now. Everything seeded here
#: ends before it, so every seeded candle is genuinely closed at request time.
NOW_OPEN = _floor(datetime.now(UTC))


def _retime(candles: list[Candle], *, last_open: datetime) -> list[Candle]:
    first = last_open - STEP * (len(candles) - 1)
    return [replace(c, open_time=first + STEP * i) for i, c in enumerate(candles)]


async def _seed(
    session: AsyncSession,
    n: int = 288,
    *,
    last_open: datetime | None = None,
    closed: bool = True,
) -> list[Candle]:
    """`n` oscillating candles ending at `last_open` (default: the last closed one)."""
    candles = _retime(oscillation(n), last_open=last_open or NOW_OPEN - STEP)
    await repository.upsert_candles(
        session,
        [Kline(c, c.open_time + STEP - timedelta(milliseconds=1), closed) for c in candles],
    )
    await session.flush()
    return candles


async def _row_count(session: AsyncSession) -> int:
    return int(
        (await session.execute(select(func.count()).select_from(BtcCandle))).scalar_one()
    )


@pytest.fixture
def lab_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LAB_BTC_RANGE_ENABLED", True)


@pytest.fixture
def lab_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LAB_BTC_RANGE_ENABLED", False)


def _live_start(candles: list[Candle], index: int) -> datetime:
    return candles[index].open_time


# --- /status: flag off -------------------------------------------------------


async def test_flag_off_says_so_and_queries_no_candles(
    client: AsyncClient,
    db_session: AsyncSession,
    lab_off: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed(db_session)

    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("the candle table was queried with the lab off")

    for name in ("closed_candles", "latest_candle", "stats"):
        monkeypatch.setattr(repository, name, boom)

    body = (await client.get(f"{PREFIX}/status")).json()
    assert body["running"] is False
    assert "LAB_BTC_RANGE_ENABLED" in body["reason"]
    assert body["price"] is None
    assert body["signal"] is None
    assert body["book"] is None
    assert body["candles"] == []
    assert body["data"] == {
        "candles": 0,
        "first_at": None,
        "last_closed_at": None,
        "stale": False,
    }
    assert body["paper_only"] is True
    assert body["symbol"] == "BTCUSDT"
    assert body["timeframe"] == "15m"


# --- /status: flag on --------------------------------------------------------


async def test_flag_on_without_candles_points_at_the_backfill(
    client: AsyncClient, lab_on: None
) -> None:
    body = (await client.get(f"{PREFIX}/status")).json()
    assert body["running"] is True
    assert "backfill" in body["reason"]
    assert body["signal"] is None
    assert body["book"] is None
    assert body["price"] is None
    assert body["candles"] == []
    assert body["data"]["candles"] == 0


async def test_status_with_candles_has_signal_book_and_chart(
    client: AsyncClient,
    db_session: AsyncSession,
    lab_on: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candles = await _seed(db_session, 288)
    live_start = _live_start(candles, 150)
    monkeypatch.setattr(settings, "LAB_BTC_RANGE_LIVE_START", live_start)

    response = await client.get(f"{PREFIX}/status")
    assert response.status_code == 200
    body = response.json()

    assert body["running"] is True
    assert body["reason"] is None
    last = candles[-1]
    assert body["price"] == {
        "value": service.price_str(last.close),
        "at": last.open_time.isoformat().replace("+00:00", "Z"),
        "candle_closed": True,
    }
    assert body["data"]["candles"] == 288
    assert body["data"]["stale"] is False
    assert body["data"]["first_at"] == candles[0].open_time.isoformat().replace("+00:00", "Z")
    assert body["data"]["last_closed_at"] == last.open_time.isoformat().replace("+00:00", "Z")

    signal = body["signal"]
    assert signal["call"] in {"long", "short", "wait"}
    assert signal["at"] == body["data"]["last_closed_at"]
    assert signal["range"] is not None
    assert all(r["text"] for r in signal["reasons"])
    if signal["call"] == "wait":
        assert signal["entry"] is None and signal["take_profit"] is None
    else:
        assert signal["entry"] is not None and signal["stop_loss"] is not None

    chart = body["candles"]
    assert len(chart) == 192
    assert [c["t"] for c in chart] == sorted(c["t"] for c in chart)
    assert chart[-1]["c"] == service.price_str(last.close)

    book = body["book"]
    assert book["started_at"] == live_start.isoformat().replace("+00:00", "Z")
    assert book["config_version"] == 1
    assert book["config"] == service.config_out(StrategyConfig()).model_dump()
    assert book["metrics"]["trades"] == book["long"]["trades"] + book["short"]["trades"]
    assert book["metrics"]["trades"] > 0
    assert book["metrics"]["ending_equity"] == book["equity_curve"][-1]["equity"]
    assert len(book["trades"]) <= 100
    entries = [t["entry_at"] for t in book["trades"]]
    assert entries == sorted(entries, reverse=True), "newest first"
    assert 2 <= len(book["equity_curve"]) <= 300


async def test_the_book_matches_a_direct_replay_of_the_stored_candles(
    client: AsyncClient,
    db_session: AsyncSession,
    lab_on: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live record and a backtest cannot disagree: same function, same candles."""
    candles = await _seed(db_session, 288)
    monkeypatch.setattr(settings, "LAB_BTC_RANGE_LIVE_START", _live_start(candles, 150))
    cfg = StrategyConfig()

    book = (await client.get(f"{PREFIX}/status")).json()["book"]
    direct = run_backtest(candles[150 - cfg.lookback :], cfg, close_open_at_end=False)

    assert book["metrics"] == service.metrics_out(direct.metrics).model_dump()
    assert [t["pnl"] for t in reversed(book["trades"])] == [
        format(t.pnl, "f") for t in direct.trades
    ]


async def test_warm_up_candles_never_leak_trades_into_the_book(
    client: AsyncClient,
    db_session: AsyncSession,
    lab_on: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candles = await _seed(db_session, 288)
    live_start = _live_start(candles, 150)
    monkeypatch.setattr(settings, "LAB_BTC_RANGE_LIVE_START", live_start)

    # Precondition: the strategy WOULD have traded before the book started, so
    # the assertion below is not vacuous.
    everything = run_backtest(candles, StrategyConfig())
    before = [t for t in everything.trades if t.entry_at < live_start]
    assert before, "fixture must trade before the live start"

    book = (await client.get(f"{PREFIX}/status")).json()["book"]
    assert book["trades"], "and after it"
    for trade in book["trades"]:
        assert datetime.fromisoformat(trade["entry_at"]) >= live_start
    # The book's own count is what a replay from the warm-up start produces,
    # which is strictly fewer than a replay of everything.
    assert book["metrics"]["trades"] == len(book["trades"]) < len(everything.trades)
    for point in book["equity_curve"]:
        assert datetime.fromisoformat(point["at"]) >= live_start


async def test_book_and_backtest_trade_lists_are_capped_keeping_the_newest(
    client: AsyncClient,
    db_session: AsyncSession,
    lab_on: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candles = await _seed(db_session, 288)
    monkeypatch.setattr(settings, "LAB_BTC_RANGE_LIVE_START", _live_start(candles, 96))
    monkeypatch.setattr(service, "BOOK_TRADES_CAP", 3)
    monkeypatch.setattr(service, "BACKTEST_TRADES_CAP", 3)

    book = (await client.get(f"{PREFIX}/status")).json()["book"]
    assert book["metrics"]["trades"] > 3
    assert len(book["trades"]) == 3

    result = (await client.post(f"{PREFIX}/backtest", json={})).json()
    assert result["metrics"]["trades"] > 3
    assert len(result["trades"]) == 3
    exits = [t["exit_at"] for t in result["trades"]]
    assert exits == sorted(exits), "oldest first"
    # The newest three of the whole run, not the first three.
    full = run_backtest(candles, StrategyConfig())
    assert result["trades"][-1]["exit_at"] == full.trades[-1].exit_at.isoformat().replace(
        "+00:00", "Z"
    )


async def test_a_forming_candle_is_the_price_but_not_the_data(
    client: AsyncClient, db_session: AsyncSession, lab_on: None
) -> None:
    candles = await _seed(db_session, 120)
    forming = Candle(
        NOW_OPEN, Decimal("100"), Decimal("120"), Decimal("90"), Decimal("111.5"), Decimal(1)
    )
    await repository.upsert_candles(
        db_session, [Kline(forming, NOW_OPEN + STEP - timedelta(milliseconds=1), False)]
    )
    await db_session.flush()

    body = (await client.get(f"{PREFIX}/status")).json()
    assert body["price"]["value"] == "111.50"
    assert body["price"]["candle_closed"] is False
    assert body["data"]["candles"] == 120
    assert body["data"]["last_closed_at"] == candles[-1].open_time.isoformat().replace(
        "+00:00", "Z"
    )
    assert all(
        c["t"] != forming.open_time.isoformat().replace("+00:00", "Z") for c in body["candles"]
    )


async def test_stale_means_the_newest_closed_candle_closed_over_two_periods_ago(
    client: AsyncClient, db_session: AsyncSession, lab_on: None
) -> None:
    # Closed 3 periods ago (opened 4 periods ago) -> stale.
    await _seed(db_session, 120, last_open=NOW_OPEN - 4 * STEP)
    assert (await client.get(f"{PREFIX}/status")).json()["data"]["stale"] is True


async def test_fresh_data_is_not_stale(
    client: AsyncClient, db_session: AsyncSession, lab_on: None
) -> None:
    await _seed(db_session, 120, last_open=NOW_OPEN - STEP)
    assert (await client.get(f"{PREFIX}/status")).json()["data"]["stale"] is False


async def test_too_few_candles_is_a_valid_wait_not_an_error(
    client: AsyncClient, db_session: AsyncSession, lab_on: None
) -> None:
    await _seed(db_session, 10)
    body = (await client.get(f"{PREFIX}/status")).json()
    assert body["signal"]["call"] == "wait"
    assert body["signal"]["range"] is None
    assert [r["code"] for r in body["signal"]["reasons"]] == ["insufficient_data"]
    assert body["book"]["metrics"]["trades"] == 0
    assert body["book"]["metrics"]["win_rate"] is None
    assert len(body["candles"]) == 10


# --- /config -----------------------------------------------------------------


async def test_config_publishes_defaults_bounds_and_the_data_range(
    client: AsyncClient, db_session: AsyncSession, lab_off: None
) -> None:
    candles = await _seed(db_session, 120)
    response = await client.get(f"{PREFIX}/config")  # works with the flag off
    assert response.status_code == 200
    body = response.json()
    assert body["config_version"] == 1
    assert body["defaults"] == service.config_out(StrategyConfig()).model_dump()
    assert set(body["bounds"]) == set(body["defaults"])
    assert body["bounds"]["lookback"] == {
        "min": "24",
        "max": "672",
        "step": "1",
        "label": body["bounds"]["lookback"]["label"],
        "help": body["bounds"]["lookback"]["help"],
        "kind": "int",
        "group": "range",
    }
    assert body["bounds"]["entry_zone"]["min"] == "0.05"
    assert body["bounds"]["allow_long"]["kind"] == "bool"
    assert {b["group"] for b in body["bounds"].values()} == {"range", "entries", "account"}
    assert body["data_first_at"] == candles[0].open_time.isoformat().replace("+00:00", "Z")
    assert body["data_last_at"] == candles[-1].open_time.isoformat().replace("+00:00", "Z")


async def test_config_with_no_candles_has_null_data_range(client: AsyncClient) -> None:
    body = (await client.get(f"{PREFIX}/config")).json()
    assert body["data_first_at"] is None
    assert body["data_last_at"] is None


# --- /backtest ---------------------------------------------------------------


async def test_backtest_default_window_runs_and_reports_what_it_ran(
    client: AsyncClient, db_session: AsyncSession, lab_off: None
) -> None:
    candles = await _seed(db_session, 288)  # works with the flag off
    response = await client.post(f"{PREFIX}/backtest", json={})
    assert response.status_code == 200
    body = response.json()

    assert body["available"] is True
    assert body["reason"] is None
    assert body["config"] == service.config_out(StrategyConfig()).model_dump()
    assert body["candles"] == 288 - 96
    assert body["start"] == candles[96].open_time.isoformat().replace("+00:00", "Z")
    assert body["end"] == candles[-1].open_time.isoformat().replace("+00:00", "Z")

    direct = run_backtest(candles, StrategyConfig())
    assert body["metrics"] == service.metrics_out(direct.metrics).model_dump()
    assert body["long"]["trades"] + body["short"]["trades"] == body["metrics"]["trades"]
    assert len(body["trades"]) == len(direct.trades)
    entries = [t["entry_at"] for t in body["trades"]]
    assert entries == sorted(entries), "oldest first"
    assert body["signal_counts"] == {
        "long": direct.signal_counts[Call.LONG],
        "short": direct.signal_counts[Call.SHORT],
        "wait": direct.signal_counts[Call.WAIT],
    }
    waits = body["wait_reasons"]
    assert waits and all(set(w) == {"code", "text", "count"} for w in waits)
    assert sum(w["count"] for w in waits) == body["signal_counts"]["wait"]
    assert [(-w["count"], w["code"]) for w in waits] == sorted(
        (-w["count"], w["code"]) for w in waits
    )
    assert 2 <= len(body["equity_curve"]) <= 500


async def test_backtest_runs_the_config_it_was_given_and_echoes_it(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed(db_session, 288)
    body = (
        await client.post(
            f"{PREFIX}/backtest",
            json={
                "config": {"allow_short": False, "starting_balance": "5000", "lookback": 48}
            },
        )
    ).json()
    assert body["available"] is True
    assert body["config"]["allow_short"] is False
    assert body["config"]["starting_balance"] == "5000"
    assert body["config"]["lookback"] == 48
    assert body["config"]["entry_zone"] == "0.20", "omitted fields take the defaults"
    assert body["short"]["trades"] == 0
    assert body["signal_counts"]["short"] == 0
    assert {t["side"] for t in body["trades"]} <= {"long"}
    assert body["candles"] == 288 - 48


async def test_backtest_honours_an_explicit_window_inclusively(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    candles = await _seed(db_session, 288)
    start, end = candles[150].open_time, candles[250].open_time
    body = (
        await client.post(
            f"{PREFIX}/backtest", json={"start": start.isoformat(), "end": end.isoformat()}
        )
    ).json()
    assert body["available"] is True
    assert body["start"] == start.isoformat().replace("+00:00", "Z")
    assert body["end"] == end.isoformat().replace("+00:00", "Z"), (
        "the candle opening at `end` is in"
    )
    assert body["candles"] == 101


@pytest.mark.parametrize(
    "config",
    [
        {"lookback": 23},
        {"lookback": 673},
        {"entry_zone": "0.5"},
        {"fee_bps": "-1"},
        {"max_leverage": 6},
        {"starting_balance": "99"},
        {"no_such_field": 1},
        {"min_width_pct": "4", "max_width_pct": "2"},
    ],
)
async def test_out_of_bounds_config_is_a_422(
    client: AsyncClient, db_session: AsyncSession, config: dict[str, object]
) -> None:
    await _seed(db_session, 120)
    assert (
        await client.post(f"{PREFIX}/backtest", json={"config": config})
    ).status_code == 422


async def test_a_window_over_365_days_is_a_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed(db_session, 120)
    end = NOW_OPEN
    start = end - timedelta(days=366)
    response = await client.post(
        f"{PREFIX}/backtest", json={"start": start.isoformat(), "end": end.isoformat()}
    )
    assert response.status_code == 422
    assert "365" in response.text
    ok = await client.post(
        f"{PREFIX}/backtest",
        json={"start": (end - timedelta(days=365)).isoformat(), "end": end.isoformat()},
    )
    assert ok.status_code == 200


async def test_an_inverted_window_is_a_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed(db_session, 120)
    t = NOW_OPEN.isoformat()
    assert (
        await client.post(f"{PREFIX}/backtest", json={"start": t, "end": t})
    ).status_code == 422


async def test_too_few_candles_is_unavailable_with_a_reason_not_an_estimate(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed(db_session, 50)  # lookback 96 needs 97
    response = await client.post(f"{PREFIX}/backtest", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert "50" in body["reason"] and "97" in body["reason"]
    assert body["candles"] == 0
    assert body["trades"] == []
    assert body["equity_curve"] == []
    assert body["wait_reasons"] == []
    assert body["metrics"]["trades"] == 0
    assert body["metrics"]["win_rate"] is None
    assert body["config"] == service.config_out(StrategyConfig()).model_dump()


async def test_a_backtest_with_no_candles_at_all_says_to_run_the_backfill(
    client: AsyncClient,
) -> None:
    body = (await client.post(f"{PREFIX}/backtest", json={})).json()
    assert body["available"] is False
    assert "backfill" in body["reason"]


async def test_a_backtest_writes_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed(db_session, 288)
    before = await _row_count(db_session)
    snapshot = (
        await db_session.execute(
            select(BtcCandle.open_time, BtcCandle.close, BtcCandle.updated_at)
        )
    ).all()

    for payload in ({}, {"config": {"lookback": 24}}, {"config": {"lookback": 5}}):
        await client.post(f"{PREFIX}/backtest", json=payload)
    await client.get(f"{PREFIX}/config")

    assert await _row_count(db_session) == before
    after = (
        await db_session.execute(
            select(BtcCandle.open_time, BtcCandle.close, BtcCandle.updated_at)
        )
    ).all()
    assert sorted(after) == sorted(snapshot)


# --- the wire contract -------------------------------------------------------

TYPES_TS = Path(__file__).resolve().parents[3] / "frontend/src/labs/btc-range/types.ts"

#: Mirrors `types.ts`. Checked against the file itself too when the repo root is
#: reachable (it is not inside the backend container), so neither copy can drift
#: alone.
KEYS: dict[str, set[str]] = {
    "StatusOut": {
        "running",
        "reason",
        "symbol",
        "timeframe",
        "paper_only",
        "price",
        "data",
        "signal",
        "book",
        "candles",
    },
    "DataOut": {"candles", "first_at", "last_closed_at", "stale"},
    "PriceOut": {"value", "at", "candle_closed"},
    "SignalOut": {
        "at",
        "price",
        "call",
        "confidence",
        "range",
        "entry",
        "take_profit",
        "stop_loss",
        "reward_risk",
        "reasons",
    },
    "RangeOut": {
        "support",
        "resistance",
        "mid",
        "width_pct",
        "position",
        "touches_support",
        "touches_resistance",
        "trend_efficiency",
        "confidence",
        "regime",
    },
    "ReasonOut": {"code", "text"},
    "BookOut": {
        "started_at",
        "config_version",
        "config",
        "metrics",
        "long",
        "short",
        "open_position",
        "trades",
        "equity_curve",
    },
    "MetricsOut": {
        "trades",
        "wins",
        "losses",
        "win_rate",
        "net_pnl",
        "gross_profit",
        "gross_loss",
        "profit_factor",
        "expectancy",
        "max_drawdown_pct",
        "return_pct",
        "ending_equity",
    },
    "TradeOut": {
        "side",
        "signal_at",
        "entry_at",
        "entry_price",
        "take_profit",
        "stop_loss",
        "quantity",
        "notional",
        "exit_at",
        "exit_price",
        "exit_reason",
        "fees",
        "pnl",
        "r_multiple",
    },
    "OpenPositionOut": {
        "side",
        "signal_at",
        "entry_at",
        "entry_price",
        "take_profit",
        "stop_loss",
        "quantity",
        "notional",
        "mark_price",
        "unrealised_pnl",
    },
    "EquityPointOut": {"at", "equity"},
    "CandleOut": {"t", "o", "h", "l", "c"},
    "StrategyConfigOut": set(StrategyConfig.__dataclass_fields__),
    "FieldBounds": {"min", "max", "step", "label", "help", "kind", "group"},
    "ConfigOut": {"config_version", "defaults", "bounds", "data_first_at", "data_last_at"},
    "BacktestOut": {
        "available",
        "reason",
        "config",
        "start",
        "end",
        "candles",
        "signal_counts",
        "wait_reasons",
        "metrics",
        "long",
        "short",
        "trades",
        "equity_curve",
    },
}


def _ts_interface_keys(source: str, name: str) -> set[str]:
    block = re.search(rf"export interface {name}\b[^{{]*\{{\n(.*?)\n\}}", source, re.S)
    assert block, f"{name} not found in types.ts"
    return set(re.findall(r"^  (\w+)\??:", block.group(1), re.M))


def test_the_key_table_matches_types_ts() -> None:
    if not TYPES_TS.exists():
        pytest.skip("frontend source is not mounted in this environment")
    source = TYPES_TS.read_text()
    for name, keys in KEYS.items():
        assert keys == _ts_interface_keys(source, name), name
    # BacktestOut also carries the wait-reason rows, which extend ReasonOut.
    wait_line = re.search(r"wait_reasons:[^\n]*", source)
    assert wait_line and "count" in wait_line.group(0)


async def test_response_keys_match_types_ts_exactly(
    client: AsyncClient,
    db_session: AsyncSession,
    lab_on: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candles = await _seed(db_session, 288)
    monkeypatch.setattr(settings, "LAB_BTC_RANGE_LIVE_START", _live_start(candles, 150))

    status = (await client.get(f"{PREFIX}/status")).json()
    assert set(status) == KEYS["StatusOut"]
    assert set(status["price"]) == KEYS["PriceOut"]
    assert set(status["data"]) == KEYS["DataOut"]
    assert set(status["signal"]) == KEYS["SignalOut"]
    assert set(status["signal"]["range"]) == KEYS["RangeOut"]
    assert all(set(r) == KEYS["ReasonOut"] for r in status["signal"]["reasons"])
    assert all(set(c) == KEYS["CandleOut"] for c in status["candles"])

    book = status["book"]
    assert set(book) == KEYS["BookOut"]
    assert set(book["config"]) == KEYS["StrategyConfigOut"]
    for metrics in (book["metrics"], book["long"], book["short"]):
        assert set(metrics) == KEYS["MetricsOut"]
    assert book["trades"]
    assert all(set(t) == KEYS["TradeOut"] for t in book["trades"])
    assert all(set(p) == KEYS["EquityPointOut"] for p in book["equity_curve"])

    config = (await client.get(f"{PREFIX}/config")).json()
    assert set(config) == KEYS["ConfigOut"]
    assert set(config["defaults"]) == KEYS["StrategyConfigOut"]
    assert set(config["bounds"]) == KEYS["StrategyConfigOut"]
    assert all(set(b) == KEYS["FieldBounds"] for b in config["bounds"].values())

    backtest = (await client.post(f"{PREFIX}/backtest", json={})).json()
    assert set(backtest) == KEYS["BacktestOut"]
    assert set(backtest["config"]) == KEYS["StrategyConfigOut"]
    assert set(backtest["signal_counts"]) == {"long", "short", "wait"}
    assert all(set(w) == KEYS["ReasonOut"] | {"count"} for w in backtest["wait_reasons"])
    for metrics in (backtest["metrics"], backtest["long"], backtest["short"]):
        assert set(metrics) == KEYS["MetricsOut"]
    assert all(set(t) == KEYS["TradeOut"] for t in backtest["trades"])

    unavailable = (
        await client.post(f"{PREFIX}/backtest", json={"config": {"lookback": 672}})
    ).json()
    assert unavailable["available"] is False
    assert set(unavailable) == KEYS["BacktestOut"]


def test_open_position_and_the_off_status_have_the_contract_keys() -> None:
    at = datetime(2026, 10, 8, tzinfo=UTC)
    position = OpenPosition(
        side=Call.LONG,
        signal_at=at,
        entry_at=at,
        entry_price=Decimal("60000"),
        take_profit=Decimal("60500"),
        stop_loss=Decimal("59800"),
        quantity=Decimal("0.01"),
        notional=Decimal("600"),
        entry_fee=Decimal("0.6"),
        mark_price=Decimal("60100"),
        unrealised_pnl=Decimal("0.4"),
    )
    assert set(service.open_position_out(position).model_dump()) == KEYS["OpenPositionOut"]
    assert ExitReason.END_OF_DATA.value == "end_of_data"


async def test_decimals_are_strings_and_percent_fields_are_percent(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed(db_session, 288)
    body = (await client.post(f"{PREFIX}/backtest", json={})).json()
    assert isinstance(body["metrics"]["net_pnl"], str)
    assert isinstance(body["metrics"]["ending_equity"], str)
    assert isinstance(body["config"]["starting_balance"], str)
    assert isinstance(body["config"]["lookback"], int)
    assert body["metrics"]["win_rate"] == "100.0" or float(body["metrics"]["win_rate"]) <= 100
    trade = body["trades"][0]
    assert all(isinstance(trade[k], str) for k in ("entry_price", "pnl", "fees", "quantity"))


# --- the replay subcommand ---------------------------------------------------


def test_replay_defaults_to_24_hours_and_keeps_the_other_subcommands() -> None:
    from app.labs.btc_range.__main__ import _parser

    parser = _parser()
    assert parser.parse_args(["replay"]).hours == 24
    assert parser.parse_args(["replay", "--hours", "6"]).hours == 6
    assert parser.parse_args(["backfill"]).days == 90
    assert parser.parse_args(["ingest"]).command == "ingest"


async def test_replay_reports_window_counts_trades_and_metrics(
    db_session: AsyncSession,
) -> None:
    candles = await _seed(db_session, 288)
    now = NOW_OPEN
    report = await service.replay(db_session, now=now, hours=24)

    assert report["available"] is True
    assert report["candles"] == 96
    window = report["window"]
    assert isinstance(window, dict)
    assert window["first_candle"] == candles[-96].open_time.isoformat()
    assert window["last_candle"] == candles[-1].open_time.isoformat()
    direct = run_backtest(candles[-96 - 96 :], StrategyConfig())
    assert report["trade_count"] == len(direct.trades) > 0
    trades = report["trades"]
    assert isinstance(trades, list) and len(trades) == len(direct.trades)
    assert set(trades[0]) == KEYS["TradeOut"]
    counts = report["signal_counts"]
    assert isinstance(counts, dict) and set(counts) == {"long", "short", "wait"}
    assert report["metrics"] == service.metrics_out(direct.metrics).model_dump()
    assert await _row_count(db_session) == 288, "replay writes nothing"


async def test_replay_without_enough_candles_says_so(db_session: AsyncSession) -> None:
    await _seed(db_session, 30)
    report = await service.replay(db_session, now=NOW_OPEN, hours=24)
    assert report["available"] is False
    assert "Nothing was estimated" in str(report["reason"])
