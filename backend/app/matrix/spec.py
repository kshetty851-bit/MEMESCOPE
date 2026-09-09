"""Two populations on one board, as a FACTORIAL rather than a horse race.

The instruction was to run both fresh launches and 24-hour-old tokens, in
separate sections, with roughly twenty-five arms, and see who wins.

"Who wins" out of twenty-five unrelated strategies is a question the data
cannot answer: with that many books the best line is very probably noise, and
this platform has already paid for that lesson — V6 ran twenty wallets and
eighteen finished below the failure floor. So the arms are not twenty-five
ideas. They are a 2 x 4 x 3 grid in which every arm differs from its
neighbours in EXACTLY ONE dimension:

    population   FRESH (radar, pump-suffixed) | AGED (deep AMMs, >= 24h)
    clock        5 min | 15 min | 30 min | none (the wallet ratchet alone)
    book shape   $2 x 50 | $10 x 10 | $20 x 5

Twenty-four arms. A difference between two of them is attributable to the one
thing that differs, and a difference along a whole row or column is a
dose-response rather than a winner. That is the only way a board this wide
says anything.

## The two populations, and why they need different sources

They are mutually exclusive by construction, which is why they cannot be one
section. Across 148 coins the movers labs judged, the median age at checkpoint
was 1.26 HOURS and the oldest was 18.5 — not one reached 24. Radar admits
fresh launches, so an age filter on that stream rejects everything.

    FRESH  source=radar    + mint must end in "pump" (the launchpad's suffix)
    AGED   source=deepamm  + age_hours >= 24

`deepamm` samples established Raydium, Orca, Meteora and MetaDAO markets, which
are older than a day by construction; the age condition is carried anyway so
the claim is enforced rather than assumed.

## The honest prior for the AGED section

Established tokens have been measured here before. Track Record V2 put a
confirmed-breakout entry at 2.73pp WORSE than a random bar in the same tokens,
across all seven parameterisations, best OOS PF 0.54 against 0.50 on the
pump.fun population — changing the population moved profitability not at all.
This section is run to find out whether the CLOCK behaves differently there,
not because the population is expected to win.

## Every arm carries the +10% wallet ratchet

`CompoundService` banks each wallet at CYCLE_TARGET_MULTIPLE and compounds from
REALISED equity, so $100 -> $110 -> $121. For the no-clock arms it is the only
exit, which is the arrangement the operator asked for. For the rest it sits
alongside the clock, exactly as it does in the movers lab.

WHAT THE NO-CLOCK ARMS RISK: a position is released only when the wallet banks
or the token dies. A book fully deployed in coins that neither rise 10% nor die
is locked indefinitely. That is the rule as asked for, and the failure mode is
recorded here rather than discovered later.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from decimal import Decimal as D

from app.lab.spec import Condition, Exits, Strategy, rules_json

SPEC_VERSION = "matrix-1.0.0"

STARTING_EQUITY = D("100")
CYCLE_TARGET_MULTIPLE = D("1.10")
FAILURE_EQUITY_FLOOR = D("50")

#: Depth floor, shared by both sections so the populations differ in age and
#: venue rather than in what counts as tradeable.
MIN_LIQUIDITY_USD = D("100000")

#: The AGED section's threshold, as instructed.
MIN_AGE_HOURS = D("24")

#: Judged ten minutes after admission, matching the movers lab: the research
#: that motivated these entries read its quantities at a token's tenth print,
#: and the median token reaches that 9.8 minutes after first sight.
CHECKPOINT_MINUTES = 10

#: THE THREE AXES.
POPULATIONS = ("F", "A")
CLOCKS: tuple[tuple[str, float | None], ...] = (
    ("05", 5 / 60), ("15", 15 / 60), ("30", 0.5), ("NC", None),
)
SHAPES: tuple[tuple[D, int], ...] = ((D("2"), 50), (D("10"), 10), (D("20"), 5))

_FRESH = (
    Condition(feature="mint_suffix_pump", op="gte", value=D("1"),
              reason="mint_not_pump_suffixed"),
    Condition(feature="liq", op="gte", value=MIN_LIQUIDITY_USD,
              reason="liq_below_100k"),
)
_AGED = (
    Condition(feature="age_hours", op="gte", value=MIN_AGE_HOURS,
              reason="younger_than_24h"),
    Condition(feature="liq", op="gte", value=MIN_LIQUIDITY_USD,
              reason="liq_below_100k"),
)
ENTRY_BY_POPULATION = {"F": _FRESH, "A": _AGED}
SOURCE_BY_POPULATION = {"F": "radar", "A": "deepamm"}

#: The AGED section samples a fixed universe, so it must be allowed to redraw a
#: token after a cooldown or it exhausts that universe in one burst. Keyed by
#: SOURCE, so the fresh section — where every candidate is a one-time launch
#: event — can never redraw.
REJUDGE_BY_SOURCE = {"deepamm": __import__("datetime").timedelta(hours=6)}
SAMPLE_PER_TICK = 1
DEEP_VENUES = ("raydium", "orca", "meteora", "metadao")


def _arm(pop: str, clock_id: str, clock: float | None,
         stake: D, slots: int) -> Strategy:
    section = "FRESH" if pop == "F" else "AGED"
    held = "no clock" if clock is None else f"{clock_id} min"
    return Strategy(
        id=f"{pop}-{clock_id}-{int(stake)}",
        name=f"{section} {held} ${int(stake)}x{slots}",
        hypothesis=(
            f"On {section.lower()} coins, holding {held} with a +10% wallet "
            f"ratchet and ${int(stake)} across {slots} returns more than it costs."
        ),
        checkpoint_minutes=CHECKPOINT_MINUTES,
        entry=ENTRY_BY_POPULATION[pop],
        size_usd=stake, max_concurrent=slots,
        max_exposure_usd=stake * slots,
        # No take-profit anywhere: the wallet target is the profit rule, and a
        # per-position one would decide trades before the clock did and make
        # the clock axis measure itself.
        exits=Exits(take_profit=None, time_exit_hours=clock),
        evidence=("TRACK_RECORD_V2_PUT_THIS_POPULATION_2.73pp_BELOW_RANDOM"
                  if pop == "A" else "MOVERS_RECORD_FAVOURED_PUMP_SUFFIXED"),
        overfit_risk="UNTESTED",
    )


STRATEGIES: tuple[Strategy, ...] = tuple(
    _arm(pop, cid, clock, stake, slots)
    for pop in POPULATIONS
    for cid, clock in CLOCKS
    for stake, slots in SHAPES
)

BY_ID = {s.id: s for s in STRATEGIES}

SOURCE_BY_STRATEGY = {s.id: SOURCE_BY_POPULATION[s.id.split("-")[0]]
                      for s in STRATEGIES}


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
         "sources": SOURCE_BY_STRATEGY,
         "strategies": [clean(s) for s in STRATEGIES]},
        sort_keys=True, separators=(",", ":"), default=str,
    )


SPEC_HASH = hashlib.sha256(_canonical().encode()).hexdigest()

assert len(STRATEGIES) == 24, "2 populations x 4 clocks x 3 shapes"
assert len(BY_ID) == 24, "arm ids must be unique"
assert all(len(s.id) <= 8 for s in STRATEGIES), (
    "strategy_id is varchar(8) in lab_decisions; a longer id fails on insert"
)
# THE factorial property: for any two arms differing in one axis, everything
# else is identical. Checked on the clock axis, which is the one most likely to
# be edited by hand.
for _stake, _slots in SHAPES:
    for _pop in POPULATIONS:
        _row = [s for s in STRATEGIES
                if s.id.startswith(_pop) and s.size_usd == _stake]
        assert len({s.entry for s in _row}) == 1, (
            "arms in one row must share an entry, or the clock axis measures "
            "the entry too"
        )
        assert len({s.exits.time_exit_hours for s in _row}) == 4, (
            "a row must span all four clocks exactly once"
        )
assert all(s.exits.take_profit is None for s in STRATEGIES), (
    "a per-position target would decide trades before the clock did"
)
assert all(s.size_usd * s.max_concurrent == s.max_exposure_usd
           for s in STRATEGIES), "each book must be fully deployable"
assert {SOURCE_BY_STRATEGY[s.id] for s in STRATEGIES} == {"radar", "deepamm"}

__all__ = ["BY_ID", "CYCLE_TARGET_MULTIPLE", "DEEP_VENUES",
           "FAILURE_EQUITY_FLOOR", "MIN_AGE_HOURS", "MIN_LIQUIDITY_USD",
           "REJUDGE_BY_SOURCE", "SAMPLE_PER_TICK", "SOURCE_BY_STRATEGY",
           "SPEC_HASH", "SPEC_VERSION", "STARTING_EQUITY", "STRATEGIES",
           "rules_json"]
