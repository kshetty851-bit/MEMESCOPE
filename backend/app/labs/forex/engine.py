"""Backtest execution engine. Pure: no I/O, no clock, no randomness.

Turns a strategy's `Signal`s into fills, exits and a money ledger. Every rule
here exists to stop a backtest from flattering the strategy:

* A signal is decided at the CLOSE of bar i, so it can only fill at the OPEN of
  bar i+1 — never at the close that produced it.
* Candles are mid prices; spread and slippage are charged on every fill, and a
  stop that gaps fills at the (worse) gapped price, not at the stop.
* When one bar touches both stop and target the order is unknowable from that
  bar. 1-minute data decides it if it covers the bar; otherwise the stop wins
  and the trade is flagged, counted and disclosed.
* Leverage only CAPS position size. Returns are never price move x leverage.
* Losers are never dropped: positions still open at the end are closed at the
  last close and counted.

Prices are floats for speed (a year of 5-minute bars is ~75k); every money
figure that leaves the engine is a Decimal quantised to cents.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from app.labs.forex.sessions import in_session, rollovers_between, swap_multiplier
from app.labs.forex.types import (
    CENT,
    TIMEFRAME_SECONDS,
    BacktestConfig,
    BacktestResult,
    Candle,
    Direction,
    DirectionMode,
    EquityPoint,
    ExitReason,
    Instrument,
    Session,
    Signal,
    SkippedSignal,
    SkipReason,
    StrategyId,
    Trade,
)

ASSUMPTIONS: tuple[str, ...] = (
    "entry_next_bar_open",
    "candles_treated_as_mid_spread_symmetric",
    "stop_first_when_ambiguous",
    "tp_limit_fill_no_slippage",
    "stop_gap_fills_at_open",
    "rollover_2200_utc_wednesday_triple",
    "margin_closeout_at_bar_extreme",
    "leverage_caps_size_not_returns",
)

# Where to mark open positions: the bar's open, its close, or its adverse extreme.
_OPEN, _CLOSE, _ADVERSE = 0, 1, 2
# What one bar (or 1-minute candle) did to a position's stop and target.
_NONE, _STOP, _TP, _BOTH = 0, 1, 2, 3

_DAY = timedelta(days=1)
_MINUTE = timedelta(minutes=1)
# Float floor() guard: 10 / 0.002 can land on 4999.999999999999.
_EPS = 1e-9


def _q(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_EVEN)


def _dec(x: float) -> Decimal:
    # repr() round-trips; the rounding strips float noise like 1.1000700000000001
    # so a price that was quoted to 5 places is not carried as 17.
    return Decimal(repr(round(x, 10)))


def _money(x: float) -> Decimal:
    return _q(Decimal(repr(round(x, 8))))


@dataclass(slots=True, eq=False)
class _Pos:
    id: int
    d: int
    direction: Direction
    signal_time: datetime
    entry_time: datetime
    entry_idx: int
    entry: float
    stop: float
    tp: float | None
    #: Signed infinity when there is no target, so the hit test needs no branch.
    tp_f: float
    units: int
    risk_usd: Decimal
    margin: Decimal
    margin_f: float
    entry_comm: Decimal
    entry_comm_f: float
    entry_cost: Decimal
    reason: str
    accrued_to: datetime
    next_roll: datetime | None
    fin: Decimal = Decimal(0)
    fin_f: float = 0.0


class _Engine:
    def __init__(
        self,
        cfg: BacktestConfig,
        candles: Sequence[Candle],
        signals: Sequence[Signal],
        instrument: Instrument,
        lower_tf: Sequence[Candle] | None,
        trade_from: datetime | None,
    ) -> None:
        if instrument.quote == "USD":
            self.usd_quote = True
        elif instrument.base == "USD":
            self.usd_quote = False
        else:
            raise ValueError(f"unsupported cross {instrument.symbol}: need a USD leg")
        n = len(candles)
        if n == 0:
            raise ValueError("no candles")
        start = 0
        if trade_from is not None:
            while start < n and candles[start].open_time < trade_from:
                start += 1
            if start == n:
                raise ValueError("trade_from is after the last candle")

        self.cfg = cfg
        self.candles = candles
        self.inst = instrument
        self.lower = lower_tf
        self.n = n
        self.start = start
        self.tf_seconds = TIMEFRAME_SECONDS[cfg.timeframe]
        self.tf_delta = timedelta(seconds=self.tf_seconds)
        pip = instrument.pip_size
        self.half = cfg.costs.spread_pips * pip / 2
        self.slip = cfg.costs.slippage_pips * pip
        self.min_units = instrument.min_units
        self.contract = Decimal(instrument.contract_size)
        self.lev = cfg.risk.max_leverage
        self.risk_pct = float(cfg.risk.risk_per_trade_pct)
        self.daily_pct = float(cfg.risk.max_daily_loss_pct)
        self.closeout_pct = float(cfg.risk.margin_closeout_pct)
        self.financing = cfg.costs.financing_enabled
        self.window: Session | None = None
        if cfg.params.close_at_session_end:
            self.window = (
                cfg.params.trading_session
                if cfg.strategy == StrategyId.LONDON_BREAKOUT
                else cfg.session_filter
            )

        self.balance = cfg.risk.initial_capital
        self.balance_f = float(self.balance)
        self.open: list[_Pos] = []
        self.trades: list[Trade] = []
        self.curve: list[EquityPoint] = []
        self.skipped: list[SkippedSignal] = []
        self.next_id = 1
        self.closeouts = 0
        self.ltf_resolved = 0
        self.ambiguous = 0
        self.ltf_index: dict[datetime, int] | None = None

        self.day = -1
        self.trades_today = 0
        self.blocked = False
        self.day_start = 0.0
        self.loss_threshold = 0.0

        self.by_entry: dict[int, list[Signal]] = {}
        self.no_next: list[Signal] = []
        self.n_signals = 0
        for sig in signals:
            if not 0 <= sig.index < n:
                raise ValueError(f"signal index {sig.index} outside candles")
            if sig.stop_distance <= 0:
                raise ValueError("signal stop_distance must be positive")
            if sig.take_profit_distance is not None and sig.take_profit_distance <= 0:
                raise ValueError("signal take_profit_distance must be positive")
            if sig.index < start:
                continue
            self.n_signals += 1
            if sig.index + 1 >= n:
                self.no_next.append(sig)
            else:
                self.by_entry.setdefault(sig.index + 1, []).append(sig)

    # ------------------------------------------------------------------ marks

    def _mark(self, p: _Pos, kind: int, c: Candle) -> float:
        if kind == _OPEN:
            base = c.open
        elif kind == _CLOSE:
            base = c.close
        else:
            base = c.low if p.d > 0 else c.high
        return base - p.d * self.half

    def _unreal(self, p: _Pos, price: float) -> float:
        conv = 1.0 if self.usd_quote else 1.0 / price
        # Entry commission is deducted here (not only at exit) so equity is
        # never flattered by costs already incurred.
        return p.units * (price - p.entry) * p.d * conv + p.fin_f - p.entry_comm_f

    def _unreal_sum(self, kind: int, c: Candle) -> float:
        total = 0.0
        for p in self.open:
            total += self._unreal(p, self._mark(p, kind, c))
        return total

    def _used_margin(self, exclude: _Pos | None = None) -> float:
        return sum(p.margin_f for p in self.open if p is not exclude)

    def _point(self, when: datetime, kind: int, c: Candle) -> None:
        if not self.open:
            self.curve.append(EquityPoint(when, self.balance, self.balance, 0.0))
            return
        u = self._unreal_sum(kind, c)
        eq = self.balance_f + u
        util = self._used_margin() / eq * 100 if eq > 0 else 100.0
        self.curve.append(EquityPoint(when, self.balance, self.balance + _money(u), util))

    # ------------------------------------------------------------- daily limit

    def _new_day(self, day: int, c: Candle) -> None:
        self.day = day
        self.trades_today = 0
        self.blocked = False
        self.day_start = self.balance_f + self._unreal_sum(_OPEN, c)
        self.loss_threshold = self.day_start * self.daily_pct / 100

    def _check_daily(self, kind: int, c: Candle) -> None:
        if self.daily_pct <= 0 or self.blocked:
            return
        eq = self.balance_f + self._unreal_sum(kind, c)
        if eq - self.day_start <= -self.loss_threshold:
            self.blocked = True

    # --------------------------------------------------------------- financing

    def _accrue(self, p: _Pos, upto: datetime) -> None:
        if p.next_roll is None or upto < p.next_roll:
            return
        swap = (
            self.cfg.costs.swap_long_per_lot if p.d > 0 else self.cfg.costs.swap_short_per_lot
        )
        lots = Decimal(p.units) / self.contract
        for r in rollovers_between(p.accrued_to, upto):
            mult = swap_multiplier(r)
            if mult:
                amount = swap * lots * mult
                p.fin += amount
                p.fin_f += float(amount)
        p.accrued_to = upto
        p.next_roll = rollovers_between(upto, upto + _DAY)[0]

    # ------------------------------------------------------------------- exits

    def _close(
        self,
        p: _Pos,
        price: float,
        reason: ExitReason,
        when: datetime,
        c: Candle,
        kind: int,
        *,
        slipped: bool,
        ambiguous: bool = False,
    ) -> None:
        if self.financing:
            self._accrue(p, when)
        self.open.remove(p)
        diff = (_dec(price) - _dec(p.entry)) * p.d
        gross = Decimal(p.units) * diff
        conv = 1.0
        if not self.usd_quote:
            gross = gross / _dec(price)
            conv = 1.0 / price
        gross = _q(gross)
        exit_comm = _q(
            Decimal(p.units) / self.contract * self.cfg.costs.commission_per_lot_side
        )
        commission = p.entry_comm + exit_comm
        financing = _q(p.fin)
        net = gross - commission + financing
        exit_cost = _money(p.units * (self.half + (self.slip if slipped else 0.0)) * conv)
        r_mult = float(net / p.risk_usd) if p.risk_usd else 0.0
        self.trades.append(
            Trade(
                id=p.id,
                direction=p.direction,
                signal_time=p.signal_time,
                entry_time=p.entry_time,
                exit_time=when,
                entry_price=p.entry,
                exit_price=price,
                stop_price=p.stop,
                take_profit_price=p.tp,
                units=p.units,
                risk_usd=p.risk_usd,
                gross_pnl=gross,
                commission=commission,
                spread_slippage_cost=p.entry_cost + exit_cost,
                financing=financing,
                net_pnl=net,
                r_multiple=r_mult,
                exit_reason=reason,
                reason=p.reason,
                ambiguous_exit=ambiguous,
                margin_used=p.margin,
            )
        )
        self.balance += net
        self.balance_f = float(self.balance)
        self._point(when, kind, c)
        self._check_daily(kind, c)

    def _stop_fill(self, p: _Pos, o: float) -> float:
        d = p.d
        # Gapping through the stop fills at the gapped open, which is worse.
        return d * min(d * p.stop, d * (o - d * self.half)) - d * self.slip

    def _tp_fill(self, p: _Pos, o: float) -> float:
        e = o - p.d * self.half
        # A limit order: no slippage, and a gap beyond it fills at the better open.
        return e if p.d * (e - p.tp_f) >= 0 else p.tp_f

    def _classify(self, p: _Pos, o: float, h: float, lo: float) -> int:
        d = p.d
        adv, fav = (lo, h) if d > 0 else (h, lo)
        shift = d * self.half
        stop_hit = d * (adv - shift - p.stop) <= 0
        tp_hit = d * (fav - shift - p.tp_f) >= 0
        if not stop_hit and not tp_hit:
            return _NONE
        if stop_hit and tp_hit:
            e_o = o - shift
            # The open is the first price of the bar, so a gap settles the order.
            if d * (e_o - p.stop) <= 0:
                return _STOP
            if d * (e_o - p.tp_f) >= 0:
                return _TP
            return _BOTH
        return _STOP if stop_hit else _TP

    def _lower_bars(self, t: datetime) -> list[Candle] | None:
        lower = self.lower
        if lower is None or self.tf_seconds < 60:
            return None
        if self.ltf_index is None:
            self.ltf_index = {k.open_time: i for i, k in enumerate(lower)}
        out: list[Candle] = []
        for k in range(self.tf_seconds // 60):
            idx = self.ltf_index.get(t + _MINUTE * k)
            if idx is None:
                # A partial walk could miss an earlier touch; stay conservative.
                return None
            out.append(lower[idx])
        return out

    def _intrabar(self, p: _Pos, c: Candle) -> tuple[float, ExitReason, bool, bool] | None:
        """(price, reason, slipped, ambiguous) if the bar exits `p`, else None."""
        cls = self._classify(p, c.open, c.high, c.low)
        if cls == _NONE:
            return None
        if cls == _STOP:
            return self._stop_fill(p, c.open), ExitReason.STOP_LOSS, True, False
        if cls == _TP:
            return self._tp_fill(p, c.open), ExitReason.TAKE_PROFIT, False, False
        minutes = self._lower_bars(c.open_time)
        if minutes is not None:
            for m in minutes:
                mc = self._classify(p, m.open, m.high, m.low)
                if mc == _STOP:
                    self.ltf_resolved += 1
                    return self._stop_fill(p, m.open), ExitReason.STOP_LOSS, True, False
                if mc == _TP:
                    self.ltf_resolved += 1
                    return self._tp_fill(p, m.open), ExitReason.TAKE_PROFIT, False, False
                if mc == _BOTH:
                    self.ambiguous += 1
                    return self._stop_fill(p, m.open), ExitReason.STOP_LOSS, True, True
        self.ambiguous += 1
        return self._stop_fill(p, c.open), ExitReason.STOP_LOSS, True, True

    def _session_exits(self, j: int, c: Candle, window: Session) -> None:
        if in_session(c.open_time, window):
            return
        for p in list(self.open):
            if p.entry_idx < j:
                price = c.open - p.d * self.half - p.d * self.slip
                self._close(
                    p, price, ExitReason.SESSION_END, c.open_time, c, _OPEN, slipped=True
                )

    def _closeout(self, c: Candle) -> None:
        eq = self.balance_f + self._unreal_sum(_ADVERSE, c)
        if eq > self._used_margin() * self.closeout_pct / 100:
            return
        self.closeouts += 1
        for p in list(self.open):
            price = self._mark(p, _ADVERSE, c) - p.d * self.slip
            self._close(
                p, price, ExitReason.MARGIN_CLOSEOUT, c.open_time, c, _ADVERSE, slipped=True
            )

    # ----------------------------------------------------------------- entries

    def _skip(self, sig: Signal, reason: SkipReason) -> None:
        self.skipped.append(
            SkippedSignal(self.candles[sig.index].open_time, sig.direction, reason)
        )

    def _try_enter(self, sig: Signal, j: int) -> None:
        sig_bar = self.candles[sig.index]
        c = self.candles[j]
        if c.open_time - sig_bar.open_time != self.tf_delta:
            self._skip(sig, SkipReason.GAP_BEFORE_ENTRY)
            return
        mode = self.cfg.direction
        if (mode == DirectionMode.LONG_ONLY and sig.direction != Direction.LONG) or (
            mode == DirectionMode.SHORT_ONLY and sig.direction != Direction.SHORT
        ):
            self._skip(sig, SkipReason.DIRECTION_DISABLED)
            return
        sf = self.cfg.session_filter
        if sf is not None and not in_session(c.open_time, sf):
            self._skip(sig, SkipReason.OUTSIDE_SESSION)
            return
        risk = self.cfg.risk
        if len(self.open) >= risk.max_open_positions:
            self._skip(sig, SkipReason.MAX_OPEN_POSITIONS)
            return
        if self.trades_today >= risk.max_trades_per_day:
            self._skip(sig, SkipReason.MAX_TRADES_PER_DAY)
            return
        if self.blocked:
            self._skip(sig, SkipReason.DAILY_LOSS_LIMIT)
            return

        d = 1 if sig.direction == Direction.LONG else -1
        fill = round(c.open + d * (self.half + self.slip), 10)
        conv = 1.0 if self.usd_quote else 1.0 / fill
        equity = self.balance_f + self._unreal_sum(_OPEN, c)
        if equity <= 0:
            self._skip(sig, SkipReason.SIZE_BELOW_MINIMUM)
            return
        risk_budget = equity * self.risk_pct / 100
        raw = risk_budget / (sig.stop_distance * conv)
        units = math.floor(raw / self.min_units + _EPS) * self.min_units
        if units < self.min_units:
            self._skip(sig, SkipReason.SIZE_BELOW_MINIMUM)
            return
        # Leverage caps the size; it never scales the P&L.
        base_to_usd = fill if self.usd_quote else 1.0
        free = equity - self._used_margin()
        cap = (
            math.floor(free * self.lev / base_to_usd / self.min_units + _EPS) * self.min_units
            if free > 0
            else 0
        )
        if cap < self.min_units:
            self._skip(sig, SkipReason.MARGIN_INSUFFICIENT)
            return
        units = int(min(units, cap))

        margin_f = units * base_to_usd / self.lev
        stop = round(fill - d * sig.stop_distance, 10)
        tpd = sig.take_profit_distance
        tp = None if tpd is None else round(fill + d * tpd, 10)
        comm = _q(Decimal(units) / self.contract * self.cfg.costs.commission_per_lot_side)
        pos = _Pos(
            id=self.next_id,
            d=d,
            direction=sig.direction,
            signal_time=sig_bar.open_time,
            entry_time=c.open_time,
            entry_idx=j,
            entry=fill,
            stop=stop,
            tp=tp,
            tp_f=d * math.inf if tp is None else tp,
            units=units,
            risk_usd=_money(units * sig.stop_distance * conv),
            margin=_money(margin_f),
            margin_f=margin_f,
            entry_comm=comm,
            entry_comm_f=float(comm),
            entry_cost=_money(units * (self.half + self.slip) * conv),
            reason=sig.reason,
            accrued_to=c.open_time,
            next_roll=rollovers_between(c.open_time, c.open_time + _DAY)[0]
            if self.financing
            else None,
        )
        self.next_id += 1
        self.trades_today += 1
        self.open.append(pos)

    # -------------------------------------------------------------------- loop

    def run(self) -> BacktestResult:
        candles, n = self.candles, self.n
        last = n - 1
        first = candles[self.start]
        self.curve.append(EquityPoint(first.open_time, self.balance, self.balance, 0.0))

        for j in range(self.start, n):
            c = candles[j]
            t = c.open_time
            day = t.toordinal()
            if day != self.day:
                self._new_day(day, c)

            if self.open:
                if self.financing:
                    for p in self.open:
                        self._accrue(p, t)
                if self.window is not None:
                    self._session_exits(j, c, self.window)

            sigs = self.by_entry.get(j)
            if sigs:
                for sig in sigs:
                    self._try_enter(sig, j)

            if self.open:
                for p in list(self.open):
                    hit = self._intrabar(p, c)
                    if hit is not None:
                        price, reason, slipped, amb = hit
                        self._close(
                            p, price, reason, t, c, _CLOSE, slipped=slipped, ambiguous=amb
                        )
                if self.open:
                    self._closeout(c)
            if j == last and self.open:
                for p in list(self.open):
                    price = c.close - p.d * self.half - p.d * self.slip
                    self._close(
                        p,
                        price,
                        ExitReason.END_OF_DATA,
                        t + self.tf_delta,
                        c,
                        _CLOSE,
                        slipped=True,
                    )

            self._check_daily(_CLOSE, c)
            if j == last or candles[j + 1].open_time.toordinal() != day:
                self._point(t, _CLOSE, c)

        for sig in self.no_next:
            self._skip(sig, SkipReason.NO_NEXT_BAR)
        self.trades.sort(key=lambda tr: tr.id)
        return BacktestResult(
            config=self.cfg,
            start=first.open_time,
            end=candles[last].open_time,
            bars=self.n - self.start,
            trades=tuple(self.trades),
            equity_curve=tuple(self.curve),
            skipped=tuple(self.skipped),
            final_balance=self.balance,
            exits_resolved_by_lower_tf=self.ltf_resolved,
            exits_ambiguous=self.ambiguous,
            margin_closeouts=self.closeouts,
            signals=self.n_signals,
            assumptions=ASSUMPTIONS,
        )


def run_backtest(
    cfg: BacktestConfig,
    candles: Sequence[Candle],
    signals: Sequence[Signal],
    *,
    instrument: Instrument,
    lower_tf: Sequence[Candle] | None = None,
    trade_from: datetime | None = None,
) -> BacktestResult:
    """Replay `signals` over `candles` and return every trade, skip and cost.

    Deterministic: the same inputs always give an equal result.
    """
    return _Engine(cfg, candles, signals, instrument, lower_tf, trade_from).run()
