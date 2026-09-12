"""STRATEGY F — LOSS-BOUNDED

Read the module docstring before you deploy this. It does not do what the
previous draft of this file claimed, and the correction matters.

WHAT CHANGED FROM THE DRAFT
----------------------------
An earlier version of this module was built on a $300k liquidity floor that
looked strongly profitable on karthik_closed_trades.csv. Two errors:

  1. I computed Karthik's trading window as 21 days. It is 1.75 days, and
     264 of its 311 trades opened on ONE calendar day (2026-08-22). Every
     per-day figure derived from it was wrong.

  2. The $300k result is n=28, 26 of which are from that single day. The
     bootstrap 95% CI on its mean net P&L per trade is [-$0.67, +$3.17] —
     it straddles zero. Drop its two best trades and the mean falls from
     $1.35 to $0.59. It is not an edge; it is a day.

The floor was then tested on rafiq_lab_closed_trades.csv (n=559, books
A2-E2) and it DID NOT REPLICATE: at the same $300k floor, v2 is still
-$2.50/trade and its zero rate barely moves (18.2% -> 17.0%, against
46.6% -> 14.3% in Karthik).

The reconciliation, which is itself a finding: liquidity separates zeros
from survivors at p=0.0001 across Karthik's full range, at p=0.03 above
$100k, and NOT AT ALL above $200k (p=0.16). v2's median entry liquidity is
$246,719. v2 already operates entirely inside the band where the liquidity
signal is exhausted. Its gate captured that edge already, and it was not
enough.

THE FINDING THAT DOES HOLD — WHY EVERY EXIT RULE FAILED
---------------------------------------------------------
Of v2's 102 total losses, 98 exited on `stop`. The stop fired. On those 98:

    exit_observed_price / stop_price   median 0.0003   (p90 0.0015)
    exit_friction_usd                  median $0.00
    frictionless_pnl                   median -100% of stake

The price at the exit observation was three ten-thousandths of the stop
level. Friction contributed nothing. Even buying and selling at the observed
mid with zero fee and zero impact, the trade was a total loss.

So the token did not slip through the stop. It fell ~3,000x between two
observations. That is not an execution problem and not a stop-placement
problem, and it is why A2 through E2 — which are all exit-rule variations —
all lost. No stop, trail, time-box, or fill-model improvement can recover a
position whose price is gone.

Only two levers remain: do not enter, or bound the size.

THE BREAK-EVEN ARITHMETIC — E[r] = (1-p)*survivor_return - p
--------------------------------------------------------------
    book        n    zero rate   survivor avg   zero rate NEEDED   E[r]/trade
    A2         60      10.0%         +2.0%           <= 1.9%         -8.24%
    B2        210      15.2%         +9.5%           <= 8.7%         -7.16%
    C2        162      22.2%         +4.2%           <= 4.0%        -18.95%
    D2         77      23.4%         -2.0%          impossible      -24.93%
    E2         50      20.0%        +14.9%          <= 12.9%         -8.11%
    Karthik   311      46.6%        +40.7%          <= 28.9%        -24.92%

Every book needs its zero rate roughly HALVED to reach break-even. That is
the whole problem, stated in one number, and no parameter in this file
moves it — because no decision-time variable in the data separates zeros
from survivors in v2 (liquidity p=0.39, entry slippage p=0.45, detection
delay p=0.45, stake p=0.11; all n=559).

WHAT F THEREFORE IS
--------------------
F is not a profit strategy. It is a loss-bounded configuration that makes
the system survivable long enough to collect the data that would identify
zeros before entry. It does three things, all of which are arithmetic
rather than prediction:

  * Entry gate at the best-measured cell (liq >= $200k AND, where recorded,
    mcap >= $200k). On Karthik that cell is n=54, zero rate 24.1%,
    E[r] = +0.87%/trade — the only positive cell found. On v2 the same gate
    gives -10.90%/trade. Treat +0.87% as break-even, not as an edge.
  * 1% position size. A zero then costs 1% of book instead of the 5% that
    A2, D2 and E2 paid at $50 on $1,000.
  * A hard equity floor and a daily trade cap, which stop the bleeding
    rather than reversing it.

WHAT F CANNOT DO
-----------------
It cannot return 5%/day. On a $1,000 book that is $50.00/day. Under the
gate above, simulated over the actual return distribution (20,000 draws):

    source     cap/day   median day     p05      p95    P(losing day)
    Karthik        5        +$0.37    -$24.94  +$22.03      43.8%
    Karthik       20        +$1.62    -$45.11  +$46.39      47.1%
    v2             5        -$4.60    -$26.69  +$11.22      66.8%
    v2            20       -$21.38    -$61.40  +$14.91      82.8%

The two requirements also contradict each other directly. "Never below
$1,000" and "5%/day" cannot both hold, because the only configuration with
positive expectancy in this data has a ~44% losing-day rate. Any book that
trades will spend many days under its starting value.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.labs.rafiq.adapters.engine import ExitRules, SimConfig
from app.labs.rafiq.adapters.profiles import StrategyProfile
from app.labs.rafiq.adapters.sizing import SizingPolicy

#: The best-measured cell, not a tuned optimum. Karthik n=54, E[r] +0.87%/trade.
#: Above $200k the liquidity/zero association is no longer significant
#: (p=0.16), so raising this further buys nothing measurable and costs volume.
MIN_LIQUIDITY_USD = Decimal(200_000)

#: v2 does not record market cap at all. Where it is unavailable this gate
#: does not block — an absent field must not silently admit or silently
#: refuse, so `admits` reports which checks it was actually able to run.
MIN_MARKET_CAP_USD = Decimal(200_000)

#: v2 ran 376 gated trades in 0.64 days = 588/day. At a negative expectancy
#: the trade count is the multiplier on the loss; this is the cap that was
#: missing, not a preference.
MAX_TRADES_PER_DAY = 20

LOSS_BOUNDED = StrategyProfile(
    lane="loss_bounded",
    # Exits are E2's, unchanged and deliberately so. E2 had the best survivor
    # return of any book (+14.9%) and the evidence above says exits are not
    # where the loss comes from. Changing them would be motion, not progress.
    exits=ExitRules(take_profit_mult=Decimal("1.30"), stop_mult=Decimal("0.88"),
                    trailing_frac=Decimal("0.20"), max_hold=timedelta(hours=8)),
    sizing=SizingPolicy(
        risk_per_trade=Decimal("0.01"),
        max_pool_fraction=Decimal("0.02"),
        max_impact_pct=Decimal("1.5"),
        exit_stress_factor=Decimal("0.25"),
        max_notional_usd=Decimal(10),      # 1% of a $1,000 book.
    ),
    sim=SimConfig(decision_latency=timedelta(seconds=15),
                  blackout_threshold=timedelta(minutes=5),
                  liquidity_collapse_frac=Decimal("0.20")),
    entry_threshold=Decimal(70),
    designed_breakeven_win_rate=Decimal("31.4"),
)

#: Kept as an alias so existing imports of the draft name keep working.
ZERO_AVOIDANCE = LOSS_BOUNDED


def admits(liquidity_usd, market_cap_usd=None):
    """F's entry gate.

    Returns (admit, reason, checks_run). `checks_run` names the gates that
    were actually evaluated, so a caller can never mistake "market cap was
    not recorded" for "market cap passed" — the failure mode that let v2
    run without a market-cap gate while its config file listed one.
    """
    checks = []
    if liquidity_usd is None:
        return False, "liquidity unknown - refusing (unknown is not safe)", checks
    checks.append("liquidity")
    if Decimal(str(liquidity_usd)) < MIN_LIQUIDITY_USD:
        return False, (f"liquidity ${float(liquidity_usd):,.0f} below "
                       f"${float(MIN_LIQUIDITY_USD):,.0f}"), checks
    if market_cap_usd is not None:
        checks.append("market_cap")
        if Decimal(str(market_cap_usd)) < MIN_MARKET_CAP_USD:
            return False, (f"market cap ${float(market_cap_usd):,.0f} below "
                           f"${float(MIN_MARKET_CAP_USD):,.0f}"), checks
    return True, None, checks


@dataclass(frozen=True)
class EquityFloor:
    """A hard floor on book equity. Halts NEW entries; never force-closes.

    Force-closing on a breach would realise every open position at once, and
    the evidence above says those sales land at ~0.0003x the marked price on
    a dying pool. The floor stops new risk. It does not panic-sell into the
    exact conditions that produce the -100% rows.
    """

    floor_usd: Decimal
    enabled: bool = True

    def breached(self, equity_usd: Decimal) -> bool:
        return self.enabled and Decimal(str(equity_usd)) <= self.floor_usd

    def check(self, equity_usd: Decimal):
        """(halt, reason)."""
        if not self.enabled:
            return False, None
        if Decimal(str(equity_usd)) <= self.floor_usd:
            return True, (f"equity ${float(equity_usd):,.2f} at or below hard "
                          f"floor ${float(self.floor_usd):,.2f} - no new entries")
        return False, None


#: The floor exactly as requested: $1,000 on a $1,000 book.
#: It halts on the first dollar of drawdown. In the measured distribution
#: 44-67% of days end below the starting book, so this will halt almost at
#: once. That is the floor doing what it was asked to do.
FLOOR_AT_START = EquityFloor(floor_usd=Decimal(1000))

#: A floor that leaves room to trade: 10% below start.
FLOOR_WITH_ROOM = EquityFloor(floor_usd=Decimal(900))


@dataclass
class DailyTradeCap:
    """Caps entries per UTC day. The lever v2 did not have."""

    max_per_day: int = MAX_TRADES_PER_DAY
    _day: date = None
    _count: int = 0

    def allows(self, today: date) -> bool:
        if today != self._day:
            return self.max_per_day > 0
        return self._count < self.max_per_day

    def record(self, today: date) -> None:
        if today != self._day:
            self._day, self._count = today, 0
        self._count += 1

    def remaining(self, today: date) -> int:
        if today != self._day:
            return self.max_per_day
        return max(0, self.max_per_day - self._count)


def may_enter(*, equity_usd, today, liquidity_usd, market_cap_usd=None,
              floor: EquityFloor = FLOOR_WITH_ROOM,
              cap: DailyTradeCap = None):
    """The whole gate in one call. Returns (allow, reason).

    Order matters: portfolio-level halts are checked before instrument-level
    ones, so a floor breach is always reported as a floor breach and never
    masked by a token that happened to also fail its liquidity check.
    """
    halted, why = floor.check(equity_usd)
    if halted:
        return False, why
    if cap is not None and not cap.allows(today):
        return False, (f"daily trade cap reached ({cap.max_per_day}/day) - "
                       f"no further entries today")
    ok, why, _checks = admits(liquidity_usd, market_cap_usd)
    if not ok:
        return False, why
    return True, None
