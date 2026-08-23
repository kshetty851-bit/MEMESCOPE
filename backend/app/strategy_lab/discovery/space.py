"""The search space. **Bounded, balanced, and declared before anything runs.**

1,850 definitions, not millions. §3's ceiling is a research constraint, not a
compute one: a search wide enough to contain a lucky combination for any
dataset will find one, and the finding will be the search rather than the
market.

── THE DESIGN IS A FULL FACTORIAL, ON PURPOSE ───────────────────────────────

    11 entry x 3 size x 7 profit x 8 exit  =  1,848   (+2 legacy reference)

Balanced levels rather than a hand-picked list, because §30 asks which design
choices associate with better out-of-sample performance. That question is only
answerable if every level of every dimension appears against every level of the
others; an unbalanced set would let "age >= 4h looks good" mean nothing more
than "age >= 4h happened to be paired with the good exits".

── WHAT IS NOT IN THE SPACE, AND WHY ────────────────────────────────────────

Every omission below is a data fact, checked against the live set, not a
preference:

  * **Prior-hour extension** (§4). `price_change_1h` and `price_change_5m` are
    NULL on all 150,013 eligible Radar decisions — the provider block does not
    carry them. Not testable.
  * **Wallet-flow features** (§5). No point-in-time capture exists for these
    opportunities. Backfilling current wallet state into an old decision would
    be look-ahead of the worst kind. Labelled `FUTURE_FEATURES_NOT_READY`.
  * **SEC-2 as a search dimension** (§4). It is a structural gate upstream of
    the canonical opportunity, not an alpha variable, and only 16 of 1,027
    opportunities carry an evaluation timestamped at or before their own
    eligibility. Carried as evidence; never a filter here.
  * **12h holds** (§8). Requiring 12h of forward coverage cuts the usable set
    from 565 to 324 *and* biases what remains toward the earliest hours, which
    would break the chronological split. See `MAX_HOLD`.
  * **Liquidity-aware sizing** (§6). Explicitly deferred: prior analyses of it
    were methodologically flawed, and mixing it into a fixed-size search would
    contaminate the comparison rather than settle it.
  * **Portfolio breakers** (§9). Second stage, applied only to survivors, so
    the base-strategy signal is not confounded by risk machinery.

── THRESHOLDS COME FROM THE OBSERVED DISTRIBUTION ───────────────────────────

Measured over the live canonical set: liq/mcap p10 0.040, median 0.258,
p90 1.385; market cap p10 $14k, median $99k, p90 $1.8m. The 0.20 and 0.35 cuts
therefore sit either side of the median, which is what makes them informative
rather than decorative.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

from app.strategy_lab.rules import DecayRule, Rung, StrategyRules, TrailingRule

#: Bumped when the space changes shape. Stored on every run so two vintages are
#: never pooled.
SPACE_VERSION = "1.0.0"

#: The longest hold any definition may use, and therefore the forward coverage
#: every canonical opportunity must have for the whole search to see an
#: identical population. Six hours, because twelve costs 43% of the sample and
#: takes it disproportionately from the early hours — which would put the
#: chronological split and the population change in the same experiment.
MAX_HOLD = timedelta(hours=6)

FUTURE_FEATURES_NOT_READY = (
    "unique_buyers_5m, unique_buyers_1h, unique_sellers_5m, unique_sellers_1h, "
    "tx_per_wallet, repeat_wallet_ratio, top5_tx_share, top10_tx_share, "
    "top5_volume_share, top10_volume_share, buyer_breadth, seller_breadth"
)

_NO_PROVIDER = (
    "NULL on all 150,013 eligible Radar decisions — the provider does not "
    "supply it"
)

UNAVAILABLE_FEATURES: dict[str, str] = {
    "price_change_1h": _NO_PROVIDER,
    "price_change_5m": _NO_PROVIDER,
    "buys_1h / sells_1h": (
        "NULL on all eligible Radar decisions — the provider supplies 24h "
        "counts only"
    ),
    "wallet_flow_*": (
        "FUTURE_FEATURES_NOT_READY — no point-in-time capture exists: "
        f"{FUTURE_FEATURES_NOT_READY}"
    ),
    "sec2_status": (
        "only 16 of 1,027 opportunities carry an evaluation at or before their "
        "own eligibility; a structural gate, not an alpha variable"
    ),
}


# ── Entry ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class EntryConfig:
    """A point-in-time admission rule. Every field reads frozen evidence only."""

    key: str
    label: str
    #: Seconds since this platform first discovered the token. A lower bound on
    #: true age — named for what it measures, as `strategies.S9` documents.
    min_discovery_age: timedelta | None = None
    min_liq_to_mcap: Decimal | None = None
    max_liq_to_mcap: Decimal | None = None
    min_liquidity_usd: Decimal | None = None
    #: Sells divided by buys over 24h. Computed from the two counts rather than
    #: inverting the stored buy/sell ratio, so a zero on either side is visible
    #: rather than an infinity.
    min_sell_buy: Decimal | None = None
    #: Reject when `lo <= s/b < hi`. §4's band form, kept as a rejection rather
    #: than a minimum because that is how it was posed.
    reject_sell_buy_band: tuple[Decimal, Decimal] | None = None

    def describe(self) -> str:
        parts: list[str] = []
        if self.min_discovery_age is not None:
            parts.append(f"age >= {self.min_discovery_age.total_seconds() / 3600:g}h")
        if self.min_liq_to_mcap is not None:
            parts.append(f"liq/mcap >= {self.min_liq_to_mcap}")
        if self.max_liq_to_mcap is not None:
            parts.append(f"liq/mcap <= {self.max_liq_to_mcap}")
        if self.min_liquidity_usd is not None:
            parts.append(f"liquidity >= ${self.min_liquidity_usd:,.0f}")
        if self.min_sell_buy is not None:
            parts.append(f"sell/buy >= {self.min_sell_buy}")
        if self.reject_sell_buy_band is not None:
            lo, hi = self.reject_sell_buy_band
            parts.append(f"reject {lo} <= sell/buy < {hi}")
        return " and ".join(parts) if parts else "no entry filter"

    @property
    def family(self) -> str:
        """Which feature family this level belongs to. Used by attribution."""
        if self.min_discovery_age is not None and self.min_liq_to_mcap is not None:
            return "combo"
        if self.min_discovery_age is not None:
            return "age"
        if self.min_liq_to_mcap is not None:
            return "liq_mcap"
        if self.min_sell_buy is not None or self.reject_sell_buy_band is not None:
            return "sell_buy"
        if self.min_liquidity_usd is not None:
            return "liquidity"
        return "none"


_H = lambda h: timedelta(hours=h)  # noqa: E731

ENTRIES: tuple[EntryConfig, ...] = (
    EntryConfig(key="E-none", label="No entry filter"),
    EntryConfig(key="E-age2", label="Age >= 2h", min_discovery_age=_H(2)),
    EntryConfig(key="E-age4", label="Age >= 4h", min_discovery_age=_H(4)),
    EntryConfig(key="E-age6", label="Age >= 6h", min_discovery_age=_H(6)),
    EntryConfig(key="E-age12", label="Age >= 12h", min_discovery_age=_H(12)),
    EntryConfig(key="E-lm20", label="Liq/mcap >= 0.20", min_liq_to_mcap=Decimal("0.20")),
    EntryConfig(key="E-lm35", label="Liq/mcap >= 0.35", min_liq_to_mcap=Decimal("0.35")),
    EntryConfig(key="E-sb10", label="Sell/buy >= 0.10", min_sell_buy=Decimal("0.10")),
    EntryConfig(
        key="E-sbband",
        label="Reject sell/buy in [0.10, 0.35)",
        reject_sell_buy_band=(Decimal("0.10"), Decimal("0.35")),
    ),
    EntryConfig(
        key="E-liq50k",
        label="Liquidity >= $50,000",
        min_liquidity_usd=Decimal(50_000),
    ),
    EntryConfig(
        key="E-age4lm20",
        label="Age >= 4h and liq/mcap >= 0.20",
        min_discovery_age=_H(4),
        min_liq_to_mcap=Decimal("0.20"),
    ),
)


# ── Size ────────────────────────────────────────────────────────────────────

#: §6. Three fixed sizes, plus $100 kept apart as a legacy reference rather
#: than as a fourth level — it is the live wallet's size, not a hypothesis.
SIZES: tuple[Decimal, ...] = (Decimal(10), Decimal(25), Decimal(50))
LEGACY_SIZE = Decimal(100)


# ── Profit taking ───────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ProfitConfig:
    key: str
    label: str
    rungs: tuple[Rung, ...]

    def describe(self) -> str:
        if not self.rungs:
            return "no take-profit; the whole position runs to the exit rule"
        parts = [f"{r.fraction * 100:g}% at {r.multiple:g}x" for r in self.rungs]
        remainder = Decimal(1) - sum((r.fraction for r in self.rungs), Decimal(0))
        if remainder > 0:
            parts.append(f"{remainder * 100:g}% held to the exit rule")
        return "take " + ", ".join(parts)


def _rungs(*pairs: tuple[str, str]) -> tuple[Rung, ...]:
    return tuple(Rung(multiple=Decimal(m), fraction=Decimal(f)) for m, f in pairs)


PROFITS: tuple[ProfitConfig, ...] = (
    ProfitConfig(key="P0", label="No take profit", rungs=()),
    ProfitConfig(
        key="P1",
        label="Full ladder to 2x",
        rungs=_rungs(("1.25", "0.25"), ("1.50", "0.25"), ("1.75", "0.25"), ("2.00", "0.25")),
    ),
    ProfitConfig(
        key="P2",
        label="Ladder + 25% runner",
        rungs=_rungs(("1.25", "0.25"), ("1.50", "0.25"), ("1.75", "0.25")),
    ),
    ProfitConfig(
        key="P3",
        label="Early harvest, 50% runner",
        rungs=_rungs(("1.25", "0.25"), ("1.50", "0.25")),
    ),
    ProfitConfig(key="P4", label="Principal recovery at 2x", rungs=_rungs(("2.00", "0.50"))),
    ProfitConfig(key="P5", label="50/50 at 1.5x", rungs=_rungs(("1.50", "0.50"))),
    #: §7 lists P6 (barbell) with the same rungs as P3. Kept as a distinct key
    #: because the brief distinguishes them; identical results are the expected
    #: outcome and act as a determinism check, exactly as S3/S10 do in
    #: `strategy_lab.strategies`.
    ProfitConfig(
        key="P6",
        label="Barbell, 50% runner",
        rungs=_rungs(("1.25", "0.25"), ("1.50", "0.25")),
    ),
)

P3_P6_EQUIVALENCE = (
    "P3 and P6 carry identical rungs — §7 specifies the same ladder for both. "
    "Identical results are expected and serve as a determinism check, not a bug."
)


# ── Exit / hold ─────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ExitConfig:
    key: str
    label: str
    hold_for: timedelta
    trailing: TrailingRule | None = None
    decay: tuple[DecayRule, ...] = ()

    def describe(self) -> str:
        hours = self.hold_for.total_seconds() / 3600
        parts = [f"hard expiry at {hours:g}h"]
        if self.trailing is not None:
            if self.trailing.activation_multiple is None:
                parts.insert(0, f"{self.trailing.drawdown * 100:g}% trailing stop from entry")
            else:
                parts.insert(
                    0,
                    f"{self.trailing.drawdown * 100:g}% trailing stop, armed only after "
                    f"{self.trailing.activation_multiple:g}x",
                )
        if self.decay:
            parts.insert(0, "deterministic time-decay exit for stagnant positions")
        if self.trailing is None and not self.decay:
            parts.insert(0, "no stop of any kind")
        return "; ".join(parts)

    @property
    def family(self) -> str:
        if self.decay:
            return "decay"
        if self.trailing is None:
            return "pure_hold"
        return (
            "trail_from_entry"
            if self.trailing.activation_multiple is None
            else "trail_after_profit"
        )


#: §6's S6 logic, reused verbatim rather than restated — a second copy of a
#: threshold is a second thing to keep in agreement.
_DECAY = (
    DecayRule(
        at=timedelta(minutes=60),
        never_exceeded=Decimal("1.10"),
        at_or_below=Decimal("1.00"),
    ),
    DecayRule(
        at=timedelta(minutes=120),
        never_exceeded=Decimal("1.20"),
        at_or_below=Decimal("1.05"),
    ),
)

EXITS: tuple[ExitConfig, ...] = (
    ExitConfig(key="X-hold2", label="Pure hold 2h", hold_for=_H(2)),
    ExitConfig(key="X-hold4", label="Pure hold 4h", hold_for=_H(4)),
    ExitConfig(key="X-hold6", label="Pure hold 6h", hold_for=MAX_HOLD),
    ExitConfig(
        key="X-tr25",
        label="Trail 25% from entry, 6h",
        hold_for=MAX_HOLD,
        trailing=TrailingRule(drawdown=Decimal("0.25")),
    ),
    ExitConfig(
        key="X-tr35",
        label="Trail 35% from entry, 6h",
        hold_for=MAX_HOLD,
        trailing=TrailingRule(drawdown=Decimal("0.35")),
    ),
    ExitConfig(
        key="X-tr25a15",
        label="Trail 25% after 1.5x, 6h",
        hold_for=MAX_HOLD,
        trailing=TrailingRule(drawdown=Decimal("0.25"), activation_multiple=Decimal("1.5")),
    ),
    ExitConfig(
        key="X-tr35a15",
        label="Trail 35% after 1.5x, 6h",
        hold_for=MAX_HOLD,
        trailing=TrailingRule(drawdown=Decimal("0.35"), activation_multiple=Decimal("1.5")),
    ),
    ExitConfig(key="X-decay", label="Time-decay + 6h", hold_for=MAX_HOLD, decay=_DECAY),
)

#: §8 lists E4 ("ladder only + hard expiry") and E5 ("ladder + activated
#: trail"). Both are already in the space as *combinations*: E4 is any
#: `PROFITS` entry with rungs paired with `X-hold*`, and E5 is one paired with
#: `X-tr*a15`. Adding them as separate exit families would duplicate rows under
#: two names and double-count them in attribution.
EXIT_FAMILIES_NOTE = (
    "§8's E4 and E5 are combinations rather than exit families: E4 = any laddered "
    "profit config with a pure-hold exit, E5 = a laddered profit config with an "
    "activated trail. Both are present; neither is a separate key."
)


# ── Portfolio (stage two) ───────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PortfolioConfig:
    """§9. Applied only to survivors, never mixed into the base search."""

    key: str
    label: str
    #: Pause *new entries* after this many catastrophic closes inside `window`.
    breaker_losses: int | None = None
    breaker_window: timedelta | None = None
    #: Cap on the share of the wallet that may be deployed at once.
    max_exposure_pct: Decimal | None = None

    def describe(self) -> str:
        parts: list[str] = []
        if self.breaker_losses is not None and self.breaker_window is not None:
            hours = self.breaker_window.total_seconds() / 3600
            parts.append(
                f"pause new entries after {self.breaker_losses} catastrophic losses "
                f"within {hours:g}h (open positions keep exiting)"
            )
        if self.max_exposure_pct is not None:
            parts.append(f"deploy at most {self.max_exposure_pct:g}% of the wallet at once")
        return "; ".join(parts) if parts else "no portfolio control"


PORTFOLIOS: tuple[PortfolioConfig, ...] = (
    PortfolioConfig(key="R-none", label="None"),
    PortfolioConfig(
        key="R-brkA",
        label="Breaker A",
        breaker_losses=2,
        breaker_window=timedelta(hours=6),
    ),
    PortfolioConfig(
        key="R-brkB",
        label="Breaker B",
        breaker_losses=3,
        breaker_window=timedelta(hours=24),
    ),
    PortfolioConfig(key="R-exp25", label="Max exposure 25%", max_exposure_pct=Decimal(25)),
    PortfolioConfig(key="R-exp40", label="Max exposure 40%", max_exposure_pct=Decimal(40)),
    PortfolioConfig(key="R-exp60", label="Max exposure 60%", max_exposure_pct=Decimal(60)),
)

NO_PORTFOLIO = PORTFOLIOS[0]


# ── A generated definition ──────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Candidate:
    """One immutable strategy definition. Hashed, versioned, never edited."""

    strategy_id: str
    version: str
    entry: EntryConfig
    size_usd: Decimal
    profit: ProfitConfig
    exit: ExitConfig
    portfolio: PortfolioConfig
    #: Legacy reference rows are ranked alongside and labelled apart. They are
    #: what we already do, so they can never be a "discovery".
    reference: bool = False

    @property
    def key(self) -> str:
        return f"{self.strategy_id}@{self.version}"

    @property
    def rules(self) -> StrategyRules:
        """The pure exit contract, assembled from the two config halves."""
        return StrategyRules(
            rungs=self.profit.rungs,
            trailing=self.exit.trailing,
            decay=self.exit.decay,
            hold_for=self.exit.hold_for,
        )

    def canonical(self) -> dict[str, Any]:
        """The definition, **without its id**.

        Deliberately excludes `strategy_id` **and every config key**: a
        definition hash should fingerprint what the strategy *does*, not what it
        is called. Including the id made every hash unique by construction; then
        including `profit.key` kept P3 and P6 apart on their names alone, though
        the brief specifies identical rungs for both. Only parameters are hashed.

        The keys are not lost — they live on `factors()`, which is what
        attribution groups by and what the UI filters on.
        """
        entry = self.entry
        return {
            "version": self.version,
            "entry": {
                "min_discovery_age_s": (
                    None
                    if entry.min_discovery_age is None
                    else entry.min_discovery_age.total_seconds()
                ),
                "min_liq_to_mcap": _s(entry.min_liq_to_mcap),
                "max_liq_to_mcap": _s(entry.max_liq_to_mcap),
                "min_liquidity_usd": _s(entry.min_liquidity_usd),
                "min_sell_buy": _s(entry.min_sell_buy),
                "reject_sell_buy_band": (
                    None
                    if entry.reject_sell_buy_band is None
                    else [str(x) for x in entry.reject_sell_buy_band]
                ),
            },
            "size_usd": str(self.size_usd),
            "profit": {
                "rungs": [[str(r.multiple), str(r.fraction)] for r in self.profit.rungs],
            },
            "exit": {
                "hold_s": self.exit.hold_for.total_seconds(),
                "trailing": (
                    None
                    if self.exit.trailing is None
                    else {
                        "drawdown": str(self.exit.trailing.drawdown),
                        "activation": _s(self.exit.trailing.activation_multiple),
                        "fraction": str(self.exit.trailing.fraction),
                    }
                ),
                "decay": [
                    [d.at.total_seconds(), str(d.never_exceeded), str(d.at_or_below)]
                    for d in self.exit.decay
                ],
            },
            "portfolio": {
                "breaker_losses": self.portfolio.breaker_losses,
                "breaker_window_s": (
                    None
                    if self.portfolio.breaker_window is None
                    else self.portfolio.breaker_window.total_seconds()
                ),
                "max_exposure_pct": _s(self.portfolio.max_exposure_pct),
            },
        }

    @property
    def definition_hash(self) -> str:
        return hashlib.sha256(
            json.dumps(self.canonical(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def explain(self) -> str:
        """§29. Plain English, no parameter blob."""
        size = f"${self.size_usd:,.0f} entries"
        who = (
            "on every canonical opportunity"
            if self.entry.family == "none"
            else (f"on tokens where {self.entry.describe()}")
        )
        return (
            f"{size} {who}. Then {self.profit.describe()}. "
            f"Exit: {self.exit.describe()}."
            + (
                ""
                if self.portfolio.key == "R-none"
                else f" Risk: {self.portfolio.describe()}."
            )
        )

    #: The design choices attribution groups by.
    def factors(self) -> dict[str, str]:
        return {
            "entry": self.entry.key,
            "entry_family": self.entry.family,
            "size": f"${self.size_usd:,.0f}",
            "profit": self.profit.key,
            "exit": self.exit.key,
            "exit_family": self.exit.family,
            "portfolio": self.portfolio.key,
        }


def _s(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def generate(version: str = "v1") -> list[Candidate]:
    """The full factorial, plus the legacy reference rows. Deterministic.

    Ordering is fixed by the declaration order of each dimension, so the same
    call always produces the same ids in the same sequence — which is what lets
    a run be reproduced and a result be traced back to a definition.
    """
    out: list[Candidate] = []
    index = 0
    for entry in ENTRIES:
        for size in SIZES:
            for profit in PROFITS:
                for exit_config in EXITS:
                    index += 1
                    out.append(
                        Candidate(
                            strategy_id=f"DISC-A{index:04d}",
                            version=version,
                            entry=entry,
                            size_usd=size,
                            profit=profit,
                            exit=exit_config,
                            portfolio=NO_PORTFOLIO,
                        )
                    )

    # The live wallet's size and rule, carried through the identical machinery.
    legacy_exit = next(e for e in EXITS if e.key == "X-tr25")
    for profit in (PROFITS[0], PROFITS[2]):
        index += 1
        out.append(
            Candidate(
                strategy_id=f"DISC-L{index:04d}",
                version=version,
                entry=ENTRIES[0],
                size_usd=LEGACY_SIZE,
                profit=profit,
                exit=legacy_exit,
                portfolio=NO_PORTFOLIO,
                reference=True,
            )
        )
    return out


def with_portfolio(candidate: Candidate, portfolio: PortfolioConfig, index: int) -> Candidate:
    """Stage two: the same base strategy behind a risk control."""
    return Candidate(
        strategy_id=f"DISC-R{index:04d}",
        version=candidate.version,
        entry=candidate.entry,
        size_usd=candidate.size_usd,
        profit=candidate.profit,
        exit=candidate.exit,
        portfolio=portfolio,
        reference=candidate.reference,
    )


def summary() -> dict[str, Any]:
    """What the search space is, for the report and the UI."""
    return {
        "space_version": SPACE_VERSION,
        "entries": len(ENTRIES),
        "sizes": len(SIZES),
        "profits": len(PROFITS),
        "exits": len(EXITS),
        "portfolios_stage_two": len(PORTFOLIOS) - 1,
        "generated": len(ENTRIES) * len(SIZES) * len(PROFITS) * len(EXITS) + 2,
        "max_hold_hours": MAX_HOLD.total_seconds() / 3600,
        "unavailable_features": UNAVAILABLE_FEATURES,
        "notes": [EXIT_FAMILIES_NOTE, P3_P6_EQUIVALENCE],
    }
