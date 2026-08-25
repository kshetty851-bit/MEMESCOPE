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
SPEC_VERSION = "1.0.0"

STARTING_EQUITY = Decimal("1000.00")
#: Circuit breaker (mission §14): below this a strategy stops opening, and its
#: open positions still run to their own frozen exits.
FAILURE_EQUITY_FLOOR = Decimal("800.00")

# --------------------------------------------------------------- conditions

#: Comparison vocabulary. Deliberately tiny: every frozen rule in §19 is one of
#: these against one named feature, which is what makes a decision replayable.
OPS = ("gte", "lte", "gt", "lt", "is_true", "gt_field", "eq")


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

STRATEGIES: tuple[Strategy, ...] = (
    Strategy(
        id="V6-01", name="CASH-CONTROL",
        hypothesis="Doing nothing beats every strategy. Six prior studies say yes.",
        checkpoint_minutes=None, entry=(), size_usd=D("0"), max_concurrent=0,
        max_exposure_usd=D("0"), exits=Exits(),
        evidence="DEFINITIONAL", overfit_risk="NONE",
        hist={"trades": 0, "expectancy": 0.0, "end_equity": 1000.00, "max_dd": 0.0},
    ),
    Strategy(
        id="V6-02", name="RANDOM-CONTROL",
        hypothesis="Any selection rule must beat blind entry from the same eligible pool.",
        checkpoint_minutes=30, entry=(), size_usd=D("10"), max_concurrent=8,
        max_exposure_usd=D("80"),
        exits=Exits(take_profit=D("1.25"), time_exit_hours=6),
        evidence="HIGH", overfit_risk="NONE",
        hist={"trades": 790, "win": 0.565, "expectancy": -1.644, "pf": 0.468,
              "max_dd": 0.506, "end_equity": 497.01, "exec_125": 0.545,
              "exec_150": 0.396, "exec_200": 0.225, "ex_best1": -1.652, "ex_best3": -1.667},
    ),
    Strategy(
        id="V6-03", name="KARTHIK-REPLICA",
        hypothesis="Production's live policy is the honest baseline; reproduce it exactly.",
        checkpoint_minutes=0, entry=(), size_usd=D("10"), max_concurrent=20,
        max_exposure_usd=D("200"), exits=Exits(take_profit=D("1.25")),
        evidence="HIGH_LIVE_ANCHORED", overfit_risk="NONE",
        hist={"trades": 2466, "win": 0.526, "expectancy": -2.749, "pf": 0.366,
              "max_dd": 0.991, "end_equity": 9.42, "exec_125": 0.495,
              "exec_150": 0.350, "exec_200": 0.206, "ex_best1": -2.752, "ex_best3": -2.757},
    ),
    Strategy(
        id="V6-04", name="LIQ-CORE-100K",
        hypothesis="Pool depth at +30m is survival evidence and execution capacity.",
        checkpoint_minutes=30,
        entry=(_c("liq", "gte", D("100000"), "liq_below_100k"),),
        size_usd=D("10"), max_concurrent=10, max_exposure_usd=D("100"),
        exits=Exits(take_profit=D("1.25")),
        evidence="HIGH", overfit_risk="LOW",
        hist={"trades": 372, "win": 0.720, "expectancy": -0.887, "pf": 0.682,
              "max_dd": 0.210, "end_equity": 815.50, "exec_125": 0.654,
              "exec_150": 0.486, "exec_200": 0.314, "ex_best1": -0.900, "ex_best3": -0.929},
    ),
    Strategy(
        id="V6-05", name="LIQ-DEEP-300K",
        hypothesis="The depth effect is monotone; 3x the floor should roughly halve the loss.",
        checkpoint_minutes=30,
        entry=(_c("liq", "gte", D("300000"), "liq_below_300k"),),
        size_usd=D("10"), max_concurrent=10, max_exposure_usd=D("100"),
        exits=Exits(take_profit=D("1.25")),
        evidence="MEDIUM", overfit_risk="LOW",
        hist={"trades": 173, "win": 0.751, "expectancy": -0.460, "pf": 0.815,
              "max_dd": 0.135, "end_equity": 931.33, "exec_125": 0.732,
              "exec_150": 0.589, "exec_200": 0.405, "ex_best1": -0.488, "ex_best3": -0.544},
    ),
    Strategy(
        id="V6-06", name="LIQ-ULTRA-400K",
        hypothesis=("Above ~$400k depth the executable 1.25x rate (81.5%) finally clears the "
                    "~80% breakeven bar a 1.25x/-100% payoff requires."),
        checkpoint_minutes=30,
        entry=(_c("liq", "gte", D("400000"), "liq_below_400k"),),
        size_usd=D("10"), max_concurrent=8, max_exposure_usd=D("80"),
        exits=Exits(take_profit=D("1.25")),
        evidence="MEDIUM_LOW", overfit_risk="HIGH",
        hist={"trades": 113, "win": 0.832, "expectancy": 0.565, "pf": 1.336,
              "max_dd": 0.035, "end_equity": 1064.51, "exec_125": 0.815,
              "exec_150": 0.676, "exec_200": 0.454, "ex_best1": 0.532, "ex_best3": 0.464},
        caveats=("only_candidate_beating_cash_with_robustness",
                 "quiet_regime_negative_1_58",
                 "gate_population_share_moved_0_to_48_percent",
                 "n_below_protocol_minimum",
                 "seventh_pass_over_a_closed_dataset"),
    ),
    Strategy(
        id="V6-07", name="LIQ-ULTRA-500K-TP150",
        hypothesis=("At >=$500k the 1.5x rate is 69.1% against a ~67% breakeven bar, so the "
                    "larger target should pay more than 1.25x. Perturbs V6-06 on both axes."),
        checkpoint_minutes=30,
        entry=(_c("liq", "gte", D("500000"), "liq_below_500k"),),
        size_usd=D("15"), max_concurrent=8, max_exposure_usd=D("120"),
        exits=Exits(take_profit=D("1.50")),
        evidence="LOW", overfit_risk="HIGH",
        hist={"trades": 96, "win": 0.708, "expectancy": 1.160, "pf": 1.265,
              "max_dd": 0.064, "end_equity": 1117.29, "exec_125": 0.819,
              "exec_150": 0.691, "exec_200": 0.489, "ex_best1": 1.060, "ex_best3": 0.853},
        caveats=("quiet_regime_negative_5_30", "n_96", "perturbation_twin_of_V6-06"),
    ),
    Strategy(
        id="V6-08", name="LIQ-STABILITY",
        hypothesis=("Rug mechanics are liquidity mechanics: refuse decaying pools and exit the "
                    "moment depth halves, rather than predicting anything."),
        checkpoint_minutes=30,
        entry=(_c("liq", "gte", D("100000"), "liq_below_100k"),
               _c("liqchg_15m", "gte", D("-0.10"), "liquidity_decaying_over_10pct")),
        size_usd=D("10"), max_concurrent=10, max_exposure_usd=D("100"),
        exits=Exits(take_profit=D("1.25"), liquidity_exit_frac_of_entry=D("0.50"),
                    liquidity_exit_absolute_usd=D("1000"),
                    sell_route_loss="exit_at_best_quote"),
        evidence="HIGH", overfit_risk="LOW",
        hist={"trades": 368, "win": 0.682, "expectancy": -1.368, "pf": 0.568,
              "max_dd": 0.308, "end_equity": 728.31, "exec_125": 0.666,
              "exec_150": 0.498, "exec_200": 0.319, "ex_best1": -1.384, "ex_best3": -1.415},
    ),
    Strategy(
        id="V6-09", name="LIQ-GROWTH",
        hypothesis="Pools still GAINING depth at +30m are being added to, not exited.",
        checkpoint_minutes=30,
        entry=(_c("liq", "gte", D("100000"), "liq_below_100k"),
               _c("liqchg_15m", "gte", D("0.0"), "liquidity_not_growing")),
        size_usd=D("10"), max_concurrent=10, max_exposure_usd=D("100"),
        exits=Exits(take_profit=D("1.50")),
        evidence="HIGH", overfit_risk="LOW",
        hist={"trades": 312, "win": 0.583, "expectancy": -1.216, "pf": 0.707,
              "max_dd": 0.287, "end_equity": 735.04, "exec_125": 0.667,
              "exec_150": 0.505, "exec_200": 0.323, "ex_best1": -1.243, "ex_best3": -1.297},
    ),
    Strategy(
        id="V6-10", name="LIQ-MCAP-FLOAT",
        hypothesis=("A low liquidity/market-cap ratio means the float is not yet in the pool, "
                    "leaving room to rise. Contradicts the 'safety gate' intuition."),
        checkpoint_minutes=30,
        entry=(_c("liq", "gte", D("100000"), "liq_below_100k"),
               _c("liq_mcap", "lte", D("0.15"), "liq_mcap_above_0_15")),
        size_usd=D("10"), max_concurrent=10, max_exposure_usd=D("100"),
        exits=Exits(take_profit=D("1.25")),
        evidence="MEDIUM", overfit_risk="MEDIUM_HIGH",
        hist={"trades": 269, "win": 0.773, "expectancy": -0.258, "pf": 0.886,
              "max_dd": 0.151, "end_equity": 903.98, "exec_125": 0.684,
              "exec_150": 0.498, "exec_200": 0.291, "ex_best1": -0.275, "ex_best3": -0.310},
        caveats=("feature_reversed_sign_in_two_prior_studies",),
    ),
    Strategy(
        id="V6-11", name="BUYER-DOMINANCE",
        hypothesis=("When sells are under 45% of trades in the last 15 min, the marginal "
                    "participant is still accumulating."),
        checkpoint_minutes=30,
        entry=(_c("liq", "gte", D("100000"), "liq_below_100k"),
               _c("sell_share_15m", "lte", D("0.45"), "sell_share_above_0_45")),
        size_usd=D("10"), max_concurrent=10, max_exposure_usd=D("100"),
        exits=Exits(take_profit=D("1.25")),
        evidence="HIGH", overfit_risk="LOW",
        hist={"trades": 305, "win": 0.767, "expectancy": -0.314, "pf": 0.865,
              "max_dd": 0.141, "end_equity": 903.07, "exec_125": 0.704,
              "exec_150": 0.532, "exec_200": 0.338, "ex_best1": -0.329, "ex_best3": -0.360},
    ),
    Strategy(
        id="V6-12", name="WALLET-FLOW-BREADTH",
        hypothesis=("Breadth of participation, not transaction count, separates a real market "
                    "from a handful of wallets trading with themselves."),
        checkpoint_minutes=30,
        entry=(_c("liq", "gte", D("50000"), "liq_below_50k"),
               _c("flow_quality", "eq", "exact", "flow_window_capped"),
               _c("w1h_unique_wallets", "gte", 20, "wallets_below_20"),
               _c("w1h_unique_buyers", "gt_field", "w1h_unique_sellers",
                  "buyers_not_above_sellers"),
               _c("w1h_top10_tx_share", "lte", D("0.80"), "top10_share_above_80pct")),
        size_usd=D("10"), max_concurrent=10, max_exposure_usd=D("100"),
        exits=Exits(take_profit=D("1.25"), time_exit_hours=6),
        evidence="NONE_HISTORICALLY", overfit_risk="NOT_APPLICABLE",
        hist={"proxy_rule": "liq>=50k AND tx_15m>=50 AND sell_share_15m<=0.50",
              "trades": 449, "win": 0.668, "expectancy": -1.568, "pf": 0.524,
              "max_dd": 0.328, "end_equity": 677.28, "exec_125": 0.665,
              "exec_150": 0.491, "exec_200": 0.292, "ex_best1": -1.581, "ex_best3": -1.607},
        hist_is_proxy=True,
        note=("wallet_flow_snapshots is keyed by POOL address, not mint. The Lab resolves "
              "mint -> active pool from the token's own snapshots before reading flow. "
              "Forward availability measured at 68.6% at the 30m checkpoint; 20.9% of "
              "windows are 'capped' and are skipped by rule."),
    ),
    Strategy(
        id="V6-13", name="MOMENTUM-CONFIRM",
        hypothesis="Rising, and not extended: buy strength that has not yet given anything back.",
        checkpoint_minutes=30,
        entry=(_c("liq", "gte", D("100000"), "liq_below_100k"),
               _c("ret_15m", "gt", D("0.0"), "not_rising_15m"),
               _c("dd_from_peak_det", "gte", D("-0.15"), "drawdown_over_15pct")),
        size_usd=D("10"), max_concurrent=10, max_exposure_usd=D("100"),
        exits=Exits(take_profit=D("1.50"), time_exit_hours=6),
        evidence="HIGH", overfit_risk="LOW",
        hist={"trades": 349, "win": 0.564, "expectancy": -1.756, "pf": 0.596,
              "max_dd": 0.448, "end_equity": 551.73, "exec_125": 0.678,
              "exec_150": 0.520, "exec_200": 0.332, "ex_best1": -1.782, "ex_best3": -1.833},
    ),
    Strategy(
        id="V6-14", name="VOLUME-ACCEL-TRAIL",
        hypothesis=("Accelerating volume marks the start of a move worth trailing rather than "
                    "capping. DELIBERATE REFUTATION TEST of the trailing-stop family."),
        checkpoint_minutes=30,
        entry=(_c("liq", "gte", D("100000"), "liq_below_100k"),
               _c("vol_accel", "gt", D("0.0"), "volume_not_accelerating"),
               _c("vol1h", "gte", D("50000"), "vol1h_below_50k")),
        size_usd=D("10"), max_concurrent=10, max_exposure_usd=D("100"),
        exits=Exits(trailing_drawdown=D("0.35"), trailing_arm_at=D("1.50"),
                    time_exit_hours=6, sell_route_loss="exit_at_best_quote"),
        evidence="HIGH", overfit_risk="LOW",
        hist={"trades": 146, "win": 0.247, "expectancy": -4.565, "pf": 0.384,
              "max_dd": 0.533, "end_equity": 467.30, "exec_125": 0.656,
              "exec_150": 0.496, "exec_200": 0.312, "ex_best1": -5.504, "ex_best3": -6.247},
        note="Matches production generation 7's trailing policy; included as a control.",
    ),
    Strategy(
        id="V6-15", name="EARLY-ENTRY-FAST",
        hypothesis=("Speed beats confirmation: enter at admission, take a small target fast, "
                    "and cut the holding period so capital turns over before the pool dies."),
        checkpoint_minutes=0,
        entry=(_c("liq", "gte", D("100000"), "liq_below_100k"),),
        size_usd=D("5"), max_concurrent=20, max_exposure_usd=D("100"),
        exits=Exits(take_profit=D("1.25"), time_exit_hours=2),
        evidence="HIGH", overfit_risk="LOW",
        hist={"trades": 651, "win": 0.656, "expectancy": -0.855, "pf": 0.469,
              "max_dd": 0.400, "end_equity": 605.05, "exec_125": 0.605,
              "exec_150": 0.437, "exec_200": 0.267, "ex_best1": -0.860, "ex_best3": -0.869},
    ),
    Strategy(
        id="V6-16", name="LATE-CONFIRM-60",
        hypothesis=("Surviving the full 60-minute nursery window is itself the filter; the "
                    "same depth gate applied later should admit better tokens."),
        checkpoint_minutes=60,
        entry=(_c("liq", "gte", D("100000"), "liq_below_100k"),),
        size_usd=D("10"), max_concurrent=10, max_exposure_usd=D("100"),
        exits=Exits(take_profit=D("1.25")),
        evidence="HIGH", overfit_risk="LOW",
        hist={"trades": 302, "win": 0.748, "expectancy": -0.470, "pf": 0.809,
              "max_dd": 0.094, "end_equity": 928.19, "exec_125": 0.677,
              "exec_150": 0.505, "exec_200": 0.281, "ex_best1": -0.486, "ex_best3": -0.518},
    ),
    Strategy(
        id="V6-17", name="COMBINED-QUALITY",
        hypothesis=("One condition per surviving family, no weights, no model: depth AND "
                    "stability AND buyer balance AND not-broken."),
        checkpoint_minutes=30,
        entry=(_c("liq", "gte", D("100000"), "liq_below_100k"),
               _c("liqchg_15m", "gte", D("0.0"), "liquidity_not_growing"),
               _c("sell_share_15m", "lte", D("0.50"), "sell_share_above_0_50"),
               _c("dd_from_peak_det", "gte", D("-0.30"), "drawdown_over_30pct")),
        size_usd=D("10"), max_concurrent=10, max_exposure_usd=D("100"),
        exits=Exits(take_profit=D("1.25")),
        evidence="HIGH", overfit_risk="LOW_MEDIUM",
        hist={"trades": 309, "win": 0.725, "expectancy": -0.816, "pf": 0.703,
              "max_dd": 0.189, "end_equity": 838.32, "exec_125": 0.676,
              "exec_150": 0.516, "exec_200": 0.328, "ex_best1": -0.832, "ex_best3": -0.866},
    ),
    Strategy(
        id="V6-18", name="CAPITAL-PRESERVE",
        hypothesis=("Ultra-selective, smallest size, tightest concurrency: lose the least. "
                    "Given six NO-EDGE verdicts, minimising exposure may be the best policy."),
        checkpoint_minutes=60,
        entry=(_c("liq", "gte", D("300000"), "liq_below_300k"),
               _c("liqchg_15m", "gte", D("0.0"), "liquidity_not_growing"),
               _c("sell_share_15m", "lte", D("0.45"), "sell_share_above_0_45")),
        size_usd=D("5"), max_concurrent=4, max_exposure_usd=D("20"),
        exits=Exits(take_profit=D("1.25"), liquidity_exit_frac_of_entry=D("0.50"),
                    liquidity_exit_absolute_usd=D("1000"),
                    sell_route_loss="exit_at_best_quote"),
        evidence="MEDIUM", overfit_risk="LOW",
        hist={"trades": 134, "win": 0.739, "expectancy": -0.339, "pf": 0.740,
              "max_dd": 0.032, "end_equity": 989.33, "exec_125": 0.764,
              "exec_150": 0.585, "exec_200": 0.317, "ex_best1": -0.358, "ex_best3": -0.396},
    ),
    Strategy(
        id="V6-19", name="EXEC-2X-HUNTER",
        hypothesis=("Executable 2x lives in deep pools with balanced flow. Bank half at 1.25x "
                    "to pay for the attempt, move to break-even, let the rest run to 2x."),
        checkpoint_minutes=30,
        entry=(_c("liq", "gte", D("400000"), "liq_below_400k"),
               _c("sell_share_15m", "lte", D("0.50"), "sell_share_above_0_50")),
        size_usd=D("10"), max_concurrent=8, max_exposure_usd=D("80"),
        exits=Exits(partial_at=D("1.25"), partial_fraction=D("0.50"),
                    runner_target=D("2.00"), break_even_arm=D("1.25"),
                    break_even_exit=D("1.00"), sell_route_loss="exit_at_best_quote"),
        evidence="LOW", overfit_risk="HIGH",
        hist={"trades": 105, "win": 0.486, "expectancy": 0.047, "pf": 1.016,
              "max_dd": 0.088, "end_equity": 951.51, "exec_125": 0.820,
              "exec_150": 0.680, "exec_200": 0.450, "ex_best1": -0.035, "ex_best3": -0.181},
        caveats=("fails_drop_best_1",
                 "live_forward_arena_had_0_executable_2x_in_54_closed_positions"),
    ),
    Strategy(
        id="V6-20", name="TRADEABILITY-2SIDED",
        hypothesis=("Sellability is the binding constraint, not direction. Require a real "
                    "two-sided Jupiter route before committing capital."),
        checkpoint_minutes=30,
        entry=(_c("buy_route_ok", "is_true", None, "buy_route_failed"),
               _c("sell_route_ok", "is_true", None, "sell_route_failed"),
               _c("buy_impact_pct", "lte", D("3.0"), "impact_above_3pct"),
               _c("liq", "gte", D("100000"), "liq_below_100k")),
        size_usd=D("10"), max_concurrent=10, max_exposure_usd=D("100"),
        exits=Exits(take_profit=D("1.25"), liquidity_exit_absolute_usd=D("1000"),
                    sell_route_loss="exit_at_best_quote"),
        evidence="NONE_HISTORICALLY", overfit_risk="NOT_APPLICABLE",
        hist={"proxy_rule": "liq>=100k AND volume_1h/liquidity <= 3.0",
              "trades": 268, "win": 0.772, "expectancy": -0.269, "pf": 0.881,
              "max_dd": 0.162, "end_equity": 885.67, "exec_125": 0.683,
              "exec_150": 0.496, "exec_200": 0.293, "ex_best1": -0.286, "ex_best3": -0.320},
        hist_is_proxy=True,
        note=("Checkpoint quote coverage was 4.9% at +30m in the forward window, so expect "
              "very few trades. Never impute tradeability: no quote => SKIP. Measured "
              "forward: 32 of 112 route-resolved tokens were BUY_OK / SELL_FAILED."),
    ),
)

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

assert len(STRATEGIES) == 20, "V6 is exactly twenty strategies"
assert len({s.id for s in STRATEGIES}) == 20, "strategy ids must be unique"
