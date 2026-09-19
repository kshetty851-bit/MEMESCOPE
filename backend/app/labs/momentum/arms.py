"""Fifty strategies on one universe, and five of them are dice.

## One factor at a time

Every strategy is the BASE strategy with ONE thing changed — a threshold, a
filter, a slice of the universe, the timeframe or the exit. So each one
answers a single question ("does a bigger candle help?", "does a stop at the
candle's low help?") against the base, instead of fifty rules racing each
other, where the leader is simply whichever got luckiest.

## The dice are the point

A leaderboard of fifty always has a leader. The controls buy the same
universe at random (`R5_TIME`), at the same moments as the base with random
tokens (`R5_SAME`), or any green candle at random (`R5_GREEN`) — same costs,
same exits, provably no edge. A strategy has shown something only when it
beats the control on its own timeframe by more than chance allows across
fifty comparisons.

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
    min_body_x: float | None = None
    min_vol_x: float | None = None
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
                    f"{self.min_vol_x:g}x normal volume with more buys than "
                    "sells — bought mid-move, not at a candle close")
        if self.side == "down":
            parts = [f"a red candle down {self.min_ret:.0%}+"]
        else:
            parts = [f"a green candle up {self.min_ret:.0%}+"]
        if self.min_body_x:
            parts.append(f"{self.min_body_x:g}x the token's usual candle")
        if self.min_vol_x:
            parts.append(f"on {self.min_vol_x:g}x normal volume")
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
    if rule.min_body_x is not None and (f.body_x is None or f.body_x < rule.min_body_x):
        return False
    if rule.min_vol_x is not None and (f.vol_x is None or f.vol_x < rule.min_vol_x):
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
    if s.volume_m5 / (s.volume_h24 / 288) < (rule.min_vol_x or 0):
        return False
    return (s.buys_m5 or 0) > (s.sells_m5 or 0)


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
            return (f"a random {self.tf} candle of a random token, at the rate "
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
#: trip), on 3x normal volume, closing in the top 40% of its range with more
#: buys than sells.
M5 = Rule(min_ret=0.02, min_body_x=3.0, min_vol_x=3.0, min_clv=0.6, min_buy_ratio=1.01)
#: The same shape on slower bars, with the absolute floor scaled up: a 15m
#: bar is three 5m bars and a 1h bar twelve.
M15 = replace(M5, min_ret=0.03)
M1H = replace(M5, min_ret=0.05)
#: The impulse a PRIOR bar must have been to count as one (first/second leg).
IMPULSE_RET: dict[str, float] = {"5m": M5.min_ret, "15m": M15.min_ret, "1h": M1H.min_ret}

TRADE_HOLD = 6  # bars: 30 minutes on 5m, 90 on 15m, six hours on 1h

ARMS: tuple[Arm, ...] = (
    # ---- controls: they cannot have an edge -------------------------------------
    Arm("R5_TIME", "control", "5m", TRADE_HOLD, control="time", matches="M5_BASE",
        note="random 5m candle, random token, base rate"),
    Arm("R5_SAME", "control", "5m", TRADE_HOLD, control="same", matches="M5_BASE",
        note="the base's moments, random tokens"),
    Arm("R5_GREEN", "control", "5m", TRADE_HOLD, control="green", matches="M5_BASE",
        note="random green 5m candle, base rate"),
    Arm("R15_TIME", "control", "15m", TRADE_HOLD, control="time", matches="M15_BASE",
        note="random 15m candle, 15m base rate"),
    Arm("R1H_TIME", "control", "1h", TRADE_HOLD, control="time", matches="M1H_BASE",
        note="random 1h candle, 1h base rate"),

    # ---- 5m: the base, then one entry condition changed each ----------------------
    Arm("M5_BASE", "entry", "5m", TRADE_HOLD, M5, vs="R5_TIME",
        note="THE momentum candle, out after 30 minutes"),
    Arm("M5_LOOSE", "entry", "5m", TRADE_HOLD,
        Rule(min_ret=0.01, min_body_x=2.0, min_vol_x=2.0, min_clv=0.5), vs="R5_TIME",
        note="weaker candles: 1%, 2x body, 2x volume"),
    Arm("M5_BIG", "entry", "5m", TRADE_HOLD, replace(M5, min_ret=0.04, min_body_x=5.0),
        vs="M5_BASE", note="bigger: 4%, 5x the usual body"),
    Arm("M5_HUGE", "entry", "5m", TRADE_HOLD, replace(M5, min_ret=0.08, min_body_x=5.0),
        vs="M5_BASE", note="8%+ in five minutes: continuation or exhaustion?"),
    Arm("M5_VOL6", "entry", "5m", TRADE_HOLD, replace(M5, min_vol_x=6.0),
        vs="M5_BASE", note="volume climax: 6x normal"),
    Arm("M5_NOVOL", "entry", "5m", TRADE_HOLD, replace(M5, min_vol_x=None),
        vs="M5_BASE", note="price only, volume ignored"),
    Arm("M5_TOPCLOSE", "entry", "5m", TRADE_HOLD, replace(M5, min_clv=0.9),
        vs="M5_BASE", note="closes at its high: no upper wick"),
    Arm("M5_BUYERS", "entry", "5m", TRADE_HOLD, replace(M5, min_buy_ratio=2.0),
        vs="M5_BASE", note="twice as many buys as sells"),
    Arm("M5_BREAKOUT", "entry", "5m", TRADE_HOLD, replace(M5, breakout=True),
        vs="M5_BASE", note="and closes above the 2-hour high"),
    Arm("M5_FIRST", "entry", "5m", TRADE_HOLD, replace(M5, first=True),
        vs="M5_BASE", note="first impulse after two quiet hours"),
    Arm("M5_SECOND", "entry", "5m", TRADE_HOLD, replace(M5, second=True),
        vs="M5_BASE", note="second leg: another impulse in the last hour"),
    Arm("M5_TREND", "entry", "5m", TRADE_HOLD, replace(M5, trend=True),
        vs="M5_BASE", note="with the trend: above the 4h average, up on the day"),
    Arm("M5_COUNTER", "entry", "5m", TRADE_HOLD, replace(M5, counter=True),
        vs="M5_BASE", note="against the day: down 10%+ on 24h"),
    Arm("M5_BREADTH", "entry", "5m", TRADE_HOLD, replace(M5, breadth=True),
        vs="M5_BASE", note="only when most of the market is up"),
    Arm("M5_CONFIRM", "entry", "5m", TRADE_HOLD, replace(M5, confirm=True),
        vs="M5_BASE", note="wait for the next candle to close green too"),
    Arm("M5_PULLBACK", "entry", "5m", TRADE_HOLD, replace(M5, pullback=True),
        vs="M5_BASE", note="limit buy at the candle's midpoint, 15 min to fill"),

    # ---- the universe, sliced -------------------------------------------------------
    Arm("M5_LIQ_S", "universe", "5m", TRADE_HOLD, replace(M5, liq=(5e4, 2.5e5)),
        vs="M5_BASE", note="small pools: $50k-$250k"),
    Arm("M5_LIQ_M", "universe", "5m", TRADE_HOLD, replace(M5, liq=(2.5e5, 1e6)),
        vs="M5_BASE", note="mid pools: $250k-$1M"),
    Arm("M5_LIQ_L", "universe", "5m", TRADE_HOLD, replace(M5, liq=(1e6, 1e15)),
        vs="M5_BASE", note="deep pools: $1M+"),
    Arm("M5_AGE_1M", "universe", "5m", TRADE_HOLD, replace(M5, age=(7, 30)),
        vs="M5_BASE", note="young: 7-30 days old"),
    Arm("M5_AGE_6M", "universe", "5m", TRADE_HOLD, replace(M5, age=(30, 180)),
        vs="M5_BASE", note="1-6 months old"),
    Arm("M5_AGE_OLD", "universe", "5m", TRADE_HOLD, replace(M5, age=(180, 1e9)),
        vs="M5_BASE", note="6 months and older"),

    # ---- the base entry, one exit changed each ----------------------------------------
    Arm("X5_HOLD3", "exit", "5m", 3, M5, vs="M5_BASE", note="out after 15 minutes"),
    Arm("X5_HOLD12", "exit", "5m", 12, M5, vs="M5_BASE", note="out after 1 hour"),
    Arm("X5_HOLD48", "exit", "5m", 48, M5, vs="M5_BASE", note="out after 4 hours"),
    Arm("X5_LOW_1R", "exit", "5m", 24, M5, stop="low", target_r=D(1),
        vs="M5_BASE", note="stop at the candle's low, target 1R"),
    Arm("X5_LOW_2R", "exit", "5m", 24, M5, stop="low", target_r=D(2),
        vs="M5_BASE", note="stop at the candle's low, target 2R"),
    Arm("X5_LOW_3R", "exit", "5m", 48, M5, stop="low", target_r=D(3),
        vs="M5_BASE", note="stop at the candle's low, target 3R"),
    Arm("X5_MID_2R", "exit", "5m", 24, M5, stop="mid", target_r=D(2),
        vs="M5_BASE", note="tight stop at the candle's midpoint, target 2R"),
    Arm("X5_TRAIL5", "exit", "5m", 48, M5, trail=D("0.05"),
        vs="M5_BASE", note="5% trailing stop"),
    Arm("X5_TRAIL10", "exit", "5m", 96, M5, trail=D("0.10"),
        vs="M5_BASE", note="10% trailing stop, up to 8 hours"),
    Arm("X5_TP5", "exit", "5m", 24, M5, tp=D("0.05"),
        vs="M5_BASE", note="take +5%"),
    Arm("X5_TP10", "exit", "5m", 48, M5, tp=D("0.10"),
        vs="M5_BASE", note="take +10%"),
    Arm("X5_RED", "exit", "5m", 24, M5, red_exit=True,
        vs="M5_BASE", note="ride it until a candle closes red"),
    Arm("X5_SCALE", "exit", "5m", 48, M5, stop="low", target_r=D(3), scale=True,
        vs="M5_BASE", note="split exit: half at +1R, rest at +3R or breakeven"),

    # ---- slower candles -----------------------------------------------------------------
    Arm("M15_BASE", "m15", "15m", TRADE_HOLD, M15, vs="R15_TIME",
        note="the momentum candle on 15m bars, out after 90 minutes"),
    Arm("M15_BREAKOUT", "m15", "15m", TRADE_HOLD, replace(M15, breakout=True),
        vs="M15_BASE", note="and above the 6-hour high"),
    Arm("M15_LOW_2R", "m15", "15m", 24, M15, stop="low", target_r=D(2),
        vs="M15_BASE", note="stop at the candle's low, target 2R"),
    Arm("M15_TRAIL10", "m15", "15m", 48, M15, trail=D("0.10"),
        vs="M15_BASE", note="10% trailing stop, up to 12 hours"),
    Arm("M1H_BASE", "m1h", "1h", TRADE_HOLD, M1H, vs="R1H_TIME",
        note="the momentum candle on 1h bars, out after 6 hours"),
    Arm("M1H_BREAKOUT", "m1h", "1h", TRADE_HOLD, replace(M1H, breakout=True),
        vs="M1H_BASE", note="and above the 24-hour high"),
    Arm("M1H_TRAIL15", "m1h", "1h", 48, M1H, trail=D("0.15"),
        vs="M1H_BASE", note="15% trailing stop, up to 2 days"),

    # ---- caught mid-candle ------------------------------------------------------------------
    Arm("CATCH_4", "catch", "tick", TRADE_HOLD,
        Rule(min_ret=0.04, min_vol_x=3.0, rolling=True), vs="R5_TIME",
        note="up 4%+ in the last 5 minutes, bought on the spot"),
    Arm("CATCH_8", "catch", "tick", TRADE_HOLD,
        Rule(min_ret=0.08, min_vol_x=3.0, rolling=True), vs="CATCH_4",
        note="up 8%+ in the last 5 minutes, bought on the spot"),

    # ---- the opposite bet -------------------------------------------------------
    Arm("DIP5", "dip", "5m", TRADE_HOLD,
        replace(M5, side="down", min_buy_ratio=None), vs="R5_TIME",
        note="buy the RED momentum candle: bet on the snap-back"),
)

BY_NAME: dict[str, Arm] = {a.name: a for a in ARMS}
CONTROLS: tuple[Arm, ...] = tuple(a for a in ARMS if a.is_control)

assert len(ARMS) == 50, f"fifty strategies, not {len(ARMS)}"
assert len({a.name for a in ARMS}) == len(ARMS), "names are unique"
assert all(len(a.name) <= 32 for a in ARMS), "a name must fit the column"
assert all((a.rule is None) == a.is_control for a in ARMS), "controls have no rule"
assert all(a.vs in BY_NAME or a.is_control for a in ARMS), "every strategy has a yardstick"
assert all(a.matches in BY_NAME for a in CONTROLS), "a control matches a real strategy"
assert all(a.target_r is None or a.stop for a in ARMS), "an R target needs a stop"
assert {a.tf for a in ARMS} == {"5m", "15m", "1h", "tick"}
