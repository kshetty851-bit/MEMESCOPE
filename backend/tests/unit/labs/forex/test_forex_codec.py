"""ConfigJSON <-> BacktestConfig.

The property that matters: a config read back from what a run recorded is EQUAL
to the config that was run. If it were not, "re-run this saved version" would
quietly run something else. The second property: a value outside the bounds is
refused, never clamped - a silently adjusted risk percent is a run that did not
test what the person asked.
"""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from app.labs.forex import codec, meta
from app.labs.forex.codec import ConfigError, config_from_json, config_to_json
from app.labs.forex.types import (
    BacktestConfig,
    CostConfig,
    DirectionMode,
    RiskConfig,
    Session,
    StopMethod,
    StrategyId,
    StrategyParams,
    TakeProfitMethod,
    Timeframe,
)

pytestmark = pytest.mark.unit


def _variants() -> list[BacktestConfig]:
    out = [meta.default_config(s) for s in StrategyId]
    out.append(
        BacktestConfig(
            strategy=StrategyId.BOLLINGER_REVERSION,
            symbol="USDJPY",
            timeframe=Timeframe.M15,
            direction=DirectionMode.SHORT_ONLY,
            params=StrategyParams(
                trend_filter=False,
                trend_timeframe=Timeframe.H1,
                stop_method=StopMethod.FIXED_PIPS,
                take_profit_method=TakeProfitMethod.NONE,
                bb_std=2.5,
                trading_session=Session(8, 17, 30, 45),
            ),
            costs=CostConfig(
                spread_pips=1.4,
                commission_per_lot_side=Decimal("2.75"),
                swap_long_per_lot=Decimal("-10.50"),
                financing_enabled=False,
            ),
            risk=RiskConfig(
                initial_capital=Decimal("25000.50"),
                risk_per_trade_pct=Decimal("0.25"),
                max_leverage=5,
            ),
            session_filter=Session(7, 12),
        )
    )
    return out


@pytest.mark.parametrize("cfg", _variants(), ids=lambda c: f"{c.strategy.value}-{c.symbol}")
def test_a_config_survives_json_exactly(cfg: BacktestConfig) -> None:
    """Through real JSON text, so a float or Decimal that only round-trips
    in memory cannot pass."""
    wire = json.loads(json.dumps(config_to_json(cfg)))
    assert config_from_json(wire) == cfg


def test_money_is_a_string_and_enums_are_values() -> None:
    data = config_to_json(meta.default_config(StrategyId.LONDON_BREAKOUT))
    assert data["risk"]["initial_capital"] == "1000"
    assert data["risk"]["risk_per_trade_pct"] == "0.5"
    assert data["costs"]["commission_per_lot_side"] == "3.50"
    assert data["costs"]["swap_long_per_lot"] == "-7.00"
    assert data["timeframe"] == "5m"
    assert data["params"]["stop_method"] == "range"
    assert data["params"]["asian_session"] == {
        "start_hour": 0,
        "end_hour": 6,
        "start_minute": 0,
        "end_minute": 0,
    }
    assert data["session_filter"] is None


def test_a_decimal_sent_as_a_number_does_not_pick_up_float_noise() -> None:
    data = config_to_json(meta.default_config(StrategyId.RSI_PULLBACK))
    data["risk"]["risk_per_trade_pct"] = 0.1
    assert config_from_json(data).risk.risk_per_trade_pct == Decimal("0.1")


def test_omitted_fields_take_the_defaults() -> None:
    cfg = config_from_json({"strategy": "rsi_pullback"})
    assert cfg == BacktestConfig(strategy=StrategyId.RSI_PULLBACK)


def _with(path: str, value: Any) -> dict[str, Any]:
    data = config_to_json(meta.default_config(StrategyId.RSI_PULLBACK))
    group, _, name = path.partition(".")
    if name:
        data[group][name] = value
    else:
        data[group] = value
    return data


@pytest.mark.parametrize(
    ("path", "bad"),
    [
        ("risk.max_leverage", 21),
        ("risk.max_leverage", 0),
        ("risk.risk_per_trade_pct", "5.01"),
        ("risk.risk_per_trade_pct", "0.009"),
        ("risk.initial_capital", "99"),
        ("risk.initial_capital", "10000001"),
        ("costs.spread_pips", 20.5),
        ("costs.spread_pips", -0.1),
        ("costs.slippage_pips", 21),
        ("params.rsi_period", 1),
        ("params.rsi_period", 501),
        ("params.atr_period", 1),
        ("params.bb_period", 600),
        ("params.trend_ema_period", 1),
        ("params.risk_reward", 0.2),
        ("params.risk_reward", 10.5),
        ("risk.max_daily_loss_pct", "51"),
        ("risk.margin_closeout_pct", "0"),
        ("costs.commission_per_lot_side", "-1"),
        ("symbol", "XAUUSD"),
        ("timeframe", "4h"),
        ("direction", "sideways"),
        ("params.stop_method", "guess"),
    ],
)
def test_out_of_bounds_values_are_refused_not_clamped(path: str, bad: Any) -> None:
    with pytest.raises(ConfigError):
        config_from_json(_with(path, bad))


@pytest.mark.parametrize(
    ("path", "good"),
    [
        ("risk.max_leverage", 20),
        ("risk.max_leverage", 1),
        ("risk.risk_per_trade_pct", "5"),
        ("risk.risk_per_trade_pct", "0.01"),
        ("risk.initial_capital", "100"),
        ("risk.initial_capital", "10000000"),
        ("costs.spread_pips", 0),
        ("costs.spread_pips", 20),
        ("params.rsi_period", 2),
        ("params.rsi_period", 500),
        ("params.risk_reward", 0.25),
        ("params.risk_reward", 10),
    ],
)
def test_the_bounds_are_inclusive(path: str, good: Any) -> None:
    config_from_json(_with(path, good))


def test_config_error_is_a_value_error() -> None:
    """The API maps ValueError to 422; the class must stay in that family."""
    assert issubclass(ConfigError, ValueError)


def test_wrong_types_are_refused() -> None:
    for path, bad in [
        ("risk.max_leverage", 2.5),
        ("risk.max_leverage", True),
        ("params.trend_filter", 1),
        ("params.rsi_period", "14"),
        ("costs.spread_pips", "1"),
        ("risk.initial_capital", "lots"),
        ("risk.initial_capital", None),
        ("params.asian_session", "0-6"),
    ]:
        with pytest.raises(ConfigError):
            config_from_json(_with(path, bad))


def test_unknown_fields_are_refused() -> None:
    data = config_to_json(meta.default_config(StrategyId.RSI_PULLBACK))
    for where in (None, "params", "costs", "risk"):
        bad = json.loads(json.dumps(data))
        (bad if where is None else bad[where])["leverage_x"] = 3
        with pytest.raises(ConfigError):
            config_from_json(bad)


def test_the_strategy_is_required() -> None:
    with pytest.raises(ConfigError):
        config_from_json({"symbol": "EURUSD"})
    with pytest.raises(ConfigError):
        config_from_json("rsi_pullback")


def test_cross_field_rules() -> None:
    data = _with("params.min_range_pips", 80.0)
    with pytest.raises(ConfigError, match="min_range_pips"):
        config_from_json(data)
    with pytest.raises(ConfigError, match="rsi_long_level"):
        config_from_json(_with("params.rsi_long_level", 70.0))
    # The range stop belongs to the London breakout alone.
    with pytest.raises(ConfigError, match="range"):
        config_from_json(_with("params.stop_method", "range"))
    london = config_to_json(meta.default_config(StrategyId.LONDON_BREAKOUT))
    london["params"]["trading_session"] = {"start_hour": 22, "end_hour": 2}
    with pytest.raises(ConfigError, match="midnight"):
        config_from_json(london)


def test_sessions_are_validated() -> None:
    with pytest.raises(ConfigError):
        config_from_json(_with("session_filter", {"start_hour": 25, "end_hour": 3}))
    with pytest.raises(ConfigError):
        config_from_json(_with("session_filter", {"start_hour": 3}))
    with pytest.raises(ConfigError):
        config_from_json(
            _with("session_filter", {"start_hour": 3, "end_hour": 24, "end_minute": 5})
        )
    ok = config_from_json(_with("session_filter", {"start_hour": 3, "end_hour": 24}))
    assert ok.session_filter == Session(3, 24)


def test_an_instrument_must_be_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.labs.forex import types

    monkeypatch.setitem(
        types.INSTRUMENTS, "GBPUSD", replace(types.INSTRUMENTS["GBPUSD"], enabled=False)
    )
    with pytest.raises(ConfigError, match="not enabled"):
        config_from_json(_with("symbol", "GBPUSD"))
    assert config_from_json(_with("symbol", "USDJPY")).symbol == "USDJPY"


# --- grids -----------------------------------------------------------------


BASE = meta.default_config(StrategyId.RSI_PULLBACK)


def test_a_default_grid_validates_for_its_strategy() -> None:
    for sid in StrategyId:
        grid = codec.validate_grid(meta.default_config(sid), meta.default_grid(sid))
        assert grid


def test_a_grid_is_capped_at_36_cells() -> None:
    codec.validate_grid(
        BASE,
        {
            "params.rsi_period": [10, 12, 14, 16, 18, 20],
            "params.risk_reward": [1, 1.5, 2, 2.5, 3, 3.5],
        },
    )
    with pytest.raises(ConfigError, match="36"):
        codec.validate_grid(
            BASE,
            {
                "params.rsi_period": [10, 12, 14, 16, 18, 20, 22],
                "params.risk_reward": [1, 1.5, 2, 2.5, 3, 3.5],
            },
        )


@pytest.mark.parametrize(
    "space",
    [
        {},
        {"symbol": ["EURUSD"]},
        {"timeframe": ["5m"]},
        {"strategy": ["rsi_pullback"]},
        {"params.nope": [1]},
        {"params.rsi_period": []},
        {"params.rsi_period": [14, 14]},
        {"params.rsi_period": [1]},  # below the bound: a grid cell is held to the same limits
        {"params.rsi_period": ["fourteen"]},
        {"risk.max_leverage": [50]},
        {"params.asian_session": [{"start_hour": 0, "end_hour": 6}]},
    ],
)
def test_a_bad_grid_is_refused(space: dict[str, Any]) -> None:
    with pytest.raises(ConfigError):
        codec.validate_grid(BASE, space)


def test_apply_params_validates_the_result() -> None:
    cfg = codec.apply_params(BASE, {"params.rsi_period": 21, "params.risk_reward": 2.5})
    assert cfg.params.rsi_period == 21
    assert cfg.params.risk_reward == 2.5
    with pytest.raises(ConfigError):
        codec.apply_params(BASE, {"params.rsi_period": 1})
