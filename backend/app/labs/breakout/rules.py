"""Every trading decision, as pure functions. No session, no clock, no I/O.

`trader.py` is the part that reads and writes; this is the part that decides.
The split exists so the rules can be tested with hand-computed numbers rather
than with a database, and so the answer to "why did it buy that?" is one
function rather than a method on a service.

**`trail_step` is shared with Phase 2's `trail_result`.** The episode table
records what a $100 position with a $25 trailing stop WOULD have done; the
live trader runs the same stop at its own slot size. Those two numbers have
to agree or the recorded outcome is measuring a different strategy from the
one being traded — so they are not two implementations that a test compares,
they are one function that a test folds two ways.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.labs.breakout import config

# Exit reasons, in the order they are checked.
FORCED_EXIT = "forced_exit"
TRAIL_STOP = "trail_stop"
FAILED_SETUP = "failed_setup"
TIME_STOP = "time_stop"
HALT = "halt"
FLATTEN = "flatten"

# Why a candidate was not entered.
SKIP_LIQUIDITY = "liquidity"
SKIP_POOL_SHARE = "pool_share"
SKIP_NO_PRICE = "no_price"
SKIP_HELD = "already_held"


@dataclass(frozen=True, slots=True)
class Candidate:
    """A token whose episode transitioned into PRE_BREAKOUT on the last closed
    bar, with everything the entry rules need to judge it."""

    mint: str
    episode_id: object | None
    score: int
    liquidity_usd: float | None
    volume_24h_usd: float | None
    #: The open of the bar we are filling on — not the close we decided on.
    fill_open: float


@dataclass(frozen=True, slots=True)
class Held:
    """An open position, as the rules see it."""

    mint: str
    qty: float
    entry_price: float
    slot_size: float
    high_water_value: float
    opened_at: datetime


@dataclass(frozen=True, slots=True)
class Fill:
    price: float
    qty: float
    notional: float
    fees: float


# --- costs ---------------------------------------------------------------------

# Every cost and cap below reads `config` INSIDE the body, never as a default
# argument. A default is bound at import, so `monkeypatch.setattr(config, ...)`
# — or any future replay that wants to sweep slippage — would silently change
# nothing while appearing to work. The rest of this lab reads its flags at call
# time for the same reason.

def buy_price(price: float, bps: int | None = None) -> float:
    return price * (1 + (config.SLIPPAGE_BPS if bps is None else bps) / 10_000)


def sell_price(price: float, bps: int | None = None) -> float:
    return price * (1 - (config.SLIPPAGE_BPS if bps is None else bps) / 10_000)


def fee(notional: float, bps: int | None = None) -> float:
    return abs(notional) * (config.FEE_BPS if bps is None else bps) / 10_000


def slot_size(equity: float, slots: int | None = None) -> float:
    """Equity divided by the slot count, at the moment of entry.

    It compounds as the account grows and shrinks as it falls, which is the
    point. There is deliberately NO floor: the decision list says to carry on
    below $100 of equity rather than stop, because the kill switch is the only
    thing allowed to halt trading.
    """
    return equity / (config.SLOTS if slots is None else slots)


def open_fill(price: float, size: float) -> Fill:
    """A market buy of `size` dollars at `price`, with slippage and fee.

    The fee is charged on the notional actually paid, and the quantity bought
    is what the size buys AFTER the fee — so a $100 slot never spends $100.30.
    """
    filled = buy_price(price)
    notional = size / (1 + config.FEE_BPS / 10_000)
    return Fill(price=filled, qty=notional / filled, notional=notional,
                fees=fee(notional))


def close_fill(qty: float, price: float) -> Fill:
    filled = sell_price(price)
    notional = qty * filled
    return Fill(price=filled, qty=qty, notional=notional, fees=fee(notional))


# --- entry ---------------------------------------------------------------------

def entry_skip(candidate: Candidate, size: float, held: frozenset[str]) -> str | None:
    """Why this candidate is not entered, or None.

    The pool-share cap is the one that matters on Solana: a $100 order into a
    $15,000 pool is 0.67% of the book and moves the price more than the
    slippage model admits. Refusing it is the honest answer.
    """
    if candidate.mint in held:
        return SKIP_HELD
    if candidate.fill_open <= 0:
        return SKIP_NO_PRICE
    liquidity = candidate.liquidity_usd
    if liquidity is None or liquidity < config.MIN_LIQ_FOR_ENTRY:
        return SKIP_LIQUIDITY
    if size > liquidity * config.MAX_POOL_SHARE_PCT / 100:
        return SKIP_POOL_SHARE
    return None


def rank(candidates: Sequence[Candidate]) -> list[Candidate]:
    """Highest momentum first; ties broken by 24h volume, then by mint so the
    order is total and a re-run cannot shuffle it. Pre-decided."""
    return sorted(candidates,
                  key=lambda c: (-c.score, -(c.volume_24h_usd or 0.0), c.mint))


def choose_entries(
    candidates: Sequence[Candidate], *, equity: float, held: frozenset[str],
    free_slots: int, halted: bool = False,
) -> tuple[list[tuple[Candidate, Fill]], dict[str, str]]:
    """`(entries, skipped)` — who gets the free slots, and why the rest did not.

    Slot size is computed ONCE from the equity at the start of the pass, so
    two tokens entering on the same bar get the same size and the order they
    are processed in cannot change either one.
    """
    if halted or free_slots <= 0:
        return [], {c.mint: "halted" if halted else "no_slot" for c in candidates}

    size = slot_size(equity)
    entries: list[tuple[Candidate, Fill]] = []
    skipped: dict[str, str] = {}
    taken = set(held)
    for candidate in rank(candidates):
        if len(entries) >= free_slots:
            skipped[candidate.mint] = "no_slot"
            continue
        reason = entry_skip(candidate, size, frozenset(taken))
        if reason is not None:
            skipped[candidate.mint] = reason
            continue
        entries.append((candidate, open_fill(candidate.fill_open, size)))
        taken.add(candidate.mint)
    return entries, skipped


# --- the trailing stop ----------------------------------------------------------

def trail_amount(slot: float, pct: float | None = None) -> float:
    """The dollar distance the stop hangs below the high-water value."""
    return slot * (config.TRAIL_PCT if pct is None else pct) / 100


def stop_value(high_water: float, trail: float) -> float:
    return high_water - trail


@dataclass(frozen=True, slots=True)
class TrailStep:
    stopped: bool
    #: The value the position exited at, when `stopped`.
    exit_value: float
    high_water: float


def trail_step(
    *, qty: float, low: float, high: float, high_water: float, trail: float,
) -> TrailStep:
    """One bar of the trailing stop. **The low is taken before the high.**

    A bar that would both take the stop out and set a new high exits at the
    stop: we cannot see the order within a bar, so we assume the order that
    costs us. Getting this backwards is how a backtest invents money, and it
    is the single line that decides whether these numbers mean anything.

    The high-water mark is raised only AFTER the low has been checked, so a
    stop can never be lifted by a high the price reached after it would
    already have been hit.

    Folded over a series this is Phase 2's `trail_result`; called once per
    tick it is the live trader's stop. One function, two callers — which is
    what makes the recorded outcome and the traded outcome the same rule
    rather than two implementations somebody has to keep in step.
    """
    stop = stop_value(high_water, trail)
    if qty * low <= stop:
        return TrailStep(stopped=True, exit_value=stop, high_water=high_water)
    return TrailStep(stopped=False, exit_value=0.0,
                     high_water=max(high_water, qty * high))


# --- exit ----------------------------------------------------------------------

def exit_reason(
    position: Held, *, low: float, high: float, close: float, now: datetime,
    episode_failed: bool, in_universe: bool,
) -> tuple[str, float] | None:
    """`(reason, exit_price)` or None. First rule wins, in this order:

    1. `forced_exit` — the token left the universe. We can no longer price it
       honestly, so we take the last mark we had rather than carry a position
       we cannot see.
    2. `trail_stop` — the stop, evaluated low-first.
    3. `failed_setup` — the episode closed FAILED **and** we are under water.
       A failed setup that is nonetheless in profit keeps its trailing stop:
       the stop is the exit that knows what the price is doing.
    4. `time_stop` — held `MAX_HOLD_HOURS` and still under water. Same
       reasoning: a winner is not closed on the clock.
    """
    if not in_universe:
        return FORCED_EXIT, close
    trail = trail_amount(position.slot_size)
    step = trail_step(qty=position.qty, low=low, high=high,
                      high_water=position.high_water_value, trail=trail)
    if step.stopped:
        return TRAIL_STOP, step.exit_value / position.qty
    under_water = close < position.entry_price
    if episode_failed and under_water:
        return FAILED_SETUP, close
    if under_water and now - position.opened_at >= timedelta(hours=config.MAX_HOLD_HOURS):
        return TIME_STOP, close
    return None


# --- the account ----------------------------------------------------------------

def drawdown_pct(equity: float, peak: float) -> float:
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - equity) / peak * 100)


def should_halt(equity: float, peak: float, limit: float | None = None) -> bool:
    """The kill switch. Only a CLI reset clears it — deliberately, because a
    drawdown that deep means the rule is wrong, and an account that un-halts
    itself would just do it again."""
    return drawdown_pct(equity, peak) > (
        config.MAX_DRAWDOWN_PCT if limit is None else limit)


def pnl(entry_notional: float, exit_notional: float, fees: float) -> tuple[float, float]:
    """`(usd, pct)` net of every cost, measured against what was actually put in."""
    net = exit_notional - entry_notional - fees
    return net, (net / entry_notional * 100 if entry_notional > 0 else 0.0)
