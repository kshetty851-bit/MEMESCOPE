"""The strategy: when to enter, how much, when to leave. Pure.

`decide()` takes a `Snapshot` of what is known on one closed 4h bar, the
open positions and the account equity, and returns orders. It reads no
database, no clock and no network; the caller passes `now`. Every rule
here is a value in `config.py`, snapshotted into a `StrategyConfig` so a
replay can vary them without touching the module.

Fills are the caller's job (`sim.py`): an order decided on a bar is filled
at the NEXT bar's open, at cost. `stop_distance` travels with the order so
the stop can be fixed at the actual fill price.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from app.labs.crypto_trend import config
from app.labs.crypto_trend.regime import CHOP, RISK_OFF, RISK_ON, Regime
from app.labs.crypto_trend.trend import (
    DOWN,
    LONG_BIAS,
    SHORT_BIAS,
    UP,
    TrendState,
    Verdict,
    coin_verdict,
    compute_trend_states,
)

LONG, SHORT = "LONG", "SHORT"
OPEN, CLOSE = "OPEN", "CLOSE"

# --- the interface the replay drives ---------------------------------------------
#
# A rule set is a MODULE exposing these eight names. `replay.py` resolves one
# by `config.STRATEGY` and never mentions a timeframe of its own, which is
# what lets `slow_daily` reuse the harness, the account and the costs
# unchanged. This module is the `default` rule set.
#
#   TIMEFRAMES          the states to compute, decision timeframe first
#   DECISION_TIMEFRAME  the bars the replay steps and fills on
#   compute_states      (symbol, tf, candles, computed_at) -> list[state | None]
#   breadth_direction   the per-coin direction the regime counts
#   verdict_of          (states, symbol) -> Verdict
#   advance             positions, one bar later
#   exit_reason         the first exit rule that fires, or None
#   decide              the orders for this bar

TIMEFRAMES: tuple[str, ...] = ("4h", "1h")
DECISION_TIMEFRAME = "4h"


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    timeframe: str = "4h"
    strength_min: float = 40.0
    chop_breadth_min: float = 0.40
    funding_short_max: float = -0.0003
    max_positions: int = 5
    max_same_side: int = 4
    max_new_entries_per_bar: int = 2
    risk_per_trade: float = 0.01
    stop_atr: float = 2.0
    max_notional_pct: float = 0.20
    trail_trigger_atr: float = 1.5
    trail_atr: float = 2.5
    max_bars: int = 60
    fee_taker: float = 0.0005
    slippage_bps: float = 5.0
    funding_fallback: float = 0.0001
    starting_equity: float = 1000.0

    @classmethod
    def from_module(cls) -> StrategyConfig:
        """A snapshot of `config.py` as it is NOW — after any replay override."""
        return cls(
            timeframe=config.STRATEGY_TIMEFRAME, strength_min=float(config.STRENGTH_MIN),
            chop_breadth_min=float(config.CHOP_BREADTH_MIN),
            funding_short_max=float(config.FUNDING_SHORT_MAX),
            max_positions=int(config.MAX_POSITIONS), max_same_side=int(config.MAX_SAME_SIDE),
            max_new_entries_per_bar=int(config.MAX_NEW_ENTRIES_PER_BAR),
            risk_per_trade=float(config.RISK_PER_TRADE), stop_atr=float(config.STOP_ATR),
            max_notional_pct=float(config.MAX_NOTIONAL_PCT),
            trail_trigger_atr=float(config.TRAIL_TRIGGER_ATR),
            trail_atr=float(config.TRAIL_ATR),
            max_bars=int(config.MAX_BARS), fee_taker=float(config.FEE_TAKER),
            slippage_bps=float(config.SLIPPAGE_BPS),
            funding_fallback=float(config.FUNDING_FALLBACK),
            starting_equity=float(config.SIM_STARTING_EQUITY),
        )


@dataclass(frozen=True, slots=True)
class Position:
    symbol: str
    side: str
    qty: float
    entry_price: float
    #: Fixed at fill: entry -/+ stop_distance. Never moves.
    stop: float
    stop_distance: float
    atr_at_entry: float
    opened_at: datetime
    #: Closed 4h bars seen since the fill.
    bars_held: int
    #: Best close in the position's favour, from which the trail hangs.
    best_close: float
    #: None until the trail has triggered; then it only ever tightens.
    trail_stop: float | None
    notional_at_entry: float
    implied_leverage: float
    fees_paid: float
    funding_paid: float
    reason: str
    #: RISK_PER_TRADE x equity at the decision. The risk actually taken is
    #: `qty x stop_distance`, and is smaller whenever the notional cap bound.
    intended_risk_usd: float = 0.0

    @property
    def sign(self) -> float:
        return 1.0 if self.side == LONG else -1.0

    def unrealised(self, mark: float) -> float:
        return (mark - self.entry_price) * self.qty * self.sign


@dataclass(frozen=True, slots=True)
class Order:
    symbol: str
    action: str
    side: str
    reason: str
    #: OPEN only.
    qty: float | None = None
    stop_distance: float | None = None
    atr: float | None = None
    notional: float | None = None
    implied_leverage: float | None = None
    reference_price: float | None = None
    intended_risk_usd: float | None = None


@dataclass(frozen=True, slots=True)
class Snapshot:
    """What is known on one closed bar. `previous` is the prior bar's
    states, for detecting a verdict FLIP rather than a verdict."""
    now: datetime
    states: Mapping[str, Mapping[str, TrendState | None]]
    previous: Mapping[str, Mapping[str, TrendState | None]]
    regime: Regime | None
    #: Latest known funding rate per symbol, per 8h.
    funding: Mapping[str, float]
    universe: frozenset[str]


def compute_states(symbol: str, timeframe: str, candles, *, computed_at: datetime):
    """Every bar's state, causally. The replay indexes this."""
    return compute_trend_states(symbol, timeframe, candles, computed_at=computed_at)


def breadth_direction(states: Mapping[str, TrendState | None]) -> str | None:
    """The direction this coin contributes to the regime's breadth."""
    state = states.get(DECISION_TIMEFRAME)
    return None if state is None else state.direction


def atr_of(state: TrendState) -> float:
    return state.atr_pct / 100.0 * state.close


def verdict_of(states: Mapping[str, TrendState | None], symbol: str) -> Verdict:
    return coin_verdict(symbol, states.get("4h"), states.get("1h"))


# --- positions between bars ----------------------------------------------------

def advance(positions: Iterable[Position],
            states: Mapping[str, Mapping[str, TrendState | None]],
            cfg: StrategyConfig) -> list[Position]:
    """One closed bar later: count it, move the best close, tighten the
    trail. The trail triggers once profit reaches TRAIL_TRIGGER_ATR x the
    entry ATR and then hangs TRAIL_ATR x the CURRENT ATR off the best
    close, only ever moving in the position's favour."""
    out = []
    for p in positions:
        state = states.get(p.symbol, {}).get(cfg.timeframe)
        if state is None:
            out.append(replace(p, bars_held=p.bars_held + 1))
            continue
        close = state.close
        best = max(p.best_close, close) if p.side == LONG else min(p.best_close, close)
        trail = p.trail_stop
        if (best - p.entry_price) * p.sign >= cfg.trail_trigger_atr * p.atr_at_entry:
            candidate = best - cfg.trail_atr * atr_of(state) * p.sign
            if trail is None:
                trail = candidate
            else:
                trail = max(trail, candidate) if p.side == LONG else min(trail, candidate)
        out.append(replace(p, bars_held=p.bars_held + 1, best_close=best, trail_stop=trail))
    return out


# --- exits -----------------------------------------------------------------------

def exit_reason(p: Position, snapshot: Snapshot, cfg: StrategyConfig) -> str | None:
    """The first rule that fires, in this order: universe, regime, verdict,
    hard stop, trail, time. Stops are judged on the CLOSE of the bar and
    filled at the next open — a bar-close system, not an intrabar one."""
    if p.symbol not in snapshot.universe:
        return "universe_exit"
    r = snapshot.regime
    if r is not None and ((p.side == LONG and r.regime == RISK_OFF)
                          or (p.side == SHORT and r.regime == RISK_ON)):
        return "regime_exit"
    v = verdict_of(snapshot.states.get(p.symbol, {}), p.symbol).verdict
    if (p.side == LONG and v == SHORT_BIAS) or (p.side == SHORT and v == LONG_BIAS):
        return "verdict_exit"
    state = snapshot.states.get(p.symbol, {}).get(cfg.timeframe)
    if state is None:
        return None
    close = state.close
    if (close - p.stop) * p.sign <= 0:
        return "hard_stop"
    if p.trail_stop is not None and (close - p.trail_stop) * p.sign <= 0:
        return "trail_stop"
    if p.bars_held >= cfg.max_bars and p.unrealised(close) < 0:
        return "time_stop"
    return None


# --- sizing -----------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Size:
    qty: float
    stop_distance: float
    notional: float
    implied_leverage: float
    #: RISK_PER_TRADE x equity.
    intended_risk_usd: float
    #: qty x stop_distance — what the stop can actually lose.
    risk_usd: float


def size(equity: float, close: float, atr_value: float, cfg: StrategyConfig) -> Size | None:
    """Risk RISK_PER_TRADE of equity against a STOP_ATR x ATR stop; the
    notional that implies, capped at MAX_NOTIONAL_PCT of equity."""
    if equity <= 0 or close <= 0 or atr_value <= 0:
        return None
    stop_distance = cfg.stop_atr * atr_value
    stop_pct = stop_distance / close
    intended = cfg.risk_per_trade * equity
    notional = min(intended / stop_pct, cfg.max_notional_pct * equity)
    qty = notional / close
    return Size(qty=qty, stop_distance=stop_distance, notional=notional,
                implied_leverage=notional / equity, intended_risk_usd=intended,
                risk_usd=qty * stop_distance)


# --- entries ------------------------------------------------------------------------

def _side_allowed(side: str, regime: Regime | None, cfg: StrategyConfig) -> str | None:
    """None when allowed, else why not."""
    if regime is None:
        return "no regime"
    if side == LONG:
        if regime.regime == RISK_ON:
            return None
        if regime.regime == CHOP and regime.breadth_up >= cfg.chop_breadth_min:
            return None
        return f"regime {regime.regime}, breadth_up {regime.breadth_up:.2f}"
    if regime.regime == RISK_OFF:
        return None
    if regime.regime == CHOP and regime.breadth_down >= cfg.chop_breadth_min:
        return None
    return f"regime {regime.regime}, breadth_down {regime.breadth_down:.2f}"


def entry_candidates(snapshot: Snapshot,
                     cfg: StrategyConfig) -> list[tuple[str, str, TrendState]]:
    """(symbol, side, 4h state) for every coin whose verdict FLIPPED to a
    bias on this bar and passes the regime, BTC, strength and funding gates.
    Strongest first, so a cap admits the best of them."""
    out = []
    for symbol in sorted(snapshot.universe):
        states = snapshot.states.get(symbol, {})
        state = states.get(cfg.timeframe)
        if state is None:
            continue
        now = verdict_of(states, symbol).verdict
        before = verdict_of(snapshot.previous.get(symbol, {}), symbol).verdict
        if now == before or now not in (LONG_BIAS, SHORT_BIAS):
            continue
        side = LONG if now == LONG_BIAS else SHORT
        if _side_allowed(side, snapshot.regime, cfg) is not None:
            continue
        btc = snapshot.regime.btc_direction if snapshot.regime else None
        if (side == LONG and btc == DOWN) or (side == SHORT and btc == UP):
            continue
        if state.strength < cfg.strength_min:
            continue
        funding = snapshot.funding.get(symbol, cfg.funding_fallback)
        if side == SHORT and funding < cfg.funding_short_max:
            continue
        out.append((symbol, side, state))
    out.sort(key=lambda t: (-t[2].strength, t[0]))
    return out


def decide(snapshot: Snapshot, positions: Sequence[Position], equity: float,
           cfg: StrategyConfig) -> list[Order]:
    """Exits first, then entries into whatever room the exits leave — at
    most MAX_NEW_ENTRIES_PER_BAR of them, strongest first, so one rally
    cannot open the whole book on one close. A position closing on this bar
    frees its slot and its symbol at the same next-open fill the entry
    would take."""
    orders: list[Order] = []
    closing: set[str] = set()
    for p in positions:
        reason = exit_reason(p, snapshot, cfg)
        if reason is not None:
            orders.append(Order(p.symbol, CLOSE, p.side, reason))
            closing.add(p.symbol)

    remaining = [p for p in positions if p.symbol not in closing]
    held = {p.symbol for p in remaining}
    per_side = {LONG: sum(1 for p in remaining if p.side == LONG),
                SHORT: sum(1 for p in remaining if p.side == SHORT)}
    room = min(cfg.max_positions - len(remaining), cfg.max_new_entries_per_bar)
    for symbol, side, state in entry_candidates(snapshot, cfg):
        if room <= 0:
            break
        if symbol in held or per_side[side] >= cfg.max_same_side:
            continue
        sz = size(equity, state.close, atr_of(state), cfg)
        if sz is None:
            continue
        orders.append(Order(
            symbol, OPEN, side,
            reason=(f"verdict flip to {LONG_BIAS if side == LONG else SHORT_BIAS}, "
                    f"strength {state.strength}, "
                    f"regime {snapshot.regime.regime if snapshot.regime else '-'}"),
            qty=sz.qty, stop_distance=sz.stop_distance, atr=atr_of(state),
            notional=sz.notional, implied_leverage=sz.implied_leverage,
            reference_price=state.close, intended_risk_usd=sz.intended_risk_usd))
        held.add(symbol)
        per_side[side] += 1
        room -= 1
    return orders
