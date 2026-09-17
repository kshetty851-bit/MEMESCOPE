"""The five v2 runners, as five values.

WHAT CHANGED FROM v1, AND WHY THE BOOKS ARE RENAMED
---------------------------------------------------
v1 spent three of its five books (A, C, D) on near-identical rule sets that
differed only in a liquidity-stop flag and a daily-breaker flag. All three
landed between -42% and -53%, so those two flags were shown to be irrelevant
and three books bought one answer.

v2 spends each book on a different question, and holds the entry gate constant
across four of them so the gate itself is what A2 measures against v1's A:

    A2  What does the entry gate alone do? Directly comparable to v1's A.
    B2  Does the gate push the best v1 book over the line?
    C2  Does scaling out beat a hard cap, given losers go to -100%?
    D2  Is the +30% cap cutting off the tail that pays for the rugs?
    E2  Does a much harder gate work, at a much lower trade count?

The codes are `A2`-`E2` rather than `A`-`E` because the ledger is keyed on
them and a v2 book is not a continuation of a v1 book. v1's rows were archived
and removed before these were activated; reusing the letters would have made
two different experiments share a column.

WHY VALUES AND NOT FIVE CLASSES
-------------------------------
Unchanged from v1, and still the point: one engine, five configurations, so a
difference in the record is a difference in the rule rather than a difference
in which copy of the tick loop was edited last.

A NOTE ON THE GATE THESE ALL CARRY
----------------------------------
`entry_gate.py` documents in full that the gate was replayed over v1's own
closed trades before any of this was written, and that the replay refuted the
premise. This is a forward run of a rule the backward evidence says does not
work. That is a deliberate choice, not an oversight.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from app.labs.rafiq import entry_gate
from app.labs.rafiq.adapters.engine import ExitRules
from app.labs.rafiq.adapters.profiles import StrategyProfile
from app.labs.rafiq.adapters.sizing import SizingPolicy
from app.labs.rafiq.entry_gate import GateThresholds
from app.labs.rafiq.g1 import strategy_G1 as g1
from app.labs.rafiq.strategies import strategy_e_ensemble as e
from app.labs.rafiq.strategies import strategy_f2
from app.labs.rafiq.strategies.strategy_a_hard_stop import HARD_STOP_GUARD
from app.labs.rafiq.strategies.strategy_b_time_boxed import TIME_BOXED_EXIT
from app.labs.rafiq.strategies.strategy_c_volatility_adjusted import (
    sized_for_liquidity,
    stop_distance_for,
)
from app.labs.rafiq.strategies.strategy_e_ensemble import ENSEMBLE_GUARDED


@dataclass(frozen=True, slots=True)
class Leg:
    """One slice of a position, with its own way out.

    A single-leg book is the ordinary case and carries `fraction = 1`. C2 is
    the only book with two, which is the whole question it asks: half the
    position takes a fixed +30%, the other half has no target at all and
    leaves on the trail.

    The stop and the max hold are NOT per-leg — the spec gives C2 one stop and
    one hold, and a leg that could outlive its sibling would be a different
    experiment from the one being run.
    """

    fraction: Decimal
    take_profit_mult: Decimal | None
    trailing_frac: Decimal | None

    @property
    def canonical(self) -> dict:
        return {"fraction": str(self.fraction),
                "take_profit_mult": (None if self.take_profit_mult is None
                                     else str(self.take_profit_mult)),
                "trailing_frac": (None if self.trailing_frac is None
                                  else str(self.trailing_frac))}


#: C2 and D2 are exit shapes v1 never ran, so they are composed here from A's
#: sizing, simulation and entry threshold rather than given files of their own:
#: everything they specify, they specify in `exits` and `legs` below, and
#: borrowing the rest keeps them comparable to A2 on every axis but the one
#: under test. `take_profit_mult=None` on the profile is the honest value for
#: a book whose target lives on its legs — D2 has no target at all.
def _over_a(lane: str, *, stop_mult: Decimal, trailing_frac: Decimal | None,
            hold: timedelta, take_profit_mult: Decimal | None) -> StrategyProfile:
    return StrategyProfile(
        lane=lane,
        exits=ExitRules(take_profit_mult=take_profit_mult, stop_mult=stop_mult,
                        trailing_frac=trailing_frac, max_hold=hold),
        sizing=HARD_STOP_GUARD.sizing,
        sim=HARD_STOP_GUARD.sim,
        entry_threshold=HARD_STOP_GUARD.entry_threshold,
        designed_breakeven_win_rate=None,  # no fixed target: not defined here
    )


PARTIAL_EXIT = _over_a("partial_exit", stop_mult=Decimal("0.88"),
                       trailing_frac=Decimal("0.25"), hold=timedelta(hours=4),
                       take_profit_mult=None)

NO_CAP = _over_a("no_cap", stop_mult=Decimal("0.88"),
                 trailing_frac=Decimal("0.25"), hold=timedelta(hours=4),
                 take_profit_mult=None)


@dataclass(frozen=True, slots=True)
class LabStrategy:
    """One runner. `code` is what the ledger and the page call it."""

    code: str
    name: str
    #: The one-line question this book exists to answer. Shown on the page, so
    #: a reader never has to reconstruct why a column is there.
    question: str
    profile: StrategyProfile
    #: How the position is split at entry. One leg for every book but C2.
    legs: tuple[Leg, ...]
    #: The entry conditions. Identical across A2-D2 on purpose; E2 is stricter.
    gate: GateThresholds = entry_gate.DEFAULT
    #: True for E2: the stop distance and the size come from C's liquidity
    #: policy instead of the profile's flat `stop_mult`.
    liquidity_derived_risk: bool = False
    #: True for E2: the daily breaker is consulted before every entry.
    daily_breaker: bool = False
    #: True for E2: consensus + manipulation veto gate the entry.
    consensus_gate: bool = False
    #: False for a retired book. It still SETTLES its open positions under the
    #: geometry frozen on each row — force-closing would sell into exactly the
    #: drained pools that produce the 0.0003x fills — but it opens nothing new.
    #:
    #: Deliberately OUTSIDE `digest`: retiring a book must not change the hash
    #: its record was opened under, or the runner halts on drift it caused
    #: itself. Verified: A2-E2's digests are unchanged by this field.
    enters: bool = True
    #: F2 only. Rafiq's own `EquityFloor` level: at or below this the book
    #: stops OPENING positions. It never force-closes — selling into a drained
    #: pool is what produces the 0.0003x fills, so the floor deliberately
    #: exposes no liquidate path and `test_floor_does_not_expose_a_force_close`
    #: keeps it that way.
    #:
    #: $900 and not $1,000 on Karthik's explicit instruction. At $1,000 on a
    #: $1,000 book the first losing trade halts it permanently and the sample
    #: is one trade; $900 gives F2 room for about ninety $10 losses, which is
    #: the smallest floor that can still collect a testable sample.
    equity_floor: Decimal | None = None
    #: F2 only. Rafiq's `MAX_TRADES_PER_DAY`. Counted per calendar day in UTC
    #: against positions actually opened, because an in-memory counter would
    #: reset on every worker restart and the cap would quietly stop binding.
    max_trades_per_day: int | None = None
    #: G1 only. Exits come from `strategy_G1.evaluate` (partial sale, uncapped
    #: runner), sizing from `strategy_G1.position_size`, and the book carries
    #: `strategy_G1.EquityRatchet`. The digest is then the canonical JSON's.
    g1: bool = False

    @property
    def digest(self) -> str:
        """A stable hash of every constant that changes this strategy's result.

        Written onto the ledger row at activation and compared on every tick.
        Changing a number here is not a tweak — it is a new record. The gate
        thresholds are inside the hash because a gate that admits a different
        population produces a different book.

        G1's rules live in its canonical JSON, so G1 hashes that — every value
        in it, and none of the `_`-prefixed prose.
        """
        if self.g1:
            return hashlib.sha256(json.dumps(
                {"code": self.code, "config": _rules(G1_CONFIG)},
                sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        x, s = self.profile.exits, self.profile.sizing
        canonical = {
            "code": self.code, "lane": self.profile.lane,
            "take_profit_mult": (None if x.take_profit_mult is None
                                 else str(x.take_profit_mult)),
            "stop_mult": str(x.stop_mult),
            "trailing_frac": None if x.trailing_frac is None else str(x.trailing_frac),
            "max_hold_seconds": x.max_hold.total_seconds(),
            "legs": [leg.canonical for leg in self.legs],
            "risk_per_trade": str(s.risk_per_trade),
            "max_notional_usd": str(s.max_notional_usd),
            "entry_threshold": str(self.profile.entry_threshold),
            "entry_gate": self.gate.canonical,
            "liquidity_derived_risk": self.liquidity_derived_risk,
            "daily_breaker": self.daily_breaker,
            "consensus_gate": self.consensus_gate,
            "volatility_policy": (
                _volatility_canonical() if self.liquidity_derived_risk else None
            ),
            "breaker_policy": _breaker_canonical() if self.daily_breaker else None,
        }
        # Added only when set, so a book that has neither hashes exactly as it
        # did before these fields existed. They ARE rules — they change which
        # candidates become positions — so for the book that has them they
        # belong in the hash, unlike `enters`.
        if self.equity_floor is not None:
            canonical["equity_floor"] = str(self.equity_floor)
        if self.max_trades_per_day is not None:
            canonical["max_trades_per_day"] = self.max_trades_per_day
        return hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


def _volatility_canonical() -> dict:
    p = e.VOLATILITY_POLICY
    return {"base_stop_pct": str(p.base_stop_pct),
            "reference_liquidity_usd": str(p.reference_liquidity_usd),
            "min_stop_pct": str(p.min_stop_pct), "max_stop_pct": str(p.max_stop_pct),
            "sensitivity": str(p.sensitivity)}


def _breaker_canonical() -> dict:
    p = e.DAILY_POLICY
    return {"max_daily_drawdown": str(p.max_daily_drawdown),
            "max_daily_realised_loss": str(p.max_daily_realised_loss)}


def _rules(node):
    """The config without its commentary: every `_`-prefixed key dropped."""
    if isinstance(node, dict):
        return {k: _rules(v) for k, v in node.items() if not k.startswith("_")}
    return node


#: G1's canonical config, as delivered. The runner reads the values that
#: `strategy_G1.py` does not carry (the impact ceiling, the score floor, the
#: ratchet's opening floor, the breaker level) from here, and
#: `test_g1_engine.py` holds the ones it does carry equal to it.
G1_CONFIG: dict = json.loads(
    (pathlib.Path(__file__).parent / "g1" / "strategy_G1.json").read_text())


def _pct(value) -> Decimal:
    return Decimal(str(value)) / 100


_G1_EXITS = G1_CONFIG["exits"]
_G1_GATE = G1_CONFIG["entry_gate"]

#: The impact ceiling and the two floors are F2's; what differs is that a
#: missing market cap does not refuse — `strategy_G1.admits` reports it as a
#: check it could not run, and the runner honours that.
G1_GATE = GateThresholds(
    min_liquidity_usd=Decimal(str(_G1_GATE["min_liquidity_usd"])),
    min_market_cap_usd=Decimal(str(_G1_GATE["min_market_cap_usd"])),
    max_entry_price_impact_pct=Decimal(str(_G1_GATE["max_impact_pct"])),
    reject_if_market_cap_unknown=False,
)

#: The ratchet's opening state: high-water at the starting book, floor at the
#: config's $950 — `EquityRatchet`'s own defaults, which the JSON restates.
G1_STARTING_EQUITY = Decimal(str(G1_CONFIG["starting_capital_usd"]))
G1_INITIAL_FLOOR = Decimal(str(G1_CONFIG["equity_ratchet"]["initial_floor_usd"]))

#: What the page shows for G1. Only `entry_threshold` and `max_hold` are read
#: by the runner; the exits themselves are `strategy_G1.evaluate`'s.
MOONSHOT = StrategyProfile(
    lane="moonshot",
    exits=ExitRules(take_profit_mult=None, stop_mult=Decimal(str(_G1_EXITS["stop"])),
                    trailing_frac=Decimal(str(_G1_EXITS["runner"]["trail_frac"])),
                    max_hold=timedelta(minutes=_G1_EXITS["max_hold_minutes"])),
    sizing=SizingPolicy(
        risk_per_trade=_pct(G1_CONFIG["sizing"]["position_pct_of_book"]),
        max_pool_fraction=strategy_f2.LOSS_BOUNDED.sizing.max_pool_fraction,
        max_impact_pct=Decimal(str(_G1_GATE["max_impact_pct"])),
        exit_stress_factor=strategy_f2.LOSS_BOUNDED.sizing.exit_stress_factor,
        max_notional_usd=Decimal(str(G1_CONFIG["sizing"]["position_usd"])),
    ),
    sim=strategy_f2.LOSS_BOUNDED.sim,
    entry_threshold=Decimal(G1_CONFIG["entry_score_min"]),
)


_WHOLE = Decimal(1)
_HALF = Decimal("0.5")

#: The run A2-F2 traded in. Archived: nothing in it opens a position again.
ARCHIVED_RUN = "F2-and-earlier"
#: G1's run. The date is the day its config was frozen (`generated` in the
#: JSON); `activated_at` on the row records when it actually started.
G1_RUN = f"G1-{G1_CONFIG['generated']}"
#: The only run the beat trades.
CURRENT_RUN = G1_RUN

#: A2-F2, as they traded. Kept so an archived book still renders and its
#: digest still verifies; `enters` is off because the run is closed.
ARCHIVED_STRATEGIES: tuple[LabStrategy, ...] = (
    # A2 changes exactly one thing against v1's A: the gate. It is the control,
    # and if it does not clearly beat A's -53% the rest of this tells us little.
    LabStrategy("A2", "Gate only",
                "What does the entry gate alone do, against v1's A?",
                HARD_STOP_GUARD,
                legs=(Leg(_WHOLE, Decimal("1.30"), Decimal("0.20")),),
                enters=False),

    # B was v1's only book near breakeven before costs (-0.3%/trade gross over
    # 151 trades), so v2 treats B as the template rather than A. Same rules,
    # gate added.
    LabStrategy("B2", "Fast and cheap, gated",
                "Does the gate push the best v1 book over the line?",
                TIME_BOXED_EXIT,
                legs=(Leg(_WHOLE, Decimal("1.20"), None),), enters=False),

    # C2's two legs ARE the question. Half takes the same +30% A2 takes; half
    # has no target and can only leave on the trail, the stop or the hold.
    LabStrategy("C2", "Partial exit",
                "Does scaling out beat a hard cap, given losers go to -100%?",
                PARTIAL_EXIT,
                legs=(Leg(_HALF, Decimal("1.30"), None),
                      Leg(_HALF, None, Decimal("0.25"))), enters=False),

    # v1 closed trades at +29% that would have run to +352%, +373%, +261%.
    # D2 removes the cap entirely and shortens the hold to pay for it.
    LabStrategy("D2", "No cap",
                "Is the +30% cap cutting off the tail that pays for the rugs?",
                NO_CAP,
                legs=(Leg(_WHOLE, None, Decimal("0.25")),), enters=False),

    # E2 keeps v1 E's three guards and runs the gate far stricter on top. It is
    # expected to trade rarely — v1's E closed nothing at all in 19 hours on
    # dev — and a low trade count is the cost of the question it asks.
    LabStrategy("E2", "Strict",
                "Does a much harder gate work, at a much lower trade count?",
                ENSEMBLE_GUARDED,
                legs=(Leg(_WHOLE, Decimal("1.30"), Decimal("0.20")),),
                gate=entry_gate.STRICT,
                liquidity_derived_risk=True, daily_breaker=True,
                consensus_gate=True, enters=False),

    # F2 is the active book, and it is NOT a sixth exit variant. A2-E2 settled
    # that question: 98 of their 102 total losses exited on `stop`, at a median
    # 0.0003x the stop price with zero friction, so the price was already gone
    # and no exit rule could have recovered it. F2 therefore keeps E2's exits
    # unchanged — E2 had the best survivor return of any book at +14.9% — and
    # changes only arithmetic:
    #
    #   $10 instead of $50, so a total loss costs 1% of book and not 5%;
    #   20 entries a day against v2's observed 588;
    #   a $900 floor that halts new entries and never force-closes.
    #
    # None of that creates an edge. It keeps the book alive long enough to
    # collect the ~200 trades that would test whether holder concentration or
    # LP status separate total losses before entry, which is the only number
    # that matters and the one nothing here moves.
    LabStrategy("F2", "Loss bounded",
                "Does bounding size and count keep the book alive long enough "
                "to collect a testable sample?",
                strategy_f2.LOSS_BOUNDED,
                legs=(Leg(_WHOLE, Decimal("1.30"), Decimal("0.20")),),
                gate=entry_gate.F2, daily_breaker=True,
                equity_floor=strategy_f2.FLOOR_WITH_ROOM.floor_usd,
                max_trades_per_day=strategy_f2.MAX_TRADES_PER_DAY, enters=False),
)

#: G1 replaces F2 in the sixth slot and is the only book that opens
#: positions. One leg: its partial sale is bookkeeping on the row, not a
#: second position, because the 25% it keeps is decided at +30%, not at entry.
#: No static floor — the ratchet is its floor — and E's daily breaker, which
#: is the 5% mark-to-market line the config asks for.
G1 = LabStrategy(
    "G1", "Moonshot",
    "Does resolving in 45 minutes, with an uncapped runner and a floor that "
    "only moves up, make money per trade?",
    MOONSHOT, legs=(Leg(_WHOLE, None, g1.RUNNER_TRAIL),), gate=G1_GATE,
    daily_breaker=True, g1=True)

RUNS: dict[str, tuple[LabStrategy, ...]] = {ARCHIVED_RUN: ARCHIVED_STRATEGIES,
                                             G1_RUN: (G1,)}

#: The books the lab trades NOW. HQ's analyst desks seat themselves from this
#: name (`app.hq_ops.desk.strategy_for`) and read "as the lab is registered
#: now", so it must follow the current run: pointed at the archive, every
#: desk reported "not registered" for books the analyst looks up in G1's run.
STRATEGIES: tuple[LabStrategy, ...] = RUNS[CURRENT_RUN]

BY_CODE = {s.code: s for run in RUNS.values() for s in run}


def stop_pct_for(strategy: LabStrategy,
                 liquidity_usd: Decimal | None) -> Decimal | None:
    """Percent stop distance for this candidate, or None if it cannot be set.

    E2 defers to Rafiq's `stop_distance_for`, which returns None for an
    unpriceable pool. None means "cannot size this trade" — the caller declines
    it rather than reaching for a fallback number.
    """
    if strategy.liquidity_derived_risk:
        return stop_distance_for(liquidity_usd, policy=e.VOLATILITY_POLICY)
    return (Decimal(1) - strategy.profile.exits.stop_mult) * 100


def notional_for(strategy: LabStrategy, *, equity: Decimal,
                 liquidity_usd: Decimal | None,
                 stop_pct: Decimal | None) -> Decimal:
    """What this strategy stakes on this candidate, across all its legs.

    The figure is the WHOLE position. C2 splits it afterwards; it is not sized
    per leg, because a gate applied to half a position is a different gate, and
    two $25 buys pay less impact than the one $50 buy this book actually makes.
    """
    if stop_pct is None or stop_pct <= 0:
        return Decimal(0)
    cap = strategy.profile.sizing.max_notional_usd
    if strategy.liquidity_derived_risk:
        return sized_for_liquidity(
            equity, liquidity_usd, stop_pct=stop_pct,
            risk_per_trade=strategy.profile.sizing.risk_per_trade,
            max_notional_usd=cap)
    if liquidity_usd is None or liquidity_usd <= 0:
        return Decimal(0)
    return min(equity * strategy.profile.sizing.risk_per_trade / (stop_pct / 100), cap)


def max_hold_for(strategy: LabStrategy) -> timedelta:
    return strategy.profile.exits.max_hold


assert {s.code for s in ARCHIVED_STRATEGIES} == {"A2", "B2", "C2", "D2", "E2", "F2"}, \
    "the archived run must hold exactly the six v2 books"
assert len(BY_CODE) == sum(len(run) for run in RUNS.values()), \
    "a code may name one book only, across every run"
assert [s.code for s in RUNS[CURRENT_RUN] if s.enters] == ["G1"], \
    "G1 is the only book that opens positions"
assert all(sum((leg.fraction for leg in s.legs), Decimal(0)) == 1
           for s in BY_CODE.values()), \
    "every book's legs must account for exactly the whole position"
