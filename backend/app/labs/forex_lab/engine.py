"""The hedged grid itself. Pure Python: no DB, no network, no clock.

Everything here is a function of (candles, config), which is what makes the
strategy testable to the cent without a database in the room and what makes
two runs over the same candles produce byte-identical trade lists.

## The grid

Centred at `C`, `N` levels each side, `S` pips apart. At every level below `C`
there is a BUY LIMIT and a SELL STOP; at every level above, a SELL LIMIT and a
BUY STOP. Both orders at a level trigger at the same price — falling through
`C-kS` opens a long *and* a short, which is the whole point of a hedged grid.

Each fill carries a take-profit one step in its own favourable direction:

    limit fills take profit one step TOWARD the centre
    stop  fills take profit one step AWAY from the centre

which is the same rule stated twice — a limit is filled against the move and a
stop with it. When a take-profit closes a position, the order that opened it is
re-placed at its level.

## Where the conservatism lives

Four places, each of which costs the strategy money on purpose:

1. **Both intra-candle orderings are simulated** — `open→low→high→close` and
   `open→high→low→close` — on cloned state, and the one that ends with lower
   equity is the one that happened. A candle whose range reaches no trigger
   skips both, which is the great majority of minutes.
2. **Level N sits exactly on the re-centre boundary**, so its orders fill and
   are then closed by the re-centre at the same price — two spreads paid for
   nothing. Filling first is strictly worse than not filling, so that is the
   order.
3. **At one price point, new entries are processed before take-profits.**
   Entries consume margin, so doing them first produces more rejections; a
   take-profit processed first would have freed the margin that let them in.
4. **Equity marks at the closing side of the spread** — longs at bid, shorts at
   ask — so an open position shows the half-spread it would pay to leave, the
   way a real platform shows it. Margin calls therefore arrive slightly early.

Market closes (re-centre and stop-out) pay slippage as well as the spread:
they are the one moment a grid is closing many positions into a fast move, so
treating them as stop fills rather than limit fills is the honest reading.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.labs.forex_lab import config

_NY = ZoneInfo("America/New_York")
#: Prices carry five decimals; anything below this is float noise, not a move.
EPS = 1e-9
#: A leg that fires this many triggers is a bug, not a market.
_MAX_EVENTS_PER_LEG = 4096


class EngineError(RuntimeError):
    """The simulation reached a state the strategy cannot explain."""


@dataclass(frozen=True, slots=True)
class GridConfig:
    step_pips: float = config.DEFAULT_STEP_PIPS
    levels: int = config.DEFAULT_LEVELS
    lots: float = config.DEFAULT_LOTS
    #: Size of the STOP orders as a multiple of `lots`. 0.0 removes them, which
    #: is the neutral grid the sweep uses as its baseline.
    stop_multiplier: float = 1.0
    spread_pips: float = config.DEFAULT_SPREAD_PIPS
    stop_slippage_pips: float = config.DEFAULT_STOP_SLIPPAGE_PIPS
    start_equity: float = config.DEFAULT_START_EQUITY
    leverage: int = config.LEVERAGE
    margin_cap: float = config.MARGIN_CAP
    stop_out_ratio: float = config.STOP_OUT_RATIO
    swap_enabled: bool = True
    triple_wednesday: bool = True

    @property
    def step(self) -> float:
        """Step as a price difference, not pips."""
        return self.step_pips * config.PIP

    @property
    def half_spread(self) -> float:
        return self.spread_pips * config.PIP / 2.0

    @property
    def slip(self) -> float:
        return self.stop_slippage_pips * config.PIP

    @property
    def name(self) -> str:
        return f"S{self.step_pips:g}_N{self.levels}_M{self.stop_multiplier:g}"


@dataclass(slots=True)
class Order:
    """A resting grid order. `trigger_dir` is the direction price must travel
    to reach it: -1 for everything below the centre, +1 for everything above."""

    level: int  # signed, -N..-1 and 1..N
    kind: str  # buy_limit | sell_stop | sell_limit | buy_stop
    price: float  # trigger, a MID price
    side: int  # +1 long, -1 short
    lots: float
    tp: float  # take-profit, a MID price
    trigger_dir: int

    @property
    def is_stop(self) -> bool:
        return self.kind.endswith("_stop")


@dataclass(slots=True)
class Position:
    side: int
    lots: float
    entry: float  # the price actually paid, spread and slippage included
    tp: float  # MID price at which the take-profit fires
    margin: float
    opened_at: datetime
    origin: Order  # re-placed verbatim when the take-profit closes this
    swap_paid: float = 0.0
    cost_paid: float = 0.0  # spread + slippage booked at entry, in USD

    @property
    def tp_dir(self) -> int:
        return 1 if self.side > 0 else -1


@dataclass(slots=True)
class Trade:
    opened_at: datetime
    closed_at: datetime
    side: int
    lots: float
    entry: float
    exit: float
    kind: str  # the order that opened it
    reason: str  # tp | recenter | stopout | end
    #: The move from the order's LEVEL to the exit's mid — the trade with no
    #: friction at all.
    gross: float
    #: Spread and slippage, both legs. `pnl == gross - cost`, exactly.
    cost: float
    #: Carry booked night by night while the position was open. Reported
    #: alongside `pnl`, not inside it: it hit the balance as it accrued.
    swap: float
    pnl: float


def _units(lots: float) -> float:
    return lots * config.MICRO_LOT_UNITS


def _swap_rates(year: int) -> tuple[float, float]:
    table = config.SWAP_USD_PER_MICRO_LOT
    if year in table:
        return table[year]
    nearest = min(table, key=lambda y: (abs(y - year), y))
    return table[nearest]


class GridEngine:
    """One grid, one wallet, driven candle by candle.

    `step(candle)` is the whole interface. Everything else is state a test may
    read: `positions`, `orders`, `balance`, `center`, `trades`, `stats`.
    """

    def __init__(self, cfg: GridConfig, start_price: float, start_ts: datetime) -> None:
        self.cfg = cfg
        self.balance = cfg.start_equity
        self.center = round(start_price, 7)
        self.orders: list[Order] = []
        self.positions: list[Position] = []
        self.trades: list[Trade] = []
        self.mark = start_price
        self.stats = {
            "recenters": 0,
            "stopouts": 0,
            "rejected_fills": 0,
            "fills": 0,
            "spread_paid": 0.0,
            "swap_paid": 0.0,
            "recenter_loss": 0.0,
            "stopout_loss": 0.0,
            "tp_pnl": 0.0,
            # The forced liquidation at the end of the replay. Its own bucket,
            # because without one the cost breakdown does not add up to the
            # final equity printed underneath it — and a reader who checks the
            # arithmetic and finds it short has every reason to distrust the
            # rest of the table.
            "end_pnl": 0.0,
        }
        self.rejections: list[tuple[datetime, str, float]] = []
        #: The lowest equity the account ever showed, at the worse extreme of
        #: each candle. A run whose FINAL equity looks survivable can still have
        #: passed through zero, and a profit factor computed over a blown
        #: account is a number about a thing that stopped existing.
        self.min_equity = cfg.start_equity
        #: Running peak and the worst peak-to-trough fall from it, both measured
        #: on EVERY candle rather than on a daily close. A daily sample cannot
        #: see a trough that recovers before the day ends, and the gate this
        #: feeds is a drawdown ceiling — under-measuring it passes runs that
        #: should fail.
        self.peak_equity = cfg.start_equity
        self.max_drawdown = 0.0
        self._last_rollover: date | None = None
        self._build_grid(start_ts)

    # --- grid construction ----------------------------------------------------

    def _build_grid(self, ts: datetime) -> None:
        cfg = self.cfg
        step, centre = cfg.step, self.center
        stop_lots = cfg.lots * cfg.stop_multiplier
        self.orders = []
        for k in range(1, cfg.levels + 1):
            below = round(centre - k * step, 7)
            above = round(centre + k * step, 7)
            # Below the centre: a buy limit (TP one step toward the centre)
            # and a sell stop (TP one step away).
            self.orders.append(
                Order(-k, "buy_limit", below, +1, cfg.lots, round(below + step, 7), -1)
            )
            if stop_lots > 0:
                self.orders.append(
                    Order(-k, "sell_stop", below, -1, stop_lots, round(below - step, 7), -1)
                )
            # Above: a sell limit (TP toward the centre), a buy stop (away).
            self.orders.append(
                Order(k, "sell_limit", above, -1, cfg.lots, round(above - step, 7), +1)
            )
            if stop_lots > 0:
                self.orders.append(
                    Order(k, "buy_stop", above, +1, stop_lots, round(above + step, 7), +1)
                )
        self._refresh_bounds()

    def _refresh_bounds(self) -> None:
        """The nearest trigger each way, cached so the common candle — the one
        that reaches nothing at all — costs two comparisons."""
        cfg = self.cfg
        reach = cfg.levels * cfg.step
        down = [self.center - reach]
        up = [self.center + reach]
        for o in self.orders:
            (down if o.trigger_dir < 0 else up).append(o.price)
        for p in self.positions:
            (down if p.tp_dir < 0 else up).append(p.tp)
        self._bound_down = max(down)
        self._bound_up = min(up)

    # --- money ----------------------------------------------------------------

    def _close_price(self, side: int, mid: float, slipping: bool) -> float:
        """What a close actually executes at. A long sells into the bid."""
        cfg = self.cfg
        adj = cfg.half_spread + (cfg.slip if slipping else 0.0)
        return mid - adj if side > 0 else mid + adj

    def _open_price(self, side: int, mid: float, slipping: bool) -> float:
        cfg = self.cfg
        adj = cfg.half_spread + (cfg.slip if slipping else 0.0)
        return mid + adj if side > 0 else mid - adj

    def unrealized(self, mid: float) -> float:
        """Marked at the side a close would execute against — no slippage, as a
        platform's equity line does not price the exit's urgency."""
        total = 0.0
        for p in self.positions:
            x = self._close_price(p.side, mid, slipping=False)
            total += p.side * (x - p.entry) * _units(p.lots)
        return total

    @property
    def used_margin(self) -> float:
        return sum(p.margin for p in self.positions)

    def equity(self, mid: float) -> float:
        return self.balance + self.unrealized(mid)

    def _margin_for(self, lots: float, price: float) -> float:
        return lots * config.MICRO_LOT_UNITS * price / self.cfg.leverage

    # --- events ---------------------------------------------------------------

    def _open(self, o: Order, mid: float, ts: datetime) -> bool:
        """Fill one order. False means the margin cap rejected it."""
        entry = self._open_price(o.side, mid, slipping=o.is_stop)
        margin = self._margin_for(o.lots, entry)
        eq = self.equity(mid)
        if self.used_margin + margin > self.cfg.margin_cap * eq + EPS:
            self.stats["rejected_fills"] += 1
            self.rejections.append((ts, o.kind, o.price))
            return False
        cost = (abs(entry - mid)) * _units(o.lots)
        self.positions.append(
            Position(
                side=o.side,
                lots=o.lots,
                entry=entry,
                tp=o.tp,
                margin=margin,
                opened_at=ts,
                origin=replace(o),
                cost_paid=cost,
            )
        )
        self.stats["fills"] += 1
        self.stats["spread_paid"] += cost
        return True

    def _close(
        self, p: Position, mid: float, ts: datetime, reason: str, slipping: bool
    ) -> float:
        x = self._close_price(p.side, mid, slipping=slipping)
        gross = p.side * (x - p.entry) * _units(p.lots)
        exit_cost = abs(x - mid) * _units(p.lots)
        self.stats["spread_paid"] += exit_cost
        # `gross` already has the entry cost inside it, because `entry` is the
        # price that was paid rather than the level. `cost` is reported
        # separately so the breakdown adds up; it is not subtracted twice.
        pnl = gross
        self.balance += pnl
        self.trades.append(
            Trade(
                opened_at=p.opened_at,
                closed_at=ts,
                side=p.side,
                lots=p.lots,
                entry=p.entry,
                exit=x,
                kind=p.origin.kind,
                reason=reason,
                gross=p.side * (mid - p.origin.price) * _units(p.lots),
                cost=p.cost_paid + exit_cost,
                swap=p.swap_paid,
                pnl=pnl,
            )
        )
        self.positions.remove(p)
        return pnl

    def _close_all(self, mid: float, ts: datetime, reason: str) -> float:
        total = 0.0
        for p in list(self.positions):
            total += self._close(p, mid, ts, reason, slipping=True)
        return total

    def _recenter(self, mid: float, ts: datetime) -> None:
        loss = self._close_all(mid, ts, "recenter")
        self.stats["recenters"] += 1
        self.stats["recenter_loss"] += loss
        self.center = round(mid, 7)
        self._build_grid(ts)

    def _stop_out(self, mid: float, ts: datetime) -> None:
        loss = self._close_all(mid, ts, "stopout")
        self.stats["stopouts"] += 1
        self.stats["stopout_loss"] += loss
        self.orders = []
        self.center = round(mid, 7)
        self._build_grid(ts)

    # --- the sweep ------------------------------------------------------------

    def _next_trigger(self, cur: float, target: float, d: int) -> float | None:
        """The nearest price in the HALF-OPEN interval (cur, target] travelling
        in direction `d` at which anything happens, or None.

        Half-open, not closed, and that is the whole of the fill semantics: an
        order fires when price ARRIVES at its level, never because price was
        already sitting on it. The difference shows up the moment a
        take-profit re-places an order at a level price is currently touching —
        under a closed interval that order fires the instant the move reverses,
        without price ever having crossed it, which would hand the grid a free
        fill at every turning point that happens to land on a level. The gap
        from one candle's close to the next candle's open is walked as a leg of
        its own, so an order the market gapped onto is still reached.
        """
        best: float | None = None
        reach = self.cfg.levels * self.cfg.step
        cands = [self.center + d * reach]
        cands += [o.price for o in self.orders if o.trigger_dir == d]
        cands += [p.tp for p in self.positions if p.tp_dir == d]
        for price in cands:
            # Half-open: strictly past `cur`, up to and including `target`.
            if d < 0:
                reached = cur - EPS > price >= target - EPS
                nearer = best is None or price > best
            else:
                reached = cur + EPS < price <= target + EPS
                nearer = best is None or price < best
            if reached and nearer:
                best = price
        return best

    def _process_point(self, mid: float, d: int, ts: datetime) -> bool:
        """Everything that happens at one price. True if the grid re-centred.

        Entries first, then take-profits: see conservatism note 3 at the top.
        """
        # 1. entries
        firing = [o for o in self.orders if o.trigger_dir == d and abs(o.price - mid) < EPS]
        for o in firing:
            self.orders.remove(o)
            self._open(o, mid, ts)
        # 2. take-profits
        for p in [p for p in self.positions if p.tp_dir == d and abs(p.tp - mid) < EPS]:
            origin = p.origin
            pnl = self._close(p, mid, ts, "tp", slipping=False)
            self.stats["tp_pnl"] += pnl
            self.orders.append(replace(origin))
        # 3. the hard stop, last: it undoes everything above, on purpose
        reach = self.cfg.levels * self.cfg.step
        if mid <= self.center - reach + EPS or mid >= self.center + reach - EPS:
            self._recenter(mid, ts)
            return True
        self._refresh_bounds()
        return False

    def _run_leg(self, p_from: float, p_to: float, ts: datetime) -> None:
        self.mark = p_to
        if abs(p_to - p_from) < EPS:
            return
        d = 1 if p_to > p_from else -1
        cur = p_from
        for _ in range(_MAX_EVENTS_PER_LEG):
            nxt = self._next_trigger(cur, p_to, d)
            if nxt is None:
                return
            cur = nxt
            self._process_point(cur, d, ts)
            self._check_stop_out(cur, ts)
        raise EngineError(f"leg {p_from}->{p_to} at {ts} fired {_MAX_EVENTS_PER_LEG} triggers")

    def _check_stop_out(self, mid: float, ts: datetime) -> None:
        um = self.used_margin
        if um > 0 and self.equity(mid) < self.cfg.stop_out_ratio * um - EPS:
            self._stop_out(mid, ts)

    # --- swap -----------------------------------------------------------------

    def _apply_swap(self, ts: datetime) -> None:
        """Charge every 17:00 New York rollover that has passed since the last.

        Driven by the rollover CALENDAR rather than by the arrival of a candle
        at 17:00, because the Friday rollover lands on the weekly close and the
        feed may have no tick at that minute. Missing it would quietly hand the
        strategy a free night every week.
        """
        if not self.cfg.swap_enabled or not self.positions:
            ny = ts.astimezone(_NY)
            self._last_rollover = (
                ny.date() if ny.hour >= config.SWAP_HOUR_NY else ny.date() - timedelta(days=1)
            )
            return
        ny = ts.astimezone(_NY)
        r_date = ny.date() if ny.hour >= config.SWAP_HOUR_NY else ny.date() - timedelta(days=1)
        if self._last_rollover is None:
            self._last_rollover = r_date
            return
        if r_date <= self._last_rollover:
            return
        d = self._last_rollover + timedelta(days=1)
        while d <= r_date:
            if d.weekday() < 5:  # brokers roll Mon-Fri; the weekend is Wednesday's
                mult = (
                    3.0
                    if (
                        self.cfg.triple_wednesday and d.weekday() == config.TRIPLE_SWAP_WEEKDAY
                    )
                    else 1.0
                )
                long_rate, short_rate = _swap_rates(d.year)
                for p in self.positions:
                    amt = (long_rate if p.side > 0 else short_rate) * p.lots * mult
                    p.swap_paid += amt
                    self.balance += amt
                    self.stats["swap_paid"] += amt
            d += timedelta(days=1)
        self._last_rollover = r_date

    # --- cloning, for the two-ordering comparison -----------------------------

    def _clone(self) -> GridEngine:
        c = GridEngine.__new__(GridEngine)
        c.cfg = self.cfg
        c.balance = self.balance
        c.center = self.center
        c.orders = [replace(o) for o in self.orders]
        c.positions = [replace(p, origin=replace(p.origin)) for p in self.positions]
        c.trades = list(self.trades)
        c.mark = self.mark
        c.stats = dict(self.stats)
        c.rejections = list(self.rejections)
        c.min_equity = self.min_equity
        c.peak_equity = self.peak_equity
        c.max_drawdown = self.max_drawdown
        c._last_rollover = self._last_rollover
        c._bound_down = self._bound_down
        c._bound_up = self._bound_up
        return c

    def _adopt(self, other: GridEngine) -> None:
        self.balance = other.balance
        self.center = other.center
        self.orders = other.orders
        self.positions = other.positions
        self.trades = other.trades
        self.mark = other.mark
        self.stats = other.stats
        self.rejections = other.rejections
        self.min_equity = other.min_equity
        self.peak_equity = other.peak_equity
        self.max_drawdown = other.max_drawdown
        self._last_rollover = other._last_rollover
        self._bound_down = other._bound_down
        self._bound_up = other._bound_up

    # --- the public step ------------------------------------------------------

    def _walk(self, o: float, a: float, b: float, c: float, ts: datetime) -> None:
        # `mark` is where the market was left. Walking it to this candle's open
        # first is what makes a gap a crossing rather than a teleport.
        self._run_leg(self.mark, o, ts)
        self._run_leg(o, a, ts)
        self._run_leg(a, b, ts)
        self._run_leg(b, c, ts)

    def step(
        self,
        minute: datetime,
        mid_open: float,
        mid_high: float,
        mid_low: float,
        mid_close: float,
    ) -> None:
        self._apply_swap(minute)

        # The bound check is conservative: `_bound_up` is the nearest up-trigger
        # and `_bound_down` the nearest down one, so a candle that stays inside
        # them cannot fire anything. Most minutes do.
        touches = not (mid_high < self._bound_up - EPS and mid_low > self._bound_down + EPS)
        if touches:
            low_first = self._clone()
            low_first._walk(mid_open, mid_low, mid_high, mid_close, minute)
            high_first = self._clone()
            high_first._walk(mid_open, mid_high, mid_low, mid_close, minute)
            worse = (
                low_first
                if low_first.equity(mid_close) <= high_first.equity(mid_close)
                else high_first
            )
            self._adopt(worse)

        # The margin call is checked on EVERY candle, not only on the ones that
        # took the slow path. A candle can clear the bound check — or take the
        # slow path and fire nothing — while the mark alone walks the account
        # into a stop-out, and a stop-out that only happens on candles that
        # traded is a stop-out the backtest would mostly miss.
        low, high = self.unrealized(mid_low), self.unrealized(mid_high)
        worst_mid = mid_low if low < high else mid_high
        self._mark_equity(self.balance + min(low, high), self.balance + max(low, high))
        self._check_stop_out(worst_mid, minute)
        self.mark = mid_close

    def _mark_equity(self, worst: float, best: float) -> None:
        """Update the low-water mark and the drawdown from this candle.

        The peak is taken from the candle's BEST equity and the fall measured to
        its WORST, which assumes the high came before the low. Within one minute
        that is a few pips of difference, and it is the same conservative
        posture as resolving fills by the worse of the two orderings: a
        drawdown ceiling should be approached from above.
        """
        if worst < self.min_equity:
            self.min_equity = worst
        if best > self.peak_equity:
            self.peak_equity = best
        if self.peak_equity > 0:
            fall = (self.peak_equity - worst) / self.peak_equity
            if fall > self.max_drawdown:
                self.max_drawdown = fall

    def finish(self, minute: datetime, mid_close: float) -> None:
        """Close what is still open, so the equity curve ends at cash."""
        self.stats["end_pnl"] += self._close_all(mid_close, minute, "end")
        self.orders = []
        self.mark = mid_close
