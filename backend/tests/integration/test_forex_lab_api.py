"""`/api/v1/labs/forex/*` against real rows.

The properties defended here:

* a stored candle is never overwritten - re-importing reports `rows_existing`
  and leaves the stored prices alone;
* a run records the config it ran, the data fingerprint and a result of codes
  that are rendered to prose on read; its trade list is complete, losers
  included;
* a request out of bounds is refused with 422 before any job is queued, and a
  write without a signed-in user is 401;
* a download that fails day by day is recorded day by day and retried - never
  fatal, never cached as done;
* the JSON keys match the page's `types.ts` - the page is built against them
  and a rename breaks it with no build error.

Jobs are executed inline (`service.execute_run` on the test's session) rather
than waiting for the background task, which would open a session on the
development database.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.labs.forex import jobs, repository, service
from app.labs.forex.providers import DayFetch, ProviderError
from app.labs.forex.types import Candle
from tests.unit.labs.forex.synthetic import START, synthetic

pytestmark = pytest.mark.integration

PREFIX = f"{settings.API_V1_PREFIX}/labs/forex"
WINDOW = {
    "start": (START + timedelta(days=12)).isoformat(),
    "end": (START + timedelta(days=40)).isoformat(),
}
SMALL = {"grid": {"params.rsi_period": [10, 14]}, "mc_iterations": 100}

M5 = synthetic(40, __import__("app.labs.forex.types", fromlist=["Timeframe"]).Timeframe.M5)

TRADE_COLUMNS = [
    "id", "direction", "signal_time", "entry_time", "exit_time", "entry_price", "exit_price",
    "stop_price", "take_profit_price", "units", "risk_usd", "gross_pnl", "commission",
    "spread_slippage_cost", "financing", "net_pnl", "r_multiple", "exit_reason", "reason",
    "ambiguous_exit", "duration_minutes",
]  # fmt: skip


def csv_text(candles: Sequence[Candle], *, shift: float = 0.0) -> str:
    rows = ["timestamp,open,high,low,close,volume"]
    for c in candles:
        rows.append(
            f"{c.open_time.isoformat()},{c.open + shift:.5f},{c.high + shift:.5f},"
            f"{c.low + shift:.5f},{c.close + shift:.5f},{c.volume:.0f}"
        )
    return "\n".join(rows) + "\n"


def import_body(candles: Sequence[Candle] = M5, **over: Any) -> dict[str, Any]:
    body = {
        "symbol": "EURUSD",
        "timeframe": "5m",
        "fmt": "generic",
        "utc_offset_minutes": 0,
        "filename": "eurusd-5m.csv",
        "content": csv_text(candles),
    }
    body.update(over)
    return body


async def stored_candle(db: AsyncSession, c: Candle) -> Candle:
    rows = await repository.load_candles(
        db, "EURUSD", "5m", c.open_time, c.open_time + timedelta(minutes=5)
    )
    return rows[0]


@pytest.fixture
def launched(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Capture background launches instead of starting a task on the real database."""
    ids: list[int] = []

    async def fake_launch(run_id: int) -> None:
        ids.append(run_id)

    monkeypatch.setattr(service, "launch", fake_launch)
    return ids


@pytest.fixture
async def seeded(client: AsyncClient, auth_headers: dict[str, str]) -> dict[str, Any]:
    r = await client.post(f"{PREFIX}/data/import", json=import_body(), headers=auth_headers)
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


async def queue(client: AsyncClient, headers: dict[str, str], **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": "backtest",
        "config": {"strategy": "rsi_pullback"},
        **WINDOW,
        "name": "inline",
    }
    body.update(over)
    r = await client.post(f"{PREFIX}/runs", json=body, headers=headers)
    assert r.status_code == 202, r.text
    return r.json()  # type: ignore[no-any-return]


async def run_inline(
    client: AsyncClient, db: AsyncSession, run_id: int, **kw: Any
) -> dict[str, Any]:
    await service.execute_run(db, run_id, commit=False, **kw)
    r = await client.get(f"{PREFIX}/runs/{run_id}")
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


# --- reads are public, writes are not ---------------------------------------------------


async def test_writes_need_a_signed_in_user(client: AsyncClient) -> None:
    posts = {
        f"{PREFIX}/data/import": import_body(M5[:20]),
        f"{PREFIX}/data/fetch": {
            "provider": "dukascopy",
            "symbol": "EURUSD",
            "start_date": "2024-03-04",
            "end_date": "2024-03-05",
        },
        f"{PREFIX}/runs": {
            "kind": "backtest",
            "config": {"strategy": "rsi_pullback"},
            **WINDOW,
        },
        f"{PREFIX}/versions": {"name": "x", "config": {"strategy": "rsi_pullback"}},
    }
    for url, body in posts.items():
        r = await client.post(url, json=body)
        assert r.status_code == 401, url


async def test_reads_are_public(client: AsyncClient) -> None:
    for path in (
        "/meta",
        "/data",
        "/runs",
        "/versions",
        "/data/quality?symbol=EURUSD&timeframe=5m",
    ):
        r = await client.get(f"{PREFIX}{path}")
        assert r.status_code == 200, path


# --- meta -------------------------------------------------------------------------------


async def test_meta_is_the_form_definition(client: AsyncClient) -> None:
    body = (await client.get(f"{PREFIX}/meta")).json()
    assert set(body) == {
        "instruments", "timeframes", "risk_options_pct", "strategies", "shared_fields",
        "providers", "target_pcts", "disclaimer",
    }  # fmt: skip
    assert body["timeframes"] == ["1m", "5m", "15m", "1h"]
    assert body["risk_options_pct"] == ["0.25", "0.5", "1", "2"]
    assert body["target_pcts"] == [5, 10, 20, 50, 100]
    assert {i["symbol"] for i in body["instruments"]} == {"EURUSD", "GBPUSD", "USDJPY"}
    assert [s["id"] for s in body["strategies"]] == [
        "london_breakout", "rsi_pullback", "bollinger_reversion",
    ]  # fmt: skip
    for s in body["strategies"]:
        assert set(s) == {"id", "name", "description", "timeframe", "default_config",
                          "param_fields", "default_grid"}  # fmt: skip
        assert s["default_config"]["strategy"] == s["id"]
        assert s["default_config"]["risk"]["initial_capital"] == "1000"
        assert s["default_grid"]
        for f in s["param_fields"] + body["shared_fields"]:
            assert {"path", "label", "kind", "help"} <= set(f)
            assert f["kind"] in {"int", "float", "bool", "enum", "session", "decimal"}
    assert body["disclaimer"]["code"] == "historical_observation_not_forecast"
    assert body["disclaimer"]["text"]
    assert {p["id"] for p in body["providers"]} == {"dukascopy", "csv"}
    leverage = next(f for f in body["shared_fields"] if f["path"] == "risk.max_leverage")
    assert (leverage["min"], leverage["max"]) == (1, 20)


async def test_every_default_config_is_accepted_by_the_run_endpoint(
    client: AsyncClient,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
    launched: list[int],
) -> None:
    for s in (await client.get(f"{PREFIX}/meta")).json()["strategies"]:
        run = await queue(client, auth_headers, config=s["default_config"])
        assert run["config"] == s["default_config"], "the recorded config is the submitted one"


# --- CSV import -------------------------------------------------------------------------


async def test_import_reports_what_it_stored(seeded: dict[str, Any]) -> None:
    assert (
        seeded["rows_total"] == seeded["rows_accepted"] == seeded["rows_inserted"] == len(M5)
    )
    assert seeded["rows_existing"] == 0 and seeded["error_count"] == 0
    assert seeded["detected_format"] == "generic"
    assert seeded["source"] == "csv" and seeded["filename"] == "eurusd-5m.csv"
    assert seeded["start"].startswith("2024-03-04") and seeded["end"]
    q = seeded["quality"]
    assert q["bars"] == len(M5) and q["grade"] in {"good", "fair"}
    assert q["notes"] and all(n["text"] for n in q["notes"])
    assert all(n["text"] for n in seeded["notes"])
    assert set(seeded) == {
        "id", "symbol", "timeframe", "source", "filename", "rows_total", "rows_accepted",
        "rows_inserted", "rows_existing", "error_count", "errors", "detected_format", "start",
        "end", "quality", "notes", "created_at",
    }  # fmt: skip


async def test_reimporting_is_idempotent_and_never_overwrites(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    seeded: dict[str, Any],
) -> None:
    first = M5[100]
    before = await stored_candle(db_session, first)

    again = await client.post(
        f"{PREFIX}/data/import", json=import_body(), headers=auth_headers
    )
    body = again.json()
    assert body["rows_inserted"] == 0 and body["rows_existing"] == len(M5)

    # Same timestamps, every price moved: still nothing is replaced.
    shifted = import_body(content=csv_text(M5, shift=0.0005))
    moved = (
        await client.post(f"{PREFIX}/data/import", json=shifted, headers=auth_headers)
    ).json()
    assert moved["rows_inserted"] == 0 and moved["rows_existing"] == len(M5)
    after = await stored_candle(db_session, first)
    assert after == before


async def test_an_overlapping_file_inserts_only_the_new_rows(
    client: AsyncClient, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    overlap = synthetic(
        45, __import__("app.labs.forex.types", fromlist=["Timeframe"]).Timeframe.M5
    )
    body = (
        await client.post(
            f"{PREFIX}/data/import", json=import_body(overlap), headers=auth_headers
        )
    ).json()
    assert body["rows_existing"] == len(M5)
    assert body["rows_inserted"] == len(overlap) - len(M5)


async def test_bad_rows_are_reported_with_line_numbers_and_nothing_is_repaired(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    good = csv_text(M5[:10]).splitlines()
    content = "\n".join([*good, "not,a,candle", "2024-03-05T00:00:00+00:00,1,x,1,1,1"]) + "\n"
    body = (
        await client.post(
            f"{PREFIX}/data/import", json=import_body(content=content), headers=auth_headers
        )
    ).json()
    assert body["rows_accepted"] == 10 and body["rows_inserted"] == 10
    assert body["error_count"] == 2
    assert [e["line"] for e in body["errors"]] == [12, 13]
    assert all(e["message"] for e in body["errors"])


async def test_histdata_offsets_come_with_a_rendered_note(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    content = "20240304 170000;1.08000;1.08010;1.07990;1.08005;0\n"
    body = (
        await client.post(
            f"{PREFIX}/data/import",
            json=import_body(timeframe="1m", fmt="histdata", content=content),
            headers=auth_headers,
        )
    ).json()
    assert body["detected_format"] == "histdata"
    assert body["start"].startswith("2024-03-04T22:00:00")  # 17:00 EST is 22:00 UTC
    note = body["notes"][0]
    assert note["code"] == "histdata_est_fixed_utc_minus_5" and "UTC-5" in note["text"]


@pytest.mark.parametrize(
    "over",
    [
        {"symbol": "XAUUSD"},
        {"timeframe": "4h"},
        {"utc_offset_minutes": 5000},
        {"fmt": "excel"},
        {"content": ""},
    ],
)
async def test_import_refuses_a_bad_request(
    client: AsyncClient, auth_headers: dict[str, str], over: dict[str, Any]
) -> None:
    r = await client.post(
        f"{PREFIX}/data/import", json=import_body(M5[:5], **over), headers=auth_headers
    )
    assert r.status_code == 422


# --- data overview and quality ----------------------------------------------------------


async def test_data_lists_what_is_stored(client: AsyncClient, seeded: dict[str, Any]) -> None:
    body = (await client.get(f"{PREFIX}/data")).json()
    assert set(body) == {"datasets", "imports", "fetch", "providers"}
    ds = next(
        d for d in body["datasets"] if d["symbol"] == "EURUSD" and d["timeframe"] == "5m"
    )
    assert ds["bars"] == len(M5) and ds["sources"] == ["csv"]
    assert ds["start"].startswith("2024-03-04")
    assert body["imports"][0]["id"] == seeded["id"]
    assert body["fetch"] is None


async def test_quality_of_stored_candles(client: AsyncClient, seeded: dict[str, Any]) -> None:
    q = (await client.get(f"{PREFIX}/data/quality?symbol=EURUSD&timeframe=5m")).json()
    assert q["derived_from"] == "stored" and q["bars"] == len(M5)
    assert q["grade"] in {"good", "fair"} and q["coverage_pct"] > 97
    assert q["duplicates"] == 0 and q["ohlc_violations"] == 0
    assert {"gaps", "notes", "gap_count", "largest_gap_bars", "expected_bars"} <= set(q)
    assert q["notes"][0]["text"]

    windowed = (
        await client.get(
            f"{PREFIX}/data/quality?symbol=EURUSD&timeframe=5m"
            "&start=2024-03-11T00:00:00Z&end=2024-03-18T00:00:00Z"
        )
    ).json()
    assert 0 < windowed["bars"] < q["bars"]


async def test_quality_of_a_timeframe_built_from_one_minute_candles(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    from app.labs.forex.types import Timeframe

    m1 = synthetic(2, Timeframe.M1)
    r = await client.post(
        f"{PREFIX}/data/import", json=import_body(m1, timeframe="1m"), headers=auth_headers
    )
    assert r.status_code == 200
    q = (await client.get(f"{PREFIX}/data/quality?symbol=EURUSD&timeframe=5m")).json()
    assert q["derived_from"] == "resampled_from_1m"
    assert q["timeframe"] == "5m" and q["bars"] > 0


async def test_quality_with_no_data_is_an_empty_report_not_an_estimate(
    client: AsyncClient,
) -> None:
    q = (await client.get(f"{PREFIX}/data/quality?symbol=GBPUSD&timeframe=15m")).json()
    assert q["bars"] == 0 and q["grade"] == "empty"
    r = await client.get(f"{PREFIX}/data/quality?symbol=XAUUSD&timeframe=5m")
    assert r.status_code == 422


# --- strategy versions ------------------------------------------------------------------


async def test_versions_increment_per_name_and_are_immutable(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    cfg = {"strategy": "rsi_pullback", "params": {"rsi_period": 21}}
    one = await client.post(
        f"{PREFIX}/versions", json={"name": "swing", "config": cfg, "notes": "first"},
        headers=auth_headers,
    )  # fmt: skip
    assert one.status_code == 201, one.text
    assert one.json()["version"] == 1 and one.json()["notes"] == "first"
    cfg2 = {"strategy": "rsi_pullback", "params": {"rsi_period": 10}}
    two = await client.post(
        f"{PREFIX}/versions", json={"name": "swing", "config": cfg2}, headers=auth_headers
    )
    assert two.json()["version"] == 2
    other = await client.post(
        f"{PREFIX}/versions",
        json={"name": "other", "config": {"strategy": "bollinger_reversion"}},
        headers=auth_headers,
    )
    assert other.json()["version"] == 1

    listed = (await client.get(f"{PREFIX}/versions")).json()["versions"]
    swing = [v for v in listed if v["name"] == "swing"]
    assert [v["version"] for v in swing] == [2, 1], "newest version of a name first"
    assert swing[1]["config"]["params"]["rsi_period"] == 21, (
        "version 1 is untouched by version 2"
    )
    assert swing[0]["config"]["risk"]["initial_capital"] == "1000", "stored as the full config"
    assert set(listed[0]) == {
        "id",
        "name",
        "version",
        "strategy",
        "config",
        "notes",
        "created_at",
    }


async def test_a_version_with_a_bad_config_is_refused(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    r = await client.post(
        f"{PREFIX}/versions",
        json={
            "name": "bad",
            "config": {"strategy": "rsi_pullback", "risk": {"max_leverage": 50}},
        },
        headers=auth_headers,
    )
    assert r.status_code == 422


async def test_a_run_can_be_made_from_a_saved_version(
    client: AsyncClient,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
    launched: list[int],
) -> None:
    v = (
        await client.post(
            f"{PREFIX}/versions",
            json={
                "name": "v",
                "config": {"strategy": "rsi_pullback", "params": {"rsi_period": 21}},
            },
            headers=auth_headers,
        )
    ).json()
    r = await client.post(
        f"{PREFIX}/runs",
        json={"kind": "backtest", "strategy_version_id": v["id"], **WINDOW},
        headers=auth_headers,
    )
    assert r.status_code == 202, r.text
    assert r.json()["config"]["params"]["rsi_period"] == 21
    assert r.json()["strategy_version_id"] == v["id"]


# --- a backtest, end to end -------------------------------------------------------------


async def test_a_backtest_is_queued_then_runs_and_records_everything(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    seeded: dict[str, Any],
    launched: list[int],
) -> None:
    run = await queue(client, auth_headers)
    assert launched == [run["id"]], "the request hands the job to the background runner"
    assert run["status"] == "queued" and run["progress"] == 0 and run["kind"] == "backtest"
    assert run["config"]["strategy"] == "rsi_pullback"
    assert run["config"]["risk"]["risk_per_trade_pct"] == "0.5"
    assert run["config_version"] == 1 and run["app_version"] == settings.VERSION
    assert run["name"] == "inline" and run["data_fingerprint"] is None
    assert set(run) == {
        "id", "kind", "status", "progress", "message", "name", "strategy_version_id", "config",
        "request", "data_fingerprint", "config_version", "app_version", "summary", "error",
        "created_at", "started_at", "finished_at",
    }  # fmt: skip

    queued = (await client.get(f"{PREFIX}/runs/{run['id']}")).json()
    assert queued["run"]["status"] == "queued" and queued["result"] is None

    detail = await run_inline(client, db_session, run["id"])
    done = detail["run"]
    assert done["status"] == "done", done["error"]
    assert done["progress"] == 100 and done["finished_at"] and done["started_at"]
    assert re.fullmatch(r"[0-9a-f]{64}", done["data_fingerprint"])
    result = detail["result"]
    assert result["type"] == "backtest"

    # The summary is the run's own headline numbers.
    assert done["summary"]["total_trades"] == result["metrics"]["total_trades"] > 0
    assert done["summary"]["net_return_pct"] == result["metrics"]["net_return_pct"]

    # Prose is rendered on read from stored codes.
    assert all(a["text"] for a in result["assumptions"]) and len(result["assumptions"]) == 8
    assert all(s["text"] and s["count"] > 0 for s in result["skipped_text"])
    assert (
        result["data"]["sources"] == ["csv"] and result["data"]["htf_derived"] == "resampled"
    )
    assert result["data"]["quality_grade"] in {"good", "fair"}
    assert result["data"]["lower_tf_available"] is False
    assert result["monte_carlo"]["assumptions"][0]["text"]
    assert result["targets"]["disclaimers"][0]["text"]

    # Money is a string; the trade list is complete.
    assert isinstance(result["metrics"]["ending_balance"], str)
    assert len(result["trades"]) == result["metrics"]["total_trades"]
    assert {"equity_curve", "drawdown", "months", "baseline", "bootstrap"} <= set(result)


async def test_trades_csv_has_every_trade_losers_included(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    seeded: dict[str, Any],
    launched: list[int],
) -> None:
    run = await queue(client, auth_headers)
    detail = await run_inline(client, db_session, run["id"])
    trades = detail["result"]["trades"]

    r = await client.get(f"{PREFIX}/runs/{run['id']}/trades.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert f"forex-run-{run['id']}-trades.csv" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert list(rows[0]) == TRADE_COLUMNS
    assert len(rows) == len(trades) > 0
    assert [int(x["id"]) for x in rows] == [t["id"] for t in trades]
    assert any(float(x["net_pnl"]) < 0 for x in rows), "losing trades are exported too"
    assert {x["ambiguous_exit"] for x in rows} <= {"true", "false"}
    assert all(x["exit_reason"] for x in rows)


async def test_trades_csv_of_a_run_that_has_not_finished_is_409(
    client: AsyncClient,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
    launched: list[int],
) -> None:
    run = await queue(client, auth_headers)
    assert (await client.get(f"{PREFIX}/runs/{run['id']}/trades.csv")).status_code == 409


async def test_a_comparison_has_no_single_trade_list(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    seeded: dict[str, Any],
    launched: list[int],
) -> None:
    compare = await queue(client, auth_headers, kind="compare", config=None)
    await run_inline(client, db_session, compare["id"])
    assert (await client.get(f"{PREFIX}/runs/{compare['id']}/trades.csv")).status_code == 400


async def test_trades_csv_of_an_unknown_run_is_404(client: AsyncClient) -> None:
    assert (await client.get(f"{PREFIX}/runs/999999/trades.csv")).status_code == 404


async def test_a_missing_run_is_404(client: AsyncClient) -> None:
    assert (await client.get(f"{PREFIX}/runs/424242")).status_code == 404


async def test_runs_list_newest_first_and_filter_by_kind(
    client: AsyncClient,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
    launched: list[int],
) -> None:
    a = await queue(client, auth_headers)
    b = await queue(client, auth_headers, kind="research", options=SMALL)
    c = await queue(client, auth_headers)
    runs = (await client.get(f"{PREFIX}/runs")).json()["runs"]
    assert [r["id"] for r in runs][:3] == [c["id"], b["id"], a["id"]]
    assert "result" not in runs[0]
    only = (await client.get(f"{PREFIX}/runs?kind=research&limit=5")).json()["runs"]
    assert [r["id"] for r in only] == [b["id"]]
    assert (await client.get(f"{PREFIX}/runs?kind=nonsense")).status_code == 422
    assert (await client.get(f"{PREFIX}/runs?limit=0")).status_code == 422


# --- refusing a bad request -------------------------------------------------------------


@pytest.mark.parametrize(
    "over",
    [
        {"config": {"strategy": "rsi_pullback", "risk": {"max_leverage": 50}}},
        {"config": {"strategy": "rsi_pullback", "risk": {"risk_per_trade_pct": "10"}}},
        {"config": {"strategy": "rsi_pullback", "risk": {"initial_capital": "5"}}},
        {"config": {"strategy": "rsi_pullback", "costs": {"spread_pips": 99}}},
        {"config": {"strategy": "rsi_pullback", "params": {"rsi_period": 1}}},
        {"config": {"strategy": "rsi_pullback", "params": {"risk_reward": 0}}},
        {"config": {"strategy": "martingale"}},
        {"config": {"strategy": "rsi_pullback", "symbol": "XAUUSD"}},
        {"config": {"strategy": "rsi_pullback", "mystery": 1}},
        {"config": None},
        {"start": WINDOW["end"], "end": WINDOW["start"]},
        {"start": "2020-01-01T00:00:00Z", "end": "2024-12-31T00:00:00Z"},
        {"config": {"strategy": "rsi_pullback", "symbol": "GBPUSD"}},  # no GBPUSD data stored
        {"strategy_version_id": 99999},
        {"options": {"unknown": 1}},
        {"kind": "fetch"},
    ],
)
async def test_an_invalid_run_is_422_and_queues_nothing(
    client: AsyncClient,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
    launched: list[int],
    over: dict[str, Any],
) -> None:
    body: dict[str, Any] = {
        "kind": "backtest", "config": {"strategy": "rsi_pullback"}, **WINDOW,
    }  # fmt: skip
    body.update(over)
    r = await client.post(f"{PREFIX}/runs", json=body, headers=auth_headers)
    assert r.status_code == 422, r.text
    assert launched == [], "nothing is handed to the background runner"


@pytest.mark.parametrize(
    "grid",
    [
        {
            "params.rsi_period": [10, 12, 14, 16, 18, 20, 22],
            "params.risk_reward": [1, 1.5, 2, 2.5, 3, 3.5],
        },
        {"params.nope": [1]},
        {"risk.max_leverage": [99]},
        {"params.rsi_period": []},
    ],
)
async def test_a_research_grid_is_capped_and_checked(
    client: AsyncClient,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
    launched: list[int],
    grid: dict[str, Any],
) -> None:
    r = await client.post(
        f"{PREFIX}/runs",
        json={"kind": "research", "config": {"strategy": "rsi_pullback"}, **WINDOW,
              "options": {"grid": grid}},
        headers=auth_headers,
    )  # fmt: skip
    assert r.status_code == 422, grid
    assert launched == []


# Monday 18 March, a day and a half: far too short to split three ways.
SHORT = {
    "start": (START + timedelta(days=14)).isoformat(),
    "end": (START + timedelta(days=14, hours=30)).isoformat(),
}


@pytest.mark.parametrize("kind", ["research", "compare"])
async def test_research_and_compare_need_room_for_a_split(
    client: AsyncClient,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
    launched: list[int],
    kind: str,
) -> None:
    r = await client.post(
        f"{PREFIX}/runs",
        json={"kind": kind, "config": {"strategy": "rsi_pullback"}, **SHORT},
        headers=auth_headers,
    )
    assert r.status_code == 422
    assert "too short" in r.text, "refused for the split, not for missing data"
    assert launched == []


async def test_a_plain_backtest_of_a_short_window_is_fine(
    client: AsyncClient,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
    launched: list[int],
) -> None:
    ok = await client.post(
        f"{PREFIX}/runs",
        json={"kind": "backtest", "config": {"strategy": "rsi_pullback"}, **SHORT},
        headers=auth_headers,
    )
    assert ok.status_code == 202, ok.text


# --- research and compare, end to end ---------------------------------------------------


async def test_a_research_run_end_to_end(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    seeded: dict[str, Any],
    launched: list[int],
) -> None:
    run = await queue(client, auth_headers, kind="research", options=SMALL)
    detail = await run_inline(client, db_session, run["id"])
    assert detail["run"]["status"] == "done", detail["run"]["error"]
    result = detail["result"]
    assert result["type"] == "research"
    assert result["selection_note"]["code"] == "selection_on_development_only"
    assert "validation and test" in result["selection_note"]["text"].lower()
    assert set(result["split"]) == {"development", "validation", "test"}
    assert len(result["optimisation"]["rows"]) == 2
    assert result["scorecard"]["verdict"]["text"] and result["scorecard"]["rank"] == 1
    assert all(f["text"] for f in result["scorecard"]["flags"])
    assert detail["run"]["summary"]["verdict_code"] == result["scorecard"]["verdict"]["code"]
    assert result["walk_forward"]["efficiency_note"]["text"]  # window shorter than 90+30 days
    assert set(result["targets"]) == {"full", "out_of_sample"}

    csv_rows = (
        (await client.get(f"{PREFIX}/runs/{run['id']}/trades.csv")).text.strip().splitlines()
    )
    assert len(csv_rows) - 1 == len(result["trades"]), "the full-period backtest's trades"


async def test_a_compare_run_ranks_the_default_strategies(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    seeded: dict[str, Any],
    launched: list[int],
) -> None:
    run = await queue(
        client, auth_headers, kind="compare", config=None, options={"mc_iterations": 100}
    )
    assert run["config"] is None and len(run["request"]["configs"]) == 3
    detail = await run_inline(client, db_session, run["id"])
    assert detail["run"]["status"] == "done", detail["run"]["error"]
    result = detail["result"]
    assert result["type"] == "compare"
    assert [c["rank"] for c in result["scorecards"]] == [1, 2, 3]
    assert all(c["verdict"]["text"] for c in result["scorecards"])
    assert set(result["per_strategy"]) == {
        "london_breakout",
        "rsi_pullback",
        "bollinger_reversion",
    }
    assert {"window", "split"} <= set(result)


async def test_compare_accepts_explicit_configs(
    client: AsyncClient,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
    launched: list[int],
) -> None:
    configs = [
        {"strategy": "rsi_pullback"},
        {"strategy": "rsi_pullback", "params": {"rsi_period": 21}},
    ]
    run = await queue(client, auth_headers, kind="compare", config=None, configs=configs)
    assert len(run["request"]["configs"]) == 2
    seven = [{"strategy": "rsi_pullback"}] * 7
    r = await client.post(
        f"{PREFIX}/runs",
        json={"kind": "compare", "configs": seven, **WINDOW},
        headers=auth_headers,
    )
    assert r.status_code == 422


# --- failures and interruptions ---------------------------------------------------------


async def test_a_job_that_raises_fails_the_run_and_says_why(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    seeded: dict[str, Any],
    launched: list[int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise ValueError("window_too_short_for_split")

    monkeypatch.setattr(jobs, "run_backtest_job", boom)
    run = await queue(client, auth_headers)
    detail = await run_inline(client, db_session, run["id"])
    assert detail["run"]["status"] == "failed" and detail["result"] is None
    assert "too short" in detail["run"]["error"], "a known code is rendered, not shown raw"
    assert detail["run"]["finished_at"]


async def test_a_run_over_a_range_with_no_candles_fails_cleanly(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    seeded: dict[str, Any],
    launched: list[int],
) -> None:
    """Data present when queued, gone when the job loads it (a deploy between)."""
    run = await queue(client, auth_headers)
    await db_session.execute(__import__("sqlalchemy").text("delete from forex_candles"))
    detail = await run_inline(client, db_session, run["id"])
    assert detail["run"]["status"] == "failed"
    assert detail["run"]["error"] == "No stored candles cover the requested range."


async def test_a_run_nobody_is_running_is_marked_interrupted(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    seeded: dict[str, Any],
    launched: list[int],
) -> None:
    stale = await queue(client, auth_headers)
    live = await queue(client, auth_headers)
    later = datetime.now(UTC) + timedelta(hours=1)

    service._LIVE.add(live["id"])
    try:
        read = await service.get_run(db_session, stale["id"], now=later)
        still = await service.get_run(db_session, live["id"], now=later)
    finally:
        service._LIVE.discard(live["id"])
    assert read["run"]["status"] == "failed"
    assert read["run"]["error"] == "The server stopped before this run finished."
    assert still["run"]["status"] == "queued", "a run this process is running is left alone"

    # And not before the grace period.
    fresh = await queue(client, auth_headers)
    assert (await service.get_run(db_session, fresh["id"]))["run"]["status"] == "queued"


# --- downloads --------------------------------------------------------------------------


class FakeProvider:
    """A feed that answers weekdays, is empty on weekends, and can fail a day."""

    name = "dukascopy"

    def __init__(self, fail: set[date] | None = None) -> None:
        self.fail = fail or set()
        self.calls: list[date] = []

    async def fetch_day(self, symbol: str, day: date) -> DayFetch:
        self.calls.append(day)
        if day in self.fail:
            raise ProviderError(f"{day}: HTTP 503")
        if day.weekday() >= 5:
            return DayFetch(day, (), True, self.name)
        t0 = datetime(day.year, day.month, day.day, tzinfo=UTC)
        candles = tuple(
            Candle(t0 + timedelta(minutes=i), 1.08, 1.0805, 1.0795, 1.0801, 7.0)
            for i in range(10)
        )
        return DayFetch(day, candles, False, self.name)


FETCH = {"provider": "dukascopy", "symbol": "EURUSD", "start_date": "2024-03-04",
         "end_date": "2024-03-10"}  # fmt: skip


async def test_a_fetch_records_failed_days_and_retries_only_them(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    launched: list[int],
) -> None:
    wednesday = date(2024, 3, 6)
    r = await client.post(f"{PREFIX}/data/fetch", json=FETCH, headers=auth_headers)
    assert r.status_code == 202, r.text
    assert r.json()["kind"] == "fetch" and r.json()["status"] == "queued"
    assert launched == [r.json()["id"]]

    flaky = FakeProvider(fail={wednesday})
    detail = await run_inline(client, db_session, r.json()["id"], provider=flaky)
    assert detail["run"]["status"] == "done", detail["run"]["error"]
    res = detail["result"]
    assert res["type"] == "fetch" and res["days_total"] == 7
    assert (res["days_fetched"], res["days_failed"], res["days_empty"]) == (6, 1, 2)
    assert res["candles_inserted"] == 4 * 10
    assert res["failures"] == [
        {"day": "2024-03-06", "error": "ProviderError: 2024-03-06: HTTP 503"}
    ]
    assert len(flaky.calls) == 7

    overview = (await client.get(f"{PREFIX}/data")).json()
    assert overview["fetch"] == {
        "provider": "dukascopy", "days_ok": 4, "days_empty": 2, "days_failed": 1,
        "first_day": "2024-03-04", "last_day": "2024-03-10",
    }  # fmt: skip
    ds = next(d for d in overview["datasets"] if d["timeframe"] == "1m")
    assert ds["bars"] == 40 and ds["sources"] == ["dukascopy"]

    # Second request: every good day comes from the cache, the failed one is retried.
    again = (
        await client.post(f"{PREFIX}/data/fetch", json=FETCH, headers=auth_headers)
    ).json()
    healthy = FakeProvider()
    detail2 = await run_inline(client, db_session, again["id"], provider=healthy)
    assert healthy.calls == [wednesday]
    assert (detail2["result"]["days_cached"], detail2["result"]["days_fetched"]) == (6, 1)
    assert detail2["result"]["days_failed"] == 0
    overview2 = (await client.get(f"{PREFIX}/data")).json()
    assert overview2["fetch"]["days_failed"] == 0 and overview2["fetch"]["days_ok"] == 5


async def test_a_day_that_has_not_finished_is_never_cached_as_done(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    launched: list[int],
) -> None:
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).date().isoformat()
    r = await client.post(
        f"{PREFIX}/data/fetch",
        json={**FETCH, "start_date": tomorrow, "end_date": tomorrow},
        headers=auth_headers,
    )
    provider = FakeProvider()
    detail = await run_inline(client, db_session, r.json()["id"], provider=provider)
    assert provider.calls == []
    assert detail["result"]["days_incomplete"] == 1 and detail["result"]["days_fetched"] == 0


@pytest.mark.parametrize(
    "over",
    [
        {"provider": "yahoo"},
        {"symbol": "XAUUSD"},
        {"start_date": "2024-03-10", "end_date": "2024-03-04"},
        {"start_date": "2023-01-01", "end_date": "2024-03-04"},  # more than 366 days
    ],
)
async def test_a_bad_fetch_is_refused(
    client: AsyncClient,
    auth_headers: dict[str, str],
    launched: list[int],
    over: dict[str, Any],
) -> None:
    r = await client.post(f"{PREFIX}/data/fetch", json={**FETCH, **over}, headers=auth_headers)
    assert r.status_code == 422
    assert launched == []


async def test_366_days_is_the_limit_inclusive(
    client: AsyncClient, auth_headers: dict[str, str], launched: list[int]
) -> None:
    ok = await client.post(
        f"{PREFIX}/data/fetch",
        json={**FETCH, "start_date": "2023-03-04", "end_date": "2024-03-03"},  # 366 days
        headers=auth_headers,
    )
    assert ok.status_code == 202, ok.text
