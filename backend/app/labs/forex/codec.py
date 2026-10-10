"""ConfigJSON <-> BacktestConfig, with bounds. Pure.

The JSON a run records is exactly what was run, and reading it back must give
an EQUAL `BacktestConfig` - otherwise "re-run this version" would quietly run
something else. So money-like fields (capital, commission, swap, risk percent)
travel as decimal STRINGS and are parsed with `Decimal(str)`, never through a
float; enums travel as their values; sessions as
`{start_hour, end_hour, start_minute, end_minute}`.

Bounds live here, not in the request schema: the same limits must hold for a
config that arrives from a saved version, a CLI call or a grid cell, and a
schema validator would only see the first. Every violation raises
`ConfigError`, a `ValueError` the API maps to 422. Nothing is clamped or
repaired - a value out of range is refused, because a silently adjusted risk
percent is a run that did not test what the person asked.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

from app.labs.forex.research import with_param
from app.labs.forex.types import (
    INSTRUMENTS,
    BacktestConfig,
    CostConfig,
    DirectionMode,
    RiskConfig,
    Session,
    StopMethod,
    StrategyId,
    StrategyParams,
    Timeframe,
)

MAX_LEVERAGE = 20
MAX_GRID_CELLS = 36

#: (low, high) inclusive. Anything not listed here is not a number field.
FLOAT_BOUNDS: dict[str, tuple[float, float]] = {
    "params.stop_atr_multiple": (0.1, 20.0),
    "params.stop_pips": (0.5, 500.0),
    "params.risk_reward": (0.25, 10.0),
    "params.take_profit_pips": (0.5, 1000.0),
    "params.breakout_buffer_pips": (0.0, 50.0),
    "params.range_stop_buffer_pips": (0.0, 50.0),
    "params.min_range_pips": (0.0, 500.0),
    "params.max_range_pips": (0.0, 1000.0),
    "params.rsi_long_level": (1.0, 99.0),
    "params.rsi_short_level": (1.0, 99.0),
    "params.bb_std": (0.1, 5.0),
    "params.rsi_oversold": (1.0, 99.0),
    "params.rsi_overbought": (1.0, 99.0),
    "params.trend_max_distance_atr": (0.0, 20.0),
    "costs.spread_pips": (0.0, 20.0),
    "costs.slippage_pips": (0.0, 20.0),
}
INT_BOUNDS: dict[str, tuple[int, int]] = {
    "params.trend_ema_period": (2, 500),
    "params.atr_period": (2, 500),
    "params.rsi_period": (2, 500),
    "params.bb_period": (2, 500),
    "params.breakout_confirmation_bars": (1, 20),
    "params.reentry_window_bars": (1, 50),
    "risk.max_leverage": (1, MAX_LEVERAGE),
    "risk.max_trades_per_day": (1, 1000),
    "risk.max_open_positions": (1, 10),
}
DECIMAL_BOUNDS: dict[str, tuple[Decimal, Decimal]] = {
    "costs.commission_per_lot_side": (Decimal(0), Decimal(50)),
    "costs.swap_long_per_lot": (Decimal(-100), Decimal(100)),
    "costs.swap_short_per_lot": (Decimal(-100), Decimal(100)),
    "risk.initial_capital": (Decimal(100), Decimal(10_000_000)),
    "risk.risk_per_trade_pct": (Decimal("0.01"), Decimal(5)),
    "risk.max_daily_loss_pct": (Decimal(0), Decimal(50)),
    "risk.margin_closeout_pct": (Decimal(1), Decimal(100)),
}
BOOL_FIELDS = {
    "params.trend_filter",
    "params.close_at_session_end",
    "params.one_trade_per_side_per_day",
    "costs.financing_enabled",
}
SESSION_FIELDS = ("params.asian_session", "params.trading_session")

_TOP_LEVEL = (
    "strategy",
    "symbol",
    "timeframe",
    "direction",
    "params",
    "costs",
    "risk",
    "session_filter",
)
#: Grid and sensitivity paths may vary these groups only; the instrument,
#: timeframe and strategy define WHAT is tested and are never searched over.
SEARCHABLE_PREFIXES = ("params.", "costs.", "risk.")


class ConfigError(ValueError):
    """A config (or grid) that is out of bounds or malformed. Maps to 422."""


# --------------------------------------------------------------------------
# To JSON
# --------------------------------------------------------------------------


def _dec_str(value: Decimal) -> str:
    return format(value, "f")


def session_to_json(s: Session | None) -> dict[str, int] | None:
    if s is None:
        return None
    return {
        "start_hour": s.start_hour,
        "end_hour": s.end_hour,
        "start_minute": s.start_minute,
        "end_minute": s.end_minute,
    }


def _group_to_json(obj: object) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in dataclasses.fields(obj):  # type: ignore[arg-type]
        value = getattr(obj, f.name)
        if isinstance(value, Enum):
            out[f.name] = value.value
        elif isinstance(value, Decimal):
            out[f.name] = _dec_str(value)
        elif isinstance(value, Session):
            out[f.name] = session_to_json(value)
        else:
            out[f.name] = value
    return out


def config_to_json(cfg: BacktestConfig) -> dict[str, Any]:
    return {
        "strategy": cfg.strategy.value,
        "symbol": cfg.symbol,
        "timeframe": cfg.timeframe.value,
        "direction": cfg.direction.value,
        "params": _group_to_json(cfg.params),
        "costs": _group_to_json(cfg.costs),
        "risk": _group_to_json(cfg.risk),
        "session_filter": session_to_json(cfg.session_filter),
    }


# --------------------------------------------------------------------------
# From JSON
# --------------------------------------------------------------------------


def _is_number(v: object) -> bool:
    return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)


def _float(v: object, path: str) -> float:
    if not _is_number(v):
        raise ConfigError(f"{path}: expected a number")
    f = float(v)  # type: ignore[arg-type]
    if not math.isfinite(f):
        raise ConfigError(f"{path}: must be finite")
    return f


def _int(v: object, path: str) -> int:
    if not _is_number(v):
        raise ConfigError(f"{path}: expected a whole number")
    f = float(v)  # type: ignore[arg-type]
    if not math.isfinite(f) or not f.is_integer():
        raise ConfigError(f"{path}: expected a whole number")
    return int(f)


def _decimal(v: object, path: str) -> Decimal:
    # Strings are the contract; a JSON number is accepted too, but through its
    # shortest repr so 0.1 stays 0.1 instead of becoming a float expansion.
    if isinstance(v, bool) or not isinstance(v, (str, int, float, Decimal)):
        raise ConfigError(f"{path}: expected a decimal string")
    try:
        d = Decimal(str(v).strip())
    except InvalidOperation as exc:
        raise ConfigError(f"{path}: not a decimal number") from exc
    if not d.is_finite():
        raise ConfigError(f"{path}: must be finite")
    return d


def _enum(v: object, enum: type[Enum], path: str) -> Any:
    try:
        return enum(v)
    except ValueError as exc:
        allowed = ", ".join(str(m.value) for m in enum)
        raise ConfigError(f"{path}: must be one of {allowed}") from exc


def _bool(v: object, path: str) -> bool:
    if not isinstance(v, bool):
        raise ConfigError(f"{path}: expected true or false")
    return v


def session_from_json(v: object, path: str) -> Session:
    if not isinstance(v, Mapping):
        raise ConfigError(f"{path}: expected a session object")
    unknown = set(v) - {"start_hour", "end_hour", "start_minute", "end_minute"}
    if unknown:
        raise ConfigError(f"{path}: unknown keys {sorted(unknown)}")
    if "start_hour" not in v or "end_hour" not in v:
        raise ConfigError(f"{path}: start_hour and end_hour are required")
    s = Session(
        _int(v["start_hour"], f"{path}.start_hour"),
        _int(v["end_hour"], f"{path}.end_hour"),
        _int(v.get("start_minute", 0), f"{path}.start_minute"),
        _int(v.get("end_minute", 0), f"{path}.end_minute"),
    )
    _check_session(s, path)
    return s


def _check_session(s: Session, path: str) -> None:
    if not (0 <= s.start_hour <= 23 and 0 <= s.start_minute <= 59):
        raise ConfigError(f"{path}: start must be a time of day (00:00 to 23:59)")
    # 24:00 is allowed as an END only: "until midnight".
    if not (0 <= s.end_hour <= 24 and 0 <= s.end_minute <= 59):
        raise ConfigError(f"{path}: end must be a time of day (00:00 to 24:00)")
    if s.end_hour == 24 and s.end_minute != 0:
        raise ConfigError(f"{path}: end must not be after 24:00")


def _group_from_json(cls: type, data: object, group: str, base: object) -> Any:
    """Build dataclass `cls` from `data`; missing keys take `base`'s values."""
    if data is None:
        data = {}
    if not isinstance(data, Mapping):
        raise ConfigError(f"{group}: expected an object")
    names = {f.name for f in dataclasses.fields(cls)}
    unknown = set(data) - names
    if unknown:
        raise ConfigError(f"{group}: unknown fields {sorted(unknown)}")
    kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        default = getattr(base, f.name)
        if f.name not in data:
            kwargs[f.name] = default
            continue
        raw = data[f.name]
        path = f"{group}.{f.name}"
        if isinstance(default, Enum):
            kwargs[f.name] = _enum(raw, type(default), path)
        elif isinstance(default, bool):
            kwargs[f.name] = _bool(raw, path)
        elif isinstance(default, Decimal):
            kwargs[f.name] = _decimal(raw, path)
        elif isinstance(default, int):
            kwargs[f.name] = _int(raw, path)
        elif isinstance(default, float):
            kwargs[f.name] = _float(raw, path)
        elif isinstance(default, Session):
            kwargs[f.name] = session_from_json(raw, path)
        else:  # pragma: no cover - a new field type must be taught here
            raise ConfigError(f"{path}: unsupported field type")
    return cls(**kwargs)


def config_from_json(data: object) -> BacktestConfig:
    """Parse and VALIDATE. Raises `ConfigError` on anything out of bounds."""
    if not isinstance(data, Mapping):
        raise ConfigError("config: expected an object")
    unknown = set(data) - set(_TOP_LEVEL)
    if unknown:
        raise ConfigError(f"config: unknown fields {sorted(unknown)}")
    if "strategy" not in data:
        raise ConfigError("config.strategy is required")
    strategy = _enum(data["strategy"], StrategyId, "strategy")
    symbol = data.get("symbol", "EURUSD")
    if not isinstance(symbol, str):
        raise ConfigError("symbol: expected a string")
    timeframe = _enum(data.get("timeframe", Timeframe.M5.value), Timeframe, "timeframe")
    direction = _enum(
        data.get("direction", DirectionMode.BOTH.value), DirectionMode, "direction"
    )
    sf = data.get("session_filter")
    cfg = BacktestConfig(
        strategy=strategy,
        symbol=symbol,
        timeframe=timeframe,
        direction=direction,
        params=_group_from_json(
            StrategyParams, data.get("params"), "params", StrategyParams()
        ),
        costs=_group_from_json(CostConfig, data.get("costs"), "costs", CostConfig()),
        risk=_group_from_json(RiskConfig, data.get("risk"), "risk", RiskConfig()),
        session_filter=None if sf is None else session_from_json(sf, "session_filter"),
    )
    validate_config(cfg)
    return cfg


# --------------------------------------------------------------------------
# Bounds
# --------------------------------------------------------------------------


def _get(cfg: BacktestConfig, path: str) -> object:
    obj: object = cfg
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def validate_config(cfg: BacktestConfig) -> None:
    inst = INSTRUMENTS.get(cfg.symbol)
    if inst is None:
        raise ConfigError(f"symbol: unknown instrument {cfg.symbol!r}")
    if not inst.enabled:
        raise ConfigError(f"symbol: {cfg.symbol} is not enabled yet")

    for path, (lo, hi) in FLOAT_BOUNDS.items():
        v = _get(cfg, path)
        if not isinstance(v, float) or not lo <= v <= hi:
            raise ConfigError(f"{path}: must be between {lo:g} and {hi:g}")
    for path, (ilo, ihi) in INT_BOUNDS.items():
        v = _get(cfg, path)
        if not isinstance(v, int) or isinstance(v, bool) or not ilo <= v <= ihi:
            raise ConfigError(f"{path}: must be a whole number between {ilo} and {ihi}")
    for path, (dlo, dhi) in DECIMAL_BOUNDS.items():
        v = _get(cfg, path)
        if not isinstance(v, Decimal) or not v.is_finite() or not dlo <= v <= dhi:
            raise ConfigError(f"{path}: must be between {dlo} and {dhi}")

    p = cfg.params
    for path in SESSION_FIELDS:
        s = _get(cfg, path)
        assert isinstance(s, Session)
        _check_session(s, path)
    if cfg.session_filter is not None:
        _check_session(cfg.session_filter, "session_filter")
    if p.min_range_pips > p.max_range_pips:
        raise ConfigError("params.min_range_pips must not exceed params.max_range_pips")
    if p.rsi_long_level >= p.rsi_short_level:
        raise ConfigError("params.rsi_long_level must be below params.rsi_short_level")
    if p.rsi_oversold >= p.rsi_overbought:
        raise ConfigError("params.rsi_oversold must be below params.rsi_overbought")
    if p.stop_method is StopMethod.RANGE and cfg.strategy is not StrategyId.LONDON_BREAKOUT:
        raise ConfigError("params.stop_method 'range' is only defined for the London breakout")
    if cfg.strategy is StrategyId.LONDON_BREAKOUT:
        for path in SESSION_FIELDS:
            s = _get(cfg, path)
            assert isinstance(s, Session)
            if s.start_hour * 60 + s.start_minute >= s.end_hour * 60 + s.end_minute:
                raise ConfigError(f"{path}: must not wrap midnight for the London breakout")


# --------------------------------------------------------------------------
# Grids
# --------------------------------------------------------------------------


def validate_grid(
    base: BacktestConfig, space: Mapping[str, object], *, max_cells: int = MAX_GRID_CELLS
) -> dict[str, Sequence[object]]:
    """Check an optimisation grid and return it normalised to lists.

    Every path must name a scalar field in params / costs / risk, every value
    must be a legal value for it (the WHOLE config is re-validated per value),
    and the product of the value counts is capped. The cap is what keeps a
    request from holding the one worker slot for an hour.
    """
    if not isinstance(space, Mapping) or not space:
        raise ConfigError("grid: expected a non-empty object of path -> values")
    cells = 1
    out: dict[str, Sequence[object]] = {}
    for path, values in space.items():
        if not isinstance(path, str) or not path.startswith(SEARCHABLE_PREFIXES):
            raise ConfigError(f"grid: {path!r} is not a searchable parameter path")
        if path in SESSION_FIELDS:
            raise ConfigError(f"grid: {path} cannot be searched")
        if not isinstance(values, (list, tuple)) or not values:
            raise ConfigError(f"grid: {path} needs a non-empty list of values")
        if len({repr(v) for v in values}) != len(values):
            raise ConfigError(f"grid: {path} repeats a value")
        cells *= len(values)
        if cells > max_cells:
            raise ConfigError(f"grid: more than {max_cells} cells")
        for v in values:
            try:
                candidate = with_param(base, path, v)
            except (ValueError, TypeError) as exc:
                raise ConfigError(f"grid: {path}: {exc}") from exc
            validate_config(candidate)
        out[path] = list(values)
    return out


def apply_params(base: BacktestConfig, params: Mapping[str, object]) -> BacktestConfig:
    cfg = base
    for path, value in params.items():
        try:
            cfg = with_param(cfg, path, value)
        except (ValueError, TypeError) as exc:
            raise ConfigError(f"{path}: {exc}") from exc
    validate_config(cfg)
    return cfg
