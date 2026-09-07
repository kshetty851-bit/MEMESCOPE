"""DEPTH — twenty wallets that differ in ONE number.

No momentum condition. No score. No flow filter. Every wallet buys any
pump.fun token that clears its liquidity floor at the 30-minute checkpoint,
banks its whole book at +10% and compounds from what it realised. The floors
run from $25k to $1M and that is the only thing separating them.

## Why this experiment and not another entry rule

Ten findings on this platform have now said the same thing: selection does not
move the outcome. V6's twenty hypotheses, V7's take-profit grid, the Compound
ratchet, the copy lab, and Momentum V2's momentum-times-depth grid — in every
one the designed arms failed, and in three of them a RANDOM control beat them.

Momentum V2 was the clearest. Its winner was `RANDOM-CONTROL-1M` at $126.50,
ahead of all eighteen momentum arms, none of which finished above its $100
start. Its identical twin one floor down, `RANDOM-CONTROL-300K`, went to ZERO.
Same rule, same ratchet, same size, same universe; only the floor differed, and
the outcome differed by the entire book.

That is the only structure ten experiments have produced, so it is the one
worth measuring properly rather than assuming.

## What this can and cannot show

It is a DOSE-RESPONSE curve, not an A/B. Twenty floors log-spaced across the
range where the population actually thins, so the question is not "is $1M
better than $300k" — one pair of wallets can differ by luck, and that is
exactly what the V2 result might be. The question is whether equity rises
MONOTONICALLY across twenty points. A trend across twenty is hard to fake; a
gap between two is not.

**The ceiling is real and it is the finding's limit.** Measured over the three
days to 2026-09-07, pump.fun tokens with a live snapshot numbered 18,417 in
total, but only 806 above $100k, 291 above $250k, 29 above $500k and TEN above
$1M. So the top wallets fish in a pond of a few dozen names and will trade
rarely and repeatedly. If a depth effect appears up there, it is an effect over
about ten tokens — which is a watchlist, not a strategy, and this registry says
so rather than letting a reader discover it later.

The ladder therefore stops at $1M. Floors above that were the obvious design
and would have produced wallets with almost nothing to buy.

## Everything else is held constant, deliberately

$100 a wallet, **$5 a position, twenty open**, 30-minute checkpoint, six-hour
time exit, no take-profit, +10% wallet ratchet.

v1 ran $20 x 5 and is kept as the comparison: same twenty floors, same
universe, same target, same horizon, so the ONLY difference between the two
tournaments is position size. That is what makes v1's record worth keeping
rather than deleting.

Note this breaks the earlier equality with Momentum V2, which still runs
$20 x 5. The floors-versus-momentum comparison is now confounded by size; the
v1-versus-v2 comparison is the clean one.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from decimal import Decimal as D

from app.lab.spec import Condition, Exits, Strategy, rules_json

SPEC_VERSION = "depth-2.0.0"

STARTING_EQUITY = D("100")
CYCLE_TARGET_MULTIPLE = D("1.10")
FAILURE_EQUITY_FLOOR = D("50")

#: v2, 2026-09-07. Was $20 x 5.
#:
#: The book is unchanged at $100; only the SLICING moved. It matters because
#: every loss here is total — 39 of 39 deaths in v1 closed at exactly -100% —
#: and at $20 a position ONE death costs a fifth of the wallet, which puts the
#: +10% cycle target out of reach until several wins have repaired it. At $5 a
#: death costs a twentieth, and the target stays reachable.
#:
#: This does NOT change expectancy. Twenty small bets on a negative-mean
#: population have the same expected value as five large ones and merely reach
#: it with less noise. What it changes is the RATCHET's mechanics, which is the
#: thing being tested.
#:
#: It should also fix a flaw v1 exposed: with five slots, adjacent floors held
#: the same top-five tokens and twenty cells produced only NINE distinct books.
#: Twenty slots reach further into each floor's eligible set, so the cells have
#: room to diverge.
SIZE_USD = D("5")
MAX_CONCURRENT = 20

#: Twenty floors, roughly log-spaced from $25k to $1M — the range over which
#: the pump.fun population goes from thousands of tokens to about ten. Round
#: numbers rather than exact powers, because a reader has to hold them in mind.
_FLOORS: tuple[int, ...] = (
    25_000, 30_000, 40_000, 50_000, 65_000,
    80_000, 100_000, 125_000, 150_000, 175_000,
    200_000, 250_000, 300_000, 350_000, 400_000,
    500_000, 600_000, 750_000, 875_000, 1_000_000,
)

#: Same provenance gate as Momentum V2, so the two are comparable and the
#: universe is held constant while the floor moves.
_PUMPFUN = Condition(feature="is_pumpfun", op="gte", value=D("1"),
                     reason="not_a_pumpfun_token")


def _label(floor: int) -> str:
    return f"{floor // 1000}K" if floor < 1_000_000 else "1M"


STRATEGIES: tuple[Strategy, ...] = tuple(
    Strategy(
        id=f"DPT-{i:02d}",
        name=f"DEPTH-{_label(floor)}",
        hypothesis=(
            f"Buying any pump.fun token with at least ${floor:,} of liquidity, "
            "with no other condition, compounds at +10% a cycle."
        ),
        checkpoint_minutes=30,
        entry=(_PUMPFUN,
               Condition(feature="liq", op="gte", value=D(floor),
                         reason=f"liq_below_{floor}")),
        size_usd=SIZE_USD,
        max_concurrent=MAX_CONCURRENT,
        max_exposure_usd=STARTING_EQUITY,
        exits=Exits(take_profit=None, time_exit_hours=6),
        evidence="DOSE_RESPONSE_CELL",
        overfit_risk="NONE",
        note=(
            "No selection of any kind beyond the floor. If this curve is flat, "
            "depth is not the lever either and the search for one should stop."
        ),
    )
    for i, floor in enumerate(_FLOORS, start=1)
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

assert len(STRATEGIES) == 20, "twenty floors"
assert _FLOORS == tuple(sorted(_FLOORS)), "the ladder must read in order"
assert len(set(_FLOORS)) == 20, "no duplicate floors"
# THE property of this experiment: one variable, and one only.
for _s in STRATEGIES:
    assert len(_s.entry) == 2, f"{_s.id} has a condition beyond the floor"
    assert {c.feature for c in _s.entry} == {"is_pumpfun", "liq"}, _s.id
assert len({(s.size_usd, s.max_concurrent, s.checkpoint_minutes,
             s.exits.time_exit_hours, s.exits.take_profit)
            for s in STRATEGIES}) == 1, "only the floor may vary"

__all__ = ["BY_ID", "CYCLE_TARGET_MULTIPLE", "FAILURE_EQUITY_FLOOR",
           "SPEC_HASH", "SPEC_VERSION", "STARTING_EQUITY", "STRATEGIES",
           "rules_json"]
