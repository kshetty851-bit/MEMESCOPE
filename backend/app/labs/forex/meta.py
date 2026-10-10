"""What the lab offers: strategy defaults, form fields and default grids. Pure.

`/meta` is the page's form definition, so the page never hard-codes a default
or a bound. The bounds shown here are the same constants `codec` enforces - the
field specs are built from `codec.FLOAT_BOUNDS` and friends, not copied - so
the form cannot promise a value the server will refuse.

Defaults are baseline hypotheses, not tuned values. `CONFIG_VERSION` in `types`
is bumped whenever one changes, and every run records it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.labs.forex import codec
from app.labs.forex.types import (
    INSTRUMENTS,
    TIMEFRAME_SECONDS,
    BacktestConfig,
    DirectionMode,
    StopMethod,
    StrategyId,
    StrategyParams,
    TakeProfitMethod,
    Timeframe,
)

TIMEFRAMES = tuple(tf.value for tf in TIMEFRAME_SECONDS)
RISK_OPTIONS_PCT = ("0.25", "0.5", "1", "2")
TARGET_PCTS = (5, 10, 20, 50, 100)
DISCLAIMER_CODE = "historical_observation_not_forecast"

DEFAULT_GRIDS: dict[StrategyId, dict[str, list[object]]] = {
    StrategyId.LONDON_BREAKOUT: {
        "params.breakout_buffer_pips": [0, 1, 2, 3],
        "params.risk_reward": [1.0, 1.5, 2.0, 2.5],
    },
    StrategyId.RSI_PULLBACK: {
        "params.rsi_period": [10, 14, 21],
        "params.risk_reward": [1.5, 2.0, 2.5],
    },
    StrategyId.BOLLINGER_REVERSION: {
        "params.bb_std": [1.5, 2.0, 2.5],
        "params.stop_atr_multiple": [1.0, 1.5, 2.0],
    },
}


@dataclass(frozen=True, slots=True)
class StrategyInfo:
    id: StrategyId
    name: str
    description: str
    timeframe: Timeframe
    params: StrategyParams


STRATEGIES: dict[StrategyId, StrategyInfo] = {
    StrategyId.LONDON_BREAKOUT: StrategyInfo(
        StrategyId.LONDON_BREAKOUT,
        "London breakout",
        "Draws the high and low of the Asian session (00:00-06:00 UTC), then enters on "
        "the first close beyond that range during the London window (07:00-10:00 UTC), "
        "in the direction of the higher-timeframe trend. The stop sits on the opposite "
        "side of the range and open trades are closed when the window ends.",
        Timeframe.M5,
        StrategyParams(
            stop_method=StopMethod.RANGE,
            breakout_buffer_pips=1.0,
            close_at_session_end=True,
        ),
    ),
    StrategyId.RSI_PULLBACK: StrategyInfo(
        StrategyId.RSI_PULLBACK,
        "RSI pullback",
        "In a higher-timeframe uptrend, enters long when RSI rises back through the "
        "long level after a dip; in a downtrend, enters short when RSI falls back "
        "through the short level after a rally. The stop is a multiple of ATR.",
        Timeframe.M5,
        StrategyParams(),
    ),
    StrategyId.BOLLINGER_REVERSION: StrategyInfo(
        StrategyId.BOLLINGER_REVERSION,
        "Bollinger reversion",
        "Waits for a close outside the Bollinger band with RSI at an extreme, then "
        "enters when price closes back inside the band within a few bars, unless "
        "price is stretched too far from the trend average. The stop is a multiple "
        "of ATR.",
        Timeframe.M5,
        StrategyParams(),
    ),
}


def default_config(strategy: StrategyId) -> BacktestConfig:
    info = STRATEGIES[strategy]
    return BacktestConfig(strategy=strategy, timeframe=info.timeframe, params=info.params)


def default_grid(strategy: StrategyId) -> dict[str, list[object]]:
    return {path: list(values) for path, values in DEFAULT_GRIDS[strategy].items()}


# --------------------------------------------------------------------------
# Field specs
# --------------------------------------------------------------------------


def _field(
    path: str,
    label: str,
    kind: str,
    help: str = "",
    **extra: Any,
) -> dict[str, Any]:
    out: dict[str, Any] = {"path": path, "label": label, "kind": kind, "help": help}
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def _num(
    path: str, label: str, help: str, step: float | int | str | None = None
) -> dict[str, Any]:
    """A numeric field whose min / max come from `codec`'s bounds."""
    if path in codec.INT_BOUNDS:
        lo_i, hi_i = codec.INT_BOUNDS[path]
        return _field(path, label, "int", help, min=lo_i, max=hi_i, step=step or 1)
    if path in codec.FLOAT_BOUNDS:
        lo_f, hi_f = codec.FLOAT_BOUNDS[path]
        return _field(path, label, "float", help, min=lo_f, max=hi_f, step=step)
    lo_d, hi_d = codec.DECIMAL_BOUNDS[path]
    return _field(path, label, "decimal", help, min=str(lo_d), max=str(hi_d), step=step)


def _options(enum: type[Any], skip: tuple[Any, ...] = ()) -> list[str]:
    return [m.value for m in enum if m not in skip]


def shared_fields() -> list[dict[str, Any]]:
    enabled = [s for s, i in INSTRUMENTS.items() if i.enabled]
    trend_tfs = _options(Timeframe, (Timeframe.M1,))
    return [
        _field("symbol", "Instrument", "enum", "Currency pair to test.", options=enabled),
        _field(
            "timeframe",
            "Timeframe",
            "enum",
            "Candle size the strategy trades on.",
            options=list(TIMEFRAMES),
        ),
        _field(
            "direction",
            "Direction",
            "enum",
            "Which sides may be traded.",
            options=_options(DirectionMode),
        ),
        _field(
            "session_filter",
            "Entry window (UTC)",
            "session",
            "Extra restriction on when new trades may open, as HH:MM-HH:MM. Empty = any time.",
        ),
        _num(
            "costs.spread_pips",
            "Spread (pips)",
            "Full bid/ask spread charged on every fill.",
            0.1,
        ),
        _num("costs.slippage_pips", "Slippage (pips)", "Extra adverse price per fill.", 0.1),
        _num(
            "costs.commission_per_lot_side",
            "Commission (USD per lot per side)",
            "Charged on entry and again on exit.",
            "0.5",
        ),
        _num(
            "costs.swap_long_per_lot",
            "Swap long (USD per lot per night)",
            "Negative = the account pays. Wednesday charges three nights.",
            "0.5",
        ),
        _num(
            "costs.swap_short_per_lot",
            "Swap short (USD per lot per night)",
            "Negative = the account pays. Wednesday charges three nights.",
            "0.5",
        ),
        _field(
            "costs.financing_enabled",
            "Charge overnight financing",
            "bool",
            "Applies swap to positions held through 22:00 UTC.",
        ),
        _num(
            "risk.initial_capital", "Starting capital (USD)", "Account currency is USD.", "100"
        ),
        _num(
            "risk.max_leverage",
            "Maximum leverage",
            "Caps position size; it never multiplies returns.",
        ),
        _num(
            "risk.risk_per_trade_pct",
            "Risk per trade (%)",
            "Percent of equity lost if the stop is hit; sets the position size.",
            "0.05",
        ),
        _num(
            "risk.max_daily_loss_pct",
            "Daily loss limit (%)",
            "No new entries for the rest of the UTC day once reached. 0 = off.",
            "0.5",
        ),
        _num("risk.max_trades_per_day", "Max trades per day", "New entries per UTC day."),
        _num(
            "risk.max_open_positions", "Max open positions", "Positions open at the same time."
        ),
        _num(
            "risk.margin_closeout_pct",
            "Margin close-out (%)",
            "Everything is closed when equity / used margin falls to this.",
            "5",
        ),
        _field(
            "params.trend_filter",
            "Higher-timeframe trend filter",
            "bool",
            "Only trade in the direction of the trend average.",
        ),
        _field(
            "params.trend_timeframe",
            "Trend timeframe",
            "enum",
            "Candle size the trend average is built from.",
            options=trend_tfs,
        ),
        _num("params.trend_ema_period", "Trend EMA period", "Bars of the trend timeframe."),
        _num("params.atr_period", "ATR period", "Bars used for the average true range."),
        _field(
            "params.stop_method",
            "Stop method",
            "enum",
            "How far away the stop is placed. 'range' applies to the London breakout only.",
            options=_options(StopMethod),
        ),
        _num(
            "params.stop_atr_multiple",
            "Stop distance (x ATR)",
            "Used when the stop method is atr.",
            0.1,
        ),
        _num(
            "params.stop_pips",
            "Stop distance (pips)",
            "Used when the stop method is fixed_pips.",
            1,
        ),
        _field(
            "params.take_profit_method",
            "Take-profit method",
            "enum",
            "How the target is placed.",
            options=_options(TakeProfitMethod),
        ),
        _num(
            "params.risk_reward",
            "Reward to risk",
            "Target distance as a multiple of the stop.",
            0.25,
        ),
        _num(
            "params.take_profit_pips",
            "Take-profit (pips)",
            "Used when the method is fixed_pips.",
            1,
        ),
        _field(
            "params.close_at_session_end",
            "Close at window end",
            "bool",
            "Close any open trade when the strategy's window ends.",
        ),
    ]


def param_fields(strategy: StrategyId) -> list[dict[str, Any]]:
    if strategy is StrategyId.LONDON_BREAKOUT:
        return [
            _field(
                "params.asian_session",
                "Asian range window (UTC)",
                "session",
                "The hours whose high and low define the range.",
            ),
            _field(
                "params.trading_session",
                "Trading window (UTC)",
                "session",
                "Breakouts count only inside this window.",
            ),
            _num(
                "params.breakout_buffer_pips",
                "Breakout buffer (pips)",
                "A close must be this far beyond the range.",
                0.5,
            ),
            _num(
                "params.breakout_confirmation_bars",
                "Confirmation closes",
                "Consecutive closes beyond the range required.",
            ),
            _num(
                "params.range_stop_buffer_pips",
                "Range stop buffer (pips)",
                "Extra distance beyond the opposite side of the range.",
                0.5,
            ),
            _num(
                "params.min_range_pips",
                "Minimum range (pips)",
                "Days with a narrower Asian range are skipped.",
                1,
            ),
            _num(
                "params.max_range_pips",
                "Maximum range (pips)",
                "Days with a wider Asian range are skipped.",
                1,
            ),
            _field(
                "params.one_trade_per_side_per_day",
                "One trade per side per day",
                "bool",
                "At most one long and one short breakout each day.",
            ),
        ]
    if strategy is StrategyId.RSI_PULLBACK:
        return [
            _num("params.rsi_period", "RSI period", "Bars used for RSI."),
            _num(
                "params.rsi_long_level",
                "Long level",
                "RSI rising back through this level triggers a long.",
                1,
            ),
            _num(
                "params.rsi_short_level",
                "Short level",
                "RSI falling back through this level triggers a short.",
                1,
            ),
        ]
    return [
        _num("params.bb_period", "Band period", "Bars used for the moving average and bands."),
        _num(
            "params.bb_std",
            "Band width (std devs)",
            "Standard deviations either side of the average.",
            0.1,
        ),
        _num("params.rsi_period", "RSI period", "Bars used for RSI."),
        _num("params.rsi_oversold", "RSI oversold", "A long setup needs RSI below this.", 1),
        _num(
            "params.rsi_overbought", "RSI overbought", "A short setup needs RSI above this.", 1
        ),
        _num(
            "params.reentry_window_bars",
            "Re-entry window (bars)",
            "Bars after the outside close in which the close back inside must happen.",
        ),
        _num(
            "params.trend_max_distance_atr",
            "Max stretch from trend (x ATR)",
            "Setups further than this from the trend average are skipped. 0 = off.",
            0.5,
        ),
    ]


def instruments_meta() -> list[dict[str, Any]]:
    return [
        {
            "symbol": i.symbol,
            "base": i.base,
            "quote": i.quote,
            "pip_size": i.pip_size,
            "price_decimals": i.price_decimals,
            "contract_size": i.contract_size,
            "min_units": i.min_units,
            "enabled": i.enabled,
        }
        for i in INSTRUMENTS.values()
    ]


def strategies_meta() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sid, info in STRATEGIES.items():
        out.append(
            {
                "id": sid.value,
                "name": info.name,
                "description": info.description,
                "timeframe": info.timeframe.value,
                "default_config": codec.config_to_json(default_config(sid)),
                "param_fields": param_fields(sid),
                "default_grid": default_grid(sid),
            }
        )
    return out
