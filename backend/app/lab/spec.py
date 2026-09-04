"""V6 FORWARD STRATEGY LAB — the frozen 20-strategy registry.

Source of truth: `V6_FINAL_20_STRATEGIES v1.0.0`, section 19 of
`~/Projects/memescope-research/v6/V6_STRATEGY_DESIGN.md`. This module is a
faithful transcription of that YAML block, encoded as data rather than as code
so that no strategy can acquire behaviour a reader of the specification cannot
see.

**Immutability.** `SPEC_HASH` is the SHA-256 of the canonical JSON of the whole
registry. It is written onto every strategy row at activation and compared on
every tick; a mismatch stops the Lab rather than scoring tokens against rules
that have drifted from the ones the record was opened under. Changing any
number here is not a tweak — it is V6.x or V7, with a fresh record starting at
zero (mission §5).

Pure data and pure functions. No I/O, no clock, no settings, no randomness.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from decimal import Decimal

#: Bumping this starts a new record at zero. It is not a version of the code.
#:
#: 1.1.0 — the $100 book. Two things forced it, and neither could be applied to a
#: running record without rewriting history, which is why this is a new tournament
#: rather than an edit:
#:
#:   * $1,000 hid the losses. The strategies deploy $80–$200 of it, so 80–90% of
#:     every book sat idle and diluted the percentage. Replayed against the real
#:     price record, the same trades on a $100 book at the SAME $10 positions came
#:     to a mean of −33.6% in nineteen hours, with the random control at −98%. The
#:     book is what the operator will actually fund, so the book is now $100 and
#:     the positions are sized to fit it.
#:
#:   * Fourteen of the nineteen trading strategies had no time exit. A position
#:     that neither reaches its target nor dies simply never returns its capital —
#:     V6-04's first entry was still open nineteen hours later marked at $0.0003 —
#:     and on a small book that is capital removed from the experiment, not a
#:     position. Every trading strategy now has one.
#: **V7 — the take-profit tournament.**
#:
#: V6.1 concluded on 2026-08-29: eighteen of twenty strategies fell below the
#: failure floor and were retired, and every one of the nineteen that traded
#: lost money. That result stands. This asks the question V6 could not, because
#: V6 answered it wrong by construction.
#:
#: Every V6 strategy took profit at 1.25x or 1.5x. `peak_exec_multiple` is
#: recorded only while a position is OPEN, so a position closed at 1.25x records
#: a peak of 1.25x — and the whole registry therefore looked like a population
#: whose tokens never ran. Measured against the raw price path instead, on the
#: Lab's OWN traded tokens over their own six-hour windows:
#:
#:     reached 1.25x   56.3%
#:     reached 1.5x    44.0%
#:     reached 2x      19.7%
#:
#: V6 was selling into moves that kept going, and its own instrumentation could
#: not show that.
#:
#: Whether capturing them PAYS is undetermined rather than promising. Simulating
#: higher targets on the price path gives +$241 after costs with no execution
#: haircut and -$145 with the haircut measured at the tail (chart 2x moves
#: overstate executable ones by a third). The sign turns on an assumption this
#: data cannot settle, which is exactly what a forward tournament settles: the
#: Lab measures EXECUTABLE multiples, and running it uncensored is the only way
#: to know.
SPEC_VERSION = "1.2.0"

#: What the operator will actually fund. See the note above: this is the number
#: that decides whether a loss reads as −5% or −50%, and the honest one is the one
#: the money is really at.
STARTING_EQUITY = Decimal("100.00")
#: Circuit breaker (mission §14): below this a strategy stops opening, and its
#: open positions still run to their own frozen exits. Held at 80% of the book,
#: as it was at $1,000.
FAILURE_EQUITY_FLOOR = Decimal("80.00")

#: No strategy may commit more than this fraction of its book at once. At $1,000
#: the caps happened to land at 8–20%, which was never a decision — it was the
#: residue of sizes chosen for a book ten times larger. Capping the FRACTION makes
#: it one: enough capital genuinely at work to be worth measuring, enough held back
#: that one bad hour is a drawdown rather than the end of the record.
MAX_DEPLOYED_FRACTION = Decimal("0.60")

# --------------------------------------------------------------- conditions

#: Comparison vocabulary. Deliberately tiny: every frozen rule in §19 is one of
#: these against one named feature, which is what makes a decision replayable.
OPS = ("gte", "lte", "gt", "lt", "is_true", "gt_field", "eq")


#: Feature names as a reader would say them. The engine never reads these.
FEATURE_LABELS = {
    "liq": "liquidity",
    "liq_mcap": "liquidity / market cap",
    "liqchg_15m": "liquidity change over 15 min",
    "ret_15m": "price return over 15 min",
    "vol_accel": "volume acceleration (5m vs previous 5m)",
    "vol1h": "volume over 1 hour",
    "sell_share_15m": "sell share of trades over 15 min",
    "dd_from_peak_det": "drawdown from peak since detection",
    "tx_15m": "trades over 15 min",
    "w1h_unique_wallets": "unique wallets (1h)",
    "w1h_unique_buyers": "unique buyers (1h)",
    "w1h_unique_sellers": "unique sellers (1h)",
    "w1h_top10_tx_share": "top-10 wallet share of trades (1h)",
    "flow_quality": "wallet-flow window quality",
    "buy_route_ok": "Jupiter BUY quote",
    "sell_route_ok": "Jupiter SELL quote",
    "buy_impact_pct": "quoted buy price impact",
}

#: Features denominated in dollars, percent, or a bare count.
_USD = {"liq", "vol1h"}
_PCT = {"liq_mcap", "liqchg_15m", "ret_15m", "vol_accel", "sell_share_15m",
        "dd_from_peak_det", "w1h_top10_tx_share", "buy_impact_pct"}


def _fmt(feature: str, value: object) -> str:
    if feature in _USD:
        return f"${int(Decimal(str(value))):,}"
    if feature in _PCT:
        pct = Decimal(str(value)) * (1 if feature == "buy_impact_pct" else 100)
        return f"{pct.normalize():f}%"
    return str(value)


@dataclass(frozen=True, slots=True)
class Condition:
    """One entry condition. `feature` UNKNOWN => the condition is FALSE.

    `reason` is what the ledger records when this condition is the first to
    fail, so a skip always names a measured cause rather than a vague one.
    """

    feature: str
    op: str
    value: object = None
    reason: str = ""

    def evaluate(self, features: dict) -> bool:
        got = features.get(self.feature)
        if got is None:
            return False
        if self.op == "is_true":
            return bool(got)
        if self.op == "gt_field":
            other = features.get(str(self.value))
            return other is not None and Decimal(str(got)) > Decimal(str(other))
        if self.op == "eq":
            return got == self.value
        left, right = Decimal(str(got)), Decimal(str(self.value))
        return {
            "gte": left >= right, "lte": left <= right,
            "gt": left > right, "lt": left < right,
        }[self.op]

    @property
    def skip_reason(self) -> str:
        return self.reason or f"{self.feature}_{self.op}_{self.value}"

    def describe(self) -> str:
        """The condition in words, for readers rather than for the engine."""
        name = FEATURE_LABELS.get(self.feature, self.feature)
        if self.op == "is_true":
            return f"{name} succeeded"
        if self.op == "gt_field":
            return f"{name} > {FEATURE_LABELS.get(str(self.value), self.value)}"
        if self.op == "eq":
            return f"{name} is \"{self.value}\""
        symbol = {"gte": "\u2265", "lte": "\u2264", "gt": ">", "lt": "<"}[self.op]
        return f"{name} {symbol} {_fmt(self.feature, self.value)}"


@dataclass(frozen=True, slots=True)
class Exits:
    """The frozen exit policy. `None` means the mechanism is absent, not zero.

    Level triggers (take_profit, partial_at, runner_target, break_even_arm) are
    measured on the **executable multiple of the original position size** —
    `sell_proceeds(original_quantity, price, liquidity) / cost` — never on the
    chart price. That is the V6 frozen definition and the only one under which
    a "2x" means a sale that could actually have happened.
    """

    take_profit: Decimal | None = None
    #: V6 contains no conventional stop losses. Historically they filled at a
    #: median of $0.03 against a nominal -25%, so the spec omits them on
    #: purpose; the field exists only so its absence is explicit.
    stop_loss: Decimal | None = None
    trailing_drawdown: Decimal | None = None
    trailing_arm_at: Decimal | None = None
    partial_at: Decimal | None = None
    partial_fraction: Decimal | None = None
    runner_target: Decimal | None = None
    break_even_arm: Decimal | None = None
    break_even_exit: Decimal | None = None
    time_exit_hours: int | None = None
    stagnation_hours: int | None = None
    liquidity_exit_frac_of_entry: Decimal | None = None
    liquidity_exit_absolute_usd: Decimal | None = None
    #: "hold_and_retry" keeps the position when the route is gone (the V6
    #: default); "exit_at_best_quote" sells into whatever is quotable.
    sell_route_loss: str = "hold_and_retry"

    def describe(self) -> list[str]:
        """The exit policy in words, in the order the engine evaluates it."""
        out: list[str] = ["dead pool settles at $0.00"]
        if self.liquidity_exit_absolute_usd is not None:
            out.append(f"exit if liquidity < ${int(self.liquidity_exit_absolute_usd):,}")
        if self.liquidity_exit_frac_of_entry is not None:
            pct = int(self.liquidity_exit_frac_of_entry * 100)
            out.append(f"exit if liquidity < {pct}% of entry depth")
        out.append("sell-route loss: "
                   + ("exit at best quote" if self.sell_route_loss == "exit_at_best_quote"
                      else "hold and retry"))
        if self.break_even_arm is not None:
            out.append(f"break-even: once {self.break_even_arm}x is touched, exit if it "
                       f"returns to {self.break_even_exit or 1}x")
        if self.trailing_drawdown is not None:
            out.append(f"trailing stop {int(self.trailing_drawdown * 100)}% off the peak, "
                       f"armed only at {self.trailing_arm_at}x")
        if self.partial_at is not None:
            out.append(f"sell {int((self.partial_fraction or 0) * 100)}% at "
                       f"{self.partial_at}x")
        if self.runner_target is not None:
            out.append(f"runner exits at {self.runner_target}x")
        if self.take_profit is not None:
            out.append(f"take profit at {self.take_profit}x")
        if self.stagnation_hours is not None:
            out.append(f"stagnation exit after {self.stagnation_hours}h inside "
                       f"\u00b15% of entry")
        if self.time_exit_hours is not None:
            out.append(f"time exit at {self.time_exit_hours}h")
        else:
            out.append("no time exit")
        if self.stop_loss is None:
            out.append("no stop loss (V6 contains none by design)")
        return out


@dataclass(frozen=True, slots=True)
class Strategy:
    id: str
    name: str
    hypothesis: str
    checkpoint_minutes: int | None
    entry: tuple[Condition, ...]
    size_usd: Decimal
    max_concurrent: int
    max_exposure_usd: Decimal
    exits: Exits
    evidence: str
    overfit_risk: str
    #: Historical context. Recorded and displayed, never used in a decision.
    hist: dict = field(default_factory=dict)
    hist_is_proxy: bool = False
    caveats: tuple[str, ...] = ()
    note: str = ""

    @property
    def trades(self) -> bool:
        return self.checkpoint_minutes is not None and self.size_usd > 0


def _c(feature: str, op: str, value: object, reason: str) -> Condition:
    return Condition(feature, op, value, reason)


D = Decimal

#: The three entry rules carried forward, chosen for SAMPLE rather than result.
#:
#: V6-05, V6-10 and V6-18 produced the largest books in V6.1 — 116, 115 and 126
#: closed trades — and this experiment needs volume, not a favourite. All three
#: lost money at a 1.25x target, which is the point: if a higher target rescues
#: a losing entry rule, that is the finding, and picking the rules that already
#: looked best would have buried it under selection.
_ENTRIES: tuple[tuple[str, str, tuple[Condition, ...]], ...] = (
    ("DEEP", "liq>=300k", (_c("liq", "gte", D("300000"), "liq_below_300k"),)),
    ("FLOAT", "liq>=100k, float<=0.15",
     (_c("liq", "gte", D("100000"), "liq_below_100k"),
      _c("liq_mcap", "lte", D("0.15"), "liq_mcap_above_0_15"))),
    ("FLOW", "liq>=300k, growing, sells<=0.45",
     (_c("liq", "gte", D("300000"), "liq_below_300k"),
      _c("liqchg_15m", "gte", D("0.0"), "liquidity_not_growing"),
      _c("sell_share_15m", "lte", D("0.45"), "sell_share_above_0_45"))),
)

#: The variable under test. `None` means NO target: hold to the six-hour exit
#: whatever the price does, which is the pure "let it run" arm and the one V6
#: never had.
#:
#: 1.25 is included deliberately as the BASELINE, not as a candidate. It is what
#: every V6 strategy used, so each entry rule carries its own control and the
#: comparison is within-rule rather than against a different experiment.
_TARGETS: tuple[Decimal | None, ...] = (D("1.25"), D("1.50"), D("2.00"),
                                       D("2.50"), D("3.00"), None)


def _grid() -> tuple[Strategy, ...]:
    """Three entry rules x six targets, built as a loop rather than enumerated.

    Eighteen hand-written near-identical blocks would hide the one thing that
    matters here — that only the target differs — and would let a typo in one
    cell masquerade as a result. The generated ids are stable and the hash is
    taken over the canonical JSON, so nothing about freezing is weakened.
    """
    out: list[Strategy] = []
    n = 3
    for label, desc, entry in _ENTRIES:
        for tp in _TARGETS:
            n += 1
            tp_name = "HOLD" if tp is None else f"TP{tp.normalize()}"
            out.append(Strategy(
                id=f"V7-{n:02d}", name=f"{label}-{tp_name}",
                hypothesis=(
                    f"{desc}. Target {'none, hold to the 6h exit' if tp is None else tp}. "
                    "Only the target varies across this rule's six arms."
                ),
                checkpoint_minutes=30, entry=entry,
                size_usd=D("5"), max_concurrent=10, max_exposure_usd=D("50"),
                exits=Exits(take_profit=tp, time_exit_hours=6),
                evidence="NONE", overfit_risk="LOW",
                hist={},
                caveats=("v7_target_arm", "entry_rule_lost_money_at_1_25x_in_v6"),
            ))
    return tuple(out)


STRATEGIES: tuple[Strategy, ...] = (
    Strategy(
        id="V7-01", name="CASH-CONTROL",
        hypothesis="Doing nothing beats every strategy. Seven prior studies say yes.",
        checkpoint_minutes=None, entry=(), size_usd=D("0"), max_concurrent=0,
        max_exposure_usd=D("0"), exits=Exits(),
        evidence="DEFINITIONAL", overfit_risk="NONE",
        hist={"trades": 0, "expectancy": 0.0, "end_equity": 100.00, "max_dd": 0.0},
    ),
    Strategy(
        id="V7-02", name="RANDOM-CONTROL-TP125",
        hypothesis="Blind entry at the OLD target. The floor every V6 rule had to clear.",
        checkpoint_minutes=30, entry=(), size_usd=D("5"),
        max_concurrent=10, max_exposure_usd=D("50"),
        exits=Exits(take_profit=D("1.25"), time_exit_hours=6),
        evidence="DEFINITIONAL", overfit_risk="NONE",
        caveats=("random_entry_from_the_eligible_pool",),
    ),
    Strategy(
        id="V7-03", name="RANDOM-CONTROL-TP200",
        hypothesis=(
            "Blind entry at the NEW target. The control that decides what this "
            "tournament is actually measuring: if random entry improves as much "
            "as the rules do when the target rises, the target is the whole "
            "effect and no entry rule has shown anything."
        ),
        checkpoint_minutes=30, entry=(), size_usd=D("5"),
        max_concurrent=10, max_exposure_usd=D("50"),
        exits=Exits(take_profit=D("2.00"), time_exit_hours=6),
        evidence="DEFINITIONAL", overfit_risk="NONE",
        caveats=("random_entry_from_the_eligible_pool",),
    ),
    *_grid(),
)

def rules_json(s: "Strategy") -> dict:
    """One strategy as data a reader can check against the report.

    Carries both the machine form (feature/op/value) and the human form, so the
    page never re-derives a threshold in TypeScript — a second implementation
    would be a second answer.
    """
    from dataclasses import asdict

    return {
        "id": s.id, "name": s.name, "hypothesis": s.hypothesis,
        "checkpoint_minutes": s.checkpoint_minutes,
        "checkpoint_label": ("never" if s.checkpoint_minutes is None
                             else "at admission" if s.checkpoint_minutes == 0
                             else f"+{s.checkpoint_minutes} min"),
        "entry": [{"feature": c.feature, "op": c.op, "value": str(c.value),
                   "reason": c.skip_reason, "text": c.describe()} for c in s.entry],
        "entry_text": ([c.describe() for c in s.entry] or
                       (["never enters"] if not s.trades
                        else ["every eligible token (control)"])),
        "exits": {k: (str(v) if isinstance(v, Decimal) else v)
                  for k, v in asdict(s.exits).items() if v is not None},
        "exit_text": s.exits.describe() if s.trades else ["n/a"],
        "size_usd": str(s.size_usd), "max_concurrent": s.max_concurrent,
        "max_exposure_usd": str(s.max_exposure_usd),
        "evidence": s.evidence, "overfit_risk": s.overfit_risk,
        "hist": s.hist, "hist_is_proxy": s.hist_is_proxy,
        "caveats": list(s.caveats), "note": s.note,
    }


BY_ID = {s.id: s for s in STRATEGIES}
#: Distinct checkpoints the Lab must evaluate. Derived, never hand-maintained.
CHECKPOINTS = sorted({s.checkpoint_minutes for s in STRATEGIES if s.trades})


def _canonical() -> str:
    """Canonical JSON of the whole registry — the thing the hash is taken over.

    `hist` and `note` are excluded on purpose: they are context for a reader,
    not rules, and a typo fixed in a caveat must not invalidate a live record.
    """
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
         "strategies": [clean(s) for s in STRATEGIES]},
        sort_keys=True, separators=(",", ":"), default=str,
    )


#: Written onto every strategy row at activation and checked on every tick.
SPEC_HASH = hashlib.sha256(_canonical().encode()).hexdigest()

# V6 was exactly twenty. V7 is twenty-one, and the extra slot is a control
# rather than another strategy: three controls (cash, random at the old target,
# random at the new one) plus a 3x6 grid of entry rule against target.
#
# The count is a consequence of the design, not a constraint on it. Dropping the
# second random control to preserve a round number would have removed the arm
# that decides what this tournament measures — whether a gain comes from the
# target or from the entry rule.
assert len(STRATEGIES) == 21, "V7 is three controls plus a 3x6 target grid"
assert sum(1 for s in STRATEGIES if not s.trades) == 1, "exactly one cash control"
assert len({s.id for s in STRATEGIES}) == len(STRATEGIES), "strategy ids must be unique"
