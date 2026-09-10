"""DEX LAB — can a DexScreener top gainer be caught BEFORE it is a top gainer?

Two $100 wallets over the same pool of already-liquid Solana tokens, $5 a
position and twenty open, each held six hours. They differ by exactly ONE
condition: DEX-01 requires that the token traded at least twice its own
liquidity in the last hour, DEX-02 does not.

## The question, and why the board itself cannot answer it

Asked on 2026-09-10 how to track DexScreener's Solana top gainers early enough
to trade them. The board is a REAR-VIEW MIRROR — a token is on it because it
has already run — so the only useful form of the question is whether the same
tokens are distinguishable an hour or two before they get there.

DexScreener's public API does not expose the board at all. Its documented
endpoints are token profiles, community takeovers, ads, token boosts, orders,
pair lookup, search, token-pairs, tokens, and `metas/trending` — trending
NARRATIVES, not tokens — plus `token-boosts/top`, which ranks paid promotion
rather than price change. There is no gainers endpoint and no sort by price
change. The list is computed somewhere unreachable, exactly as pump.fun's
"Movers" list was, so it has to be rebuilt from our own observations.

That is what this lab does: it reconstructs the board's input — price and
volume against liquidity — from `token_market_snapshots`, and asks whether the
input predicts the board.

## The universe is far smaller than the mint firehose suggests

Over the wide capture of 2026-08-21..23:

    152,913  distinct Solana mints observed
      7,852  ever report pool liquidity at all          (5.1%)
        619  ever reach $100,000 of liquidity           (0.4%)

The gainers board is drawn from the last line, not the first. Ninety-five
percent of what the scanner sees is a bonding-curve coin DexScreener prices but
does not back with a pool, and no amount of watching those is watching the
board.

## What separates a future gainer, measured

Anchors are every hourly print of a token at or above $100k of liquidity;
features are read AT that print and the outcome strictly after it. Glitch
guards: `suspect` rows excluded, a price level counted only when the next print
of the same pool confirms it, and both legs of every ratio filtered identically
— the first cut of this study read the exit price unfiltered and a single
$10-pool print turned a losing bucket into a winning one.

    tokens that went on to touch 2x     1-hour turnover  20.7
    tokens that did not                 1-hour turnover   0.05

Turnover is `volume_1h / liquidity`. Neither term separates them alone; the
ratio does. Median liquidity was HIGHER among the gainers ($311k vs $178k),
which is the opposite of the pump.fun movers cohort and the reason this lab
does not inherit the Movers Lab's rules.

## It is a FLOOR, not a score

Mean six-hour multiple of the signal arm by the floor applied:

    floor 0.25 -> 1.16      floor 2.0 -> 1.47
    floor 0.5  -> 1.32      floor 5.0 -> 1.50
    floor 1.0  -> 1.51      floor 10  -> 1.51 ... floor 20 -> 1.42

Flat from 1.0 upward. There is a cliff below 1.0 and no gradient above it, so
`TURNOVER_FLOOR` is 2.0: a round number, clear of the cliff, inside the flat
region. Never rank or size by this number — it says a token is alive, not that
it will run.

## What the rule actually returned

Episode level — one entry per contiguous run of signal hours, so six hours of
the same move count once — at $100k of liquidity, six-hour hold, and a token
with no tradeable price left counted as a TOTAL LOSS rather than dropped:

                      episodes  mean    median  dead    >=2x   >=5x
    turnover >= 2.0      251    1.472   1.221   19.9%   19.9%  2.4%
    control              417    0.823   1.005    1.9%    5.3%  0.2%

The control is the finding as much as the signal is: buying an arbitrary liquid
Solana token and holding it six hours returned 0.823x. That is the number this
rule has to beat, and every no-edge verdict on this platform came from a
control rather than a strategy.

## The traps this went through, recorded because they nearly published

* **Survivorship.** The first cut required a resolvable six-hour outcome and
  reported the signal arm at 1.7x median. Eighty-two percent of signal anchors
  never resolved — they rugged, went unpriced, or switched pool — against 39%
  of controls. The surviving fifth was the winners. Resolving every anchor and
  counting an unpriced token as -100% moved the median from 1.705 to 1.221 and
  the dead rate from invisible to 19.9%.
* **An unfiltered exit price.** `p_last` was the last print in the window with
  no `suspect` or liquidity filter, while the peak leg had both. Fixing it
  changed the 3x-capped mean from 0.905 to 1.123 — in the strategy's favour,
  which is exactly why it was worth finding.
* **Age is a confound but not the answer.** Tokens under two hours old touched
  2x 15% of the time against 0% for tokens over twelve hours, but the six-hour
  hold return was ~1.0 across every age band. Age predicts VOLATILITY, not
  return; turnover predicts both.

## What is NOT established, stated plainly

* **One window, one regime.** 66 hours of 2026-08-21..23. Split-half by time
  (1.66 / 1.14) and by mint hash (1.69 / 1.31 / 1.25) both hold and both beat
  the control, but a split inside one window is not a different market.
* **The population is pump.swap and Meteora.** The local capture holds 12
  Raydium mints and 3 Orca. The DexScreener board is broader, and this lab
  cannot speak for the part of it we have never watched.
* **No execution cost is in those numbers.** A round trip is ~0.78% at this
  depth from 142,479 measured quotes, which is small against 1.472 — but the
  signal fires on tokens trading twenty times their liquidity in an hour, and
  that is where a quoted mid and a fill diverge most. This is the single
  largest reason to run it forward before believing it.
* **5.4% of signal anchors had no data at all in the following six hours** and
  are excluded rather than counted. If every one were a total loss the mean
  falls from 1.472 to ~1.33, still above the control.
* **Nine no-edge findings precede this one.** The prior is that a control wins.

## The rules, and why each is what it is

* **$100,000 of liquidity, both arms.** Route-safe: across 142,479 Jupiter
  quotes, sells at $100-250k failed to route 0.5% of the time and above $250k
  not at all. It is also where the measurement was taken.
* **Six-hour hold.** Swept: the signal arm returns 1.02x at one hour, 1.10 at
  two, 1.15 at three, 1.41 at six and 1.41 at twelve, while the dead rate keeps
  climbing (14% -> 24%). Six is where the return stops improving and the risk
  does not.
* **No take-profit, and NO WALLET RATCHET.** Capping the signal arm at 2x takes
  the mean from 1.472 to 1.149; every other lab here banks its wallet at +10%,
  which is the same cap applied to the whole book, and it would remove most of
  what this rule earns. `CYCLE_ENABLED = False` is therefore load-bearing, not
  an omission.
* **No stop loss.** A fifth of these positions go to zero and stops on such
  tokens fill at about $0.03. A stop that cannot fill is not risk control.
* **$5 x 20.** Twenty because ~3.8 signal episodes an hour were available at
  this floor and a six-hour hold therefore wants about twenty-three slots, and
  because at a 20% death rate one dead position must cost 5% of the book rather
  than 50%. BOTH ARMS SIZE IDENTICALLY — sizing that differed between them
  would confound the entry rule with the stake, which is what left V6 unable to
  attribute its own result.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal as D

from app.lab.spec import Condition, Exits, Strategy, rules_json

SPEC_VERSION = "dex-1.0.0"

STARTING_EQUITY = D("100")
FAILURE_EQUITY_FLOOR = D("50")

#: Present because `CompoundService` reads it, and inert because
#: `CYCLE_ENABLED` is False. Kept rather than removed so the canonical JSON has
#: the same shape as every other registry's.
CYCLE_TARGET_MULTIPLE = D("1.10")

#: THE RATCHET IS OFF, and this is a rule rather than a default.
#:
#: Every other lab here banks the whole book at +10% and compounds from what it
#: realised. On this cohort that is a take-profit: capping the signal arm at 2x
#: costs it 0.32 of its 1.47 mean, and a +10% portfolio target would bite far
#: sooner than 2x on any position. The measured return needs the tail, so the
#: clock is the only exit.
CYCLE_ENABLED = False

SIZE_USD = D("5")
MAX_CONCURRENT = 20
#: Flat stake. The growth ladder would raise the stake exactly when one good
#: mark had caused the crossing, and this book's return is tail-driven enough
#: that such a mark is routine.
SIZING_SCALES = False

#: Hold, in hours. Swept 1/2/3/6/12 — see the docstring.
TIME_EXIT_HOURS = 6.0

#: `volume_1h / liquidity`. A floor, not a score.
TURNOVER_FLOOR = D("2.0")

#: Depth at which a sell routes and the measurement was taken.
MIN_LIQUIDITY_USD = D("100000")
LIQUIDITY_FLOOR = MIN_LIQUIDITY_USD

#: A rolling sample of every liquid Solana token, any venue.
CANDIDATE_SOURCE = "dexboard"

#: EMPTY ON PURPOSE: no venue restriction. `DEEP_AMM_VENUES` would exclude
#: pump.swap, where most of the 619 tokens that reached $100k actually trade,
#: and the DexScreener board has no venue in it either.
DEEP_VENUES: tuple[str, ...] = ()

#: Draws per tick. The beat runs every minute, so ~120 candidates an hour are
#: offered to BOTH arms.
#:
#: Sized from what the arms can actually consume, not from what the pool holds.
#: Twenty slots on a six-hour hold is a capacity of ~3.3 positions an hour, and
#: roughly a quarter of tokens at $100k clear the turnover floor at any moment
#: (8 of 34 in a measured ten minutes), so 120 draws feed the signal arm about
#: 29 firing candidates an hour — an order of magnitude more than it can spend,
#: which is what keeps the CONTROL rather than the pool the binding constraint.
#:
#: Not larger. Every draw writes a decision row per arm whether or not there is
#: capital behind it, and a ledger nobody can read is a ledger nobody checks.
SAMPLE_PER_TICK = 2

#: A token may be judged again after an hour. Load-bearing in both directions:
#: without a cooldown a token declined once at a quiet moment could never be
#: caught during its burst, and with a shorter one the same `volume_1h` reading
#: would be judged twice and counted as two independent draws.
REJUDGE_BY_SOURCE = {"dexboard": timedelta(hours=1)}

#: BOTH wallets. Holding the pool identical is what makes this controlled.
_POOL: tuple[Condition, ...] = (
    Condition(feature="liq", op="gte", value=MIN_LIQUIDITY_USD,
              reason="liq_below_100k"),
)

#: The one condition under test.
_TURNOVER = Condition(feature="turnover_1h", op="gte", value=TURNOVER_FLOOR,
                      reason="turnover_1h_below_2")


def _wallet(sid: str, name: str, entry: tuple[Condition, ...],
            hypothesis: str, evidence: str) -> Strategy:
    return Strategy(
        id=sid, name=name, hypothesis=hypothesis,
        # Five minutes after the sampled print. The feature is a one-hour
        # volume figure and the candidate query already refuses anything whose
        # newest print is older than SAMPLE_FRESHNESS, so the position opens
        # against the reading it was judged on. A longer checkpoint would open
        # against a burst that had already finished.
        checkpoint_minutes=5,
        entry=entry,
        size_usd=SIZE_USD, max_concurrent=MAX_CONCURRENT,
        max_exposure_usd=STARTING_EQUITY,
        exits=Exits(take_profit=None, time_exit_hours=TIME_EXIT_HOURS),
        evidence=evidence, overfit_risk="UNTESTED",
    )


STRATEGIES: tuple[Strategy, ...] = (
    _wallet("DEX-01", "DEXBOARD-TURNOVER", (*_POOL, _TURNOVER),
            "A token trading at least twice its own liquidity in an hour is on "
            "its way to the gainers board; one that is not, is not.",
            "TURNOVER_20_7_VS_0_05_ON_251_EPISODES"),
    _wallet("DEX-02", "DEXBOARD-CONTROL", _POOL,
            "Turnover adds nothing: any liquid Solana token does as well.",
            "CONTROL"),
)

BY_ID = {s.id: s for s in STRATEGIES}


def _canonical() -> str:
    def clean(s: Strategy) -> dict:
        d = asdict(s)
        for k in ("hist", "note", "caveats", "hypothesis", "name",
                  "evidence", "overfit_risk", "hist_is_proxy"):
            d.pop(k, None)
        return d

    return json.dumps(
        {"version": SPEC_VERSION,
         "starting_equity": str(STARTING_EQUITY),
         "failure_floor": str(FAILURE_EQUITY_FLOOR),
         "cycle_target": str(CYCLE_TARGET_MULTIPLE),
         "strategies": [clean(s) for s in STRATEGIES]},
        sort_keys=True, separators=(",", ":"), default=str,
    )


SPEC_HASH = hashlib.sha256(_canonical().encode()).hexdigest()

#: The hash this VERSION is pinned to, asserted at import.
#:
#: The engine re-checks the stored hash every tick and HALTS entries when it
#: drifts, which is correct and also silent: three times on 2026-09-09 a live
#: tournament stopped trading and nobody noticed until they asked why. This
#: assertion fires instead on the machine of whoever made the edit, and updating
#: it is the moment to ask whether SPEC_VERSION should move too.
#:
#: Adding an arm is not safer than removing one. Both change the hash.
PINNED_SPEC_HASH = "c2adef4c6089565de5fc6fdc298bdbf5e995e93d952c42544ac849eb4f9b99a0"

assert SPEC_HASH == PINNED_SPEC_HASH, (
    f"STRATEGIES changed: hash is {SPEC_HASH[:16]}, pinned to "
    f"{PINNED_SPEC_HASH[:16]}. If the arms really changed, BUMP SPEC_VERSION "
    f"(a live tournament halts otherwise) and then update PINNED_SPEC_HASH."
)

# THE PAIR PROPERTY: the two arms differ in the turnover condition ALONE.
# Asserted at import, so a second condition cannot be added to one arm on a
# laptop and discovered in production a week later.
_s = {str(c) for c in BY_ID["DEX-01"].entry}
_c = {str(c) for c in BY_ID["DEX-02"].entry}
assert _s - _c == {str(_TURNOVER)} and _c - _s == set(), (
    "DEX-01 and DEX-02 must differ in the turnover condition alone, or the "
    "pair measures two things at once and answers neither"
)
assert BY_ID["DEX-02"].entry == _POOL, (
    "the control must be the pool alone"
)
assert all(s.exits.take_profit is None for s in STRATEGIES), (
    "a take-profit costs this cohort 0.32 of its 1.47 mean — see the docstring"
)
assert CYCLE_ENABLED is False, (
    "the +10% wallet ratchet is a portfolio-level take-profit and would remove "
    "most of what this rule earns"
)
assert all(s.exits.time_exit_hours == TIME_EXIT_HOURS for s in STRATEGIES)
assert all(s.size_usd == SIZE_USD and s.max_concurrent == MAX_CONCURRENT
           for s in STRATEGIES), (
    "both arms size identically, or the entry rule is confounded with the stake"
)
assert SIZE_USD * MAX_CONCURRENT == STARTING_EQUITY
assert not DEEP_VENUES, (
    "empty on purpose: a venue filter would drop pump.swap, where most of the "
    "tokens that reach $100k actually trade"
)

__all__ = ["BY_ID", "CANDIDATE_SOURCE", "CYCLE_ENABLED", "CYCLE_TARGET_MULTIPLE",
           "DEEP_VENUES", "FAILURE_EQUITY_FLOOR", "LIQUIDITY_FLOOR",
           "MIN_LIQUIDITY_USD", "REJUDGE_BY_SOURCE", "SAMPLE_PER_TICK",
           "SIZE_USD", "SIZING_SCALES", "SPEC_HASH", "SPEC_VERSION",
           "STARTING_EQUITY", "STRATEGIES", "TIME_EXIT_HOURS",
           "TURNOVER_FLOOR", "rules_json"]
