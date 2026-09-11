"""The replay backtester: a harness, two naive baselines, and a pre-stated gate.

Ships **no tuned strategy on purpose.** B0 and B1 exist to be beaten, and a
harness that arrives with a winner already in it is a harness nobody audits.

    graduates + checkpoint-reachers, in time order
            │
            ▼
      View(now=decision time)  ──▶  Strategy.entry()  ──▶  fill
            │                                                │
      only rows with ts <= now                        walk ticks forward
                                                             │
                                                    ExitPolicy, first to fire

## Causality is structural, not a convention

A strategy never receives the whole series. It receives a `View` built by the
harness from rows with `ts <= now`, and the slicing happens before the strategy
is called. There is no future to peek at, so peeking cannot be forgotten.
`tests/test_backtest.py` builds a View and asserts it is empty past its own
clock, and drives a deliberately greedy strategy to show it cannot see a price
it has not reached.

## Everything is denominated in the quote currency

Both sides of a pre-graduation trade exist in SOL: the curve prices in it, and
DexScreener's `price_native` is it. Converting the curve leg into USD would
need a SOL/USD rate this lab does not record — and taking one from the token's
own post-graduation samples would be reading the future to price a decision
made before it. So fills read `price_native`, and a post-graduation sample
without one (every backfilled GeckoTerminal candle) cannot be a fill point.
Those are counted, not silently skipped.

## The cost model understates a pre-graduation entry, and cannot fix it

`SLIP_BPS` is a flat assumption applied to both paths. On the post-graduation
side that is roughly fair. On the curve it is not: measured on 738 graduates,
median pre-graduation liquidity was **$4,112**, which makes a $100 buy about
2.5% of the pool and its real impact several times the 150 bps assumed here.
Jupiter routing at that depth showed ~99% buy impact and no sell route at all
for 37% of tokens.

Nothing in this harness can correct that, because the reserve series says what
the curve quoted and not what a taker would have been filled at. So a
pre-graduation strategy that clears the gate here has cleared a bar that is
**too low**, and the right next step is a depth model, not a deployment. The
post-graduation paths do not carry this caveat.

## The population is NOT just graduates

A pre-graduation strategy evaluated only on tokens that went on to graduate is
conditioned on the outcome it is trying to predict — the survivorship trap this
platform has already walked into more than once. So the population is every
token that **reached the entry checkpoint**, graduate or not, and one that
never migrates is closed at `PRE_GRAD_DEAD_HAIRCUT`.
"""

from __future__ import annotations

import csv
import io
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.labs.graduation import config
from app.labs.graduation.features import COVERAGE_SQL
from app.labs.graduation.models import (
    GradCheckpoint,
    GradCurveSample,
    GradMigration,
    GradPostgradSample,
    GradToken,
)

logger = get_logger(__name__)

_BPS = Decimal(10_000)
_Q = Decimal("0.000000000001")
_PCT = Decimal("0.0001")

PRE_GRAD = "pre_grad"
POST_GRAD = "post_grad"


# --- the replayed series ------------------------------------------------------

@dataclass(frozen=True, slots=True)
class CurveTick:
    """One reserve change, with the price the curve quoted at that state."""

    ts: datetime
    progress_pct: Decimal | None
    price: Decimal | None
    market_cap_quote: Decimal | None
    complete: bool


@dataclass(frozen=True, slots=True)
class Tick:
    """One post-graduation price observation, in quote."""

    ts: datetime
    price: Decimal
    source: str


@dataclass(frozen=True, slots=True)
class Checkpoint:
    level: Decimal
    ts: datetime
    price: Decimal | None
    market_cap_quote: Decimal | None


@dataclass(slots=True)
class Replay:
    """Everything recorded about one token, in time order."""

    mint: str
    launch_at: datetime | None
    graduated_at: datetime | None
    quote_currency: str | None
    curve: list[CurveTick] = field(default_factory=list)
    checkpoints: dict[Decimal, Checkpoint] = field(default_factory=dict)
    ticks: list[Tick] = field(default_factory=list)

    @property
    def graduated(self) -> bool:
        return self.graduated_at is not None


def curve_price(v_quote: Decimal | None, v_token: Decimal | None) -> Decimal | None:
    """Quote per token at a reserve state — the constant product's own price.

    `v_quote / v_token`, both already in whole units. Equivalently
    `market_cap_quote / token_total_supply`, and the two agree to the stored
    precision; this form is used because a checkpoint always carries reserves
    and does not always carry a supply.
    """
    if v_quote is None or v_token is None or v_token <= 0:
        return None
    return (v_quote / v_token).quantize(_Q)


# --- the causal view ----------------------------------------------------------

@dataclass(frozen=True, slots=True)
class View:
    """What a strategy may look at. Built by the harness, sliced before it.

    There is no method here that reaches past `now`, because there is nothing
    past `now` in the object at all — the harness slices the lists on the way
    in. A strategy that wanted to cheat would have to be handed the data to
    cheat with, and it is not.
    """

    mint: str
    now: datetime
    launch_at: datetime | None
    quote_currency: str | None
    curve: tuple[CurveTick, ...]
    checkpoints: tuple[Checkpoint, ...]
    ticks: tuple[Tick, ...]

    def checkpoint(self, level: Decimal) -> Checkpoint | None:
        return next((c for c in self.checkpoints if c.level == level), None)

    def latest_curve(self) -> CurveTick | None:
        return self.curve[-1] if self.curve else None

    def progress(self) -> Decimal | None:
        """Forward-filled: the last observed progress, since curve samples are
        written only when a reserve moved."""
        for tick in reversed(self.curve):
            if tick.progress_pct is not None:
                return tick.progress_pct
        return None

    def minutes_since_launch(self) -> Decimal | None:
        if self.launch_at is None:
            return None
        return Decimal((self.now - self.launch_at).total_seconds()) / 60


def view_at(replay: Replay, now: datetime) -> View:
    """The slice. The single place causality is enforced."""
    return View(
        mint=replay.mint,
        now=now,
        launch_at=replay.launch_at,
        quote_currency=replay.quote_currency,
        curve=tuple(c for c in replay.curve if c.ts <= now),
        checkpoints=tuple(sorted(
            (c for c in replay.checkpoints.values() if c.ts <= now),
            key=lambda c: c.level)),
        ticks=tuple(t for t in replay.ticks if t.ts <= now),
    )


# --- costs --------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Costs:
    """Per-side cost model. Every term is charged on BOTH legs.

    Expressed as a fraction of notional so the whole backtest stays unit-free:
    the pump fee and slippage are fractions already, and the flat priority fee
    becomes one by dividing by the position size. At the defaults that is
    100 + 150 + 40 = 290 bps a side, 5.8% round trip — which is meant to sting,
    because the real thing does.
    """

    pump_fee_bps: int = config.BACKTEST_PUMP_FEE_BPS
    slip_bps: int = config.BACKTEST_SLIP_BPS
    priority_fee_quote: Decimal = config.BACKTEST_PRIORITY_FEE_QUOTE
    notional_quote: Decimal = config.BACKTEST_NOTIONAL_QUOTE

    @property
    def side_fraction(self) -> Decimal:
        fees = (Decimal(self.pump_fee_bps) + Decimal(self.slip_bps)) / _BPS
        if self.notional_quote > 0:
            fees += self.priority_fee_quote / self.notional_quote
        return fees

    def buy_price(self, price: Decimal) -> Decimal:
        """A buy fills WORSE than the quote."""
        return price * (1 + self.side_fraction)

    def sell_price(self, price: Decimal) -> Decimal:
        """And a sell fills worse too. Floored at zero: a cost model may not
        invent a negative price."""
        return max(Decimal(0), price * (1 - self.side_fraction))


# --- exit rules ---------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ExitState:
    """What every rule is allowed to know at one tick.

    `clock_at` is when the exit clock STARTED, which is not always the entry.
    A pre-graduation entry sits on a curve that has no ticks to evaluate rules
    against, so its clock starts at the pool open — "exit five minutes after
    the open" is the only reading of a time box that means anything there.
    `entry_price` stays the real fill either way.
    """

    clock_at: datetime
    entry_price: Decimal
    tick: Tick
    peak: Decimal

    @property
    def elapsed_min(self) -> Decimal:
        return Decimal((self.tick.ts - self.clock_at).total_seconds()) / 60

    @property
    def ret(self) -> Decimal:
        if self.entry_price <= 0:
            return Decimal(0)
        return self.tick.price / self.entry_price - 1

    @property
    def from_peak(self) -> Decimal:
        if self.peak <= 0:
            return Decimal(0)
        return self.tick.price / self.peak - 1


class ExitRule(ABC):
    """One reason to close. Composable, and each names itself in the output."""

    name: str

    @abstractmethod
    def fires(self, state: ExitState) -> bool: ...


@dataclass(frozen=True, slots=True)
class TimeBox(ExitRule):
    minutes: int
    name: str = "time_box"

    def fires(self, state: ExitState) -> bool:
        return state.elapsed_min >= self.minutes


@dataclass(frozen=True, slots=True)
class TrailingStop(ExitRule):
    """Closes when price falls `pct` from the highest price SEEN SO FAR, which
    is a running figure the harness updates tick by tick — never the peak of
    the whole window, which nothing could have known at the time."""

    pct: Decimal
    name: str = "trailing_stop"

    def fires(self, state: ExitState) -> bool:
        return state.from_peak <= -self.pct


@dataclass(frozen=True, slots=True)
class HardStop(ExitRule):
    pct: Decimal
    name: str = "hard_stop"

    def fires(self, state: ExitState) -> bool:
        return state.ret <= -self.pct


@dataclass(frozen=True, slots=True)
class TakeProfit(ExitRule):
    pct: Decimal
    name: str = "take_profit"

    def fires(self, state: ExitState) -> bool:
        return state.ret >= self.pct


@dataclass(frozen=True, slots=True)
class ExitPolicy:
    """Rules in priority order. The FIRST to fire on a tick wins.

    Order matters and is the caller's to state: a stop and a take-profit can
    both be true on one 60-second bar, and which one filled is not knowable
    from minute data. Putting the loss first is the conservative reading and
    the one a backtest should take.
    """

    rules: tuple[ExitRule, ...]

    def fires(self, state: ExitState) -> str | None:
        for rule in self.rules:
            if rule.fires(state):
                return rule.name
        return None


# --- trades -------------------------------------------------------------------

@dataclass(slots=True)
class Trade:
    mint: str
    strategy: str
    path: str
    entry_at: datetime
    entry_price: Decimal
    exit_at: datetime
    exit_price: Decimal
    exit_reason: str
    gross_return: Decimal
    net_return: Decimal
    pnl_quote: Decimal
    entry_progress_pct: Decimal | None
    graduated: bool

    @property
    def iso_week(self) -> str:
        year, week, _ = self.entry_at.isocalendar()
        return f"{year}-W{week:02d}"

    def as_row(self) -> dict[str, Any]:
        return {
            "mint": self.mint, "strategy": self.strategy, "path": self.path,
            "iso_week": self.iso_week,
            "entry_at": self.entry_at.isoformat(),
            "entry_price": str(self.entry_price),
            "entry_progress_pct": ("" if self.entry_progress_pct is None
                                   else str(self.entry_progress_pct)),
            "exit_at": self.exit_at.isoformat(),
            "exit_price": str(self.exit_price),
            "exit_reason": self.exit_reason,
            "gross_return": str(self.gross_return.quantize(_PCT)),
            "net_return": str(self.net_return.quantize(_PCT)),
            "pnl_quote": str(self.pnl_quote.quantize(_Q)),
            "graduated": str(self.graduated).lower(),
        }


# --- strategies ---------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class EntrySignal:
    """What a strategy returns. The harness fills it; the strategy never does."""

    price: Decimal
    path: str
    progress_pct: Decimal | None = None


class Strategy(ABC):
    """A pluggable entry rule plus an exit policy.

    `decision_times` says WHEN this strategy wants to be asked, which is what
    lets the harness slice the data before calling it. A strategy that wanted
    to be asked continuously would name every tick; these two name one moment.
    """

    name: str

    @property
    @abstractmethod
    def exits(self) -> ExitPolicy:
        """The rules that close a position this strategy opened.

        A property rather than a field so a strategy can build its policy from
        its own parameters — `TimeBox(self.minutes)` — without the two being
        able to drift apart.
        """

    @abstractmethod
    def decision_times(self, replay: Replay) -> list[datetime]: ...

    @abstractmethod
    def entry(self, view: View) -> EntrySignal | None: ...


@dataclass(frozen=True, slots=True)
class OpenThenTimeBox(Strategy):
    """**B0** — buy the pool open, sell N minutes later. No filter at all.

    The null hypothesis in tradeable form: if graduation itself were an edge,
    this would show it. It exists to be beaten.
    """

    minutes: int = 5
    name: str = "B0_open_timebox_5m"

    @property
    def exits(self) -> ExitPolicy:
        return ExitPolicy((TimeBox(self.minutes),))

    def decision_times(self, replay: Replay) -> list[datetime]:
        return [replay.ticks[0].ts] if replay.ticks else []

    def entry(self, view: View) -> EntrySignal | None:
        if not view.ticks:
            return None
        return EntrySignal(price=view.ticks[-1].price, path=POST_GRAD,
                           progress_pct=Decimal(100))


@dataclass(frozen=True, slots=True)
class CheckpointThenOpen(Strategy):
    """**B1** — buy on the curve at a checkpoint, sell N minutes after the open.

    Deliberately naive in the way that matters: it buys every token that
    touches the level, including the ones that never graduate. Those exit at
    `PRE_GRAD_DEAD_HAIRCUT`, which is what makes this an honest baseline rather
    than a flattering one.
    """

    level: Decimal = Decimal(90)
    minutes_after_open: int = 5
    name: str = "B1_f90_then_open_5m"

    @property
    def exits(self) -> ExitPolicy:
        # The time box is measured from the ENTRY, and the entry is pre-
        # graduation, so the harness converts it: see `_exit_pre_grad`.
        return ExitPolicy((TimeBox(self.minutes_after_open),))

    def decision_times(self, replay: Replay) -> list[datetime]:
        checkpoint = replay.checkpoints.get(self.level)
        return [checkpoint.ts] if checkpoint else []

    def entry(self, view: View) -> EntrySignal | None:
        checkpoint = view.checkpoint(self.level)
        if checkpoint is None or checkpoint.price is None:
            return None
        return EntrySignal(price=checkpoint.price, path=PRE_GRAD,
                           progress_pct=view.progress())


#: The two that ship. Neither is tuned, and neither is expected to pass.
BASELINES: dict[str, Strategy] = {
    s.name: s for s in (OpenThenTimeBox(), CheckpointThenOpen())
}


# --- the harness --------------------------------------------------------------

@dataclass(slots=True)
class Position:
    mint: str
    entry_at: datetime
    exit_at: datetime
    trade: Trade


@dataclass(slots=True)
class RunResult:
    strategy: str
    trades: list[Trade] = field(default_factory=list)
    #: Tokens offered to the strategy at all.
    eligible: int = 0
    #: Offered, but the strategy named no moment to decide at. Two different
    #: things live here and the report says so: a strategy this token is not
    #: for (no f90 checkpoint, say), and a DATA GAP (a graduate whose every
    #: post-graduation sample was a backfilled candle, so it has no native
    #: price to fill against). Counted rather than left to vanish, because a
    #: funnel that starts at `considered` hides everything that never got that
    #: far.
    no_decision_time: int = 0
    considered: int = 0
    no_signal: int = 0
    skipped_no_slot: int = 0
    skipped_no_exit_data: int = 0
    dead_curve_exits: int = 0

    @property
    def counts(self) -> dict[str, int]:
        """The whole funnel, in order. Every token loaded is in exactly one
        terminal bucket, so the numbers have to add up and a reader can check
        that they do."""
        return {"eligible": self.eligible,
                "no_decision_time": self.no_decision_time,
                "considered": self.considered,
                "no_signal": self.no_signal,
                "skipped_no_slot": self.skipped_no_slot,
                "skipped_no_exit_data": self.skipped_no_exit_data,
                "trades": len(self.trades),
                "dead_curve_exits": self.dead_curve_exits}


class Backtester:
    """Replays one strategy over many tokens with a shared slot budget."""

    def __init__(self, strategy: Strategy, *, costs: Costs | None = None,
                 max_slots: int | None = None,
                 dead_haircut: Decimal | None = None,
                 dead_hours: int | None = None) -> None:
        self._strategy = strategy
        self._costs = costs or Costs()
        self._max_slots = (max_slots if max_slots is not None
                           else config.BACKTEST_MAX_SLOTS)
        self._haircut = (dead_haircut if dead_haircut is not None
                         else config.PRE_GRAD_DEAD_HAIRCUT)
        self._dead_hours = (dead_hours if dead_hours is not None
                            else config.PRE_GRAD_DEAD_HOURS)

    def run(self, replays: Sequence[Replay]) -> RunResult:
        """Every candidate in decision-time order, against a shared slot book.

        Ordered globally rather than per token because the slots are global: a
        backtest that walked tokens one at a time would let every signal fill,
        which is the same as having no slot limit at all.
        """
        result = RunResult(strategy=self._strategy.name, eligible=len(replays))
        candidates: list[tuple[datetime, Replay]] = []
        for replay in replays:
            moments = self._strategy.decision_times(replay)
            if not moments:
                result.no_decision_time += 1
                continue
            candidates.extend((when, replay) for when in moments)
        candidates.sort(key=lambda pair: (pair[0], pair[1].mint))

        open_positions: list[Position] = []
        for when, replay in candidates:
            result.considered += 1
            # Free anything that has already closed by this moment. Slots are
            # released in simulated time, not in loop order.
            open_positions = [p for p in open_positions if p.exit_at > when]

            signal = self._strategy.entry(view_at(replay, when))
            if signal is None or signal.price <= 0:
                result.no_signal += 1
                continue
            if len(open_positions) >= self._max_slots:
                # Skipped, never queued: a backtest that queues signals is
                # quietly assuming capital it did not have.
                result.skipped_no_slot += 1
                continue

            trade = self._close(replay, when, signal, result)
            if trade is None:
                result.skipped_no_exit_data += 1
                continue
            result.trades.append(trade)
            open_positions.append(Position(mint=replay.mint, entry_at=when,
                                           exit_at=trade.exit_at, trade=trade))
        return result

    # --- exits --------------------------------------------------------------

    def _close(self, replay: Replay, entry_at: datetime, signal: EntrySignal,
               result: RunResult) -> Trade | None:
        entry_fill = self._costs.buy_price(signal.price)
        if signal.path == PRE_GRAD:
            closed = self._exit_pre_grad(replay, entry_at, entry_fill, result)
        else:
            closed = self._exit_post_grad(replay, entry_at, entry_fill)
        if closed is None:
            return None
        exit_at, exit_quote, reason = closed
        return self._settle(replay, signal, entry_at, entry_fill, exit_at,
                            exit_quote, reason)

    def _exit_post_grad(self, replay: Replay, entry_at: datetime,
                        entry_fill: Decimal
                        ) -> tuple[datetime, Decimal, str] | None:
        """Walk ticks forward from the entry, first rule to fire wins."""
        return self._walk(replay.ticks, entry_at, entry_at, entry_fill)

    def _exit_pre_grad(self, replay: Replay, entry_at: datetime,
                       entry_fill: Decimal, result: RunResult
                       ) -> tuple[datetime, Decimal, str] | None:
        """Held on the curve until the pool opens, then walked like any other.

        A token that never migrates inside `PRE_GRAD_DEAD_HOURS` is written
        off: no pool, no route out, no bid. It closes at its last observed
        curve price times `(1 - haircut)` — and when the pruner has already
        taken that series away, the last observed price IS the entry, so the
        loss is exactly the haircut.
        """
        deadline = entry_at + timedelta(hours=self._dead_hours)
        opens = [t for t in replay.ticks if t.ts >= entry_at]
        if not opens or opens[0].ts > deadline:
            result.dead_curve_exits += 1
            last = next((c.price for c in reversed(replay.curve)
                         if c.ts >= entry_at and c.price is not None), None)
            reference = last if last is not None else entry_fill
            return deadline, reference * (1 - self._haircut), "dead_curve"
        # The exit clock starts at the pool open, not at the entry.
        return self._walk(replay.ticks, entry_at, opens[0].ts, entry_fill)

    def _walk(self, ticks: Sequence[Tick], after: datetime, clock_at: datetime,
              entry_fill: Decimal) -> tuple[datetime, Decimal, str] | None:
        """Tick by tick at 60-second granularity. The peak is a RUNNING peak —
        anything else would be a rule reading a high it had not reached."""
        window = [t for t in ticks if t.ts >= after]
        if not window:
            return None
        peak = window[0].price
        for tick in window:
            peak = max(peak, tick.price)
            state = ExitState(clock_at=clock_at, entry_price=entry_fill,
                              tick=tick, peak=peak)
            reason = self._strategy.exits.fires(state)
            if reason is not None:
                return tick.ts, tick.price, reason
        # Nothing fired inside the recorded window. Closing at the last tick is
        # a decision, not a neutral default, so it says so in the output.
        last = window[-1]
        return last.ts, last.price, "end_of_data"

    def _settle(self, replay: Replay, signal: EntrySignal, entry_at: datetime,
                entry_fill: Decimal, exit_at: datetime, exit_quote: Decimal,
                reason: str) -> Trade:
        exit_fill = self._costs.sell_price(exit_quote)
        gross = (exit_quote / signal.price - 1) if signal.price > 0 else Decimal(0)
        net = (exit_fill / entry_fill - 1) if entry_fill > 0 else Decimal(0)
        return Trade(
            mint=replay.mint, strategy=self._strategy.name, path=signal.path,
            entry_at=entry_at, entry_price=entry_fill,
            exit_at=exit_at, exit_price=exit_fill, exit_reason=reason,
            gross_return=gross, net_return=net,
            pnl_quote=(net * self._costs.notional_quote),
            entry_progress_pct=signal.progress_pct,
            graduated=replay.graduated,
        )


# --- walk-forward -------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class WeekStats:
    week: str
    trades: int
    wins: int
    gross_profit: Decimal
    gross_loss: Decimal
    net_pnl: Decimal

    @property
    def profit_factor(self) -> Decimal | None:
        """None when undefined — no losses at all, or no trades. A profit
        factor printed as a number when its denominator is zero is the kind of
        thing that gets quoted in a summary and believed."""
        if self.gross_loss > 0:
            return (self.gross_profit / self.gross_loss).quantize(_PCT)
        return None

    @property
    def win_rate(self) -> Decimal | None:
        if not self.trades:
            return None
        return (Decimal(self.wins) / self.trades).quantize(_PCT)


def summarise(trades: Sequence[Trade], week: str = "all") -> WeekStats:
    profit = sum((t.pnl_quote for t in trades if t.pnl_quote > 0), Decimal(0))
    loss = sum((-t.pnl_quote for t in trades if t.pnl_quote < 0), Decimal(0))
    return WeekStats(
        week=week, trades=len(trades),
        wins=sum(1 for t in trades if t.pnl_quote > 0),
        gross_profit=profit, gross_loss=loss, net_pnl=profit - loss)


def by_week(trades: Sequence[Trade]) -> list[WeekStats]:
    """One row per ISO week of ENTRY. Grouping on entry rather than exit keeps
    a trade in the week the decision was made, which is the week a walk-forward
    split is actually about."""
    weeks: dict[str, list[Trade]] = {}
    for trade in trades:
        weeks.setdefault(trade.iso_week, []).append(trade)
    return [summarise(rows, week) for week, rows in sorted(weeks.items())]


def split_halves(weeks: Sequence[WeekStats]
                 ) -> tuple[list[WeekStats], list[WeekStats]]:
    """First half in sample, second half out of sample.

    Split on WEEKS, not on trades: splitting on trade count would put part of a
    week on each side and let a strategy's in-sample half see the same market
    conditions as its out-of-sample half.
    """
    midpoint = len(weeks) // 2
    return list(weeks[:midpoint]), list(weeks[midpoint:])


def token_concentration(trades: Sequence[Trade]) -> tuple[str | None, Decimal]:
    """The mint contributing the largest share of GROSS PROFIT, and its share.

    Every no-edge finding on this platform so far has had one token carrying
    the result, so this is checked before anything is believed.
    """
    profit: dict[str, Decimal] = {}
    for trade in trades:
        if trade.pnl_quote > 0:
            profit[trade.mint] = profit.get(trade.mint, Decimal(0)) + trade.pnl_quote
    total = sum(profit.values(), Decimal(0))
    if total <= 0:
        return None, Decimal(0)
    mint = max(profit, key=lambda m: profit[m])
    return mint, (profit[mint] / total).quantize(_PCT)


# --- the gate -----------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Criterion:
    name: str
    target: str
    actual: str
    passed: bool


def evaluate_gate(trades: Sequence[Trade],
                  weeks: Sequence[WeekStats]) -> list[Criterion]:
    """The four criteria, stated before any result was looked at.

    Read as a whole: a strategy clearing profit factor on a hundred trades but
    failing concentration has not found an edge, it has found one token.
    """
    _, oos_weeks = split_halves(weeks)
    oos_trades = [t for t in trades
                  if t.iso_week in {w.week for w in oos_weeks}]
    oos = summarise(oos_trades, "oos")
    pf = oos.profit_factor
    mint, share = token_concentration(trades)
    losing = [w.week for w in oos_weeks if w.net_pnl <= 0]

    return [
        Criterion(
            name="OOS profit factor",
            target=f">= {config.GATE_MIN_PF}",
            actual=("no losses" if pf is None and oos.gross_profit > 0
                    else "n/a" if pf is None else str(pf)),
            passed=(pf is not None and pf >= config.GATE_MIN_PF)
            or (pf is None and oos.gross_profit > 0),
        ),
        Criterion(
            name="trades",
            target=f">= {config.GATE_MIN_TRADES}",
            actual=str(len(trades)),
            passed=len(trades) >= config.GATE_MIN_TRADES,
        ),
        Criterion(
            name="max token share of gross profit",
            target=f"<= {config.GATE_MAX_TOKEN_SHARE}",
            actual=f"{share} ({mint[:12] + '..' if mint else 'n/a'})",
            passed=share <= config.GATE_MAX_TOKEN_SHARE,
        ),
        Criterion(
            name="every OOS week profitable",
            target="all weeks net > 0",
            actual=("yes" if oos_weeks and not losing
                    else f"no: {', '.join(losing)}" if losing else "no weeks"),
            passed=bool(oos_weeks) and not losing,
        ),
    ]


# --- reporting ----------------------------------------------------------------

def trades_csv(trades: Sequence[Trade]) -> str:
    fields = ["mint", "strategy", "path", "iso_week", "entry_at", "entry_price",
              "entry_progress_pct", "exit_at", "exit_price", "exit_reason",
              "gross_return", "net_return", "pnl_quote", "graduated"]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for trade in trades:
        writer.writerow(trade.as_row())
    return buffer.getvalue()


def _mean(values: Any) -> float:
    """Mean of a Decimal iterable as a float, for formatting only. The stored
    numbers stay Decimal; this is the last step before a `%` format."""
    rows = list(values)
    return float(sum(rows, Decimal(0)) / len(rows)) if rows else 0.0


def _pf(stats: WeekStats) -> str:
    pf = stats.profit_factor
    if pf is not None:
        return f"{pf:.4f}"
    return "inf" if stats.gross_profit > 0 else "-"


def format_weeks(weeks: Sequence[WeekStats]) -> str:
    header = (f"{'week':<12}{'trades':>8}{'wins':>7}{'win%':>8}{'gross+':>12}"
              f"{'gross-':>12}{'net':>12}{'PF':>9}")
    lines = [header, "-" * len(header)]
    for week in weeks:
        rate = week.win_rate
        lines.append(
            f"{week.week:<12}{week.trades:>8}{week.wins:>7}"
            f"{('-' if rate is None else f'{float(rate) * 100:.1f}'):>8}"
            f"{float(week.gross_profit):>12.5f}{float(week.gross_loss):>12.5f}"
            f"{float(week.net_pnl):>12.5f}{_pf(week):>9}")
    return "\n".join(lines)


def format_gate(criteria: Sequence[Criterion]) -> str:
    verdict = "PASS" if all(c.passed for c in criteria) else "FAIL"
    width = max(len(c.name) for c in criteria) + 2
    lines = [f"GATE: {verdict}", "-" * (width + 40)]
    for c in criteria:
        lines.append(f"  [{'PASS' if c.passed else 'FAIL'}] {c.name:<{width}}"
                     f"target {c.target:<12} actual {c.actual}")
    return "\n".join(lines)


def format_report(result: RunResult, *, coverage: dict[str, Any] | None = None
                  ) -> str:
    """Coverage first, deliberately.

    What was measurable bounds what any of the numbers below it can mean, and
    printing it underneath is how a result gets read without its denominator.
    """
    lines: list[str] = []
    if coverage is not None:
        lines += ["recorded coverage",
                  "-----------------",
                  "  " + "  ".join(f"{k}={v}" for k, v in coverage.items()),
                  ""]
    weeks = by_week(result.trades)
    in_sample, oos = split_halves(weeks)

    lines += [f"strategy: {result.strategy}",
              "  " + "  ".join(f"{k}={v}" for k, v in result.counts.items()), ""]
    if not result.trades:
        lines.append("no trades — nothing to report")
        return "\n".join(lines)

    lines += [format_weeks(weeks), ""]
    for label, rows in (("in-sample (first half)", in_sample),
                        ("out-of-sample (second half)", oos),
                        ("all", weeks)):
        picked = [t for t in result.trades
                  if t.iso_week in {w.week for w in rows}]
        stats = summarise(picked, label)
        lines.append(f"  {label:<28} trades={stats.trades:<6} "
                     f"net={float(stats.net_pnl):+.5f}  PF={_pf(stats)}")
    net = _mean(t.net_return for t in result.trades)
    gross = _mean(t.gross_return for t in result.trades)
    lines += ["",
              f"  mean net return per trade: {net:+.4%}",
              f"  gross before costs:        {gross:+.4%}",
              ""]
    lines.append(format_gate(evaluate_gate(result.trades, weeks)))
    lines += ["",
              "Denominated in the QUOTE currency (SOL), not USD — a pre-grad",
              "entry and a post-grad exit only share a unit there. So these do",
              "not equal grad_features.return_*, which are USD.",
              f"Costs charged per side: {float(Costs().side_fraction) * 10000:.0f} bps "
              f"({float(Costs().side_fraction) * 2 * 100:.2f}% round trip)."]
    return "\n".join(lines)


# --- loading ------------------------------------------------------------------

async def load_replays(session: AsyncSession, *, limit: int = 5000
                       ) -> list[Replay]:
    """Every token that reached a checkpoint OR graduated, with its series.

    The population is deliberately NOT just graduates: a pre-graduation
    strategy evaluated only on tokens that went on to graduate is conditioned
    on the outcome it is trying to predict.
    """
    # `union(a, b, c)` as a function, not `a.union(b).union(c)`: chaining onto
    # a CompoundSelect is not a thing in SQLAlchemy 2.0, and it fails at
    # execute time rather than at construction.
    reached = union(
        select(GradCheckpoint.mint.label("mint")).distinct(),
        select(GradMigration.mint.label("mint")).distinct(),
        select(GradCurveSample.mint.label("mint")).distinct()
        .where(GradCurveSample.complete.is_(True)),
    ).subquery()
    mints = [row[0] for row in (await session.execute(
        select(reached.c.mint).order_by(reached.c.mint).limit(limit))).all()]
    if not mints:
        return []

    replays = {m: Replay(mint=m, launch_at=None, graduated_at=None,
                         quote_currency=None) for m in mints}

    for token in (await session.execute(
            select(GradToken.mint, GradToken.first_seen_at,
                   GradToken.quote_currency)
            .where(GradToken.mint.in_(mints)))).all():
        replays[token.mint].launch_at = token.first_seen_at
        replays[token.mint].quote_currency = token.quote_currency

    for sample in (await session.execute(
            select(GradCurveSample.mint, GradCurveSample.ts,
                   GradCurveSample.progress_pct, GradCurveSample.v_quote_reserves,
                   GradCurveSample.v_token_reserves,
                   GradCurveSample.market_cap_quote, GradCurveSample.complete)
            .where(GradCurveSample.mint.in_(mints))
            .order_by(GradCurveSample.mint, GradCurveSample.ts))).all():
        replay = replays[sample.mint]
        replay.curve.append(CurveTick(
            ts=sample.ts, progress_pct=sample.progress_pct,
            price=curve_price(sample.v_quote_reserves, sample.v_token_reserves),
            market_cap_quote=sample.market_cap_quote, complete=sample.complete))
        if sample.complete and replay.graduated_at is None:
            replay.graduated_at = sample.ts

    for mark in (await session.execute(
            select(GradCheckpoint.mint, GradCheckpoint.level_pct,
                   GradCheckpoint.ts, GradCheckpoint.v_quote_reserves,
                   GradCheckpoint.v_token_reserves,
                   GradCheckpoint.market_cap_quote)
            .where(GradCheckpoint.mint.in_(mints)))).all():
        replays[mark.mint].checkpoints[mark.level_pct] = Checkpoint(
            level=mark.level_pct, ts=mark.ts,
            price=curve_price(mark.v_quote_reserves, mark.v_token_reserves),
            market_cap_quote=mark.market_cap_quote)

    # `price_native` and not `price_usd`: see the module docstring. A backfilled
    # GeckoTerminal candle has no native price and cannot be a fill point.
    for quote in (await session.execute(
            select(GradPostgradSample.mint, GradPostgradSample.ts,
                   GradPostgradSample.price_native, GradPostgradSample.source)
            .where(GradPostgradSample.mint.in_(mints),
                   GradPostgradSample.price_native.is_not(None))
            .order_by(GradPostgradSample.mint, GradPostgradSample.ts))).all():
        replays[quote.mint].ticks.append(
            Tick(ts=quote.ts, price=quote.price_native, source=quote.source))

    for event in (await session.execute(
            select(GradMigration.mint, GradMigration.ts)
            .where(GradMigration.mint.in_(mints)))).all():
        replay = replays[event.mint]
        replay.graduated_at = (event.ts if replay.graduated_at is None
                               else min(replay.graduated_at, event.ts))

    return sorted(replays.values(),
                  key=lambda r: (r.launch_at or r.graduated_at or datetime.max
                                 .replace(tzinfo=UTC), r.mint))


async def coverage_line(session: AsyncSession) -> dict[str, Any]:
    """`COVERAGE_SQL` from `features.py`, so the backtest prints the same
    denominator the feature summary does rather than a second opinion."""
    row = (await session.execute(text(COVERAGE_SQL))).mappings().one()
    return dict(row)
