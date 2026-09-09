"""KOL — do the wallets that were early into winners keep being early?

Two $100 wallets, $10 a position, ten open, held 30 minutes. They differ in
exactly ONE condition: KOL-01 requires that a followed wallet was among this
coin's first buyers, KOL-02 does not.

## Why wallets and not posts

Asked on 2026-09-09 to track thousands of KOLs and trade what they post.
Research redirected it, on three measurements:

  * A bare ticker is unresolvable. Across 861,463 tokens in 30 days there are
    143,926 distinct symbols, and a random ticker mention maps to ~218
    candidate tokens — one symbol is shared by 3,834. "$MOON" is not a signal.
  * A post is the caller's EXIT, not their entry. They bought first; trading
    the post buys their exit liquidity by construction.
  * The wallet is free, unambiguous, and earlier. The scanner already decodes
    every trader's address; it simply never remembered them until
    `token_early_buyers`.

So this follows what they DO, and it catches the buy that precedes the post
rather than the post itself.

## Ranked on one window, traded on the next

`app/kol/ranking.py` scores wallets on early buys that went on to double
within six hours, over the seven days BEFORE the tournament opens, and the top
50 are frozen into `kol_wallet_ranks` at activation. Nothing after `valid_from`
touches the selection.

This is the discipline pump.fun's own leaderboard fails: "the five most
profitable traders of last month" is a fact about the past that predicts
nothing, and backtesting it asks whether knowing the winners in advance would
have helped. It would.

## It will trade NOTHING until it has been ranked

`kol_early` is zero when no ranking exists, so KOL-01 cannot fire before the
collector has produced enough history to rank on — deliberately. An idle
signal arm in the first week is the rule refusing to guess, not a fault. The
control trades from the start, which is what makes the eventual comparison
readable.

## What a hit rate is NOT

A wallet's score says its coins doubled from its entry within six hours. It
does not say the wallet made money — peaks are not realisable, and pump.fun's
leaderboard claimed $1M+ for wallets whose on-chain realised SOL was negative.
The base rate is reported beside every score, because if being early into
anything doubles a third of the time then a wallet at 35% is noise wearing a
rosette.

## The control is the experiment

KOL-02 draws from the SAME pool at the SAME size with the SAME exit and does
not care who bought first. If the two end level, the ranking is worthless —
and on this platform the control has won more often than not.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from decimal import Decimal as D

from app.lab.spec import Condition, Exits, Strategy, rules_json

SPEC_VERSION = "kol-1.0.0"

STARTING_EQUITY = D("100")
CYCLE_TARGET_MULTIPLE = D("1.10")
FAILURE_EQUITY_FLOOR = D("50")

SIZE_USD = D("10")
MAX_CONCURRENT = 10

#: Same hold as the Movers Lab, for the same measured reason: the median time
#: from a fillable entry to a 2x was 19.7 minutes.
TIME_EXIT_HOURS = 0.5

#: Depth at which a round trip is ~0.78% rather than a guess, from 142,479
#: Jupiter quotes. Both arms carry it, so the control is not quietly buying
#: cheaper depth than the signal.
MIN_LIQUIDITY_USD = D("100000")

_POOL: tuple[Condition, ...] = (
    Condition(feature="is_pumpfun", op="gte", value=D("1"),
              reason="not_a_pumpfun_token"),
    Condition(feature="liq", op="gte", value=MIN_LIQUIDITY_USD,
              reason="too_thin_to_fill_honestly"),
)

#: The whole hypothesis, in one line: somebody we follow got here first.
_FOLLOWED = Condition(feature="kol_early", op="gte", value=D("1"),
                      reason="no_followed_wallet_bought_early")


def _wallet(sid: str, name: str, entry: tuple[Condition, ...],
            hypothesis: str, evidence: str) -> Strategy:
    return Strategy(
        id=sid, name=name, hypothesis=hypothesis,
        # Ten minutes, matching the Movers Lab: the median token reaches its
        # tenth print at 9.8 minutes, and the early-buyer rows are written
        # when the coin crosses $100k, so both are readable by then.
        checkpoint_minutes=10,
        entry=entry,
        size_usd=SIZE_USD, max_concurrent=MAX_CONCURRENT,
        max_exposure_usd=STARTING_EQUITY,
        exits=Exits(take_profit=None, time_exit_hours=TIME_EXIT_HOURS),
        evidence=evidence, overfit_risk="UNTESTED",
    )


STRATEGIES: tuple[Strategy, ...] = (
    _wallet("KOL-01", "KOL-FOLLOWED", (*_POOL, _FOLLOWED),
            "A coin that a repeatedly-early wallet bought first outruns one "
            "from the same pool that no followed wallet touched.",
            "RANKED_ON_PRIOR_WINDOW_TRADED_FORWARD"),
    _wallet("KOL-02", "KOL-CONTROL", _POOL,
            "Depth and provenance are the whole effect, and who bought first "
            "adds nothing.",
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

assert len(STRATEGIES) == 2, "the signal and its control"
assert sum(1 for s in STRATEGIES if s.evidence == "CONTROL") == 1
# THE property: the two wallets differ by exactly one condition.
_a, _b = (set(str(c) for c in s.entry) for s in STRATEGIES)
assert _a - _b == {str(_FOLLOWED)} and _b - _a == set(), (
    "the control must differ from the signal in the followed-wallet condition ALONE"
)
assert all(s.exits.take_profit is None for s in STRATEGIES), (
    "a take-profit would measure the exit rather than the entry"
)
assert all(s.size_usd * s.max_concurrent <= STARTING_EQUITY for s in STRATEGIES)
assert len(SPEC_VERSION) <= 16, "lab_tournaments.spec_version is String(16)"

__all__ = ["BY_ID", "CYCLE_TARGET_MULTIPLE", "FAILURE_EQUITY_FLOOR",
           "MIN_LIQUIDITY_USD", "SPEC_HASH", "SPEC_VERSION", "STARTING_EQUITY",
           "STRATEGIES", "TIME_EXIT_HOURS", "rules_json"]
