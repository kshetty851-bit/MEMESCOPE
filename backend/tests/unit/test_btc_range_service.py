"""Pure parts of the lab's service layer: sampling, bounds, window and config rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.labs.btc_range import service
from app.labs.btc_range.bounds import BOUNDS, config_field_names
from app.labs.btc_range.schemas import BacktestIn, ConfigIn, StrategyConfigOut
from app.labs.btc_range.types import Reason, StrategyConfig

pytestmark = pytest.mark.unit


# --- downsample ---------------------------------------------------------------


@pytest.mark.parametrize("n", [2, 3, 299, 300, 301, 500, 2880, 35_040])
@pytest.mark.parametrize("cap", [2, 300, 500])
def test_downsample_keeps_first_and_last_and_respects_the_cap(n: int, cap: int) -> None:
    items = list(range(n))
    out = service.downsample(items, cap)
    assert len(out) <= cap
    assert out[0] == 0
    assert out[-1] == n - 1
    assert out == sorted(set(out)), "ascending, no repeats"


def test_downsample_returns_short_input_untouched() -> None:
    assert service.downsample([1, 2, 3], 300) == [1, 2, 3]
    assert service.downsample([], 300) == []


def test_downsample_needs_room_for_both_ends() -> None:
    with pytest.raises(ValueError):
        service.downsample([1, 2, 3], 1)


# --- bounds -------------------------------------------------------------------


def test_bounds_cover_exactly_the_strategy_config_fields() -> None:
    assert set(BOUNDS) == set(config_field_names())
    assert list(BOUNDS) == list(config_field_names()), "listed in declaration order"
    assert set(StrategyConfigOut.model_fields) == set(config_field_names())
    assert set(ConfigIn.model_fields) == set(config_field_names())


@pytest.mark.parametrize("name", list(BOUNDS))
def test_defaults_lie_within_bounds(name: str) -> None:
    bound = BOUNDS[name]
    value = getattr(StrategyConfig(), name)
    if bound.kind == "bool":
        assert isinstance(value, bool)
        return
    assert bound.min <= Decimal(value) <= bound.max
    assert bound.min < bound.max
    assert bound.step > 0
    assert (bound.kind == "int") == isinstance(value, int)


def test_the_documented_ranges() -> None:
    expect = {
        "lookback": (24, 672),
        "entry_zone": ("0.05", "0.45"),
        "tp_target": ("0.2", "1.0"),
        "sl_buffer": ("0.02", "1.0"),
        "fee_bps": (0, 50),
        "slippage_bps": (0, 50),
        "risk_per_trade_pct": ("0.1", "5"),
        "max_leverage": (1, 5),
        "starting_balance": (100, 1_000_000),
    }
    for name, (lo, hi) in expect.items():
        assert (BOUNDS[name].min, BOUNDS[name].max) == (Decimal(lo), Decimal(hi)), name


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("lookback", 23),
        ("lookback", 673),
        ("entry_zone", "0.46"),
        ("entry_zone", "0.04"),
        ("fee_bps", "-1"),
        ("slippage_bps", 51),
        ("max_leverage", "5.5"),
        ("starting_balance", 99),
        ("starting_balance", 1_000_001),
        ("tp_target", "NaN"),
        ("tp_target", "Infinity"),
    ],
)
def test_out_of_bounds_values_are_refused(name: str, value: object) -> None:
    with pytest.raises(ValidationError) as err:
        ConfigIn(**{name: value})
    assert err.value.errors()[0]["loc"] == (name,)


def test_bounds_edges_are_inclusive() -> None:
    ConfigIn(lookback=24, entry_zone="0.45", max_leverage=1, starting_balance=1_000_000)


def test_unknown_keys_are_refused() -> None:
    with pytest.raises(ValidationError):
        ConfigIn(lookbak=96)  # type: ignore[call-arg]


def test_omitted_and_null_fields_take_the_defaults() -> None:
    assert ConfigIn().to_config() == StrategyConfig()
    assert ConfigIn(lookback=None).to_config() == StrategyConfig()
    cfg = ConfigIn(lookback=48, entry_zone="0.25", allow_short=False).to_config()
    assert cfg == StrategyConfig(lookback=48, entry_zone=Decimal("0.25"), allow_short=False)


def test_backtest_body_defaults() -> None:
    body = BacktestIn()
    assert body.config.to_config() == StrategyConfig()
    assert body.start is None
    assert body.end is None


def test_contradictory_widths_are_refused() -> None:
    with pytest.raises(service.InvalidConfigError):
        service.check_config(
            StrategyConfig(min_width_pct=Decimal("4"), max_width_pct=Decimal("2"))
        )
    service.check_config(StrategyConfig())


# --- window -------------------------------------------------------------------

LAST = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def test_default_window_is_30_days_to_the_close_of_the_newest_candle() -> None:
    start, end = service.resolve_window(None, None, LAST) or (None, None)
    assert end == LAST + timedelta(minutes=15)
    assert start == end - timedelta(days=30)


def test_start_defaults_from_a_given_end() -> None:
    end = LAST - timedelta(days=2)
    assert service.resolve_window(None, end, LAST) == (end - timedelta(days=30), end)


def test_no_stored_candles_means_no_default_window() -> None:
    assert service.resolve_window(None, None, None) is None


def test_naive_timestamps_are_read_as_utc() -> None:
    start, end = service.resolve_window(
        datetime(2026, 10, 1), datetime(2026, 10, 2), LAST
    ) or (None, None)
    assert start == datetime(2026, 10, 1, tzinfo=UTC)
    assert end == datetime(2026, 10, 2, tzinfo=UTC)


def test_a_window_of_exactly_365_days_is_allowed_and_longer_is_not() -> None:
    end = LAST
    assert service.resolve_window(end - timedelta(days=365), end, LAST) is not None
    with pytest.raises(service.InvalidWindowError):
        service.resolve_window(end - timedelta(days=365, seconds=1), end, LAST)


@pytest.mark.parametrize("delta", [timedelta(0), timedelta(hours=1)])
def test_start_must_precede_end(delta: timedelta) -> None:
    with pytest.raises(service.InvalidWindowError):
        service.resolve_window(LAST + delta, LAST, LAST)


# --- ordering -----------------------------------------------------------------


def test_wait_reasons_sort_by_count_then_code() -> None:
    out = service.wait_reasons_out(
        {
            Reason.MID_RANGE: 5,
            Reason.TRENDING: 9,
            Reason.BREAKOUT_UP: 5,
            Reason.LOW_CONFIDENCE: 1,
        }
    )
    assert [(w.code, w.count) for w in out] == [
        ("trending", 9),
        ("breakout_up", 5),
        ("mid_range", 5),
        ("low_confidence", 1),
    ]
    assert all(w.text for w in out)


def test_decimals_never_render_with_an_exponent() -> None:
    assert service.dec(Decimal("1E+2")) == "100"
    assert service.dec(Decimal("0.50")) == "0.50"
    assert service.dec(Decimal("-0.00001")) == "-0.00001"
