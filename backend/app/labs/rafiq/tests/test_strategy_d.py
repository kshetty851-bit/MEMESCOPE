"""Strategy D: the breaker must see the hole before it is realised.

The failure it responds to is specific — a wallet down $191 on open positions
while its realised line looked survivable — so the headline test is the one
with ZERO realised losses and a purely mark-to-market drawdown. A breaker that
only trips on realised P&L is a smoke detector that goes off after the fire.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.labs.rafiq.strategies.strategy_d_daily_breaker import (
    DailyBreakerPolicy,
    DailyState,
    evaluate,
    mark_to_market_equity,
    record_realised,
)

T0 = datetime(2026, 9, 9, 9, 0, tzinfo=UTC)
POLICY = DailyBreakerPolicy()


def test_trips_on_unrealised_drawdown_with_zero_realised_losses() -> None:
    """$1,000 open-of-day; $900 cash and $40 of open positions is -6%, past
    the 5% line — and `realised_today` never moves."""
    state = DailyState.open_new_day(T0, Decimal(1_000))
    verdict = evaluate(state, now=T0 + timedelta(hours=2), cash=Decimal(900),
                       open_position_values=[Decimal(20), Decimal(20)])
    assert state.realised_today == 0
    assert verdict.halted
    assert verdict.realised_loss_pct == 0
    assert "mark-to-market" in (verdict.reason or "")


def test_does_not_trip_just_below_the_line() -> None:
    state = DailyState.open_new_day(T0, Decimal(1_000))
    verdict = evaluate(state, now=T0 + timedelta(hours=1), cash=Decimal(900),
                       open_position_values=[Decimal(60)])
    assert not verdict.halted


def test_realised_line_trips_independently() -> None:
    """The second, harder line: 8% realised, whatever the open book says."""
    state = DailyState.open_new_day(T0, Decimal(1_000))
    record_realised(state, Decimal(-85))
    verdict = evaluate(state, now=T0 + timedelta(hours=3), cash=Decimal(1_000),
                       open_position_values=[])
    assert verdict.halted
    assert "realised loss" in (verdict.reason or "")


def test_it_halts_entries_and_never_force_closes() -> None:
    """`evaluate` returns a verdict and nothing else. It has no handle on a
    position, so 'does not force-close' is a fact about its signature."""
    state = DailyState.open_new_day(T0, Decimal(1_000))
    before = [Decimal(20), Decimal(20)]
    verdict = evaluate(state, now=T0 + timedelta(hours=2), cash=Decimal(900),
                       open_position_values=before)
    assert verdict.halted
    assert before == [Decimal(20), Decimal(20)]
    assert not hasattr(verdict, "close")


def test_resets_at_the_date_rollover_with_a_fresh_baseline() -> None:
    state = DailyState.open_new_day(T0, Decimal(1_000))
    record_realised(state, Decimal(-85))
    assert evaluate(state, now=T0, cash=Decimal(915),
                    open_position_values=[]).halted

    tomorrow = T0 + timedelta(days=1)
    verdict = evaluate(state, now=tomorrow, cash=Decimal(915),
                       open_position_values=[])
    assert not verdict.halted
    assert state.day == tomorrow.date()
    assert state.realised_today == 0
    # A fresh day starts fresh: the baseline is TODAY's equity, so yesterday's
    # 8.5% hole is not carried into today's percentage.
    assert state.day_open_equity == Decimal(915)


def test_mark_to_market_never_uses_cost_basis() -> None:
    assert mark_to_market_equity(Decimal(100), [Decimal("0.55"), Decimal(8)]) \
        == Decimal("108.55")


def test_a_non_positive_day_open_equity_halts_rather_than_dividing() -> None:
    state = DailyState(day=T0.date(), day_open_equity=Decimal(0))
    verdict = evaluate(state, now=T0, cash=Decimal(0), open_position_values=[])
    assert verdict.halted


def test_policy_constants_are_rafiqs() -> None:
    assert POLICY.max_daily_drawdown == Decimal("0.05")
    assert POLICY.max_daily_realised_loss == Decimal("0.08")
