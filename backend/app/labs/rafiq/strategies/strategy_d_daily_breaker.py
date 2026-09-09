"""STRATEGY D — DAILY_DRAWDOWN_BREAKER

The most direct answer to "don't drop all earnings in the night" — a
portfolio-level halt, not a per-trade rule. This is the file that actually
does what was asked: it does not try to make a specific daily return happen
(that is not an engineering problem); it bounds how much a bad day can take
away.

THE GAP THIS CLOSES
--------------------
`risk/portfolio.py`'s existing `daily_loss_limit` check
(`check_can_open`, around line 134) compares `state.realised_today` against
equity. That only counts CLOSED trades. Karthik's snapshot shows
`Unrealised P&L: -$191.46` sitting on 20 open positions, at the exact same
moment the wallet was already down $774.86 realised — a mark-to-market hole
that a realised-only breaker would not see AT ALL until those positions were
finally closed, by which point the damage is already done and irreversible.

A breaker that only looks at realised P&L is a smoke detector that only goes
off after the room has already burned.

THE FIX
-------
Track equity at the start of each trading day (`day_open_equity`). On every
review pass, compute CURRENT full equity (cash + realised so far today +
mark-to-market value of every open position). If the drawdown from
`day_open_equity` exceeds the configured limit:

  * NEW entries halt for the remainder of the day.
  * Existing positions are NOT force-closed — they continue to be managed by
    their own exit rules (stop/target/time). Panic-liquidating into a bad
    market is its own separate risk this module does not take on.
  * The halt lifts automatically at the next day boundary, with a fresh
    `day_open_equity` snapshot — this is a daily breaker, not a permanent one.

This composes with, and does not replace, per-trade stops (Strategy A) and
time exits (Strategy B). A per-trade stop bounds one position; this bounds the
whole book in one day. Both are needed — Karthik lost money through many
individually-bounded-looking trades adding up, not just one giant one.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class DailyBreakerPolicy:
    """Provisional. Not validated against outcomes — a starting point."""

    #: Halt new entries once the day's drawdown from open-of-day equity
    #: reaches this fraction. 0.05 = halt after giving back 5% in a day.
    max_daily_drawdown: Decimal = Decimal("0.05")
    #: A second, harder line: halt regardless of the above once realised
    #: losses ALONE (ignoring any open-position mark-to-market) hit this.
    #: Catches the case where unrealised losses are masking how bad the
    #: realised picture already is.
    max_daily_realised_loss: Decimal = Decimal("0.08")


@dataclass
class DailyState:
    """Tracks one trading day's starting point. Reset explicitly at rollover
    — never inferred from a wall-clock check buried in unrelated code, so it
    is always obvious when and why a new day started."""

    day: date
    day_open_equity: Decimal
    realised_today: Decimal = Decimal(0)

    @classmethod
    def open_new_day(cls, now: datetime, equity: Decimal) -> DailyState:
        return cls(day=now.date(), day_open_equity=equity)


@dataclass(frozen=True)
class BreakerVerdict:
    halted: bool
    reason: str | None
    current_drawdown_pct: Decimal
    realised_loss_pct: Decimal


def mark_to_market_equity(cash: Decimal, open_position_values) -> Decimal:
    """Cash plus the CURRENT market value of every open position — never the
    cost basis. Cost-basis accounting is exactly what let Karthik's dashboard
    show `Capital Allocated: $200.00` beside a book actually worth $8.55; a
    breaker built on cost basis would never have seen the hole at all."""
    return cash + sum(open_position_values, Decimal(0))


def evaluate(state: DailyState, *, now: datetime, cash: Decimal,
             open_position_values,
             policy: DailyBreakerPolicy = DailyBreakerPolicy()) -> BreakerVerdict:
    """Should new entries halt for the rest of today?

    Rolls `state` onto a new day automatically when `now` has crossed a date
    boundary, seeding the new day's baseline from CURRENT equity — a fresh
    day starts fresh, it does not inherit yesterday's drawdown.
    """
    if now.date() != state.day:
        state.day = now.date()
        state.day_open_equity = mark_to_market_equity(cash, open_position_values)
        state.realised_today = Decimal(0)

    equity_now = mark_to_market_equity(cash, open_position_values)
    if state.day_open_equity <= 0:
        return BreakerVerdict(True, "day_open_equity is non-positive",
                              Decimal(0), Decimal(0))

    drawdown = (state.day_open_equity - equity_now) / state.day_open_equity
    realised_loss = (max(Decimal(0), -state.realised_today)
                     / state.day_open_equity)

    if drawdown >= policy.max_daily_drawdown:
        return BreakerVerdict(True,
                              f"daily drawdown {drawdown:.1%} >= "
                              f"{policy.max_daily_drawdown:.1%} limit "
                              f"(mark-to-market, includes open positions)",
                              drawdown, realised_loss)
    if realised_loss >= policy.max_daily_realised_loss:
        return BreakerVerdict(True,
                              f"realised loss today {realised_loss:.1%} >= "
                              f"{policy.max_daily_realised_loss:.1%} limit",
                              drawdown, realised_loss)
    return BreakerVerdict(False, None, drawdown, realised_loss)


def record_realised(state: DailyState, pnl: Decimal) -> None:
    """Call once per closed trade so `realised_today` stays current."""
    state.realised_today += pnl
