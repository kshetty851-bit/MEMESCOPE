"""Fifty paper strategies on the same graduations, and eight of them are noise.

## Why eight of them are noise on purpose

Run fifty strategies for a day and one of them leads. That is arithmetic, not
evidence — fifty coin-flippers also produce a leader, and the more arms there
are the better that leader looks. The only way a leaderboard means anything is
if it contains arms that CANNOT have an edge, so the question becomes "did the
leader beat what chance alone produced?" rather than "who is on top?".

So eight arms (`R1`-`R8`) decide by hashing the mint. They see the same
graduations, pay the same costs, and are indistinguishable from a real arm
except that their rule is provably meaningless. `control_band` reports the best
of them, and the page refuses to call a winner that has not cleared it.

## Everything else is shared

Every arm uses the same fills, the same cost model, the same `net_return`, the
same clock, in the same tick. They differ in exactly two places: which
graduations they accept (`entry`) and when they leave (`hold`, `tp`, `trail`).
A difference anywhere else would mean the tournament measures that instead.

## One tick, six queries

Fifty arms times ten slots is five hundred positions to mark. Doing that
per-arm is fifty times the work for the same answer, so the tick reads every
open position once, prices every distinct mint once, and writes once. The cost
of the tournament is therefore flat in the number of arms, which is what makes
fifty of them affordable at a fifteen-second tick.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from typing import Any, NamedTuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import settings
from app.core.logging import get_logger
from app.labs.graduation import config
from app.labs.graduation import live_decisions, live_spec, moneyblock
from app.labs.graduation.backtest import (
    HardStop,
    ExitPolicy,
    ExitState,
    TakeProfit,
    Tick,
    TrailingStop,
    amm_buy,
    amm_impact,
    amm_sell,
)
from app.labs.graduation.held_watch import Held
from app.labs.graduation.models import (
    SOURCE_HELD_WS,
    GradCurveSample,
    GradEarlyOpen,
    GradMigration,
    GradOperator,
    GradPaperPosition,
    GradPostgradSample,
    GradToken,
)
from app.labs.graduation.paper import _P, _Q, _rate, costs, in_hour_window
from app.security.liquidity import derive_or_none

logger = get_logger(__name__)


@lru_cache(maxsize=8192)
def graduation_pool(mint: str) -> str | None:
    """The pool pump.fun's migration creates for this mint: derived, not asked.

    The only thing that makes a trade a GRADUATION trade. The migration feed
    also announces `raydium-cpmm` events for tokens that never had a pump.fun
    curve — JUP, PENGU, tokenized stocks — and DexScreener's deepest pool for a
    real graduate is sometimes another pool entirely. On 2026-09-16, 357 of the
    last 12 hours' graduations were priced on exactly this address, and none of
    the 15 B3 trades that were not graduations was.
    """
    derived = derive_or_none(mint, pumpfun_program=settings.PUMPFUN_PROGRAM_ID)
    return derived[0] if derived else None


class Mark(NamedTuple):
    """A price for a held token, with the moment it was read and by whom."""

    price: Decimal
    depth: Decimal | None
    ts: datetime | None = None
    source: str | None = None


def seen_at(mark: Mark) -> datetime | None:
    """The market moment a mark describes. A socket read describes itself; a
    DexScreener row quotes a trade `FEED_LAG_S` older than its fetch."""
    if mark.ts is None:
        return None
    if mark.source == SOURCE_HELD_WS:
        return mark.ts
    return mark.ts - timedelta(seconds=config.FEED_LAG_S)


def exit_mark(marks: Iterable[Mark], due: datetime) -> Mark | None:
    """The first mark that describes the market AT OR AFTER a timed exit.

    A timed exit used to take the newest mark there was, however old. On
    2026-09-14 FAIR's pool was drained at 19:14:50, four seconds after its exit
    was due; the book closed at 19:15:00 on a price from 19:13, and a -100%
    trade was booked at -0.1%. Five B3 trades did that. Nothing that describes
    the market before the exit was due can price it.
    """
    after = [(seen, m) for m in marks
             if (seen := seen_at(m)) is not None and seen >= due]
    return min(after, key=lambda pair: pair[0])[1] if after else None


def valued(mark: Mark, open_quote: Decimal,
           liq_open: Decimal | None) -> tuple[Decimal, str | None]:
    """The price a mark can actually be sold at, and why it differs, if it does.

    A pool drained below `EXIT_COLLAPSE_FRACTION` of its entry depth has no
    price anyone can sell at. Its quote is the virtual reserve over a handful of
    tokens — DexScreener printed 1.747 SOL for a token bought at 0.0005 — so it
    is priced by the constant product instead: price moves with the square of
    the quote side, from the price paid.
    """
    if (mark.depth is not None and liq_open is not None and liq_open > 0
            and mark.depth < liq_open * config.EXIT_COLLAPSE_FRACTION):
        ratio = mark.depth / liq_open
        # Never below the price column's last place: a close that rounds to
        # zero is voided as unrepresentable, and a -100% trade would vanish
        # from the book it belongs to.
        return max(open_quote * ratio * ratio, _P), "pool_collapsed"
    return mark.price, None


@dataclass(frozen=True, slots=True)
class Arm:
    """One strategy. Frozen: the tournament is only evidence if no arm changes
    while it runs."""

    name: str
    entry: str
    hold: int
    tp: Decimal | None = None
    trail: Decimal | None = None
    #: A hard stop measured from the ENTRY price. Kept separate from `trail`,
    #: which measures from the running peak — a trailing stop on a token that
    #: only ever fell has never armed, and would not have saved anything.
    stop: Decimal | None = None
    #: Leave when the pool has lost this share of the SOL it held at entry.
    #: Measured on depth, not price: a drain empties the quote side, and the
    #: socket reads the quote side within a second of each swap.
    drain: Decimal | None = None
    #: What `hold` counts from: the entry, or the graduation itself. The pools
    #: B3 buys are drained five to seven minutes after graduating, whatever
    #: time the book happened to get in.
    clock: str = "entry"
    #: Runs, but is NOT a tournament entry and must not appear on its board.
    #:
    #: The rug-signal A/B is a separate experiment with its own pre-registered
    #: judge date. It competes with nothing here — B3 asks which pool depth to
    #: buy, the A/B asks whether a symbol predicts a rug — so ranking it beside
    #: the arms invites exactly the request that prompted this: "delete the
    #: negative ones". Ending it three weeks early would destroy the only thing
    #: a pre-registered experiment has, which is that nobody chose when to stop.
    ab_experiment: bool = False
    note: str = ""

    @property
    def is_control(self) -> bool:
        """The baseline an arm has to beat: buying every graduation above the
        floor, with no selection at all.

        Generation 2 replaced the coin-flip controls with this. A dice roll is
        a perfectly sharp null and it is executable — hash the mint, buy under
        25 — but it is not a strategy anyone would fund, and this lab exists to
        find something to fund. "No selection" is the honest null for a
        selection rule anyway: every grid arm is a SUBSET of the floor arm's
        population, so beating it is exactly the claim each one makes.

        The protection a dice roll gave against a best-of-N leader is not lost
        with it — `config.required_pf` prices that directly, from the trade
        count, and it is a harder bar than any single control.
        """
        # A stop makes it a strategy, not a baseline. The baseline is "buy
        # every graduation above the floor and hold to the clock" — adding a
        # rule to that is precisely the thing being tested against it.
        return (self.entry == "floor" and self.stop is None
                and self.drain is None and self.clock == "entry")

    @property
    def entry_rule(self) -> str:
        """Buy when — in the words the page prints."""
        return ENTRY_RULES.get(self.entry, self.entry)

    @property
    def exit_rule(self) -> str:
        """Sell when. The hold is always present because the price series ends
        an hour after the open: past it there is no mark and no exit price, so
        every arm needs a backstop whatever else it carries."""
        parts = []
        if self.drain:
            parts.append(f"the pool loses {self.drain * 100:.0f}% of its SOL")
        if self.stop:
            parts.append(f"{self.stop * 100:.0f}% below the price paid")
        if self.trail:
            parts.append(f"{self.trail * 100:.0f}% off the running peak")
        if self.tp:
            parts.append(f"{self.tp:g}x the price paid")
        parts.append(f"{self.hold} minute{'s' if self.hold != 1 else ''}"
                     + (" after graduating" if self.clock == "graduation" else ""))
        if len(parts) == 1:
            return f"at {parts[0]}"
        return "whichever comes first: " + ", or ".join(parts)

    def policy(self) -> ExitPolicy:
        rules: list[Any] = []
        # LOSS FIRST. A stop and a target can both be true on one mark, and
        # which filled is not knowable from the data — taking the loss is the
        # conservative reading.
        if self.stop:
            rules.append(HardStop(self.stop))
        if self.trail:
            rules.append(TrailingStop(self.trail))
        if self.tp:
            rules.append(TakeProfit(self.tp - 1))
        return ExitPolicy(tuple(rules))


def _curve_depth_usd(v_quote_reserves: Decimal,
                     rate: Decimal | None) -> Decimal | None:
    """The bonding curve's depth, in the units `amm_buy` expects.

    `v_quote_reserves` is the QUOTE SIDE alone. DexScreener's `liquidity_usd`
    — what every other arm passes — is the pool TOTAL, and the impact maths
    halves it to recover the quote side. Passing the curve's reserve straight
    through would therefore halve the depth and double every impact figure.
    """
    if rate is None or v_quote_reserves <= 0:
        return None
    return (v_quote_reserves * rate * 2).quantize(Decimal("0.01"))


def _coin(arm: str, mint: str, pct: int) -> bool:
    """A decision that depends on nothing. Hashed rather than `random` so it is
    the same on every tick, every restart and every replay — a control that
    changed its mind between ticks would be a different rule each time."""
    digest = hashlib.blake2b(f"{arm}:{mint}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") % 100 < pct


#: The liquidity bands, in dollars of pool at the pool open.
#:
#: B2 ($116k-$198k) was here and is RETIRED, 2026-09-15. It was the band the
#: historical slice liked best — 1.1% tail, +1.15% per token, 91% winners —
#: and forward it was the worst thing on the board. All five holds negative on
#: 90 trades each:
#:
#:     B2_116k_3m  $87.15    B2_116k_4m  $86.15    B2_116k_5m  $73.50
#:     B2_116k_2m  $71.27    B2_116k_6m  $52.27
#:
#: Five holds agreeing is a refutation of the band, not five unlucky arms. It
#: is also the cleanest in-sample/out-of-sample reversal this lab has produced,
#: and the reason a band is now chosen by forward evidence or not at all.
#:
#: THE GAP IS DELIBERATE. $116k-$198k now has no band arm. It is not unwatched
#: — every FLOOR arm still buys it, so the population is still measured; it
#: simply has no filter claiming to improve on that.
#:
#: CONTIGUOUS AND ORDERED, which is the whole design. Generation 1 ran fifty
#: independent filters and the winner had to clear the best-of-fifty noise
#: ceiling — profit factor 4.79 — which nothing reached in seventeen hours.
#: Fourteen bands were tried first and starved: each took only 25 trades a day
#: of a 320-token flow, and pooled over all three holds they produced scatter,
#: not a shape — +2.48%, +1.98%, -4.40%, +0.35%, +2.84% across neighbours. The
#: same data pooled by HOLD separated cleanly (see the arm list below), so the
#: resolution was being spent on the factor that does not move and starved from
#: the one that does. Three wide bands keep the question alive at four times
#: the sample.
#:
#: The edges come from measurement, per TOKEN (1,484 tokens, 7 days), not from
#: round numbers. Share of tokens losing more than 25% in the first five
#: minutes, by pool at the open:
#:
#:     under $17k   57.4%      $75k-$116k   12.0%
#:     $17k-$75k    32.8%      $116k-$198k   1.6%   <- 94.5% of tokens WIN here
#:                             over $198k    3.1%
#:
#: So the grid starts at $75,000 — below it a third to a half of tokens are
#: destroyed and no exit rule reaches them — and it is finest between $116k
#: and $198k, where generation 1's only real signal was hiding inside a
#: `>= $100k` floor that also swept in the worse band above.
#: Curve progress at which the pre-graduation arm buys.
#:
#: Ninety percent, and it is observable — which it was NOT when this was last
#: looked at (217 of 218 completed curves had never been seen incomplete).
#: Measured 2026-09-14 over three days: of 2,414 graduations, 51% were seen
#: still climbing and 419 (17%) were seen at >=90% while incomplete. Of 556
#: tokens that reached 90%, 419 — 75% — went on to graduate.
#:
#: Lead time from the first >=90% sighting to graduation is a median 73s, with
#: a quarter giving only 16s. That is the honest ceiling on this arm: it can
#: only trade the ones it sees in time.
#:
#: And it is fillable. The curve IS a constant-product pool, so a $100 buy
#: costs S/Q of impact against the quote reserve: a median 97.7 SOL (~$9,905)
#: at >=90%, so 1.01% — in line with the AMM arms. The bottom decile holds
#: $184 and is refused by the same 10% impact cap.
CURVE_ENTRY_PCT = Decimal("90")

LIQ_BANDS: tuple[tuple[str, int, int], ...] = (
    ("B1",  75_000,   116_000),
    ("B3", 198_000, 1_000_000_000),
)
BAND_BY_KEY: dict[str, tuple[int, int]] = {
    f"liq_{k}": (lo, hi) for k, lo, hi in LIQ_BANDS}


#: What each entry key MEANS, in the words the page prints.
#:
#: The fast arms' entries: bought in `_fill_fast`, never from the pool-open query.
FAST_ENTRIES = frozenset({"fast75", "fast75_trust"})

#: Kept beside `accepts` rather than in the frontend so the description cannot
#: drift from the rule it describes — `test_every_entry_filter_is_described`
#: fails if a filter gains a branch and loses its sentence, or vice versa.
ENTRY_RULES: dict[str, str] = {
    **{f"liq_{k}": f"the pool held ${lo:,} to ${hi:,} at the open"
       for k, lo, hi in LIQ_BANDS[:-1]},
    f"liq_{LIQ_BANDS[-1][0]}": f"the pool held over ${LIQ_BANDS[-1][1]:,} at the open",
    "curve": f"the token is still ON the bonding curve, at or past "
             f"{CURVE_ENTRY_PCT:g}% of the way to graduating — bought before "
             f"it migrates, not after",
    "floor": f"BASELINE — every graduation with a pool at or above "
             f"${LIQ_BANDS[0][1]:,}, no band selection",
    "all": "every graduation, no filter",
    "sym": "the token's symbol had been used by at least one earlier token",
    "sym3": "the symbol had been used by at least three earlier tokens",
    "newsym": "the symbol had never been seen before (the rug side of the split)",
    "night": "the pool opened between 18:00 and 06:00 UTC",
    "day": "the pool opened between 06:00 and 18:00 UTC",
    "sym_night": "symbol used before AND the pool opened 18:00-06:00 UTC",
    "band": "the pool held between $95,000 and $222,000 at the open — a band, "
            "not a floor, because tail risk rises again above it",
    "deep": "the pool held at least $100,000 at the open",
    "shallow": "the pool held under $30,000 at the open",
    "nosell": "no sells had printed in the first five minutes of flow",
    "hassell": "at least one sell had already printed",
    "bigcap": "market cap at the open was at least $1,000,000",
    "smallcap": "market cap at the open was under $200,000",
    "sym_deep": "symbol used before AND the pool held at least $100,000",
    "sym_nosell": "symbol used before AND no sells had printed",
    "deep500_flow": "the pool held at least $500,000 at the open AND more buys "
                    "than sells had printed in its first five minutes",
    "early_B3": f"the pool's OWN reserves showed over ${LIQ_BANDS[-1][1]:,} within "
                f"{config.EARLY_WINDOW_S}s of graduating — bought the moment that "
                f"was visible, not when DexScreener first listed the pool",
    "fast75": f"the pool's OWN reserves showed over ${LIQ_BANDS[0][1]:,} between "
              f"{config.FAST_MIN_AGE_S}s and {config.FAST_MAX_AGE_S}s after graduating, "
              f"read on-chain every tick — bought then, not when DexScreener listed "
              f"the pool (a median 50s for the real wallet)",
    "fast75_trust": f"as fast75, AND its operator — every wallet holding 1%+ at entry and "
                    f"whoever funded them — had {config.OPERATOR_TRUST_MIN_COINS}+ earlier "
                    f"graduations here and none of them rugged (-50% inside five minutes)",
    "rand25": "a hash of the token address, taking a quarter of them — CONTROL",
    "rand50": "a hash of the token address, taking half of them — CONTROL",
    "rand75": "a hash of the token address, taking three quarters — CONTROL",
}

#: Candidate features, measured at the pool open. Every one was chosen before
#: the tournament opened a position; none is tuned to a result.
def accepts(arm: Arm, *, mint: str, open_at: datetime, liquidity: Decimal | None,
            fdv: Decimal | None, sells: int | None, reuse: int | None,
            buys: int | None = None) -> bool:
    e = arm.entry
    band = BAND_BY_KEY.get(e)
    if band is not None:
        lo, hi = band
        return liquidity is not None and lo <= liquidity < hi
    if e == "curve":
        # The selection is in the SOURCE, not here: only tokens sitting on an
        # incomplete curve at or past CURVE_ENTRY_PCT ever reach this arm, and
        # they arrive through `_curve_candidates`, not the pool-open query.
        # Nothing further to filter, so nothing is filtered.
        return True
    if e == "early_B3":
        # Never from the pool-open query. This arm's entries arrive through
        # `_fill_early`, priced off the pool's own reserves before DexScreener
        # has listed it; buying here as well would add tokens the early watch
        # never saw, at DexScreener's later price — B3 again, under a new name.
        return False
    if e in FAST_ENTRIES:
        # Never from the pool-open query either: these arms read the pool
        # themselves in `_fill_fast`, seconds after the migration.
        return False
    if e == "floor":
        # The baseline: every graduation the grid is allowed to touch, with no
        # band selection. Same floor, same universe — so the only difference
        # between this and a grid arm is the band, which is the thing on trial.
        return liquidity is not None and liquidity >= LIQ_BANDS[0][1]
    if e == "deep500_flow":
        # Deep pool AND net buying. Replayed over 2,205 recorded graduations
        # this pair admitted 174 tokens, none of which fell more than 80%
        # inside five minutes, at a gross move of +1.208% a trade — the only
        # rule measured that clears the ~0.97% toll with room. It is here to
        # be tested FORWARD: backwards it made +$47 over its first 87 trades
        # and -$5 over its last 87, which is what a coin looks like.
        if liquidity is None or liquidity < 500_000:
            return False
        return (buys or 0) > (sells or 0)
    if e == "all":
        return True
    if e == "sym":
        return (reuse or 0) >= 1
    if e == "night":
        return in_hour_window(open_at, 18, 6)
    if e == "day":
        return not in_hour_window(open_at, 18, 6)
    if e == "sym_night":
        return (reuse or 0) >= 1 and in_hour_window(open_at, 18, 6)
    if e == "sym3":
        return (reuse or 0) >= 3
    if e == "newsym":
        return (reuse or 0) == 0
    if e == "band":
        # A BAND, not a floor. Measured per TOKEN (437 of them, because fifty
        # arms trade the same graduations and a per-trade count multiplies each
        # one ~25 times): tail risk falls from 36.8% of tokens below $17k to
        # 1.1% between $116k and $198k, then RETURNS to 5.6% above $213k. A
        # `>= $100k` floor spans the good band and the bad tail above it, which
        # is why `deep` reads +0.28% where the band reads +1.15%.
        #
        # In-sample. This arm exists to test it forward, not to be believed.
        return liquidity is not None and 95_000 <= liquidity <= 222_000
    if e == "deep":
        return liquidity is not None and liquidity >= 100_000
    if e == "shallow":
        return liquidity is not None and liquidity < 30_000
    if e == "nosell":
        return sells is not None and sells == 0
    if e == "hassell":
        return sells is not None and sells > 0
    if e == "bigcap":
        return fdv is not None and fdv >= 1_000_000
    if e == "smallcap":
        return fdv is not None and 0 < fdv < 200_000
    if e == "sym_deep":
        return (reuse or 0) >= 1 and liquidity is not None and liquidity >= 100_000
    if e == "sym_nosell":
        return (reuse or 0) >= 1 and sells is not None and sells == 0
    if e.startswith("rand"):
        return _coin(arm.name, mint, int(e[4:]))
    raise ValueError(f"unknown entry filter {e!r}")


D = Decimal
#: The fifty. Holds are 2, 3 and 5 minutes — the ONE-minute arms are gone.
#:
#: Measured on 722 tokens a $100 order could actually fill (the other 24% of
#: graduations are pools of $8-$50 that no order can touch, and their 4x
#: moves are prices nobody could have got):
#:
#:     hold    mean     median   wipeouts   trades >+50%
#:       1m   -1.69%   -0.58%      3.6%        1.7%
#:       3m   -1.08%   +0.57%      7.5%        4.2%
#:       5m   -1.41%   +1.52%     11.1%        5.7%
#:      15m  -14.50%   +1.60%     25.6%        3.7%
#:
#: Five minutes has the best median AND the most big winners; one minute is
#: worst on both and was only ever winning on wipeout rate. Fifteen is not
#: the answer either — it catches the peaks (343 of 722 tokens rise more
#: than 10%, and the median one peaks at FOURTEEN minutes) and pays for them
#: with a wipeout rate that triples. The extra ten minutes buys rugs, not
#: rallies: it produces FEWER trades above +50% than five minutes does.
#:
#: So the exit stays short and the 1m slots go to 5m. No reset: new arms
#: start at zero and the 2m and 3m arms keep their record.
#: Generation 2, opened 2026-09-13. Fifty arms: a 10 x 4 grid plus ten
#: controls.
#:
#: WHAT GENERATION 1 GOT WRONG. Fifty-one arms ran for seventeen hours and not
#: one beat the `all` arm at its own hold (0 of 47 cleared z>2, where chance
#: alone gives 1-2). The leader was a coin flip. Three things were wrong:
#:
#:  1. Thirty-nine of forty-two filters tested WHICH token to buy — symbol
#:     reuse, hour of day, market cap, seller presence. Entry selection was
#:     never the problem: 71% of trades already win, and the median token move
#:     is POSITIVE (+0.94% at 2m, +3.02% at 5m). The mean is negative only
#:     because of a left tail averaging -61.6%.
#:  2. That tail cannot be exited. Of 1,578 trades below -25%, just 33 (2%)
#:     ever passed through the -20%..-40% zone; 98% skip it between two
#:     samples. So the only defence is entering tokens that do not have one,
#:     and pool depth is the single measured property that separates them.
#:  3. Fifty independent arms set the bar at best-of-fifty noise (PF 4.79).
#:     Ordered bands replace "who won" with "what shape", which resolves far
#:     sooner.
#:
#: WHAT WAS TESTED AND DROPPED BEFORE SPENDING AN ARM ON IT:
#:
#:  - Longer holds. Inside the band, mean falls and the tail grows with every
#:    extra minute (5m +3.33% tail 1.6%; 30m -6.48% tail 14.6%). 5m stands.
#:  - Take-profits and trailing stops. Inside the band the average PEAK in
#:    five minutes is +4.33% and the five-minute mark already captures
#:    +3.33% of it. Only 3.8% of tokens ever touch +10% and 1.6% ever touch
#:    -10%. The move is smooth and small; an exit rule has nothing to catch.
#:  - FDV / liquidity, an unbacked-float proxy. Inside the band its terciles
#:    return 3.31%, 3.85%, 2.10% on an IDENTICAL 1.7% tail. No separation.
#:
#: So two factors survived and the grid tests exactly those: WHERE the pool
#: sits, and HOW LONG you hold. Sub-five-minute holds are in because nobody
#: has ever looked at them inside a band.
ARMS: tuple[Arm, ...] = (
    # DEEP POOLS ONLY, 2026-09-15. Everything else retired on request.
    #
    # B3 is the one family that never reversed. It was positive at every check
    # through a day in which every other arm wiped, it survived the slot change
    # from ten to one that killed the rest, and its worst trade is -20% to -28%
    # where everything else saw -90% or worse. Deep pools do not rug.
    #
    # WHAT THIS COSTS, recorded because it is not recoverable by looking at the
    # board later:
    #
    #  - THERE IS NO BASELINE. Every band arm was a SUBSET of FLOOR's
    #    population, so "the band beats no selection" was a question with an
    #    answer. With FLOOR gone, a profitable B3 cannot be told apart from a
    #    rising market. The verdict says so rather than implying a comparison
    #    it can no longer make.
    #  - The pre-registered rug-signal A/B (F01_all_2m against F14_symnight_2m,
    #    opened 2026-09-13, judge date 10 October) ends three weeks early. Its
    #    finding — a never-seen symbol rugs 18% against 3% — stays unconfirmed.
    #
    # Both are one commit from coming back; their trade history is untouched.
    # THE BASELINE, restored 2026-09-15. Without one the board has been saying
    # so itself for days: a profitable arm cannot be told apart from a market
    # that simply drifted up over the same tokens, because every arm here is a
    # SUBSET of this one's population. Beating it is exactly the claim each
    # selection rule makes, so until it runs, none of them has been tested.
    #
    # A NEW NAME on purpose. `FLOOR_5m` still holds 475 closed trades from the
    # generation that was retired; reusing the name would splice a fresh
    # baseline onto a wiped book and the wallet would start from that history.
    Arm("BASE_75k_5m", "floor", 5,
        note="BASELINE — every graduation over $75k, no selection, out at 5m"),
    # The one rule in 132 replayed over the full record that clears the toll
    # with room: 174 tokens, zero falling >80% inside five minutes, +1.208%
    # gross a trade. It failed the backward split (+$47 then -$5), which is
    # why it is deployed rather than believed — forward, on tokens it has
    # never seen, is the only test that has not already been failed.
    Arm("B5_500k_flow_5m", "deep500_flow", 5,
        note="pool over $500k AND net buying, out at 5m"),
    # B3_198k_3m RETIRED 2026-09-16 at -$58.90 on 213 trades. Three minutes was
    # the worst hold in every band the lab has run, and what it was there to
    # show — that leaving earlier is worse — is still shown by 4m against 5m.
    Arm("B3_198k_4m", "liq_B3", 4, note="pool over $198k, out at 4m"),
    Arm("B3_198k_5m", "liq_B3", 5, note="pool over $198k, out at 5m"),
    Arm("B3_198k_5m_SL", "liq_B3", 5, stop=Decimal("0.10"),
        note="pool over $198k, 10% stop, out at 5m"),
    # THE RUG ARMS, 2026-09-16. Eleven board trades were drained while open,
    # every one five to seven minutes after its graduation — B3 sells at about
    # six. Two ways out, tested FORWARD because both were picked on those same
    # trades:
    #  * DR leaves the moment the pool has lost a fifth of its SOL, on the
    #    socket's sub-second reserves. It never fired on the recorded history,
    #    whose DexScreener rows are 30-60s apart and see a drain only once it
    #    is over; the socket is the whole reason it can work now. A two-second
    #    cascade like FAIR's is still faster than any sell.
    #  * g4 sells four minutes after GRADUATION instead of five after entry.
    #    Replayed with rugs counted: +$89 on 215 trades and no drain, where B3
    #    lost $175 with four.
    Arm("B3_198k_5m_DR", "liq_B3", 5, drain=Decimal("0.20"),
        note="pool over $198k, out at 5m or once the pool loses a fifth of its SOL"),
    Arm("B3_198k_g4", "liq_B3", 4, clock="graduation",
        note="pool over $198k, out four minutes after graduating"),
    # TWO SHORTER GRADUATION CLOCKS, 2026-09-17, at Karthik's request after
    # ZBCN: it graduated at 17:24:30, the book bought at 17:25:07, and the
    # pool was dumped 93% in one instant at 17:27:08 — 2m38s after graduating,
    # which g4 sits past and these two sit in front of. Registered FORWARD and
    # nothing else: one rug is not evidence for a hold, and choosing 2m
    # BECAUSE it clears that one crash is the fit this lab keeps refusing.
    #
    # `_time_left` binds hardest on g2: an entry must leave a minute on the
    # clock, and DexScreener first reports a B3 pool a median 52s after the
    # migration, so g2 will fund about half of what g3 does and less than g4.
    # That is the arm, not a defect: a rule that cannot be entered in time is
    # a rule a wallet cannot run either.
    Arm("B3_198k_g2", "liq_B3", 2, clock="graduation",
        note="pool over $198k, out two minutes after graduating"),
    Arm("B3_198k_g3", "liq_B3", 3, clock="graduation",
        note="pool over $198k, out three minutes after graduating"),
    # B3, bought EARLY, 2026-09-16. DexScreener first reports a B3 pool a
    # median 52s after the migration, and that is where B3 buys. The pool's
    # own reserves say it is deep the moment it is — this arm buys then, and
    # holds five minutes from THAT entry. Same depth, same hold, earlier fill:
    # the one question is whether those seconds are worth anything.
    Arm("B3E_198k_5m", "early_B3", 5,
        note="pool's own reserves over $198k within 90s of graduating, "
             "bought on sight, out at 5m"),
    # FAST AND TRUSTED, 2026-09-19: the Tape Lab's two passing findings,
    # tested forward (`backend/app/labs/tape/README.md`). Rebuilt off the chain,
    # 18 days of graduations bought 15s after the pool opened made +0.59% a
    # trade more than the same coins bought at 45s, and keeping only coins
    # whose operator had 2+ earlier coins and no rug made +1.24% a trade on
    # days the rule never saw, against -0.45% for all of them.
    #
    # E75 buys every graduation whose pool's own reserves show $75k, read
    # on-chain 5-30s after the migration; E75T is the same with ONE extra
    # condition, a clean operator record. E75 is E75T's matched control, and
    # E75 against BASE_75k_5m is what the seconds are worth. Four minutes
    # because the backtest held four.
    Arm("E75_4m", "fast75", 4,
        note="pool's own reserves over $75k within 30s of graduating, "
             "bought on sight, out at 4m"),
    Arm("E75T_4m", "fast75_trust", 4,
        note="as E75_4m, only when the operator's earlier coins (2+) never rugged"),
    # NOT part of the tournament, and kept when everything else went. These
    # two are a PRE-REGISTERED A/B on the rug signals — a never-seen symbol
    # rugs 18% against 3%, a daytime-UTC open 15% against 5% — opened
    # 2026-09-13 with a judge date of 10 October, and `test_ab.py` exists
    # specifically to stop them being ended quietly.
    #
    # They compete with nothing here: B3 asks which pool depth to buy, this
    # asks whether a symbol predicts a rug. Retiring them three weeks short
    # would throw away two days of accumulated evidence and answer nothing.
    Arm("F01_all_2m", "all", 2, ab_experiment=True,
        note="A/B control — every graduation, out at 2m"),
    Arm("F14_symnight_2m", "sym_night", 2, ab_experiment=True,
        note="A/B arm — reused symbol AND a night-UTC open, out at 2m"),
)

BY_NAME: dict[str, Arm] = {a.name: a for a in ARMS}
#: There must be a baseline. The board spent four days telling us what a
#: tournament without one is worth: a profitable arm that cannot be told
#: apart from a market that went up. Losing it again should fail here.
assert any(a.is_control for a in ARMS), (
    "no baseline — every arm is a SUBSET of the floor arm's population, so "
    "without it none of them has been tested against anything")
CONTROLS: tuple[Arm, ...] = tuple(a for a in ARMS if a.is_control)
#: 50 original arms + F51_band_5m, added 2026-09-13 after the first fifty
#: returned no edge. The count is pinned rather than free because an arm that
#: appears mid-tournament changes what every other number means — so changing
#: it must be a deliberate edit with a date, not a side effect.
assert len(ARMS) == 14, (
    "three B3 arms (3m FROM ENTRY retired 2026-09-16 at -$58.90), B3 bought "
    "early (added 2026-09-16), the two rug arms (added 2026-09-16), the two "
    "shorter graduation clocks g2 and g3 (added 2026-09-17), the fast pair "
    "E75/E75T (added 2026-09-19), the BASELINE, the $500k+flow candidate, and "
    "the two pre-registered A/B arms — which run but are flagged off the "
    f"tournament board — not {len(ARMS)}")
assert len([a for a in ARMS if a.ab_experiment]) == 2, (
    "the rug-signal A/B is exactly F01_all_2m and F14_symnight_2m; flagging a "
    "tournament arm as an experiment would hide it from its own comparison")
assert {a.hold for a in ARMS} == {2, 3, 4, 5}, (
    "Four and five minutes, the A/B pair's two, and — from 2026-09-17 — two "
    "and three counted from GRADUATION rather than from entry, which is a "
    "different rule on a different clock: B3_198k_3m measured three minutes "
    "from the fill and was retired at -$58.90. The baseline "
    "and the $500k candidate are both five. Two and six from entry "
    "were retired after both wiped in every band. Longer is measurably worse "
    "(5m is +3.33% at a 1.6% tail; 30m is -6.48% at 14.6%), and one minute is "
    "not measurable at all: the median gap between price samples is 61s, so a "
    "60-second exit would be marked anywhere from 60 to 70+ seconds out. An "
    "arm the data cannot price is an arm a real wallet cannot verify")
assert all(a.tp is None and a.trail is None for a in ARMS), (
    "targets and TRAILING stops stay gone — every one of them held 15m+. A "
    "hard stop from entry is a different rule and is allowed")
assert all(a.stop is None or a.stop == Decimal("0.10") for a in ARMS), (
    "one stop level, so the twins differ in ONE thing. Sweeping levels here "
    "would be fitting a parameter on the same data that suggested it")
assert len([a for a in ARMS if not a.is_control]) == 13, (
    "`config.required_pf` is calibrated on the maximum of FORTY-TWO noise "
    "draws. Thirteen arms are now judged against it, so the bar is if anything "
    "CONSERVATIVE — the luckiest of thirteen reaches less than the luckiest "
    "of forty-two. Left as it is deliberately: a bar that is too hard costs a "
    "real finding some time, where one that is too easy costs a false one nothing")
assert all(a.clock in {"entry", "graduation"} for a in ARMS), "a clock is one of two"
assert all(a.drain is None or a.drain == Decimal("0.20") for a in ARMS), (
    "one drain level, for the same reason as one stop level")
assert len(CONTROLS) == 1, (
    "exactly one baseline, restored 2026-09-15. More than one would split the "
    "comparison; none is the state the board spent four days complaining about")
assert len({a.name for a in ARMS}) == len(ARMS), "arm names must be unique"
assert all(len(a.name) <= 32 for a in ARMS), "arm name must fit the column"
assert {a.entry for a in ARMS} <= set(ENTRY_RULES), (
    "every entry filter an arm uses must be described: "
    f"{ {a.entry for a in ARMS} - set(ENTRY_RULES) }")


def settle(position: GradPaperPosition, quote: Decimal, depth: Decimal | None,
           reason: str, closed_at: datetime) -> None:
    """Exit at what the pool would actually pay for this position.

    The order size on the way out is the position's CURRENT value, not
    what it cost: a token that ran 878% is ten times the order it was, into
    a pool that is usually no deeper. Pricing the exit at the quote is what
    turned a $21 pool into $878 of paper profit.

    With no recorded depth the exit is still taken — the position has to
    leave — but at the spot price with fees only, and `impact_close` stays
    NULL so the row shows the fill was never verified.

    The one place a close is booked: the live tick and a restatement both
    call it, so a restated trade is priced by the same arithmetic as a live one.
    """
    # The pool's fee at the price it is sold at: a drained pool is a tiny
    # market cap and charges the top tier.
    leg = costs(position.notional_quote, pool_fee_bps=config.pool_fee_bps(quote))
    # Value at the quote, before impact: the size of the sell order.
    value_usd = position.notional_usd * (quote / (
        position.notional_quote / position.tokens))
    fill = amm_sell(quote, value_usd=value_usd, liquidity_usd=depth,
                    fee_fraction=leg.fee_fraction)
    if fill is None:
        fill = leg.sell_price(quote)
        position.impact_close = None
    else:
        position.impact_close = (amm_impact(value_usd, depth) or Decimal(0)
                                 ).quantize(Decimal("0.000001"))
    position.liq_close_usd = depth
    proceeds = position.tokens * fill
    net = (proceeds / position.notional_quote - 1
           if position.notional_quote > 0 else Decimal(0))
    position.closed_at = closed_at
    position.close_quote = quote.quantize(_P)
    position.close_fill = fill.quantize(_P)
    position.close_reason = reason
    position.pnl_quote = (position.notional_quote * net).quantize(_Q)
    position.net_return = net.quantize(Decimal("0.00000001"))
    position.pnl_usd = (position.notional_usd * net).quantize(Decimal("0.01"))


def _timed_due(position: GradPaperPosition) -> datetime:
    """When the arm's clock says sell: minutes from the entry, or from the
    graduation for an arm that counts from there."""
    arm = BY_NAME[position.book]
    start = position.opened_at
    if arm.clock == "graduation" and position.graduated_at is not None:
        start = position.graduated_at
    return start + timedelta(minutes=arm.hold)


def _due(position: GradPaperPosition) -> datetime:
    """When a position must be sold: a stop's signal, or its clock."""
    timed = _timed_due(position)
    signal = position.exit_signal_at
    return min(timed, signal) if signal is not None else timed


def _time_left(arm: Arm, open_at: datetime, graduated_at: datetime | None) -> bool:
    """Can an arm that counts from graduation still hold for a minute?

    A pool DexScreener lists late — it has been twelve minutes — would
    otherwise be bought and sold in the same breath, paying both fees for
    nothing. An unknown graduation time cannot be counted from at all.
    """
    if arm.clock != "graduation":
        return True
    return (graduated_at is not None
            and open_at <= graduated_at + timedelta(minutes=arm.hold - 1))


def _drained(mark: Mark | None, position: GradPaperPosition,
             share: Decimal | None) -> bool:
    """Has the pool lost `share` of the SOL it held when this was bought?"""
    return (share is not None and mark is not None and mark.depth is not None
            and position.liq_open_usd is not None and position.liq_open_usd > 0
            and mark.depth < position.liq_open_usd * (1 - share))


#: Reads a pool's own vaults: (mint, pool) -> the pool now, or None.
PoolReader = Callable[[str, str], Awaitable[Held | None]]
#: Reads a coin's operator: (mint, pool) -> its wallets and their funders,
#: or None when the holders could not be read.
OperatorReader = Callable[[str, str], Awaitable[frozenset[str] | None]]


def chain_entry(pool: Held | None, sol_usd: Decimal,
                feed_price: Decimal) -> tuple[Decimal, Decimal] | None:
    """The price and depth a pool-open buy fills at: the pool's own, now.

    None when that cannot be trusted - the pool unread, not quoted in SOL (the
    SOL rate cannot state its depth), or so far from the feed's price that a
    scale error is likelier than the market (`PAPER_ENTRY_CHAIN_BAND`).
    """
    if pool is None or pool.quote_mint != config.WSOL_MINT:
        return None
    price, depth = pool.price(), pool.depth_usd(sol_usd)
    if not price or not depth:
        return None
    band = config.PAPER_ENTRY_CHAIN_BAND
    if not feed_price / band <= price <= feed_price * band:
        return None
    return price, depth


class Tournament:
    """Every arm, one tick, six queries."""

    def __init__(self, session: AsyncSession, *, now: datetime | None = None,
                 pool_reader: PoolReader | None = None,
                 operator_reader: OperatorReader | None = None,
                 money_checks: bool = False) -> None:
        self._session = session
        self._now = now or datetime.now(UTC)
        # With a reader, a pool-open buy fills at the pool's own price the
        # moment it is taken, not at DexScreener's first report (which can
        # predate the pool's first big buy - see `chain_entry`). Without one,
        # as before: the scheduler passes it; replays and old tests do not.
        self._pool_reader = pool_reader
        # The fast arms need both readers; without them they sit out, as the
        # replays and old tests do.
        self._operator_reader = operator_reader
        # The real wallet's money checks (`moneyblock`): a coin the wallet would
        # refuse, no book buys. The scheduler turns them on; replays and the
        # tests that script every query do not.
        self._money_checks = money_checks

    async def tick(self) -> dict[str, Any]:
        if not config.paper_enabled():
            return {"skipped": "graduation_paper_disabled"}
        closed = await self._manage()
        opened = await self._fill()
        return {"arms": len(ARMS), "opened": opened, "closed": closed}

    # --- marking -------------------------------------------------------------

    async def _latest_prices(self, mints: Sequence[str]) -> dict[str, Mark]:
        """Price AND pool depth per mint, at or before this tick's clock.

        The depth comes back with the price because an exit is priced against
        it: a position that ran is a larger order into the same pool, and
        selling it at the quote is the mistake this whole change exists to
        stop.

        `DISTINCT ON` rather than a query per position: fifty arms hold the
        same handful of tokens, and pricing each one once is the difference
        between six queries a tick and five hundred.
        """
        if not mints:
            return {}

        def newest(*where: Any) -> Any:
            return (select(GradPostgradSample.mint, GradPostgradSample.price_native,
                           GradPostgradSample.liquidity_usd,
                           GradPostgradSample.ts, GradPostgradSample.source)
                    .where(GradPostgradSample.mint.in_(list(mints)),
                           GradPostgradSample.price_native > 0,
                           GradPostgradSample.ts <= self._now, *where)
                    .distinct(GradPostgradSample.mint)
                    .order_by(GradPostgradSample.mint, GradPostgradSample.ts.desc()))

        rows = (await self._session.execute(newest())).all()
        # A live socket mark beats a DexScreener row stamped later: that row
        # carries its FETCH time and a price ~27s old, so newest-by-timestamp
        # is not newest-by-price. After sVkL4MXW rugged on 2026-09-15,
        # DexScreener sat 5.7x above the pool's own reserves for over a
        # minute, and a position closed on it would have booked that.
        live = (await self._session.execute(newest(
            GradPostgradSample.source == SOURCE_HELD_WS,
            GradPostgradSample.ts >= self._now - timedelta(
                seconds=config.HELD_TRUST_S)))).all()
        marks = {r.mint: Mark(r.price_native, r.liquidity_usd, r.ts, r.source)
                 for r in (*rows, *live)}
        # A position opened ON the curve has no pool sample until the token
        # migrates, and until then the curve IS its market. Without this the
        # pre-graduation arm could never be marked and never exit: its hold
        # would elapse against a price that does not exist yet.
        missing = [m for m in mints if m not in marks]
        if missing:
            rate = await self._sol_rate()
            for r in (await self._session.execute(
                    select(GradCurveSample.mint, GradCurveSample.v_quote_reserves,
                           GradCurveSample.v_token_reserves,
                           GradCurveSample.complete)
                    .where(GradCurveSample.mint.in_(missing),
                           GradCurveSample.v_quote_reserves > 0,
                           GradCurveSample.v_token_reserves > 0,
                           GradCurveSample.ts <= self._now)
                    .distinct(GradCurveSample.mint)
                    .order_by(GradCurveSample.mint,
                              GradCurveSample.ts.desc()))).all():
                if r.complete:
                    # A graduated token's curve is dead, and its last price is
                    # a fraction of where the pool trades — the early arm opens
                    # before DexScreener has a pool row, and would be marked
                    # -99% on it. No mark is the truthful answer until a pool
                    # sample exists.
                    continue
                price = r.v_quote_reserves / r.v_token_reserves
                marks[r.mint] = Mark(price, _curve_depth_usd(r.v_quote_reserves, rate))
        return marks

    async def _exit_marks(
        self, due: Sequence[GradPaperPosition]
    ) -> dict[Any, Mark | None]:
        """For each position whose timed exit is due, the mark that may price it.

        One read for every due position: their marks from the earliest due
        moment on. Few positions are due in any tick, and each has a few
        minutes of rows at most.
        """
        if not due:
            return {}
        start = min(p.opened_at for p in due)
        by_mint: dict[str, list[Mark]] = {}
        for r in (await self._session.execute(
                select(GradPostgradSample.mint, GradPostgradSample.price_native,
                       GradPostgradSample.liquidity_usd, GradPostgradSample.ts,
                       GradPostgradSample.source)
                .where(GradPostgradSample.mint.in_(sorted({p.mint for p in due})),
                       GradPostgradSample.price_native > 0,
                       GradPostgradSample.ts >= start,
                       GradPostgradSample.ts <= self._now))).all():
            by_mint.setdefault(r.mint, []).append(
                Mark(r.price_native, r.liquidity_usd, r.ts, r.source))
        return {p.id: exit_mark(by_mint.get(p.mint, ()), _due(p))
                for p in due}

    async def _sol_rate(self) -> Decimal | None:
        """SOL/USD, observed rather than fetched.

        Curve samples carry reserves in SOL and no dollar price, so the curve
        arm needs a rate to size $100 and to state pool depth in dollars. Taken
        from the newest pool sample carrying BOTH prices, which keeps the
        figure inside the same data the rest of the tick trusts — an external
        quote here would be a second failure mode inside the trading path.
        """
        row = (await self._session.execute(
            select(GradPostgradSample.price_usd, GradPostgradSample.price_native)
            .where(GradPostgradSample.price_usd > 0,
                   GradPostgradSample.price_native > 0,
                   GradPostgradSample.ts <= self._now)
            .order_by(GradPostgradSample.ts.desc()).limit(1))).first()
        return _rate(row.price_usd, row.price_native) if row else None

    async def _curve_candidates(self) -> Sequence[Any]:
        """Tokens still climbing, at or past the entry threshold.

        Newest sample per mint inside the grace window, and only while
        `complete` is still false — the moment it completes this is a pool
        open and the other forty-eight arms own it.
        """
        cutoff = self._now - timedelta(minutes=config.PAPER_ENTRY_GRACE_MINUTES)
        return (await self._session.execute(
            select(GradCurveSample.mint, GradCurveSample.ts.label("open_at"),
                   GradCurveSample.v_quote_reserves,
                   GradCurveSample.v_token_reserves,
                   GradToken.symbol)
            .outerjoin(GradToken, GradToken.mint == GradCurveSample.mint)
            .where(GradCurveSample.complete.isnot(True),
                   GradCurveSample.progress_pct >= CURVE_ENTRY_PCT,
                   GradCurveSample.v_quote_reserves > 0,
                   GradCurveSample.v_token_reserves > 0,
                   GradCurveSample.ts >= cutoff,
                   GradCurveSample.ts <= self._now)
            .distinct(GradCurveSample.mint)
            .order_by(GradCurveSample.mint, GradCurveSample.ts.desc()))).all()

    async def _manage(self) -> int:
        positions = (await self._session.scalars(
            select(GradPaperPosition)
            .where(GradPaperPosition.closed_at.is_(None),
                   GradPaperPosition.notional_usd > 0))).all()
        if not positions:
            return 0
        marks = await self._latest_prices(sorted({p.mint for p in positions}))
        exits = await self._exit_marks(
            [p for p in positions
             if p.book in BY_NAME and self._now >= _due(p)])
        closed = 0
        for position in positions:
            arm = BY_NAME.get(position.book)
            mark = marks.get(position.mint)
            price = depth = collapsed = None
            if mark is not None:
                price, collapsed = valued(mark, position.open_quote,
                                          position.liq_open_usd)
                depth = mark.depth
            if arm is None:
                # The arm was retired out of ARMS while this position was
                # open. Skipping it left the row open FOR EVER: when
                # generation 2 replaced generation 1, fifty-one positions on
                # forty-seven retired arms stayed open, the oldest a
                # two-minute hold that had been running twenty-five hours.
                # They showed on the page as open trades and could never
                # close, because nothing walks a book that is no longer an
                # arm. Settle at the last mark and say why.
                last = price if price is not None else position.last_quote
                if last is not None and last > 0:
                    self._close(position, last, depth, "arm_retired")
                    closed += 1
                continue
            if price is not None:
                position.peak_quote = max(position.peak_quote, price)
                position.last_quote = price
                position.marked_at = self._now
                if position.exit_signal_at is None:
                    fired = arm.policy().fires(ExitState(
                        clock_at=position.opened_at,
                        entry_price=position.notional_quote / position.tokens,
                        tick=Tick(ts=self._now, price=price, source="paper"),
                        peak=position.peak_quote))
                    if fired is None and _drained(mark, position, arm.drain):
                        fired = "drain_stop"
                    if fired is not None:
                        # A stop DECIDES on this mark and SELLS on the market
                        # after it: a wallet needs a moment to act, and a
                        # drain does not wait for it.
                        position.exit_signal_at = (
                            (seen_at(mark) or self._now)
                            + timedelta(seconds=config.EXIT_REACTION_S))
                        position.exit_signal = fired
            if self._now < _due(position):
                continue
            # Every exit is priced only by a mark describing the market after
            # it was due. Until one arrives the position waits, and a book that
            # is late to close is recorded late rather than early.
            out = exits.get(position.id)
            reason = (position.exit_signal
                      if position.exit_signal_at is not None
                      and position.exit_signal_at <= _timed_due(position)
                      else "max_hold")
            if out is not None:
                out_price, out_collapsed = valued(out, position.open_quote,
                                                  position.liq_open_usd)
                self._close(position, out_price, out.depth,
                            out_collapsed or reason)
                closed += 1
            elif (self._now - _due(position)).total_seconds() >= config.EXIT_MAX_WAIT_S:
                last = price if price is not None else position.last_quote
                if last is not None and last > 0:
                    self._close(position, last, depth,
                                "stale_exit" if price is not None else "end_of_data")
                    closed += 1
        return closed

    def _close(self, position: GradPaperPosition, quote: Decimal,
               depth: Decimal | None, reason: str) -> None:
        settle(position, quote, depth, reason, self._now)

    # --- filling -------------------------------------------------------------

    async def _open_counts(self) -> dict[str, int]:
        rows = (await self._session.execute(
            select(GradPaperPosition.book, func.count())
            .where(GradPaperPosition.closed_at.is_(None),
                   GradPaperPosition.notional_usd > 0)
            .group_by(GradPaperPosition.book))).all()
        return {r[0]: r[1] for r in rows}

    async def _candidates(self) -> Sequence[Any]:
        """Pool opens inside the entry grace window, with everything each arm
        needs to decide, in one read."""
        cutoff = self._now - timedelta(minutes=config.PAPER_ENTRY_GRACE_MINUTES)
        # Written to stay flat as the sample table grows, not to read well.
        #
        # The obvious form — GROUP BY mint HAVING min(ts) >= cutoff — asks
        # every mint that ever existed when its first sample was, so Postgres
        # scans the whole table: measured at 211 ms against 56,000 rows, on a
        # table growing 130,000 a day, inside a tick that runs every fifteen
        # seconds. This asks the same question backwards. A pool that opened
        # inside the window HAS a sample inside the window and NO sample
        # before it, and both of those are index lookups: 23 ms, and the first
        # step only ever touches the last few minutes of rows however large
        # the table gets.
        earlier = aliased(GradPostgradSample)
        recent = (select(GradPostgradSample.mint)
                  .where(GradPostgradSample.ts >= cutoff,
                         GradPostgradSample.ts <= self._now,
                         GradPostgradSample.price_native > 0)
                  .distinct()).subquery()
        fresh = (select(recent.c.mint)
                 .where(~select(1).select_from(earlier)
                        .where(earlier.mint == recent.c.mint,
                               earlier.ts < cutoff,
                               earlier.price_native > 0)
                        .exists())).subquery()
        opens = (select(GradPostgradSample.mint,
                        func.min(GradPostgradSample.ts).label("open_at"))
                 .join(fresh, fresh.c.mint == GradPostgradSample.mint)
                 .where(GradPostgradSample.price_native > 0)
                 .group_by(GradPostgradSample.mint)
                 .order_by(func.min(GradPostgradSample.ts))
                 .limit(64)).subquery()
        return (await self._session.execute(
            select(opens.c.mint, opens.c.open_at,
                   GradMigration.ts.label("graduated_at"),
                   GradPostgradSample.price_native, GradPostgradSample.price_usd,
                   GradPostgradSample.pair_address,
                   GradPostgradSample.liquidity_usd, GradPostgradSample.fdv,
                   GradPostgradSample.txns_m5_sells,
                   GradPostgradSample.txns_m5_buys,
                   GradToken.symbol, GradToken.first_seen_at)
            .join(GradPostgradSample,
                  (GradPostgradSample.mint == opens.c.mint)
                  & (GradPostgradSample.ts == opens.c.open_at))
            .outerjoin(GradToken, GradToken.mint == opens.c.mint)
            .outerjoin(GradMigration, GradMigration.mint == opens.c.mint))).all()

    async def _symbol_reuse(self, rows: Sequence[Any]) -> dict[str, int]:
        """How many tokens carried each candidate's symbol BEFORE it existed.

        Counted in Python from one flat read rather than a correlated
        subquery: the candidates are a handful, the answer has to be "strictly
        earlier than THIS token", and a join that expresses that is harder to
        read than it is to verify.
        """
        wanted = {(r.symbol or "").strip().lower() for r in rows if r.symbol}
        wanted.discard("")
        if not wanted:
            return {}
        seen: dict[str, list[datetime]] = {}
        for symbol, first_seen in (await self._session.execute(
                select(GradToken.symbol, GradToken.first_seen_at)
                .where(func.lower(func.trim(GradToken.symbol)).in_(wanted)))).all():
            seen.setdefault((symbol or "").strip().lower(), []).append(first_seen)
        out: dict[str, int] = {}
        for r in rows:
            key = (r.symbol or "").strip().lower()
            if not key or r.first_seen_at is None:
                continue
            out[r.mint] = sum(1 for t in seen.get(key, []) if t < r.first_seen_at)
        return out

    async def _fill_curve(self) -> int:
        """Buy tokens still climbing the curve, for the arms that want them.

        Deliberately separate from `_fill`: the candidates come from a
        different table, the price is derived from reserves rather than read
        from a feed, and the depth needs the SOL rate. Folding it into the
        pool-open path would have meant a second meaning for every field in
        that loop.
        """
        arms = [a for a in ARMS if a.entry == "curve"]
        if not arms:
            return 0
        rows = await self._curve_candidates()
        if not rows:
            return 0
        rate = await self._sol_rate()
        if rate is None:
            logger.warning("graduation_curve_no_rate", candidates=len(rows))
            return 0
        taken = {(b, m) for b, m in (await self._session.execute(
            select(GradPaperPosition.book, GradPaperPosition.mint)
            .where(GradPaperPosition.mint.in_([r.mint for r in rows]))))
            .all()}
        counts = await self._open_counts()
        opened = 0
        mirror: list[live_decisions.Mirrored] = []
        notional_quote = (config.PAPER_NOTIONAL_USD / rate).quantize(_Q)
        leg = costs(notional_quote)
        for row in rows:
            price = row.v_quote_reserves / row.v_token_reserves
            if price <= 0:
                continue
            depth = _curve_depth_usd(row.v_quote_reserves, rate)
            impact = amm_impact(config.PAPER_NOTIONAL_USD, depth)
            if impact is None or impact > config.PAPER_MAX_IMPACT:
                logger.info("graduation_curve_unfillable", mint=row.mint,
                            depth=float(depth or 0),
                            impact=float(impact) if impact is not None else None)
                continue
            fill = amm_buy(price, order_usd=config.PAPER_NOTIONAL_USD,
                           liquidity_usd=depth, fee_fraction=leg.fee_fraction)
            if fill is None or fill <= 0:
                continue
            for arm in arms:
                if (arm.name, row.mint) in taken:
                    continue
                if counts.get(arm.name, 0) >= config.PAPER_MAX_SLOTS:
                    continue
                self._session.add(GradPaperPosition(
                    book=arm.name, mint=row.mint, symbol=row.symbol,
                    opened_at=row.open_at,
                    open_quote=price.quantize(_P),
                    open_fill=fill.quantize(_P),
                    notional_usd=config.PAPER_NOTIONAL_USD,
                    sol_usd_at_open=rate.quantize(Decimal("0.000001")),
                    notional_quote=notional_quote,
                    tokens=(notional_quote / fill).quantize(_Q),
                    peak_quote=price.quantize(_P),
                    last_quote=price.quantize(_P),
                    liq_open_usd=depth,
                    impact_open=impact.quantize(Decimal("0.000001")),
                    marked_at=self._now))
                counts[arm.name] = counts.get(arm.name, 0) + 1
                taken.add((arm.name, row.mint))
                opened += 1
                if arm.name in live_spec.MIRRORS:
                    mirror.append(live_decisions.Mirrored(
                        strategy_id=live_spec.MIRRORS[arm.name],
                        mint=row.mint, opened_at=row.open_at,
                        liquidity_usd=depth, impact=impact,
                        price_native=price))
        await live_decisions.record(self._session, mirror)
        return opened

    async def _fill_early(self) -> int:
        """Buy pools the recorder saw reach B3's depth on their own reserves.

        Separate from `_fill` for the reason `_fill_curve` is: the candidates
        come from another table, and the price and depth are the pool's own
        rather than DexScreener's. The conventions are B3's, so the two can be
        compared: the position opens AT the signal (as B3's opens at its first
        sample), is sized at the same $100 against the same depth, and pays
        the same impact and fees.
        """
        arms = [a for a in ARMS if a.entry == "early_B3"]
        if not arms:
            return 0
        rows = (await self._session.execute(
            select(GradEarlyOpen, GradToken.symbol)
            .outerjoin(GradToken, GradToken.mint == GradEarlyOpen.mint)
            .where(GradEarlyOpen.crossed_at >= self._now - timedelta(
                       seconds=config.EARLY_MAX_AGE_S),
                   GradEarlyOpen.crossed_at <= self._now))).all()
        if not rows:
            return 0
        taken = {(b, m) for b, m in (await self._session.execute(
            select(GradPaperPosition.book, GradPaperPosition.mint)
            .where(GradPaperPosition.mint.in_([r[0].mint for r in rows]))))
            .all()}
        counts = await self._open_counts()
        opened = 0
        for early, symbol in rows:
            if early.pool != graduation_pool(early.mint):
                continue
            rate = _rate(early.sol_usd * early.price_native, early.price_native)
            if rate is None or early.price_native <= 0:
                continue
            impact = amm_impact(config.PAPER_NOTIONAL_USD, early.depth_usd)
            if impact is None or impact > config.PAPER_MAX_IMPACT:
                continue
            notional_quote = (config.PAPER_NOTIONAL_USD / rate).quantize(_Q)
            fee_bps = config.pool_fee_bps(early.price_native)
            leg = costs(notional_quote, pool_fee_bps=fee_bps)
            fill = amm_buy(early.price_native, order_usd=config.PAPER_NOTIONAL_USD,
                           liquidity_usd=early.depth_usd,
                           fee_fraction=leg.fee_fraction)
            if fill is None or fill <= 0:
                continue
            for arm in arms:
                if ((arm.name, early.mint) in taken
                        or counts.get(arm.name, 0) >= config.PAPER_MAX_SLOTS
                        or not _time_left(arm, early.crossed_at, early.migrated_at)):
                    continue
                self._session.add(GradPaperPosition(
                    book=arm.name, mint=early.mint, symbol=symbol,
                    opened_at=early.crossed_at,
                    open_quote=early.price_native.quantize(_P),
                    open_fill=fill.quantize(_P),
                    notional_usd=config.PAPER_NOTIONAL_USD,
                    sol_usd_at_open=rate.quantize(Decimal("0.000001")),
                    notional_quote=notional_quote,
                    tokens=(notional_quote / fill).quantize(_Q),
                    peak_quote=early.price_native.quantize(_P),
                    last_quote=early.price_native.quantize(_P),
                    liq_open_usd=early.depth_usd,
                    impact_open=impact.quantize(Decimal("0.000001")),
                    pool_fee_bps=fee_bps,
                    graduated_at=early.migrated_at,
                    marked_at=self._now))
                counts[arm.name] = counts.get(arm.name, 0) + 1
                taken.add((arm.name, early.mint))
                opened += 1
        if opened:
            logger.info("graduation_tournament_early_filled", opened=opened)
        return opened

    async def _fill_fast(self) -> int:
        """E75_4m and E75T_4m: graduations bought seconds after the migration,
        off the pool's own reserves, and - for E75T - only from operators with
        a clean record here.

        Every graduation between `FAST_MIN_AGE_S` and `FAST_MAX_AGE_S` old is
        read each tick until its pool shows `OPERATOR_RECORD_FLOOR_USD`. Then
        its operator is read and recorded whether or not anything buys it, and
        the arms buy at this tick's price if the pool holds the $75k floor.
        """
        arms = [a for a in ARMS if a.entry in FAST_ENTRIES]
        if not arms or self._pool_reader is None or self._operator_reader is None:
            return 0
        await self._label_operators()
        rows = await self._fast_candidates()
        rate = await self._sol_rate() if rows else None
        if not rows or rate is None:
            return 0
        pools = {r.mint: graduation_pool(r.mint) for r in rows}
        rows = [r for r in rows if pools[r.mint]]
        helds = await asyncio.gather(*(self._pool_reader(r.mint, pools[r.mint]) for r in rows),
                                     return_exceptions=True)
        deep = []
        for row, held in zip(rows, helds, strict=True):
            price = held.price() if isinstance(held, Held) else None
            depth = held.depth_usd(rate) if isinstance(held, Held) and price else None
            if price and depth and depth >= config.OPERATOR_RECORD_FLOOR_USD:
                deep.append((row, price, depth))
        found = await asyncio.gather(*(self._operator_reader(r.mint, pools[r.mint])
                                       for r, _, _ in deep), return_exceptions=True)
        counts = await self._open_counts()
        recent = (await moneyblock.recent_rug_ids(self._session, self._now)
                  if self._money_checks else set())
        opened = blocked = 0
        for (row, price, depth), ids in zip(deep, found, strict=True):
            ids = ids if isinstance(ids, frozenset) else None
            self._session.add(GradOperator(
                mint=row.mint, pool=pools[row.mint], migrated_at=row.ts,
                entry_at=self._now, price_native=price.quantize(_P),
                depth_usd=depth.quantize(Decimal("0.01")),
                ids=sorted(ids) if ids else None,
                label_due_at=self._now + timedelta(seconds=config.OPERATOR_LABEL_AFTER_S),
                source="live"))
            if depth < LIQ_BANDS[0][1]:
                continue  # recorded for the operator's record, too shallow to buy
            # The real wallet would refuse it, so no book here buys it either.
            if ids and (why := moneyblock.refused(ids, self._now, recent)):
                blocked += 1
                logger.info("graduation_tournament_money_blocked", mint=row.mint, reason=why)
                continue
            trusted = bool(ids) and await self._trusted(row.mint, ids)
            for arm in arms:
                if arm.entry == "fast75_trust" and not trusted:
                    continue
                if counts.get(arm.name, 0) >= config.PAPER_MAX_SLOTS:
                    continue
                if self._open_fast(arm, row, price, depth, rate):
                    counts[arm.name] = counts.get(arm.name, 0) + 1
                    opened += 1
        if deep:
            logger.info("graduation_tournament_fast_filled", recorded=len(deep), opened=opened,
                        money_blocked=blocked)
        return opened

    async def _fast_candidates(self) -> Sequence[Any]:
        """Graduations young enough to be read, not yet recorded."""
        return (await self._session.execute(
            select(GradMigration.mint, GradMigration.ts, GradToken.symbol)
            .outerjoin(GradToken, GradToken.mint == GradMigration.mint)
            .where(GradMigration.pool == config.PUMPSWAP_VENUE,
                   GradMigration.ts >= self._now - timedelta(seconds=config.FAST_MAX_AGE_S),
                   GradMigration.ts <= self._now - timedelta(seconds=config.FAST_MIN_AGE_S),
                   ~select(1).where(GradOperator.mint == GradMigration.mint).exists())
            .order_by(GradMigration.ts)
            .limit(config.FAST_MAX_PER_TICK))).all()

    async def _trusted(self, mint: str, ids: frozenset[str]) -> bool:
        """At least `OPERATOR_TRUST_MIN_COINS` earlier coins share one of these
        wallets or funders, and none of them rugged. Only labels already known
        at this tick count: a rug five minutes from now is not evidence yet."""
        known, rugs = (await self._session.execute(
            select(func.count(), func.count().filter(GradOperator.rugged.is_(True)))
            .where(GradOperator.ids.overlap(sorted(ids)),
                   GradOperator.mint != mint,
                   GradOperator.rugged.is_not(None),
                   GradOperator.labelled_at <= self._now))).one()
        return known >= config.OPERATOR_TRUST_MIN_COINS and rugs == 0

    async def _label_operators(self) -> None:
        """Whether each recorded coin rugged, `OPERATOR_LABEL_AFTER_S` after its
        entry, off its pool's own reserves. A pool still unreadable
        `OPERATOR_LABEL_GIVE_UP_S` later is closed unlabelled and never counts."""
        due = (await self._session.scalars(
            select(GradOperator)
            .where(GradOperator.labelled_at.is_(None),
                   GradOperator.label_due_at <= self._now)
            .order_by(GradOperator.label_due_at)
            .limit(config.FAST_MAX_PER_TICK))).all()
        if not due or self._pool_reader is None:
            return
        helds = await asyncio.gather(*(self._pool_reader(o.mint, o.pool) for o in due),
                                     return_exceptions=True)
        for op, held in zip(due, helds, strict=True):
            price = held.price() if isinstance(held, Held) else None
            if price is None:
                late = (self._now - op.label_due_at).total_seconds()
                if late > config.OPERATOR_LABEL_GIVE_UP_S:
                    op.labelled_at = self._now
                continue
            op.exit_price_native = price.quantize(_P)
            op.rugged = price / op.price_native - 1 <= config.OPERATOR_RUG_MOVE
            op.labelled_at = self._now

    def _open_fast(self, arm: Arm, row: Any, price: Decimal, depth: Decimal,
                   rate: Decimal) -> bool:
        """One fast position at this tick's pool price, costed like every
        other pool-open buy: the pool's fee tier, impact against its depth."""
        impact = amm_impact(config.PAPER_NOTIONAL_USD, depth)
        if impact is None or impact > config.PAPER_MAX_IMPACT:
            return False
        notional_quote = (config.PAPER_NOTIONAL_USD / rate).quantize(_Q)
        fee_bps = config.pool_fee_bps(price)
        leg = costs(notional_quote, pool_fee_bps=fee_bps)
        fill = amm_buy(price, order_usd=config.PAPER_NOTIONAL_USD, liquidity_usd=depth,
                       fee_fraction=leg.fee_fraction)
        if fill is None or fill <= 0:
            return False
        self._session.add(GradPaperPosition(
            book=arm.name, mint=row.mint, symbol=row.symbol, opened_at=self._now,
            open_quote=price.quantize(_P), open_fill=fill.quantize(_P),
            notional_usd=config.PAPER_NOTIONAL_USD,
            sol_usd_at_open=rate.quantize(Decimal("0.000001")),
            notional_quote=notional_quote,
            tokens=(notional_quote / fill).quantize(_Q),
            peak_quote=price.quantize(_P), last_quote=price.quantize(_P),
            liq_open_usd=depth.quantize(Decimal("0.01")),
            impact_open=impact.quantize(Decimal("0.000001")),
            pool_fee_bps=fee_bps, graduated_at=row.ts, marked_at=self._now))
        return True

    async def _fill(self) -> int:
        opened_curve = (await self._fill_curve() + await self._fill_early()
                        + await self._fill_fast())
        rows = await self._candidates()
        if not rows:
            return opened_curve
        reuse = await self._symbol_reuse(rows)
        mints = [r.mint for r in rows]
        # The real wallet's money checks, on the addresses `_fill_fast` recorded
        # for each coin: a coin the wallet would refuse, no book here buys.
        blocked = (await moneyblock.refusals(self._session, mints, self._now)
                   if self._money_checks else {})
        taken = {(b, m) for b, m in (await self._session.execute(
            select(GradPaperPosition.book, GradPaperPosition.mint)
            .where(GradPaperPosition.mint.in_(mints)))).all()}
        counts = await self._open_counts()
        opened = 0
        refused = 0
        foreign = 0
        unpriced = 0
        money_blocked = 0
        mirror: list[live_decisions.Mirrored] = []
        for row in rows:
            if row.price_native is None or row.price_native <= 0:
                continue
            if row.pair_address != graduation_pool(row.mint):
                # Not a pump.fun graduation trading on the pool its migration
                # made. Every arm here is a graduation rule, so none may buy it.
                foreign += 1
                continue
            rate = _rate(row.price_usd, row.price_native)
            if rate is None:
                continue
            # WHO takes it is decided on the feed's numbers, as every arm was
            # defined; WHAT it costs is the pool's own price at the moment it is
            # taken. The feed's first report can predate the pool's first big
            # buy: Bluey (2026-09-17) was booked at +1,044% on a price 11x under
            # where the pool already traded, and made +4% on-chain.
            entry_at = self._now if self._pool_reader is not None else row.open_at
            wanted = [arm for arm in ARMS
                      if (arm.name, row.mint) not in taken
                      and counts.get(arm.name, 0) < config.PAPER_MAX_SLOTS
                      and accepts(arm, mint=row.mint, open_at=row.open_at,
                                  liquidity=row.liquidity_usd, fdv=row.fdv,
                                  sells=row.txns_m5_sells, buys=row.txns_m5_buys,
                                  reuse=reuse.get(row.mint))
                      and _time_left(arm, entry_at, row.graduated_at)]
            if not wanted:
                continue
            if row.mint in blocked:
                money_blocked += 1
                logger.info("graduation_tournament_money_blocked", mint=row.mint,
                            reason=blocked[row.mint])
                continue
            price, depth = row.price_native, row.liquidity_usd
            if self._pool_reader is not None:
                priced = chain_entry(await self._pool_reader(row.mint, row.pair_address),
                                     rate, row.price_native)
                if priced is None:
                    # Not bought on a guess. Still inside the grace window, so
                    # the next tick asks the pool again.
                    unpriced += 1
                    continue
                price, depth = priced
            # Could a real wallet have filled this at all? A transaction whose
            # price move exceeds the slippage tolerance REVERTS — it does not
            # fill badly, it does not fill. Refusing here is the difference
            # between a book that informs a real wallet and one that cannot.
            impact = amm_impact(config.PAPER_NOTIONAL_USD, depth)
            if impact is None or impact > config.PAPER_MAX_IMPACT:
                refused += 1
                logger.info("graduation_tournament_unfillable", mint=row.mint,
                            liquidity=float(depth or 0),
                            impact=float(impact) if impact is not None else None)
                continue
            notional_quote = (config.PAPER_NOTIONAL_USD / rate).quantize(_Q)
            fee_bps = config.pool_fee_bps(price)
            leg = costs(notional_quote, pool_fee_bps=fee_bps)
            fill = amm_buy(price, order_usd=config.PAPER_NOTIONAL_USD,
                           liquidity_usd=depth, fee_fraction=leg.fee_fraction)
            if fill is None or fill <= 0:
                continue
            for arm in wanted:
                self._session.add(GradPaperPosition(
                    book=arm.name, mint=row.mint, symbol=row.symbol,
                    opened_at=entry_at,
                    open_quote=price.quantize(_P),
                    open_fill=fill.quantize(_P),
                    notional_usd=config.PAPER_NOTIONAL_USD,
                    sol_usd_at_open=rate.quantize(Decimal("0.000001")),
                    notional_quote=notional_quote,
                    tokens=(notional_quote / fill).quantize(_Q),
                    peak_quote=price.quantize(_P),
                    last_quote=price.quantize(_P),
                    # The feed's depth: the number the arm was chosen on.
                    liq_open_usd=row.liquidity_usd,
                    impact_open=impact.quantize(Decimal("0.000001")),
                    pool_fee_bps=fee_bps,
                    graduated_at=row.graduated_at,
                    marked_at=self._now))
                counts[arm.name] = counts.get(arm.name, 0) + 1
                taken.add((arm.name, row.mint))
                opened += 1
                # The ONLY thing that makes this arm visible to the real
                # wallet. Written in the entry's own transaction, because the
                # exit clock starts when the WALLET fills: a buy 60s late still
                # exits five minutes after itself, six minutes after
                # graduation, which wiped the wallet in 51% of replayed draws.
                if arm.name in live_spec.MIRRORS:
                    mirror.append(live_decisions.Mirrored(
                        strategy_id=live_spec.MIRRORS[arm.name],
                        mint=row.mint, opened_at=entry_at,
                        liquidity_usd=row.liquidity_usd, impact=impact,
                        price_native=price))
        await live_decisions.record(self._session, mirror)
        opened += opened_curve
        if opened or refused or foreign or unpriced or money_blocked:
            logger.info("graduation_tournament_filled", opened=opened,
                        refused_unfillable=refused, not_graduation=foreign,
                        pool_unpriced=unpriced, money_blocked=money_blocked,
                        candidates=len(rows))
        return opened
