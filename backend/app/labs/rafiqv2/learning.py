"""LEARNING — every book records every buy and adapts its own parameters.

One engine, six books. `Learning(book="A2")` and `Learning(book="G2")` keep
separate evidence and adapt separately, because the books trade different
gates and what is miscalibrated for one is not for another.

WHAT IT LEARNS, AND FROM WHAT
-------------------------------
Every buy calls `on_entry`, every close calls `on_exit`. From that stream it
adapts four things, each bounded and each requiring evidence:

  1. THE RUG LADDER. How strict the seconds-scale checks are. If tokens cut at
     30s were mostly going to recover, it loosens; if tokens that survived 30s
     mostly died anyway, it tightens.

  2. THE PROFIT LOCK. How far a winner may give back. If locks are firing and
     the token then keeps running, the lock is too tight. If winners round-trip
     to zero without the lock firing, it is too loose.

  3. POSITION SIZE. Halves it when the runner rate collapses against baseline.
     It never sizes up.

  4. THE DEATH-RATE BREAKER. How quickly to stand down.

WHAT IT STILL DOES NOT LEARN
------------------------------
Which token to buy. Over 559 v2 trades, permutation tests (20,000 iterations)
on every recorded entry-time variable: liquidity p=0.3914, entry slippage
p=0.4517, detect->open delay p=0.4500, stake p=0.1133. Nothing separated total
losses from survivors. And in the 17-19 Sep window every gate in the lab - from
$50k to $200k liquidity - admitted tokens that died; G1 bought 18 and 18 died.

A classifier over those features would learn noise and report confidence while
doing it. The two features that plausibly WOULD separate - top-10 holder
concentration and LP lock status - are still not recorded anywhere. Record
them and this section becomes buildable on evidence rather than hope.

WHY IT ADAPTS SLOWLY
----------------------
This project has twice been burned by fitting to a small sample: a $300k
liquidity floor on n=28 from a single day, and a positive F2 read on 14 trades
that reversed at n=109. Every adjustment needs a minimum sample, must clear a
significance test rather than a point estimate, moves one step, and is logged
with the evidence that justified it.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

MIN_SAMPLE = 40
SIGNIFICANCE_Z = 1.96
REGIME_WINDOW = 120

RUG_STRICTNESS_MIN = Decimal("-0.05")
RUG_STRICTNESS_MAX = Decimal("0.10")
RUG_STEP = Decimal("0.01")

LOCK_GIVEBACK_MIN = Decimal("0.05")
LOCK_GIVEBACK_MAX = Decimal("0.40")
LOCK_STEP = Decimal("0.03")


def _two_proportion_z(hits_a, n_a, hits_b, n_b) -> float:
    if n_a == 0 or n_b == 0:
        return 0.0
    p_a, p_b = hits_a / n_a, hits_b / n_b
    pooled = (hits_a + hits_b) / (n_a + n_b)
    denom = pooled * (1 - pooled) * (1 / n_a + 1 / n_b)
    if denom <= 0:
        return 0.0
    return (p_a - p_b) / math.sqrt(denom)


@dataclass(frozen=True)
class Adjustment:
    at: datetime
    book: str
    parameter: str
    old_value: Decimal
    new_value: Decimal
    reason: str
    sample_size: int
    z_score: float

    def __str__(self):
        return (f"[{self.at:%Y-%m-%d %H:%M}] {self.book} {self.parameter}: "
                f"{float(self.old_value):+.3f} -> {float(self.new_value):+.3f} "
                f"(n={self.sample_size}, z={self.z_score:+.2f}) {self.reason}")


@dataclass(frozen=True)
class TradeRecord:
    """One buy, and what became of it. This is the learning substrate."""

    mint: str
    opened_at: datetime
    stake_usd: Decimal
    entry_liquidity_usd: Decimal | None
    entry_market_cap_usd: Decimal | None
    closed_at: datetime = None
    exit_reason: str = None
    net_return: Decimal = None
    peak_multiple: Decimal = None
    token_died: bool = None
    lock_armed: bool = False

    @property
    def hold_seconds(self):
        if self.closed_at is None:
            return None
        return (self.closed_at - self.opened_at).total_seconds()


@dataclass
class RugCalibrator:
    """Are the seconds-scale gates cutting winners, or missing killers?"""

    strictness: Decimal = Decimal(0)
    _cut_but_recovered: deque = field(default_factory=lambda: deque(maxlen=400))
    _kept_but_died: deque = field(default_factory=lambda: deque(maxlen=400))

    def record(self, rec: TradeRecord) -> None:
        cut = (rec.exit_reason or "").startswith(("rug_", "abandon_"))
        if cut:
            recovered = (rec.peak_multiple or Decimal(1)) >= Decimal("1.25")
            self._cut_but_recovered.append(bool(recovered))
        else:
            self._kept_but_died.append(bool(rec.token_died))

    @property
    def sample_size(self):
        return len(self._cut_but_recovered) + len(self._kept_but_died)

    def evaluate(self, now, book):
        n_a, n_b = len(self._cut_but_recovered), len(self._kept_but_died)
        if self.sample_size < MIN_SAMPLE or n_a == 0 or n_b == 0:
            return None
        a, b = sum(self._cut_but_recovered), sum(self._kept_but_died)
        z = _two_proportion_z(a, n_a, b, n_b)
        if abs(z) < SIGNIFICANCE_Z:
            return None
        old = self.strictness
        if z > 0:
            new = max(RUG_STRICTNESS_MIN, old - RUG_STEP)
            why = (f"{100*a/n_a:.0f}% of cut tokens recovered vs {100*b/n_b:.0f}% "
                   f"of kept ones dying - loosening the gates")
        else:
            new = min(RUG_STRICTNESS_MAX, old + RUG_STEP)
            why = (f"{100*b/n_b:.0f}% of kept tokens died vs {100*a/n_a:.0f}% of "
                   f"cut ones recovering - tightening the gates")
        if new == old:
            return None
        # Built before the evidence is cleared: `sample_size` reads it.
        made = Adjustment(now, book, "rug_strictness", old, new, why,
                          self.sample_size, round(z, 3))
        self.strictness = new
        self._cut_but_recovered.clear()
        self._kept_but_died.clear()
        return made


@dataclass
class LockCalibrator:
    """Is the profit lock too tight (cutting runners) or too loose (letting
    winners round-trip)?"""

    giveback: Decimal = Decimal("0.15")
    _locked_then_ran: deque = field(default_factory=lambda: deque(maxlen=400))
    _unlocked_round_trips: deque = field(default_factory=lambda: deque(maxlen=400))

    def record(self, rec: TradeRecord) -> None:
        peak = rec.peak_multiple or Decimal(1)
        ret = rec.net_return if rec.net_return is not None else Decimal(0)
        if rec.lock_armed:
            # Did the token keep running well past where the lock sold?
            self._locked_then_ran.append(peak >= (1 + ret) * Decimal("1.5"))
        else:
            # Was it up meaningfully and still closed red?
            self._unlocked_round_trips.append(peak >= Decimal("1.10") and ret < 0)

    @property
    def sample_size(self):
        return len(self._locked_then_ran) + len(self._unlocked_round_trips)

    def evaluate(self, now, book):
        n_a, n_b = len(self._locked_then_ran), len(self._unlocked_round_trips)
        if self.sample_size < MIN_SAMPLE or n_a == 0 or n_b == 0:
            return None
        a, b = sum(self._locked_then_ran), sum(self._unlocked_round_trips)
        z = _two_proportion_z(a, n_a, b, n_b)
        if abs(z) < SIGNIFICANCE_Z:
            return None
        old = self.giveback
        if z > 0:
            new = min(LOCK_GIVEBACK_MAX, old + LOCK_STEP)
            why = (f"{100*a/n_a:.0f}% of locked exits kept running - the lock is "
                   f"too tight, allowing more give-back")
        else:
            new = max(LOCK_GIVEBACK_MIN, old - LOCK_STEP)
            why = (f"{100*b/n_b:.0f}% of unlocked winners round-tripped to a loss "
                   f"- tightening the lock")
        if new == old:
            return None
        # Built before the evidence is cleared: `sample_size` reads it.
        made = Adjustment(now, book, "lock_giveback", old, new, why,
                          self.sample_size, round(z, 3))
        self.giveback = new
        self._locked_then_ran.clear()
        self._unlocked_round_trips.clear()
        return made


@dataclass
class RegimeMonitor:
    """Is the feed producing runners at all? Sizes down when it is not."""

    window: int = REGIME_WINDOW
    _recent: deque = field(default_factory=lambda: deque(maxlen=REGIME_WINDOW))
    _baseline: float = None

    def record(self, reached_take_profit: bool) -> None:
        self._recent.append(bool(reached_take_profit))

    @property
    def sample_size(self):
        return len(self._recent)

    @property
    def runner_rate(self):
        return sum(self._recent) / len(self._recent) if self._recent else None

    def set_baseline(self, rate: float) -> None:
        self._baseline = rate

    def assessment(self):
        if self.sample_size < MIN_SAMPLE:
            return 1.0, f"regime unknown ({self.sample_size}/{MIN_SAMPLE})"
        rate = self.runner_rate
        if self._baseline is None:
            self._baseline = rate
            return 1.0, f"baseline set at {100*rate:.0f}% runner rate"
        z = _two_proportion_z(sum(self._recent), len(self._recent),
                              int(self._baseline * self.window), self.window)
        if z < -SIGNIFICANCE_Z:
            return 0.5, (f"runner rate {100*rate:.0f}% vs baseline "
                         f"{100*self._baseline:.0f}% (z={z:.2f}) - halving size")
        if z > SIGNIFICANCE_Z:
            return 1.0, (f"runner rate {100*rate:.0f}% above baseline - normal "
                         f"size, never scaling up on a hot streak")
        return 1.0, f"regime normal ({100*rate:.0f}%, z={z:.2f})"


@dataclass
class Learning:
    """The learning layer for one book.

    Wire it up once per book:
        lrn = Learning(book="G2")
        lrn.on_entry(TradeRecord(...))          # every buy
        adj = lrn.on_exit(mint, ...)            # every close
        params = lrn.current_parameters()       # before every entry
    """

    book: str
    rug: RugCalibrator = field(default_factory=RugCalibrator)
    lock: LockCalibrator = field(default_factory=LockCalibrator)
    regime: RegimeMonitor = field(default_factory=RegimeMonitor)
    open_trades: dict = field(default_factory=dict)
    history: list = field(default_factory=list)
    adjustments: list = field(default_factory=list)

    # -- every buy ---------------------------------------------------------
    def on_entry(self, rec: TradeRecord) -> None:
        self.open_trades[rec.mint] = rec

    # -- every close -------------------------------------------------------
    def on_exit(self, mint, *, closed_at, exit_reason, net_return,
                peak_multiple, token_died, lock_armed=False):
        opened = self.open_trades.pop(mint, None)
        rec = TradeRecord(
            mint=mint,
            opened_at=opened.opened_at if opened else closed_at,
            stake_usd=opened.stake_usd if opened else Decimal(0),
            entry_liquidity_usd=opened.entry_liquidity_usd if opened else None,
            entry_market_cap_usd=opened.entry_market_cap_usd if opened else None,
            closed_at=closed_at, exit_reason=exit_reason,
            net_return=Decimal(str(net_return)),
            peak_multiple=Decimal(str(peak_multiple)),
            token_died=bool(token_died), lock_armed=bool(lock_armed),
        )
        self.history.append(rec)
        self.rug.record(rec)
        self.lock.record(rec)
        self.regime.record(peak_multiple >= Decimal("1.25"))

        made = [a for a in (self.rug.evaluate(closed_at, self.book),
                            self.lock.evaluate(closed_at, self.book)) if a]
        self.adjustments.extend(made)
        return made

    # -- before every entry ------------------------------------------------
    def current_parameters(self) -> dict:
        mult, note = self.regime.assessment()
        return {
            "book": self.book,
            "rug_strictness": float(self.rug.strictness),
            "lock_giveback": float(self.lock.giveback),
            "size_multiplier": mult,
            "regime_note": note,
            "closed_trades": len(self.history),
            "open_trades": len(self.open_trades),
            "adjustments_made": len(self.adjustments),
        }

    def audit_log(self) -> list:
        return [str(a) for a in self.adjustments]
