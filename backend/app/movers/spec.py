"""MOVERS — does high turnover mark a coin BEFORE it runs?

Two $100 wallets, $10 a position, ten open. Identical in every respect except
one condition: MOV-01 requires turnover above a floor, MOV-02 does not.

## Where the rule came from

Asked on 2026-09-09 how to track pump.fun's "Movers" before they move. Their
API cannot answer it — `/coins` accepts five sorts and none of them is volume,
price change or trending — so the list has to be rebuilt from our own
observations, and the question became whether movers are distinguishable in
advance at all.

Measured over 4,130 tokens across three days, features read from the five
minutes BEFORE the outcome window and the outcome read only after it:

    tokens that later doubled       turnover 0.63, liquidity $109k
    tokens that did not             turnover 0.11, liquidity $218k

The movers traded roughly 2.8x the volume on HALF the liquidity. Neither term
separates them alone; the ratio does.

## It is a FLOOR, not a score, and the deciles say so

    turnover < 0.005   10-24% doubled
    turnover > 0.02    30-47% doubled, flat and NON-MONOTONIC

The ninth decile (29.7%) did worse than the fourth (41.2%). So turnover tells
you which coins are alive, not which live one will run. Sizing by it, or
ranking on it, would be reading a gradient that is not there. `TURNOVER_FLOOR`
sits at 1.0 — well inside the region that hit 40%, and far enough above the
0.02 cliff that a drifting denominator cannot quietly reintroduce the dead.

## What "doubled" does NOT mean

It means the price TOUCHED 2x at some later observation. It does not mean a
seller got it. Every payoff study here has found peaks are not realisable and
every exit level tested came out negative, so the 40% above is an upper bound
on opportunity and nothing like an expected return. This wallet exists to find
out what a rule can actually keep.

## The rules, and why each is what it is

* **A tenth of the wallet, ten positions.** $10 each at $100, $20 at $200,
  $30 at $300, capped at $100 once the wallet reaches $1,000. BOTH ARMS scale
  identically, which is the part that matters: sizing that differed between
  them would confound the entry rule with the stake, which is what left V6
  unable to separate the two afterwards. Scaling in step confounds nothing.
* **Liquidity >= $100k.** Measured from 142,479 Jupiter quotes, a round trip
  costs ~0.78% at that depth and is untradeable below $25k. Note this cuts
  against the signal: movers had LOWER median liquidity, so the floor is
  deliberately giving up part of the population to keep fills honest.
* **No take-profit.** A +10% cap destroyed 93% of gross return in the 15-minute
  study — capping the winners while taking losses in full is backwards. The
  time exit is the only exit, which keeps this a clean test of the ENTRY.
* **No stop loss.** Stops on these fill at ~$0.03. A stop that cannot fill is
  not risk control, it is a comforting line in a config file.
* **30-minute hold.** Median time from a fillable entry to a 2x was 19.7
  minutes (p25 8.1, p75 64.8). Thirty covers the median mover without holding
  into the decay that took the 60-minute graduation cohort to -33%.

## The control is the experiment

MOV-02 draws from the SAME pool at the SAME size with the SAME exit and does
not look at turnover. If the two end level, turnover is not a signal, and that
is a real answer. Every no-edge finding on this platform came from a control
rather than a strategy, and the random arm has now beaten the designed one
several times. Expect that.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from decimal import Decimal as D

from app.lab.spec import Condition, Exits, Strategy, rules_json

SPEC_VERSION = "movers-5.0.0"

STARTING_EQUITY = D("100")
CYCLE_TARGET_MULTIPLE = D("1.10")
FAILURE_EQUITY_FLOOR = D("50")

SIZE_USD = D("10")
MAX_CONCURRENT = 10

#: Stake a fixed FRACTION of the wallet rather than a flat amount: $10 a
#: position at $100, $20 at $200, $30 at $300, capped at $100 once the wallet
#: reaches $1,000. Ten positions, each a tenth of the balance.
#:
#: Not the default ladder, which doubles at powers of two and would stake $20
#: on that same $300 wallet. Straight proportion was the instruction and it is
#: also the gentler rule — the ladder takes its largest step exactly when one
#: good mark could have caused the crossing.
#:
#: BOTH ARMS SCALE IDENTICALLY, which is what keeps the pair readable. Sizing
#: that differed between them would confound the entry rule with the stake and
#: leave the result unattributable to either, which is what happened to V6.
SIZING_MODE = "linear"
SIZING_CAP_MULTIPLE = 10

#: Hold, in hours. 30 minutes — see the docstring.
TIME_EXIT_HOURS = 0.5

#: The floor the whole hypothesis rests on. Above the measured cliff by a wide
#: margin, because the cliff is where the dead coins stop, not where the
#: movers start.
TURNOVER_FLOOR = D("1.0")

#: Depth at which a round trip is ~0.78% rather than a guess.
MIN_LIQUIDITY_USD = D("100000")

#: BOTH wallets. Holding the pool identical is what makes this a controlled
#: comparison — a control free to buy shallower coins would differ in two ways
#: at once and the result would be unattributable.
_POOL: tuple[Condition, ...] = (
    # THE MINT MUST CARRY THE LAUNCHPAD'S SUFFIX, on the operator's instruction
    # and on this lab's own record.
    #
    # `is_pumpfun` below reads `source_program` and counts the whole pump.fun
    # ecosystem, so a coin whose program is the PumpSwap AMM passes it without
    # having been minted by the launchpad — and those are the coins with no
    # "pump" suffix. Across every movers tournament to 2026-09-09:
    #
    #     suffixed      60 closed   +$54.68
    #     unsuffixed    17 closed   -$43.52   (5 rugs)
    #
    # MOVERS-TURNOVER is the clearest case: all six of its trades were
    # unsuffixed and they were its entire -$11.73.
    #
    # STATED PLAINLY, because it is a post-hoc split on a small sample: 17
    # trades is not proof, the suffix is a mint-address convention rather than
    # a safety property, and it correlates with bonding-curve custody, so this
    # may be measuring the same thing the security gate measures. It is applied
    # because the operator asked and the record points the same way, not
    # because 17 trades settled anything.
    Condition(feature="mint_suffix_pump", op="gte", value=D("1"),
              reason="mint_not_pump_suffixed"),
    Condition(feature="is_pumpfun", op="gte", value=D("1"),
              reason="not_a_pumpfun_token"),
    Condition(feature="liq", op="gte", value=MIN_LIQUIDITY_USD,
              reason="too_thin_to_fill_honestly"),
)

# NO ROUTE CONDITION, and that was a correction rather than an omission.
#
# Both arms originally required a two-sided Jupiter quote, on the reasoning
# that a position which cannot be sold is not a trade. Measured before
# shipping: of 60,204 tokens seen in two days, 2,150 have a quote at all —
# 3.6% — and the median first quote arrives 24.2 minutes after first sight.
# The rule would therefore have traded a thirtieth of the pool, and only from
# a point at which the median mover has already run.
#
# The liquidity floor carries that safety instead, and does it on evidence:
# across 142,479 quotes, sells at $100k-250k failed to route 0.5% of the time
# and above $250k not at all. Depth is the execution guarantee here; the quote
# was a redundant gate that happened to be crippling.

def _wallet(sid: str, name: str, entry: tuple[Condition, ...],
            hypothesis: str, evidence: str,
            time_exit_hours: float | None = TIME_EXIT_HOURS) -> Strategy:
    return Strategy(
        id=sid, name=name, hypothesis=hypothesis,
        # Ten minutes, because that is where the measurement was taken. The
        # research read turnover at each token's TENTH print, and the median
        # token reaches its tenth print 9.8 minutes after first sight (p90
        # 12.4). A five-minute checkpoint would read a different quantity from
        # the one that was validated and call it the same rule.
        checkpoint_minutes=10,
        entry=entry,
        size_usd=SIZE_USD, max_concurrent=MAX_CONCURRENT,
        max_exposure_usd=STARTING_EQUITY,
        exits=Exits(take_profit=None, time_exit_hours=time_exit_hours),
        evidence=evidence, overfit_risk="UNTESTED",
    )


#: The security gate: the platform's own contract/mint/liquidity verdict must
#: have positively said VERIFIED at or before the checkpoint.
#:
#: This is the one lever the trade record actually pointed at. Over 50 closed
#: trades, partial losses averaged FOURTEEN CENTS and the entire loss was five
#: coins going to zero: -$76 against +$113 from everything else. No exit rule
#: reaches a coin that rugs inside its holding period, deeper liquidity did not
#: help (the rugs averaged $423k at entry against $258k for survivors, one
#: rugged from $1.1M), and a faster clock would not have caught them.
#:
#: UNKNOWN declines, the same as FAILED. The security module's own entry policy
#: requires every check to positively pass, and "the platform could not look"
#: is not evidence of safety. An unevaluated coin is therefore also a decline.
#:
#: THIS IS THE REAL WALLET'S OWN GATE, not a paper imitation of it. The feature
#: calls `entry_policy.decide` — the same pure function `evaluate_real_entry`
#: calls before spending real money — so a coin MOV-03 buys is a coin the real
#: wallet would have been allowed to buy, by construction rather than review.
#:
#: Replayed 2026-09-09 over all 80 movers entries to date: the real gate would
#: have allowed 4. MOV-03 was 2/2, the control 2/22, MOV-01/02 0/56 — because
#: 75 of the 80 coins had never been security-evaluated at all. That was a
#: coverage defect, not a policy one, and it is fixed in `lab_coverage`.
#:
#: WHAT THIS MEANS FOR THE CONTROL'S RESULT: MOV-04 buys coins the real wallet
#: will refuse. If it wins, the finding is "the gate costs money", NOT an
#: instruction to trade unverified coins with real funds — that trade cannot be
#: placed. Only MOV-03's result is actionable.
_SECURE = Condition(feature="security_verified", op="gte", value=D("1"),
                    reason="security_not_verified")

#: TWO wallets, starting together at $100.
#:
#: MOV-01 required turnover >= 1.0 and was retired on 2026-09-09 on
#: instruction, with 3 closed trades to its name (2 of them winners). It is
#: kept out of `STRATEGIES` rather than merely disabled so the engine cannot
#: reach a strategy id its registry no longer defines.
#:
#: WHAT THIS COSTS, STATED: MOV-02 was only ever a control, and a control with
#: nothing to control against is just a book. Nothing here can now answer
#: whether the turnover filter helped or hurt, because the comparison that
#: would have answered it no longer exists. What is left measures one thing —
#: what buying every liquid pump.fun coin and banking the wallet at +10%
#: returns — and it has no benchmark, so a good result cannot be distinguished
#: from a hot week.
#: THE THIRD TOURNAMENT TODAY, and each bump was paid for rather than avoided.
#:
#: 1.0.0 ran 07:54-11:21 and halted on `spec_hash_drift` when its registry was
#: edited underneath it. 2.0.0 started the security pair cleanly, then briefly
#: carried MOV-02 as a continuing book; MOV-02 was removed on instruction
#: because it held rules identical to the control and could therefore tell you
#: nothing it did not.
#:
#: Removing it changed SPEC_HASH again, so rather than overwrite a running
#: tournament's stored hash — which is the one move that would make every
#: future halt unenforceable — the version was bumped and the three closed
#: trades 2.0.0 had accumulated were let go. Three trades is a cheap price for
#: a guard that still works.
#:
#: A FRESH TOURNAMENT, and why the old one could not simply continue.
#:
#: `movers-1.0.0` ran from 07:54 to 11:21 on 2026-09-09 and is frozen with its
#: record intact: 56 closed trades, MOV-01 retired mid-run, MOV-02 finishing at
#: $135. It stopped because editing a live registry changes SPEC_HASH and the
#: engine halts entries the moment the stored hash and the running one disagree
#: — a tournament scored against rules edited underneath it is not the
#: experiment it claims to be, and the guard was right to stop it.
#:
#: So the security question gets its own clean run. Both arms start at $100 at
#: the same moment and differ by exactly ONE condition, which is the only shape
#: that can answer it. There is no third "incumbent" arm: on a fresh start it
#: would carry identical rules to the control and simply be a duplicate.
STRATEGIES: tuple[Strategy, ...] = (
    _wallet("MOV-03", "SECURITY-GATED", (*_POOL, _SECURE),
            "A coin the security evaluator has positively VERIFIED rugs less "
            "often than one from the same pool that it has not.",
            "RUGS_WERE_5_OF_50_TRADES_AND_ALL_OF_THE_LOSS"),
    _wallet("MOV-04", "SECURITY-CONTROL", _POOL,
            "The gate adds nothing: verified and unverified coins rug alike.",
            "CONTROL"),
    # MOV-05: THE WALLET IS THE ONLY EXIT.
    #
    # On instruction: run the book to +10% on the WHOLE PORTFOLIO, sell
    # everything, restart from what was banked, and repeat — with no holding
    # period at all. The ratchet is not new; `CompoundService` already banks
    # every wallet here at CYCLE_TARGET_MULTIPLE and compounds from REALISED
    # equity rather than from the target, so $100 -> $110 -> $121. What is new
    # is removing the clock.
    #
    # It is MOV-03's rules exactly, minus the thirty-minute exit, so MOV-03 is
    # its control and the pair asks one question: does holding until the
    # PORTFOLIO is up beat holding each position for half an hour?
    #
    # WHAT THIS RISKS, AND IT IS NOT SMALL. With no clock, a position is only
    # released when the wallet banks or the token dies. Ten slots of $10 fill
    # the $100 book completely, so a wallet that never reaches +10% never frees
    # a dollar: it is fully deployed, indefinitely, in whatever it happened to
    # buy. Neither existing arm has banked a cycle yet — MOV-04 is at $28.63
    # and MOV-03 at $100.66 — so a lock-up is the likely first outcome, not a
    # remote one. That is the rule as asked for, and the failure mode is
    # recorded here rather than discovered later.
    #
    # `_SECURE` is carried because the instruction was that whatever this
    # trades must be buyable by the REAL wallet later, and `security_verified`
    # is exactly that question: would the real wallet have been allowed to buy
    # this coin at this checkpoint.
    _wallet("MOV-05", "RATCHET-NO-CLOCK", (*_POOL, _SECURE),
            "Holding until the PORTFOLIO is up 10% beats holding each position "
            "for thirty minutes.",
            "OPERATOR_INSTRUCTION_NO_HOLD_TIME",
            time_exit_hours=None),
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
#: Three times on 2026-09-09 a live tournament was halted by `spec_hash_drift`
#: because STRATEGIES was edited without SPEC_VERSION moving — once removing an
#: arm, once adding the security pair, once adding a wallet back. Each time the
#: guard did its job and each time the lab stopped SILENTLY, and was only
#: noticed when somebody asked why nothing was trading.
#:
#: The engine's guard fires at runtime, in production, hours later. This one
#: fires at import, on the machine of whoever made the edit: change the arms
#: and this assertion fails until the hash is updated, and updating it is the
#: moment to ask whether SPEC_VERSION should move too.
#:
#: ADDING an arm is not safer than removing one. Both change the hash.
#: Moved again for movers-5.0.0, which added MOV-05 (no holding period).
#: Moved 2026-09-09 for movers-4.0.0, which added the `mint_suffix_pump`
#: condition to BOTH arms. The pin did its job: the edit failed at import
#: rather than reaching production with a stale hash, and the version was
#: bumped rather than the running tournament's stored hash overwritten.
PINNED_SPEC_HASH = "6bcc203526b37b4ae32c42442add7fe5dabb4eeb8708256e3ae350b1ceff31f2"

assert SPEC_HASH == PINNED_SPEC_HASH, (
    f"STRATEGIES changed: hash is {SPEC_HASH[:16]}, pinned to "
    f"{PINNED_SPEC_HASH[:16]}. If the arms really changed, BUMP SPEC_VERSION "
    f"(a live tournament halts otherwise) and then update PINNED_SPEC_HASH."
)

assert len(STRATEGIES) == 3, "the security pair, and the no-clock ratchet arm"
assert BY_ID["MOV-05"].exits.time_exit_hours is None, (
    "MOV-05 exists to have NO holding period; a clock here would make it a "
    "duplicate of MOV-03 and the comparison meaningless"
)
assert BY_ID["MOV-05"].entry == BY_ID["MOV-03"].entry, (
    "MOV-05 must differ from MOV-03 in the CLOCK ALONE, or the pair measures "
    "two things at once"
)
assert BY_ID["MOV-03"].exits.time_exit_hours is not None, (
    "MOV-03 is MOV-05's control and must keep its clock"
)
assert "MOV-02" not in BY_ID, (
    "MOV-02 carried rules identical to the control and could tell you nothing "
    "it did not; removed on instruction 2026-09-09"
)
# THE property, for the PAIR: MOV-03 and MOV-04 differ by exactly one
# condition. MOV-02 is deliberately outside the comparison.
_g = {str(c) for c in BY_ID["MOV-03"].entry}
_c = {str(c) for c in BY_ID["MOV-04"].entry}
assert _g - _c == {str(_SECURE)} and _c - _g == set(), (
    "the security pair must differ in the security condition ALONE"
)
assert BY_ID["MOV-04"].entry == _POOL, (
    "the control must be the pool alone — any extra condition and the pair "
    "differs in two ways"
)
# No turnover condition survives anywhere in the registry. Asserted so that
# reinstating the filter cannot happen by half: putting it back means putting
# the control back with it, or the lab claims a comparison it is not running.
assert not any(c.feature == "turnover_5m"
               for st in STRATEGIES for c in st.entry), (
    "a turnover condition without a control arm measures nothing"
)
assert all(s.exits.take_profit is None for s in STRATEGIES), (
    "a take-profit would measure the exit rather than the entry"
)
# Every arm shares the clock EXCEPT MOV-05, which exists to have none. Written
# as an explicit exception rather than relaxed to `is not None`, so a fourth arm
# cannot quietly acquire a different holding period and call itself comparable.
assert all(s.exits.time_exit_hours == TIME_EXIT_HOURS
           for s in STRATEGIES if s.id != "MOV-05"), (
    "every arm but MOV-05 holds for TIME_EXIT_HOURS; a second clock would make "
    "the arms differ in more than the thing under test"
)
assert all(s.size_usd * s.max_concurrent <= STARTING_EQUITY for s in STRATEGIES)

__all__ = ["BY_ID", "CYCLE_TARGET_MULTIPLE", "FAILURE_EQUITY_FLOOR",
           "MIN_LIQUIDITY_USD", "SPEC_HASH", "SPEC_VERSION", "STARTING_EQUITY",
           "STRATEGIES", "TIME_EXIT_HOURS", "TURNOVER_FLOOR", "rules_json"]
