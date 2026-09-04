"""MOMENTUM V2 — high momentum, real depth, and a wallet target at +10%.

Twenty $100 wallets. Each trades one momentum rule at one liquidity floor and
banks its whole book the moment total equity is up 10%, then compounds from
what it actually realised — the Compound Lab's mechanism, run across a grid
instead of on one wallet.

## What it is asking

V7 varied the TAKE-PROFIT and held the entry roughly fixed. The Compound Lab
varied neither and moved the target onto the wallet. This varies the ENTRY, and
asks the question those two could not: does selecting for momentum and depth
produce a book that reaches +10% often enough to compound, where the earlier
entry rules did not?

## The grid, and why it is a grid

Three momentum definitions against six liquidity floors, so a result can be
attributed. If one cell wins and its neighbours do not, that is noise; if a
whole row or column moves together, that is the rule or the floor doing
something. A hand-picked set of twenty thresholds could not tell those apart —
which is exactly how the mcap filter looked like an 8.51 profit factor before
split-half took it to 0.72.

  momentum                                     liquidity floor
  PRICE  ret_15m >= +10%                       $100k
  VOL    vol_accel >= +50%                     $200k
  FLOW   sell_share_15m <= 40% and 40+ trades  $300k
                                               $500k
                                               $750k
                                               $1M

3 x 6 = 18, plus TWO random controls at $300k and $1M.

**The controls are inside the twenty on purpose.** Every no-edge finding on
this platform was produced by a control, not by a strategy — the random arm has
beaten the designed ones twice. Eighteen momentum cells with nothing to compare
against would produce a leaderboard nobody could interpret: the top wallet
always looks good, and the only question that matters is whether it looks
better than buying at random from the same pool under the same ratchet.

## pump.fun only

Every wallet requires `is_pumpfun`, INCLUDING the two controls. A control that
could buy outside the universe under test would not be a control for this
experiment — it would be measuring a different pool of tokens as well as a
different rule, and any difference between it and the momentum arms could be
either one.

Provenance is `discovered_tokens.source_program`: pump.fun's bonding curve, or
PumpSwap, which is its own AMM for pools that never touch the curve. On
production those are 856,210 and 34,995 tokens; `jupiter_verified` (173) is
excluded, and so is anything else that appears later.

## Sizing

$100 a wallet, $20 a position, five open. Identical to the Compound Lab so the
two are comparable — a different size would confound the entry rule with the
position count.

## What it inherits, and what that means

No per-position take-profit: the wallet target is the exit, and a level exit
would cut a winner while the wallet was still short of its 10%. Positions stay
bounded by a six-hour clock so nothing is held forever waiting for a target
that never comes. Stops are absent because on these tokens they filled at a
median of $0.03 against a nominal -25%.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from decimal import Decimal as D

from app.lab.spec import Condition, Exits, Strategy, rules_json

SPEC_VERSION = "momentum-2.0.0"

STARTING_EQUITY = D("100")
CYCLE_TARGET_MULTIPLE = D("1.10")
FAILURE_EQUITY_FLOOR = D("50")

SIZE_USD = D("20")
MAX_CONCURRENT = 5

#: (key, label, extra conditions beyond the liquidity floor)
_MOMENTUM: tuple[tuple[str, str, tuple[Condition, ...]], ...] = (
    ("PRICE", "price up 10% in 15 min", (
        Condition(feature="ret_15m", op="gte", value=D("0.10"),
                  reason="ret_15m_below_10pct"),
    )),
    ("VOL", "5-minute volume up 50%", (
        Condition(feature="vol_accel", op="gte", value=D("0.50"),
                  reason="vol_accel_below_50pct"),
    )),
    ("FLOW", "buy-dominated and busy", (
        Condition(feature="sell_share_15m", op="lte", value=D("0.40"),
                  reason="sell_share_above_0_40"),
        Condition(feature="tx_15m", op="gte", value=D("40"),
                  reason="fewer_than_40_trades_15m"),
    )),
)

#: Liquidity floors. The lowest is deliberately below anything V7 traded: if
#: depth is what matters, the bottom of this column should be visibly worse,
#: and a grid that only spans the values already believed in cannot show that.
_LIQUIDITY: tuple[D, ...] = (D("100000"), D("200000"), D("300000"),
                             D("500000"), D("750000"), D("1000000"))


def _liq(floor: D) -> Condition:
    return Condition(feature="liq", op="gte", value=floor,
                     reason=f"liq_below_{int(floor)}")


#: Applied to EVERY wallet including the controls. The engine exposes
#: `is_pumpfun` as 1 or 0 from `discovered_tokens.source_program`.
_PUMPFUN = Condition(feature="is_pumpfun", op="gte", value=D("1"),
                     reason="not_a_pumpfun_token")


def _label(floor: D) -> str:
    return f"{int(floor) // 1000}K" if floor < 1_000_000 else "1M"


def _build() -> tuple[Strategy, ...]:
    out: list[Strategy] = []
    n = 0
    for key, text, conds in _MOMENTUM:
        for floor in _LIQUIDITY:
            n += 1
            out.append(Strategy(
                id=f"MOM-{n:02d}",
                name=f"{key}-{_label(floor)}",
                hypothesis=(
                    f"Tokens with {text} and at least ${int(floor):,} of "
                    "liquidity reach a 10% wallet gain often enough to compound."
                ),
                checkpoint_minutes=30,
                entry=(_PUMPFUN, _liq(floor), *conds),
                size_usd=SIZE_USD, max_concurrent=MAX_CONCURRENT,
                max_exposure_usd=STARTING_EQUITY,
                exits=Exits(take_profit=None, time_exit_hours=6),
                evidence="UNTESTED_FORWARD_GRID",
                overfit_risk="MEDIUM",
            ))
    # The two controls. Same ratchet, same size, no momentum condition — the
    # only thing they lack is the idea being tested.
    for floor in (D("300000"), D("1000000")):
        n += 1
        out.append(Strategy(
            id=f"MOM-{n:02d}",
            name=f"RANDOM-CONTROL-{_label(floor)}",
            hypothesis=(
                "Buying anything above this liquidity floor, with no momentum "
                "condition at all, compounds as well as selecting for momentum."
            ),
            checkpoint_minutes=30,
            entry=(_PUMPFUN, _liq(floor)),
            size_usd=SIZE_USD, max_concurrent=MAX_CONCURRENT,
            max_exposure_usd=STARTING_EQUITY,
            exits=Exits(take_profit=None, time_exit_hours=6),
            evidence="CONTROL",
            overfit_risk="NONE",
        ))
    return tuple(out)


STRATEGIES: tuple[Strategy, ...] = _build()
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

assert len(STRATEGIES) == 20, "twenty wallets"
assert len(_MOMENTUM) * len(_LIQUIDITY) == 18, "a complete 3x6 grid"
assert sum(1 for s in STRATEGIES if s.evidence == "CONTROL") == 2, (
    "the controls are what make the other eighteen interpretable"
)
assert all(s.exits.take_profit is None for s in STRATEGIES), (
    "the wallet target is the exit; a level exit would pre-empt it"
)
assert all(s.size_usd * s.max_concurrent <= STARTING_EQUITY for s in STRATEGIES)
assert len({s.id for s in STRATEGIES}) == 20
assert all(any(c.feature == "is_pumpfun" for c in s.entry) for s in STRATEGIES), (
    "every wallet trades pump.fun only — a control that could buy outside the "
    "universe under test is not a control for this experiment"
)

__all__ = ["BY_ID", "CYCLE_TARGET_MULTIPLE", "FAILURE_EQUITY_FLOOR",
           "SPEC_HASH", "SPEC_VERSION", "STARTING_EQUITY", "STRATEGIES",
           "rules_json"]
