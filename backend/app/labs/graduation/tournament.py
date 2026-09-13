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

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.logging import get_logger
from app.labs.graduation import config
from app.labs.graduation.backtest import (
    ExitPolicy,
    ExitState,
    TakeProfit,
    Tick,
    TrailingStop,
    amm_buy,
    amm_impact,
    amm_sell,
)
from app.labs.graduation.models import (
    GradCurveSample,
    GradPaperPosition,
    GradPostgradSample,
    GradToken,
)
from app.labs.graduation.paper import _P, _Q, _rate, costs, in_hour_window

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Arm:
    """One strategy. Frozen: the tournament is only evidence if no arm changes
    while it runs."""

    name: str
    entry: str
    hold: int
    tp: Decimal | None = None
    trail: Decimal | None = None
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
        return self.entry == "floor"

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
        if self.trail:
            parts.append(f"{self.trail * 100:.0f}% off the running peak")
        if self.tp:
            parts.append(f"{self.tp:g}x the price paid")
        parts.append(f"{self.hold} minute{'s' if self.hold != 1 else ''}")
        if len(parts) == 1:
            return f"at {parts[0]}"
        return "whichever comes first: " + ", or ".join(parts)

    def policy(self) -> ExitPolicy:
        rules: list[Any] = []
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


#: The fourteen liquidity bands, in dollars of pool at the pool open.
#:
#: CONTIGUOUS AND ORDERED, which is the whole design. Generation 1 ran fifty
#: independent filters and the winner had to clear the best-of-fifty noise
#: ceiling — profit factor 4.79 — which nothing reached in seventeen hours.
#: Ordered bands ask a different question: a real effect appears as a
#: SHAPE across neighbours, and noise appears as one spike beside eight flat
#: cells. A shape is visible with far fewer trades than a maximum is.
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
    ("L01", 75_000, 90_000),
    ("L02", 90_000, 105_000),
    ("L03", 105_000, 116_000),
    ("L04", 116_000, 128_000),
    ("L05", 128_000, 140_000),
    ("L06", 140_000, 155_000),
    ("L07", 155_000, 170_000),
    ("L08", 170_000, 185_000),
    ("L09", 185_000, 198_000),
    ("L10", 198_000, 220_000),
    ("L11", 220_000, 250_000),
    ("L12", 250_000, 300_000),
    ("L13", 300_000, 400_000),
    ("L14", 400_000, 1_000_000_000),
)
BAND_BY_KEY: dict[str, tuple[int, int]] = {
    f"liq_{k}": (lo, hi) for k, lo, hi in LIQ_BANDS}


#: What each entry key MEANS, in the words the page prints.
#:
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
    "band": f"the pool held ${LIQ_BANDS[3][1]:,} to ${LIQ_BANDS[8][2]:,} at "
            f"the open — generation 1's signal, as one arm",
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
    "rand25": "a hash of the token address, taking a quarter of them — CONTROL",
    "rand50": "a hash of the token address, taking half of them — CONTROL",
    "rand75": "a hash of the token address, taking three quarters — CONTROL",
}

#: Candidate features, measured at the pool open. Every one was chosen before
#: the tournament opened a position; none is tuned to a result.
def accepts(arm: Arm, *, mint: str, open_at: datetime, liquidity: Decimal | None,
            fdv: Decimal | None, sells: int | None, reuse: int | None) -> bool:
    e = arm.entry
    if e == "band":
        return (liquidity is not None
                and LIQ_BANDS[3][1] <= liquidity < LIQ_BANDS[8][2])
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
    if e == "floor":
        # The baseline: every graduation the grid is allowed to touch, with no
        # band selection. Same floor, same universe — so the only difference
        # between this and a grid arm is the band, which is the thing on trial.
        return liquidity is not None and liquidity >= LIQ_BANDS[0][1]
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
    Arm("L01_75k_2m", "liq_L01", 2, note="pool $75k-$90k, out at 2m"),
    Arm("L01_75k_3m", "liq_L01", 3, note="pool $75k-$90k, out at 3m"),
    Arm("L01_75k_5m", "liq_L01", 5, note="pool $75k-$90k, out at 5m"),
    Arm("L02_90k_2m", "liq_L02", 2, note="pool $90k-$105k, out at 2m"),
    Arm("L02_90k_3m", "liq_L02", 3, note="pool $90k-$105k, out at 3m"),
    Arm("L02_90k_5m", "liq_L02", 5, note="pool $90k-$105k, out at 5m"),
    Arm("L03_105k_2m", "liq_L03", 2, note="pool $105k-$116k, out at 2m"),
    Arm("L03_105k_3m", "liq_L03", 3, note="pool $105k-$116k, out at 3m"),
    Arm("L03_105k_5m", "liq_L03", 5, note="pool $105k-$116k, out at 5m"),
    Arm("L04_116k_2m", "liq_L04", 2, note="pool $116k-$128k, out at 2m"),
    Arm("L04_116k_3m", "liq_L04", 3, note="pool $116k-$128k, out at 3m"),
    Arm("L04_116k_5m", "liq_L04", 5, note="pool $116k-$128k, out at 5m"),
    Arm("L05_128k_2m", "liq_L05", 2, note="pool $128k-$140k, out at 2m"),
    Arm("L05_128k_3m", "liq_L05", 3, note="pool $128k-$140k, out at 3m"),
    Arm("L05_128k_5m", "liq_L05", 5, note="pool $128k-$140k, out at 5m"),
    Arm("L06_140k_2m", "liq_L06", 2, note="pool $140k-$155k, out at 2m"),
    Arm("L06_140k_3m", "liq_L06", 3, note="pool $140k-$155k, out at 3m"),
    Arm("L06_140k_5m", "liq_L06", 5, note="pool $140k-$155k, out at 5m"),
    Arm("L07_155k_2m", "liq_L07", 2, note="pool $155k-$170k, out at 2m"),
    Arm("L07_155k_3m", "liq_L07", 3, note="pool $155k-$170k, out at 3m"),
    Arm("L07_155k_5m", "liq_L07", 5, note="pool $155k-$170k, out at 5m"),
    Arm("L08_170k_2m", "liq_L08", 2, note="pool $170k-$185k, out at 2m"),
    Arm("L08_170k_3m", "liq_L08", 3, note="pool $170k-$185k, out at 3m"),
    Arm("L08_170k_5m", "liq_L08", 5, note="pool $170k-$185k, out at 5m"),
    Arm("L09_185k_2m", "liq_L09", 2, note="pool $185k-$198k, out at 2m"),
    Arm("L09_185k_3m", "liq_L09", 3, note="pool $185k-$198k, out at 3m"),
    Arm("L09_185k_5m", "liq_L09", 5, note="pool $185k-$198k, out at 5m"),
    Arm("L10_198k_2m", "liq_L10", 2, note="pool $198k-$220k, out at 2m"),
    Arm("L10_198k_3m", "liq_L10", 3, note="pool $198k-$220k, out at 3m"),
    Arm("L10_198k_5m", "liq_L10", 5, note="pool $198k-$220k, out at 5m"),
    Arm("L11_220k_2m", "liq_L11", 2, note="pool $220k-$250k, out at 2m"),
    Arm("L11_220k_3m", "liq_L11", 3, note="pool $220k-$250k, out at 3m"),
    Arm("L11_220k_5m", "liq_L11", 5, note="pool $220k-$250k, out at 5m"),
    Arm("L12_250k_2m", "liq_L12", 2, note="pool $250k-$300k, out at 2m"),
    Arm("L12_250k_3m", "liq_L12", 3, note="pool $250k-$300k, out at 3m"),
    Arm("L12_250k_5m", "liq_L12", 5, note="pool $250k-$300k, out at 5m"),
    Arm("L13_300k_2m", "liq_L13", 2, note="pool $300k-$400k, out at 2m"),
    Arm("L13_300k_3m", "liq_L13", 3, note="pool $300k-$400k, out at 3m"),
    Arm("L13_300k_5m", "liq_L13", 5, note="pool $300k-$400k, out at 5m"),
    Arm("L14_400k_2m", "liq_L14", 2, note="pool over $400k, out at 2m"),
    Arm("L14_400k_3m", "liq_L14", 3, note="pool over $400k, out at 3m"),
    Arm("L14_400k_5m", "liq_L14", 5, note="pool over $400k, out at 5m"),
    # SIX ARMS THAT ARE ALSO REAL STRATEGIES.
    #
    # Generation 1 and the first cut of generation 2 used coin flips here. A
    # dice roll is a sharp null, and it is executable — but it is not a thing
    # anyone would fund, and a lab whose leaderboard is topped by something
    # unfundable answers a question nobody asked.
    #
    # FLOOR is the baseline every grid arm is measured against: the same
    # universe, the same floor, no band. Every grid arm is a subset of its
    # population, so "beat FLOOR" is precisely the claim a band makes.
    #
    # BAND is generation 1's one real signal as a single arm ($116k-$198k),
    # kept whole so the grid can be checked against the coarse version of
    # itself — if fourteen bands find nothing the six-band lump already had,
    # the extra resolution bought nothing.
    Arm("FLOOR_2m", "floor", 2, note="BASELINE — every graduation over $75k, out at 2m"),
    Arm("FLOOR_3m", "floor", 3, note="BASELINE — every graduation over $75k, out at 3m"),
    Arm("FLOOR_5m", "floor", 5, note="BASELINE — every graduation over $75k, out at 5m"),
    Arm("BAND_2m", "band", 2, note="pool $116k-$198k, out at 2m"),
    Arm("BAND_3m", "band", 3, note="pool $116k-$198k, out at 3m"),
    Arm("BAND_5m", "band", 5, note="pool $116k-$198k, out at 5m"),
    # Carried over UNCHANGED from generation 1, and deliberately: these two
    # are a pre-registered A/B on the rug signals (a never-seen symbol rugs
    # 18% against 3%; a daytime-UTC open 15% against 5%), opened 2026-09-13
    # with a judge date of 10 October. Rebuilding the tournament around them
    # must not quietly end an experiment that has a date on it, so they keep
    # their names, their rules and their accumulated trades.
    # The pre-graduation arm. Every other arm on this board buys AFTER the
    # migration; this one buys while the token is still climbing, which is a
    # different population and a different pool — the bonding curve itself.
    #
    # Its natural comparison is F01_all_2m: the same 2-minute hold on tokens
    # bought after they graduate. "Before or after" is the question.
    Arm("CURVE90_2m", "curve", 2,
        note="pool still on the bonding curve at 90%+, out at 2m"),
    Arm("F01_all_2m", "all", 2, note="A/B control — every graduation, out at 2m"),
    Arm("F14_symnight_2m", "sym_night", 2,
        note="A/B arm — reused symbol AND a night-UTC open, out at 2m"),
)

BY_NAME: dict[str, Arm] = {a.name: a for a in ARMS}
CONTROLS: tuple[Arm, ...] = tuple(a for a in ARMS if a.is_control)
#: 50 original arms + F51_band_5m, added 2026-09-13 after the first fifty
#: returned no edge. The count is pinned rather than free because an arm that
#: appears mid-tournament changes what every other number means — so changing
#: it must be a deliberate edit with a date, not a side effect.
assert len(ARMS) == 51, f"the tournament is fifty-one arms, not {len(ARMS)}"
assert {a.hold for a in ARMS} == {2, 3, 5}, (
    "Two, three and five minutes. Longer is measurably worse INSIDE the band "
    "(5m is +3.33% at a 1.6% tail; 30m is -6.48% at 14.6%), and one minute is "
    "not measurable at all: the median gap between price samples is 61s, so a "
    "60-second exit would be marked anywhere from 60 to 70+ seconds out. An "
    "arm the data cannot price is an arm a real wallet cannot verify")
assert all(a.tp is None and a.trail is None for a in ARMS), (
    "targets and trailing stops are gone — every one of them held 15m+")
assert len([a for a in ARMS if not a.is_control]) == 48, (
    "`config.required_pf` is calibrated on the maximum of FORTY-TWO noise "
    "draws. Forty-eight arms are now judged against it, which makes that bar "
    "slightly lenient — the 95th percentile of a best-of-47 sits a shade above "
    "a best-of-42. Stated rather than fixed: recalibrating over six arms would "
    "be false precision, but a silent mismatch would not be")
assert len(CONTROLS) == 3, "three baselines, one per hold"
assert len({a.name for a in ARMS}) == 51, "arm names must be unique"
assert all(len(a.name) <= 32 for a in ARMS), "arm name must fit the column"
assert {a.entry for a in ARMS} <= set(ENTRY_RULES), (
    "every entry filter an arm uses must be described: "
    f"{ {a.entry for a in ARMS} - set(ENTRY_RULES) }")


class Tournament:
    """Every arm, one tick, six queries."""

    def __init__(self, session: AsyncSession, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or datetime.now(UTC)

    async def tick(self) -> dict[str, Any]:
        if not config.paper_enabled():
            return {"skipped": "graduation_paper_disabled"}
        closed = await self._manage()
        opened = await self._fill()
        return {"arms": len(ARMS), "opened": opened, "closed": closed}

    # --- marking -------------------------------------------------------------

    async def _latest_prices(
        self, mints: Sequence[str]
    ) -> dict[str, tuple[Decimal, Decimal | None]]:
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
        rows = (await self._session.execute(
            select(GradPostgradSample.mint, GradPostgradSample.price_native,
                   GradPostgradSample.liquidity_usd)
            .where(GradPostgradSample.mint.in_(list(mints)),
                   GradPostgradSample.price_native > 0,
                   GradPostgradSample.ts <= self._now)
            .distinct(GradPostgradSample.mint)
            .order_by(GradPostgradSample.mint, GradPostgradSample.ts.desc()))).all()
        marks = {r.mint: (r.price_native, r.liquidity_usd) for r in rows}
        # A position opened ON the curve has no pool sample until the token
        # migrates, and until then the curve IS its market. Without this the
        # pre-graduation arm could never be marked and never exit: its hold
        # would elapse against a price that does not exist yet.
        missing = [m for m in mints if m not in marks]
        if missing:
            rate = await self._sol_rate()
            for r in (await self._session.execute(
                    select(GradCurveSample.mint, GradCurveSample.v_quote_reserves,
                           GradCurveSample.v_token_reserves)
                    .where(GradCurveSample.mint.in_(missing),
                           GradCurveSample.v_quote_reserves > 0,
                           GradCurveSample.v_token_reserves > 0,
                           GradCurveSample.ts <= self._now)
                    .distinct(GradCurveSample.mint)
                    .order_by(GradCurveSample.mint,
                              GradCurveSample.ts.desc()))).all():
                price = r.v_quote_reserves / r.v_token_reserves
                marks[r.mint] = (price, _curve_depth_usd(r.v_quote_reserves, rate))
        return marks

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
        closed = 0
        for position in positions:
            arm = BY_NAME.get(position.book)
            price, depth = marks.get(position.mint, (None, None))
            if arm is None:
                # The arm was retired out of ARMS while this position was
                # open. Skipping it left the row open FOR EVER: when
                # generation 2 replaced generation 1, fifty-one positions on
                # forty-seven retired arms stayed open, the oldest a
                # two-minute hold that had been running twenty-five hours.
                # They showed on the page as open trades and could never
                # close, because nothing walks a book that is no longer an
                # arm. Settle at the last mark and say why.
                mark = price if price is not None else position.last_quote
                if mark is not None and mark > 0:
                    self._close(position, mark, depth, "arm_retired")
                    closed += 1
                continue
            age = (self._now - position.opened_at).total_seconds() / 60
            if price is not None:
                position.peak_quote = max(position.peak_quote, price)
                position.last_quote = price
                position.marked_at = self._now
                fired = arm.policy().fires(ExitState(
                    clock_at=position.opened_at,
                    entry_price=position.notional_quote / position.tokens,
                    tick=Tick(ts=self._now, price=price, source="paper"),
                    peak=position.peak_quote))
                if fired is not None:
                    self._close(position, price, depth, fired)
                    closed += 1
                    continue
            if age >= arm.hold:
                mark = price if price is not None else position.last_quote
                if mark is not None and mark > 0:
                    self._close(position, mark, depth,
                                "max_hold" if price is not None else "end_of_data")
                    closed += 1
        return closed

    def _close(self, position: GradPaperPosition, quote: Decimal,
               depth: Decimal | None, reason: str) -> None:
        """Exit at what the pool would actually pay for this position.

        The order size on the way out is the position's CURRENT value, not
        what it cost: a token that ran 878% is ten times the order it was, into
        a pool that is usually no deeper. Pricing the exit at the quote is what
        turned a $21 pool into $878 of paper profit.

        With no recorded depth the exit is still taken — the position has to
        leave — but at the spot price with fees only, and `impact_close` stays
        NULL so the row shows the fill was never verified.
        """
        leg = costs(position.notional_quote)
        # Value at the quote, before impact: the size of the sell order.
        value_usd = position.notional_usd * (quote / (
            position.notional_quote / position.tokens))
        fill = amm_sell(quote, value_usd=value_usd, liquidity_usd=depth,
                        fee_fraction=leg.fee_fraction)
        if fill is None:
            fill = leg.sell_price(quote)
        else:
            position.impact_close = (amm_impact(value_usd, depth) or Decimal(0)
                                     ).quantize(Decimal("0.000001"))
        position.liq_close_usd = depth
        proceeds = position.tokens * fill
        net = (proceeds / position.notional_quote - 1
               if position.notional_quote > 0 else Decimal(0))
        position.closed_at = self._now
        position.close_quote = quote.quantize(_P)
        position.close_fill = fill.quantize(_P)
        position.close_reason = reason
        position.pnl_quote = (position.notional_quote * net).quantize(_Q)
        position.net_return = net.quantize(Decimal("0.00000001"))
        position.pnl_usd = (position.notional_usd * net).quantize(Decimal("0.01"))

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
                   GradPostgradSample.price_native, GradPostgradSample.price_usd,
                   GradPostgradSample.liquidity_usd, GradPostgradSample.fdv,
                   GradPostgradSample.txns_m5_sells,
                   GradToken.symbol, GradToken.first_seen_at)
            .join(GradPostgradSample,
                  (GradPostgradSample.mint == opens.c.mint)
                  & (GradPostgradSample.ts == opens.c.open_at))
            .outerjoin(GradToken, GradToken.mint == opens.c.mint))).all()

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
        return opened

    async def _fill(self) -> int:
        opened_curve = await self._fill_curve()
        rows = await self._candidates()
        if not rows:
            return opened_curve
        reuse = await self._symbol_reuse(rows)
        mints = [r.mint for r in rows]
        taken = {(b, m) for b, m in (await self._session.execute(
            select(GradPaperPosition.book, GradPaperPosition.mint)
            .where(GradPaperPosition.mint.in_(mints)))).all()}
        counts = await self._open_counts()
        opened = 0
        refused = 0
        for row in rows:
            if row.price_native is None or row.price_native <= 0:
                continue
            rate = _rate(row.price_usd, row.price_native)
            if rate is None:
                continue
            # Could a real wallet have filled this at all? A transaction whose
            # price move exceeds the slippage tolerance REVERTS — it does not
            # fill badly, it does not fill. Refusing here is the difference
            # between a book that informs a real wallet and one that cannot.
            impact = amm_impact(config.PAPER_NOTIONAL_USD, row.liquidity_usd)
            if impact is None or impact > config.PAPER_MAX_IMPACT:
                refused += 1
                logger.info("graduation_tournament_unfillable", mint=row.mint,
                            liquidity=float(row.liquidity_usd or 0),
                            impact=float(impact) if impact is not None else None)
                continue
            notional_quote = (config.PAPER_NOTIONAL_USD / rate).quantize(_Q)
            leg = costs(notional_quote)
            fill = amm_buy(row.price_native, order_usd=config.PAPER_NOTIONAL_USD,
                           liquidity_usd=row.liquidity_usd,
                           fee_fraction=leg.fee_fraction)
            if fill is None or fill <= 0:
                continue
            for arm in ARMS:
                if (arm.name, row.mint) in taken:
                    continue
                if counts.get(arm.name, 0) >= config.PAPER_MAX_SLOTS:
                    continue
                if not accepts(arm, mint=row.mint, open_at=row.open_at,
                               liquidity=row.liquidity_usd, fdv=row.fdv,
                               sells=row.txns_m5_sells,
                               reuse=reuse.get(row.mint)):
                    continue
                self._session.add(GradPaperPosition(
                    book=arm.name, mint=row.mint, symbol=row.symbol,
                    opened_at=row.open_at,
                    open_quote=row.price_native.quantize(_P),
                    open_fill=fill.quantize(_P),
                    notional_usd=config.PAPER_NOTIONAL_USD,
                    sol_usd_at_open=rate.quantize(Decimal("0.000001")),
                    notional_quote=notional_quote,
                    tokens=(notional_quote / fill).quantize(_Q),
                    peak_quote=row.price_native.quantize(_P),
                    last_quote=row.price_native.quantize(_P),
                    liq_open_usd=row.liquidity_usd,
                    impact_open=impact.quantize(Decimal("0.000001")),
                    marked_at=self._now))
                counts[arm.name] = counts.get(arm.name, 0) + 1
                taken.add((arm.name, row.mint))
                opened += 1
        opened += opened_curve
        if opened or refused:
            logger.info("graduation_tournament_filled", opened=opened,
                        refused_unfillable=refused, candidates=len(rows))
        return opened
