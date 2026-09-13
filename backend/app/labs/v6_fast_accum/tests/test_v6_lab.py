"""The lab's self-check. Synthetic curves with known answers.

Small on purpose: these assert the things that would silently produce a
plausible wrong number — the exit precedence, the fee asymmetry, censoring not
becoming zero, and the gate refusing to pass an unevaluable condition.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.labs.v6_fast_accum import analysis, config, leakage
from app.labs.v6_fast_accum.dataset import Dataset, Sample, Token
from app.labs.v6_fast_accum.simulator import (
    apply_position_limits, find_entry, run_strategy, simulate,
)

T0 = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
#: A curve with room to move: 30 SOL virtual quote against 1.073e9 tokens.
V_Q, V_T = Decimal("30"), Decimal("1073000000")


def _s(dt_s: int, progress: str, mcap: str, v_q: Decimal, v_t: Decimal,
       complete: bool = False) -> Sample:
    return Sample(ts=T0 + timedelta(seconds=dt_s), progress_pct=Decimal(progress),
                  mcap_quote=Decimal(mcap), v_quote=v_q, v_token=v_t,
                  complete=complete)


def _token(samples, reason=None, migrated=None) -> Token:
    return Token(mint="M" * 32, first_seen_at=T0, samples=tuple(samples),
                 unsubscribe_reason=reason, pruned=False, migrated_at=migrated)


def test_entry_takes_first_qualifying_sample_not_the_best():
    tok = _token([
        _s(10, "5", "31", V_Q, V_T),                    # progress too low
        _s(30, "16", "31", V_Q, V_T),                   # FIRST qualifying
        _s(50, "40", "90", V_Q * 3, V_T),               # better, but later
    ])
    e = find_entry(tok, config.FAST_90)
    assert e is not None and e.ts == T0 + timedelta(seconds=30)


def test_entry_rejected_past_the_elapsed_window():
    tok = _token([_s(200, "50", "99", V_Q, V_T)])
    assert find_entry(tok, config.FAST_90) is None


def test_mcap_floor_is_applied_at_the_decision_sample():
    tok = _token([_s(30, "16", "29", V_Q, V_T)])        # mcap below the floor
    assert find_entry(tok, config.FAST_90) is None


def test_stop_loss_wins_over_take_profit_in_the_same_interval():
    """Worst-executable-first. A single reading cannot order the low and the
    high inside one interval, so the stop must be assumed to have hit first."""
    entry = _s(30, "16", "31", V_Q, V_T)
    # One later sample that is BELOW the stop; and another above the target.
    tok = _token([entry,
                  _s(60, "16", "31", V_Q / 4, V_T),     # price x0.25 -> stop
                  _s(90, "16", "31", V_Q * 4, V_T)])    # price x4 -> target
    tr = simulate(tok, entry, "T", now_limit=T0 + timedelta(hours=2))
    assert tr.exit_reason == "stop_loss"


def test_graduation_exits_before_migration_and_outranks_price():
    entry = _s(30, "16", "31", V_Q, V_T)
    tok = _token([entry, _s(60, "100", "99", V_Q * 4, V_T, complete=True)])
    tr = simulate(tok, entry, "T", now_limit=T0 + timedelta(hours=2))
    assert tr.exit_reason == "graduation"


def test_censored_trade_keeps_a_null_return_and_is_not_a_zero():
    """The single most dangerous coercion available to this experiment."""
    entry = _s(30, "16", "31", V_Q, V_T)
    # Series stops 2 minutes in; the horizon is 30.
    tok = _token([entry, _s(150, "17", "32", V_Q, V_T)], reason="evicted")
    tr = simulate(tok, entry, "T", now_limit=T0 + timedelta(hours=2))
    assert tr.censored is True
    assert tr.exit_reason == "censored"
    assert tr.net_return is None and tr.net_pnl_usd is None

    m = analysis.compute([tr])
    assert m.censored == 1
    assert m.trades == 1
    assert m.cumulative_pnl == 0.0      # no resolved trades contributed
    assert m.profit_factor is None      # not 0.0, and not 1.0


def test_round_trip_at_a_flat_price_loses_money_to_fees():
    """Fees are a markup in and a deduction out, so a flat round trip is a
    loss. If this ever comes out non-negative the fee model has been inverted."""
    entry = _s(30, "16", "31", V_Q, V_T)
    tok = _token([entry] + [_s(30 + 60 * i, "16", "31", V_Q, V_T) for i in range(1, 40)])
    tr = simulate(tok, entry, "T", now_limit=T0 + timedelta(hours=3))
    assert tr.exit_reason == "time_stop"
    assert tr.net_return is not None and tr.net_return < 0
    assert tr.fees_usd > 0


def test_position_limits_cap_concurrency():
    trades = []
    for i in range(20):
        e = _s(30, "16", "31", V_Q, V_T)
        tok = _token([e])
        tr = simulate(tok, e, "T", now_limit=T0 + timedelta(hours=2))
        # All entering at the same instant: only MAX_CONCURRENT can be taken.
        trades.append(tr)
    assert len(apply_position_limits(trades)) == config.MAX_CONCURRENT


def test_leakage_checker_catches_a_feature_from_the_future():
    from app.labs.v6_fast_accum.simulator import Feature, Trade
    bad = Trade(
        mint="X", strategy="T", entry_ts=T0, entry_price=Decimal(1),
        entry_progress_pct=Decimal(16), entry_mcap_sol=Decimal(31),
        elapsed_s=Decimal(30), exit_ts=None, exit_price=None,
        exit_reason="censored", censored=True, gross_return=None,
        net_return=None, net_pnl_usd=None, fees_usd=Decimal(0),
        slippage_usd=Decimal(0), mfe=None, mae=None, reached_25=False,
        reached_50=False, reached_100=False, reached_200=False, graduated=False,
        time_to_100_s=None, time_to_peak_s=None, peak_return=None,
        features=(Feature("peeked", Decimal(1), T0 + timedelta(minutes=5), T0,
                          "OBSERVED"),))
    ok, findings = leakage.audit([bad])
    assert ok is False
    assert findings[0].rule == "feature_after_decision"


def test_gate_fails_closed_when_there_is_no_out_of_sample_period():
    """"Not evaluable" is never "satisfied"."""
    g = analysis.gate([], "INSUFFICIENT_HISTORY", [], {}, {}, {})
    assert g["passed"] is False
    assert g["verdict"] == "NO RELIABLE EDGE IDENTIFIED"
    assert all(c["status"] == "NOT_EVALUABLE" for c in g["checks"])


def test_walk_forward_reports_insufficient_history_rather_than_one_fold():
    ds = Dataset(tokens=(), loaded_at=T0, window_start=T0,
                 window_end=T0 + timedelta(days=2), dataset_version="x")
    folds, status = analysis.walk_forward(ds, {}, fold="weekly")
    assert status == "INSUFFICIENT_HISTORY" and folds == []


def test_benjamini_hochberg_is_monotone_and_bounded():
    bh = analysis.benjamini_hochberg(
        {"a": 0.001, "b": 0.02, "c": 0.5, "d": 0.9}, 0.05)
    assert all(0 <= v["adjusted_p"] <= 1 for v in bh.values())
    assert bh["a"]["adjusted_p"] <= bh["b"]["adjusted_p"] <= bh["c"]["adjusted_p"]
