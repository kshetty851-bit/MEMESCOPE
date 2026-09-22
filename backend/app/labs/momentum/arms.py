"""Thirteen strategies on one universe, and three of them are dice.

## Run 2, from 22 September 2026

Run 1 ran fifty strategies for three days and closed 23,911 trades. It found
no edge in the momentum candle: replayed over its 890 entries, every take
profit from 3% to 30% and every hold from 30 minutes to 6 hours lost money.
What it DID find was mechanical, so run 2 is built on it:

* **Cost decides.** A round trip is 77 bps on a 30 bps venue and 185 bps on
  pump.fun's AMM, whose coins also fell more (gross -0.78% against raydium's
  +0.50%). `config.MAX_FEE_BPS` now refuses that venue outright.
* **Stops lose** (-7.6% over 1,644 stopped trades) and small take profits
  sell the winners. Run 2 has no stops and one take profit, at 15%.
* **Loud candles are the worst ones**: over 15%, -5.4% a trade.

So the arms test the three things that were not negative — a coin down on
the day, a pool over $1m, the quiet end of the rule — plus the base and the
opposite bet, each on two exits.

## One factor at a time

Every strategy is BASE with ONE thing changed. Each answers a single question
against its yardstick instead of thirteen rules racing, where the leader is
whichever got luckiest.

## The dice are the point

`RND_60` and `RND_TP15` buy the same universe at random, same costs, same
exits, provably no edge. `RND_DOWN` draws at random from coins already down
10%+ on the day, so `DOWN_60` has to beat the COIN, not just the clock.

## Frozen

A strategy is only evidence if it cannot change while it runs. Changing a
rule means a new name; the old one keeps its record.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal

from app.labs.momentum.candles import Features

D = Decimal


@dataclass(frozen=True, slots=True)
class Rule:
    """When to buy, read off one closed candle. Every field is a condition;
    `None`/`False` means "no condition"."""

    #: `up` buys a strong green candle; `down` buys a strong RED one (the
    #: opposite bet: the move reverts).
    side: str = "up"
    min_ret: float = 0.0
    #: A ceiling on the move and on the volume: the QUIET arms. Run 1 found
    #: the loud candles were the worst of the lot (over 15%: -5.4% a trade).
    max_ret: float | None = None
    min_body_x: float | None = None
    min_vol_x: float | None = None
    max_vol_x: float | None = None
    #: Where in its range it closed (1.0 = at the high). For `down`, the
    #: mirror: closed at most this far UP its range.
    min_clv: float | None = None
    #: Buys per sell inside the candle. 1.01 = "more buys than sells".
    min_buy_ratio: float | None = None
    breakout: bool = False
    #: No impulse in the previous 24 bars: the first move after quiet.
    first: bool = False
    #: At least one impulse in the previous 12 bars: a second leg.
    second: bool = False
    #: Close above its 48-bar average AND up on the day.
    trend: bool = False
    #: Down more than 10% on the day: a bounce, not a trend.
    counter: bool = False
    #: At least half the universe up over the last hour.
    breadth: bool = False
    liq: tuple[float, float] | None = None
    #: Token age band, in days since its first pool.
    age: tuple[float, float] | None = None
    #: Buy only after the NEXT bar also closes green.
    confirm: bool = False
    #: Buy only if price comes back to the candle's midpoint within 3 bars.
    pullback: bool = False
    #: The rolling rule: DexScreener's own last-five-minutes window, judged
    #: on every sample instead of at a candle's close.
    rolling: bool = False

    def words(self) -> str:
        """Buy when — in the words the page prints."""
        if self.rolling:
            return (f"the last 5 minutes are up {self.min_ret:.0%}+ on "
                    f"{self.min_vol_x:g}x normal volume — bought mid-move, not at "
                    "a candle close")
        colour, way = ("red", "down") if self.side == "down" else ("green", "up")
        span = (f"{self.min_ret:.0%}+" if self.max_ret is None
                else f"{self.min_ret:.0%}-{self.max_ret:.0%}")
        parts = [f"a {colour} candle {way} {span}"]
        if self.min_body_x:
            parts.append(f"{self.min_body_x:g}x the token's usual candle")
        if self.min_vol_x:
            volume = (f"{self.min_vol_x:g}x" if self.max_vol_x is None
                      else f"{self.min_vol_x:g}-{self.max_vol_x:g}x")
            parts.append(f"on {volume} normal volume")
        if self.min_clv is not None:
            if self.side == "down":
                parts.append(f"closing in the bottom {1 - self.min_clv:.0%} of its range")
            elif self.min_clv >= 0.9:
                parts.append("closing at its high")
            else:
                parts.append(f"closing in the top {1 - self.min_clv:.0%} of its range")
        if self.min_buy_ratio:
            parts.append("more buys than sells" if self.min_buy_ratio <= 1.01
                         else f"{self.min_buy_ratio:g}x as many buys as sells")
        if self.breakout:
            parts.append("closing above the high of the previous 24 candles")
        if self.first:
            parts.append("the first such move in 24 candles")
        if self.second:
            parts.append("after another impulse in the last 12 candles")
        if self.trend:
            parts.append("above its 48-candle average and up on the day")
        if self.counter:
            parts.append("while down 10%+ on the day")
        if self.breadth:
            parts.append("with half the universe up over the hour")
        if self.liq:
            lo, hi = self.liq
            parts.append(f"pool {_usd(lo)}+" if hi >= 1e12 else f"pool {_usd(lo)}-{_usd(hi)}")
        if self.age:
            lo, hi = self.age
            parts.append(f"token {lo:g}+ days old" if hi >= 1e6
                         else f"token {lo:g}-{hi:g} days old")
        text = ", ".join(parts)
        if self.confirm:
            text += "; bought after the NEXT candle also closes green"
        if self.pullback:
            text += ("; bought only if price dips back to the candle's midpoint "
                     "within 3 candles")
        return text


def _usd(v: float) -> str:
    return f"${v / 1e6:g}M" if v >= 1e6 else f"${v / 1e3:g}k"


@dataclass(frozen=True, slots=True)
class Context:
    """What a rule may read beyond the candle: the token and the market."""

    liquidity: float
    age_days: float
    #: Share of the universe up over the last hour, at this tick.
    breadth: float | None


def fires(rule: Rule, f: Features, ctx: Context, *, prev: Features | None = None) -> bool:
    """Does this candle meet this rule? `prev` is the candle before, for
    confirmation entries (where `f` is the confirming candle)."""
    if rule.liq and not rule.liq[0] <= ctx.liquidity < rule.liq[1]:
        return False
    if rule.age and not rule.age[0] <= ctx.age_days < rule.age[1]:
        return False
    if rule.breadth and (ctx.breadth is None or ctx.breadth < 0.5):
        return False
    if rule.confirm:
        # The momentum candle is the one BEFORE; this one only has to confirm.
        return (prev is not None and f.green
                and fires(replace(rule, confirm=False), prev, ctx))
    sign = -1 if rule.side == "down" else 1
    if sign * f.ret < rule.min_ret:
        return False
    if rule.max_ret is not None and sign * f.ret >= rule.max_ret:
        return False
    if rule.min_body_x is not None and (f.body_x is None or f.body_x < rule.min_body_x):
        return False
    if rule.min_vol_x is not None and (f.vol_x is None or f.vol_x < rule.min_vol_x):
        return False
    if rule.max_vol_x is not None and (f.vol_x is None or f.vol_x >= rule.max_vol_x):
        return False
    if rule.min_clv is not None:
        clv = f.clv if sign > 0 else 1 - f.clv
        if clv < rule.min_clv:
            return False
    if rule.min_buy_ratio is not None:
        ratio = f.buy_ratio
        if ratio is None:
            return False
        if sign > 0 and ratio < rule.min_buy_ratio:
            return False
    if rule.breakout and not f.breakout:
        return False
    if rule.first and not f.quiet:
        return False
    if rule.second and f.recent_impulses < 1:
        return False
    if rule.trend and (f.sma is None or f.bar.close <= f.sma
                       or f.bar.change_h24 is None or f.bar.change_h24 <= 0):
        return False
    return not (rule.counter and (f.bar.change_h24 is None or f.bar.change_h24 > -10))


@dataclass(frozen=True, slots=True)
class Rolling:
    """One DexScreener sample's own five-minute window."""

    change_m5: float | None
    volume_m5: float | None
    volume_h24: float | None
    buys_m5: int | None
    sells_m5: int | None


def fires_rolling(rule: Rule, s: Rolling, ctx: Context) -> bool:
    if rule.liq and not rule.liq[0] <= ctx.liquidity < rule.liq[1]:
        return False
    if s.change_m5 is None or s.change_m5 / 100 < rule.min_ret:
        return False
    if not s.volume_m5 or not s.volume_h24:
        return False
    return s.volume_m5 / (s.volume_h24 / 288) >= (rule.min_vol_x or 0)


@dataclass(frozen=True, slots=True)
class Arm:
    """One strategy: a rule to buy and a rule to sell, frozen."""

    name: str
    family: str
    tf: str
    #: Time stop, in bars of `tf` (5m bars for the rolling rule).
    hold: int
    rule: Rule | None = None
    #: Stop at the signal candle's `low` or its `mid`point.
    stop: str | None = None
    #: Target at this many R above entry (R = entry - stop).
    target_r: Decimal | None = None
    tp: Decimal | None = None
    trail: Decimal | None = None
    #: Sell at the close of the first red candle after entry.
    red_exit: bool = False
    #: Sell half at +1R and move the rest's stop to the entry price.
    scale: bool = False
    #: Controls: `time` (random bar at the base rate), `same` (the base's
    #: moments, random tokens), `green` (random green bar at the base rate).
    control: str | None = None
    #: A control drawing from a SLICE of the universe instead of all of it.
    #: `down` = only coins down 10%+ on the day, so DOWN_60's control answers
    #: "is it the candle, or just the beaten-down coin?".
    pool: str | None = None
    #: The arm whose rate or moments a control matches.
    matches: str | None = None
    #: Judged against this arm.
    vs: str | None = None
    note: str = ""
    tags: tuple[str, ...] = field(default=())

    @property
    def is_control(self) -> bool:
        return self.control is not None

    @property
    def entry_words(self) -> str:
        if self.control == "time":
            where = (" of a token already down 10%+ on the day" if self.pool == "down"
                     else " of a random token")
            return (f"a random {self.tf} candle{where}, at the rate "
                    f"{self.matches} fires — CONTROL")
        if self.control == "same":
            return (f"at the moments {self.matches} buys, the same number of "
                    "random tokens — CONTROL")
        if self.control == "green":
            return (f"a random GREEN {self.tf} candle, at the rate {self.matches} "
                    "fires — CONTROL")
        return self.rule.words() if self.rule else ""

    @property
    def exit_words(self) -> str:
        bar = "5m" if self.tf == "tick" else self.tf
        clock = f"after {self.hold} x {bar} candles"
        parts = []
        if self.stop:
            where = "low" if self.stop == "low" else "midpoint"
            parts.append(f"price falls under the signal candle's {where}")
        if self.scale:
            parts.append("half sold at +1R, the rest at +3R or back at the entry")
        elif self.target_r:
            parts.append(f"+{self.target_r:g}R (R = entry minus the stop)")
        if self.tp:
            parts.append(f"+{float(self.tp) * 100:g}%")
        if self.trail:
            parts.append(f"{float(self.trail) * 100:g}% off the high since entry")
        if self.red_exit:
            parts.append("the first red candle closes")
        parts.append(clock)
        return parts[0] if len(parts) == 1 else "first of: " + "; ".join(parts)

    @property
    def bar_seconds(self) -> int:
        return {"5m": 300, "15m": 900, "1h": 3600, "tick": 300}[self.tf]


def coin(name: str, key: str) -> float:
    """A uniform draw in [0, 1) that depends on nothing but its inputs: the
    same on every tick, restart and replay. A control that changed its mind
    between ticks would be a different rule each time."""
    digest = hashlib.blake2b(f"{name}:{key}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") / 2**64


def bar_key(pair: str, start: datetime) -> str:
    return f"{pair}:{int(start.timestamp())}"


# --- the base rules --------------------------------------------------------------
#: THE momentum candle, on 5m bars. A strong green candle — big for the token
#: (3x its usual body), big in absolute terms (2%, well above the ~1% round
#: trip), on 3x normal volume, closing in the top 40% of its range.
#:
#: NOT "more buys than sells". It was in the first version and blocked every
#: real pump of the first live hours (2026-09-19): ANONCOIN +11.2% on 16x
#: volume with 2 buys and 30 sells, ROUTER +10.4% (6 / 19), EMBER +6.0%
#: (51 / 104), BP +3.9% on 41x volume (2 / 91). A couple of large buys move a
#: pool while many small trades go the other way, on every venue, so a COUNT
#: of trades says nothing about which side is bigger. `M5_BUYERS` still tests
#: the count on its own.
M5 = Rule(min_ret=0.02, min_body_x=3.0, min_vol_x=3.0, min_clv=0.6)
#: The same shape on slower bars, with the absolute floor scaled up: a 15m
#: bar is three 5m bars and a 1h bar twelve.
M15 = replace(M5, min_ret=0.03)
M1H = replace(M5, min_ret=0.05)
#: The impulse a PRIOR bar must have been to count as one (first/second leg).
IMPULSE_RET: dict[str, float] = {"5m": M5.min_ret, "15m": M15.min_ret, "1h": M1H.min_ret}

#: Holds, in 5m bars. Run 1 tested 30 minutes to 12 hours: nothing beyond an
#: hour or two helped, and the 6-hour hold is kept only for the snap-back.
HOUR, TWO_HOURS, SIX_HOURS = 12, 24, 72
#: Run 1's exit evidence, over 890 entries replayed against their real paths:
#: a stop made every cell worse (-7.6% on 1,644 stopped trades), a 3-5% take
#: profit was worse than none, 15%+ was better. So: one take profit, no stop.
TP15 = D("0.15")

#: Run 2's five entries. Every one is BASE with ONE thing changed.
BASE = M5
#: Down 10%+ on the day. Run 1's best cell: +4.9% a trade on 44 cheap-pool
#: trades, positive in both halves (+2.9 / +6.9).
DOWN = replace(M5, counter=True)
#: A pool over $1m. +0.77% a trade on 107 trades with the 15% take profit,
#: positive in both halves (+1.05 / +0.50).
DEEP = replace(M5, liq=(1_000_000.0, 1e12))
#: The quiet end of the rule: 2-5% on 3-10x volume. Run 1's loud candles were
#: its worst trades (over 15%: -5.4%; 200+ trades in the bar: -4.4%).
QUIET = replace(M5, max_ret=0.05, max_vol_x=10.0)
#: The opposite bet, carried over from DIP5: buy the RED candle.
SNAP = replace(M5, side="down", min_buy_ratio=None)

ARMS: tuple[Arm, ...] = (
    # ---- controls: they cannot have an edge -------------------------------------
    Arm("RND_60", "control", "5m", HOUR, control="time", matches="BASE_60",
        note="random candle, random token, at the rate BASE_60 fires"),
    Arm("RND_TP15", "control", "5m", TWO_HOURS, tp=TP15, control="time",
        matches="BASE_TP15", note="the same dice, sold at +15%: the exit on its own"),
    Arm("RND_DOWN", "control", "5m", HOUR, control="time", matches="DOWN_60",
        pool="down", note="random candle of a coin already down 10%+ on the day"),

    # ---- the reference: the momentum candle, priced honestly ---------------------
    Arm("BASE_60", "entry", "5m", HOUR, BASE, vs="RND_60",
        note="THE momentum candle, out after an hour"),
    Arm("BASE_TP15", "entry", "5m", TWO_HOURS, BASE, tp=TP15, vs="RND_TP15",
        note="the same entry, sold at +15% or after two hours"),

    # ---- is a beaten-down coin the place to buy strength? -----------------------
    Arm("DOWN_60", "down", "5m", HOUR, DOWN, vs="RND_DOWN",
        note="the candle, but only while the coin is down 10%+ on the day"),
    Arm("DOWN_TP15", "down", "5m", TWO_HOURS, DOWN, tp=TP15, vs="DOWN_60",
        note="the same, sold at +15% or after two hours"),

    # ---- does a deep pool carry the move? ---------------------------------------
    Arm("DEEP_60", "universe", "5m", HOUR, DEEP, vs="BASE_60",
        note="the candle in a pool over $1m"),
    Arm("DEEP_TP15", "universe", "5m", TWO_HOURS, DEEP, tp=TP15, vs="BASE_TP15",
        note="pool over $1m, sold at +15% or after two hours"),

    # ---- is the quiet candle the better one? ------------------------------------
    Arm("QUIET_60", "quiet", "5m", HOUR, QUIET, vs="BASE_60",
        note="the small move: 2-5% on 3-10x volume, nothing louder"),
    Arm("QUIET_TP15", "quiet", "5m", TWO_HOURS, QUIET, tp=TP15, vs="BASE_TP15",
        note="the same small move, sold at +15% or after two hours"),

    # ---- the opposite bet -------------------------------------------------------
    Arm("SNAP_60", "dip", "5m", HOUR, SNAP, vs="RND_60",
        note="buy the RED momentum candle: bet on the snap-back"),
    Arm("SNAP_6H", "dip", "5m", SIX_HOURS, SNAP, vs="SNAP_60",
        note="the same red candle, given six hours to come back"),
)

BY_NAME: dict[str, Arm] = {a.name: a for a in ARMS}
CONTROLS: tuple[Arm, ...] = tuple(a for a in ARMS if a.is_control)

assert len(ARMS) == 13, f"thirteen arms, not {len(ARMS)}"
assert len({a.name for a in ARMS}) == len(ARMS), "names are unique"
assert all(len(a.name) <= 32 for a in ARMS), "a name must fit the column"
assert all((a.rule is None) == a.is_control for a in ARMS), "controls have no rule"
assert all(a.vs in BY_NAME or a.is_control for a in ARMS), "every strategy has a yardstick"
assert all(a.matches in BY_NAME for a in CONTROLS), "a control matches a real strategy"
assert all(a.target_r is None or a.stop for a in ARMS), "an R target needs a stop"
assert all(a.stop is None for a in ARMS), "run 2 has no stops: run 1 priced them at -7.6%"
