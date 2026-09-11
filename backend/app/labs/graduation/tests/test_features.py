"""The feature and outcome maths, against synthetic change-only series.

Every expected number here was worked out by hand from
`fixtures/curve_series.json`. Nothing in this file touches a database: the
engine's two computation methods take plain lists, and the SQL around them is
thin enough to check separately.

The case that matters most is `sparse`. `grad_curve_samples` holds a row only
when a reserve MOVED, so a 45-minute gap between 91% and 96% means the curve sat
still — not that nobody looked. Every time-based feature must forward-fill, and
a reader that did not would compute each velocity from the wrong end of a gap
and report exactly the tokens that stalled as the ones that flew.
"""

from __future__ import annotations

import json
import pathlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.labs.graduation import config, features
from app.labs.graduation.features import (
    CurvePoint,
    FeatureEngine,
    PricePoint,
    changes_within,
    extremes,
    minutes_covered,
    price_at,
    progress_at,
    retraced,
    returns,
    stall_count,
    velocity,
)
from app.labs.graduation.models import SOURCE_DEXSCREENER, SOURCE_GECKOTERMINAL

D = Decimal
LAUNCH = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
SERIES = json.loads((pathlib.Path(__file__).parent / "fixtures"
                     / "curve_series.json").read_text())


def at(minute: float) -> datetime:
    return LAUNCH + timedelta(minutes=minute)


def curve(name: str) -> list[CurvePoint]:
    return [CurvePoint(ts=at(m), progress_pct=D(p), market_cap_quote=None,
                       complete=c)
            for m, p, c in SERIES[name]["samples"]]


class Checkpoint:
    """Just enough of `GradCheckpoint` for `_features` to read."""

    def __init__(self, ts: datetime, market_cap_quote: Decimal | None = None):
        self.ts = ts
        self.market_cap_quote = market_cap_quote


def checkpoints(name: str) -> dict[Decimal, Checkpoint]:
    return {D(level): Checkpoint(at(minute))
            for level, minute, _ in SERIES[name]["checkpoints"]}


def prices(name: str, *, graduated_at: datetime, every_minute: bool = True
           ) -> list[PricePoint]:
    """Expand a `[minute, price]` shape into one sample a minute, held flat
    between the named points — which is what a 60-second poll produces."""
    spec = SERIES[name]
    open_at = graduated_at + timedelta(minutes=spec["open_offset_min"])
    shape = [(m, D(p)) for m, p in spec["shape"]]
    if not every_minute:
        return [PricePoint(ts=open_at + timedelta(minutes=m), price_usd=p,
                           source=SOURCE_DEXSCREENER) for m, p in shape]
    out, last = [], shape[0][1]
    limit = shape[-1][0]
    for minute in range(limit + 1):
        for m, p in shape:
            if m == minute:
                last = p
        out.append(PricePoint(ts=open_at + timedelta(minutes=minute),
                              price_usd=last, source=SOURCE_DEXSCREENER))
    return out


# --- forward-fill -------------------------------------------------------------

def test_progress_is_forward_filled_across_a_gap() -> None:
    """The 45-minute quiet stretch between 91% and 96%. Every minute of it
    reads 91%, because that is what the curve was doing."""
    sparse = curve("sparse")
    assert progress_at(sparse, at(50), launch_at=LAUNCH) == D("91.000")
    assert progress_at(sparse, at(70), launch_at=LAUNCH) == D("91.000")
    assert progress_at(sparse, at(94), launch_at=LAUNCH) == D("91.000")
    assert progress_at(sparse, at(95), launch_at=LAUNCH) == D("96.000")


def test_before_the_first_sample_is_zero_not_null() -> None:
    """A pump.fun curve holds its whole allocation the instant it is created.
    That is the protocol, not an assumption, so a look-back that reaches past
    the first sample but not past the launch reads 0."""
    late = [CurvePoint(ts=at(30), progress_pct=D("70"), market_cap_quote=None,
                       complete=False)]
    assert progress_at(late, at(10), launch_at=LAUNCH) == 0
    assert progress_at(late, LAUNCH, launch_at=LAUNCH) == 0


def test_before_the_launch_is_null_not_zero() -> None:
    """Reaching back before the token existed is unanswerable, and an
    unanswerable window must not produce a velocity."""
    sparse = curve("sparse")
    assert progress_at(sparse, LAUNCH - timedelta(minutes=1),
                       launch_at=LAUNCH) is None
    assert velocity(sparse, at(3), 5, launch_at=LAUNCH) is None
    assert progress_at(sparse, at(10), launch_at=None) == D("0.000")


# --- velocity -----------------------------------------------------------------

@pytest.mark.parametrize(("minute", "window", "expected"), [
    # At the 70% checkpoint (t+30): 5 min back lands in the gap after t+20,
    # which forward-fills to 45. (70 - 45) / 5.
    (30, 5, "5.000000"),
    # 15 min back lands at t+15, before the t+20 sample, so it fills to the
    # t+0 sample: 0. (70 - 0) / 15.
    (30, 15, "4.666667"),
    # At t+50 (80% and 90%): 5 min back is t+45, which fills to the t+30
    # sample at 70 — NOT the t+48 one, which is in the future of t+45.
    (50, 5, "4.200000"),
    (50, 15, "1.400000"),
    # At t+95 (95%): both look-backs land inside the 45-minute quiet stretch
    # and fill to 91. This is the token that stalled, and it must read slow.
    (95, 5, "1.000000"),
    (95, 15, "0.333333"),
])
def test_velocity_over_a_sparse_series(minute: int, window: int,
                                       expected: str) -> None:
    assert velocity(curve("sparse"), at(minute), window,
                    launch_at=LAUNCH) == D(expected)


def test_a_quiet_window_is_zero_velocity_not_null() -> None:
    """Both ends forward-fill to the same sample, so nothing moved — which is
    a measurement, and a different claim from 'unknown'."""
    assert velocity(curve("sparse"), at(70), 5, launch_at=LAUNCH) == 0


# --- activity -----------------------------------------------------------------

@pytest.mark.parametrize(("minute", "expected"), [(30, 2), (50, 2), (95, 1)])
def test_changes_in_the_last_fifteen_minutes(minute: int, expected: int) -> None:
    """Every row IS a change, so this is a count — and it is the closest thing
    to a trade count this lab has."""
    assert changes_within(curve("sparse"), at(minute),
                          config.ACTIVITY_WINDOW_MIN) == expected


# --- stalls -------------------------------------------------------------------

@pytest.mark.parametrize(("minute", "expected"), [(30, 0), (50, 1), (95, 2)])
def test_stall_count_from_crossing_seventy(minute: int, expected: int) -> None:
    """Gaps of five minutes or more between crossing 70% and the checkpoint:
    the 18-minute one before t+48, then the 45-minute one before t+95."""
    assert stall_count(curve("sparse"), at(30), at(minute),
                       threshold_min=config.STALL_MIN) == expected


def test_a_stall_that_starts_at_the_crossing_is_counted() -> None:
    """Measured from `start`, not only between samples. A token that crosses
    70% and then does nothing for ten minutes has stalled once, even though no
    sample marks the beginning of the silence — and counting only gaps BETWEEN
    samples would miss exactly the tokens that stall hardest."""
    quiet = [CurvePoint(ts=at(40), progress_pct=D("75"), market_cap_quote=None,
                        complete=False)]
    assert stall_count(quiet, at(30), at(40), threshold_min=5) == 1


# --- retrace ------------------------------------------------------------------

def test_retrace_is_flagged_from_a_running_peak() -> None:
    """The series runs 72 -> 88 -> 80.5. Seven and a half points given up from
    a peak of 88 — and reading only 'is it below the checkpoint level' would
    have called that a clean run, since 80.5 is still above 80."""
    retrace = curve("retrace")
    assert retraced(retrace, at(10), at(50), drop_pts=D(5)) is True
    assert retraced(retrace, at(20), at(50), drop_pts=D(5)) is True
    # The 90% checkpoint is at t+40, AFTER the fall. Nothing retraces from
    # there, so it must not be flagged.
    assert retraced(retrace, at(40), at(50), drop_pts=D(5)) is False


def test_a_smaller_give_back_is_not_a_retrace() -> None:
    assert retraced(curve("retrace"), at(10), at(50), drop_pts=D(10)) is False


def test_a_monotone_series_never_retraces() -> None:
    assert retraced(curve("sparse"), at(30), at(96), drop_pts=D(5)) is False


# --- the feature block --------------------------------------------------------

def test_the_sparse_series_produces_four_full_blocks() -> None:
    engine = FeatureEngine(session=None)  # no DB: `_features` is pure
    block = engine._features(curve("sparse"), checkpoints("sparse"),
                             launch_at=LAUNCH, graduated_at=at(96))
    assert block["f70_minutes_since_launch"] == D("30.000")
    assert block["f70_minutes_from_70"] == D("0.000")
    assert block["f70_velocity_5m"] == D("5.000000")
    assert block["f95_minutes_from_70"] == D("65.000")
    assert block["f95_stall_count"] == 2
    assert block["f95_velocity_15m"] == D("0.333333")
    assert all(block[f"f{lv}_retrace_flag"] is False for lv in (70, 80, 90, 95))


def test_a_missing_checkpoint_nulls_its_block_and_keeps_the_token() -> None:
    """'Reached 80 and died' is the row Phase 3 most needs. Dropping it would
    condition the sample on success."""
    engine = FeatureEngine(session=None)
    block = engine._features(curve("never_reached_90"),
                             checkpoints("never_reached_90"),
                             launch_at=LAUNCH, graduated_at=at(12))
    assert block["f70_at"] == at(5)
    assert block["f80_at"] == at(9)
    for name in ("at", "velocity_5m", "stall_count", "retrace_flag",
                 "minutes_since_launch"):
        assert block[f"f90_{name}"] is None, name
        assert block[f"f95_{name}"] is None, name


def test_the_retrace_flag_differs_per_checkpoint() -> None:
    engine = FeatureEngine(session=None)
    block = engine._features(curve("retrace"), checkpoints("retrace"),
                             launch_at=LAUNCH, graduated_at=at(50))
    assert block["f70_retrace_flag"] is True
    assert block["f80_retrace_flag"] is True
    assert block["f90_retrace_flag"] is False
    assert block["f95_retrace_flag"] is None   # never reached


# --- outcomes -----------------------------------------------------------------

def test_returns_are_measured_from_the_pool_open() -> None:
    grad = at(96)
    series = prices("prices_full", graduated_at=grad)
    open_price, open_at = series[0].price_usd, series[0].ts
    got = returns(series, open_price, open_at, (2, 5, 10, 30))
    assert got[2] == D("0.20000000")    # 1.2 / 1.0
    assert got[5] == D("0.50000000")
    assert got[10] == D("1.50000000")   # the 2.5 peak
    assert got[30] == D("0.40000000")


def test_max_return_drawdown_and_time_to_peak() -> None:
    """The drawdown is peak-to-trough, not versus the open: this series doubles
    and a half, and measuring against the open would call it a gain."""
    grad = at(96)
    series = prices("prices_full", graduated_at=grad)
    best, drawdown, to_peak = extremes(
        series, series[0].price_usd, series[0].ts, window_min=60)
    assert best == D("1.50000000")        # 2.5 / 1.0 - 1
    assert to_peak == D("10.000")
    assert drawdown == D("-0.68000000")   # 0.8 / 2.5 - 1


def test_price_is_forward_filled_between_samples() -> None:
    grad = at(96)
    sparse = prices("prices_full", graduated_at=grad, every_minute=False)
    assert price_at(sparse, sparse[0].ts + timedelta(minutes=7)) == D("1.5")
    assert price_at(sparse, sparse[0].ts - timedelta(minutes=1)) is None


def test_coverage_counts_minutes_not_rows() -> None:
    """Two samples in one minute do not cover two minutes."""
    open_at = at(100)
    doubled = [PricePoint(ts=open_at + timedelta(seconds=s), price_usd=D(1),
                          source=SOURCE_DEXSCREENER) for s in (0, 30, 61)]
    assert minutes_covered(doubled, open_at, window_min=60) == 2


def test_a_full_hour_produces_an_outcome() -> None:
    engine = FeatureEngine(session=None)
    grad = at(96)
    out = engine._outcomes(prices("prices_full", graduated_at=grad),
                           curve("sparse"), graduated_at=grad)
    assert out["outcome_ok"] is True
    assert out["postgrad_minutes_covered"] == 60
    assert out["sample_gap_flag"] is False
    assert out["return_5m"] == D("0.50000000")
    assert out["max_return_60m"] == D("1.50000000")
    assert out["minutes_to_peak"] == D("10.000")
    # The curve's `complete` sample is at t+96 and the pool opened two minutes
    # later, so the lag is two minutes.
    assert out["migration_lag_min"] == D("2.000")


def test_thin_coverage_nulls_every_return_and_says_why() -> None:
    """A return computed over a series with holes in it is a number with no
    error bar, and Phase 3 would be judged on it."""
    engine = FeatureEngine(session=None)
    grad = at(96)
    out = engine._outcomes(prices("prices_thin", graduated_at=grad),
                           curve("sparse"), graduated_at=grad)
    assert out["outcome_ok"] is False
    assert out["postgrad_minutes_covered"] == 30
    assert out["sample_gap_flag"] is True
    for name in ("return_2m", "return_5m", "return_60m", "max_return_60m",
                 "max_drawdown_60m", "minutes_to_peak"):
        assert out[name] is None, name
    # The denominator is still written, so the null always says why.
    assert out["open_price_usd"] == D("1.0")


def test_no_postgrad_samples_at_all() -> None:
    engine = FeatureEngine(session=None)
    out = engine._outcomes([], curve("sparse"), graduated_at=at(96))
    assert out["outcome_ok"] is False
    assert out["postgrad_minutes_covered"] == 0
    assert out["sample_gap_flag"] is True
    assert out["open_at"] is None


def test_backfilled_samples_are_counted_separately() -> None:
    """A GeckoTerminal candle covers its minute, so it is not a gap — but it is
    not the same measurement as a live poll, and a reader must be able to
    exclude it."""
    engine = FeatureEngine(session=None)
    grad = at(96)
    series = prices("prices_full", graduated_at=grad)
    mixed = [PricePoint(ts=p.ts, price_usd=p.price_usd,
                        source=SOURCE_GECKOTERMINAL if i % 10 == 0 else p.source)
             for i, p in enumerate(series)]
    out = engine._outcomes(mixed, curve("sparse"), graduated_at=grad)
    assert out["backfilled_samples"] == 6
    assert out["sample_gap_flag"] is False


def test_migration_lag_is_null_when_the_chain_never_said_complete() -> None:
    """Only the websocket reported it. The column says "not measured" rather
    than inventing a lag from the feed's own timestamp."""
    engine = FeatureEngine(session=None)
    grad = at(50)
    no_complete = [CurvePoint(ts=at(m), progress_pct=D(p),
                              market_cap_quote=None, complete=False)
                   for m, p, _ in SERIES["retrace"]["samples"]]
    out = engine._outcomes(prices("prices_full", graduated_at=grad),
                           no_complete, graduated_at=grad)
    assert out["migration_lag_min"] is None


# --- the summary --------------------------------------------------------------

def test_the_summary_reports_its_own_denominator() -> None:
    """A percentile table over the rows that happened to have clean coverage,
    with no count of the rows that did not, is the shape of every fake edge
    this platform has already found."""
    rendered = features.format_summary({
        "coverage": {"graduates": 120, "with_outcome": 88,
                     "dropped_thin_coverage": 32, "any_gap": 41,
                     "never_watched_pre_grad": 9, "reached_70": 95,
                     "reached_80": 80, "reached_90": 61, "reached_95": 40,
                     "mean_minutes_covered": 54.2},
        "distribution": [
            {"metric": "return_5m", "n": 88, "mean": D("0.05"), "p10": D("-0.4"),
             "p25": D("-0.2"), "median": D("-0.05"), "p75": D("0.1"),
             "p90": D("0.6"), "p99": D("3.0"), "max": D("9.0"),
             "share_positive": D("0.42"), "share_ge_25pct": D("0.18"),
             "share_ge_2x": D("0.03")},
        ],
    })
    assert "dropped, thin coverage   32" in rendered
    assert "return_5m" in rendered
    assert "reached 70/80/90/95      95/80/61/40" in rendered


def test_the_summary_sql_filters_on_outcome_ok() -> None:
    """Rows with thin coverage carry NULL returns. They would not bias the
    percentiles, but they would make `n` a lie about how much was measured."""
    assert features.SUMMARY_SQL.count("outcome_ok") == 2
    assert "return_5m" in features.SUMMARY_SQL
    assert "max_return_60m" in features.SUMMARY_SQL
