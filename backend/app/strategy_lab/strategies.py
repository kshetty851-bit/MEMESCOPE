"""The eleven definitions. **Versioned, hashed, and frozen once they have run.**

Ten hypotheses from the brief plus the current live wallet as a read-only
benchmark. Each is a value, not a class: the whole difference between S1 and
S10 is which rungs are in a tuple.

── WHY THESE ARE IN CODE AND NOT IN A TABLE ─────────────────────────────────

A strategy re-read from configuration after the fact can be re-read favourably.
These are literals in source, and `definition_hash` is computed from them, so a
changed threshold produces a different hash — which is what makes §17's rule
enforceable rather than aspirational. `repository.register` refuses to reuse an
id+version whose stored hash disagrees with the code's.

Changing 1.25/1.50/1.75 to 1.30/1.60/2.00 is **a new version**, S1 v2.0.0. It
is never an edit to S1 v1.0.0, because every result already published under
that name would silently come to mean something else.

── WHAT IS DELIBERATELY NOT HERE ────────────────────────────────────────────

No optimiser, no parameter sweep, no fitted survival model. §18 is explicit:
these are hypotheses to be tested exactly as specified. The one entry gate that
exists (S9's) uses evidence the platform already records at the moment of
eligibility, and its limitation is written into its own docstring rather than
into a footnote.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from app.strategy_lab.rules import DecayRule, Rung, StrategyRules, TrailingRule

_HOLD_6H = timedelta(hours=6)
#: Every strategy in the brief enters $25. The legacy benchmark does not, and
#: that difference is the point of having it — see `LEGACY_BASELINE`.
_ENTRY = Decimal(25)


@dataclass(frozen=True, slots=True)
class StrategyDefinition:
    """One versioned hypothesis. Immutable, and hashed so it stays that way."""

    strategy_id: str
    version: str
    name: str
    purpose: str
    entry_size_usd: Decimal
    rules: StrategyRules
    #: Minimum age at the moment of eligibility, or `None` for no entry gate.
    #: Measured from first discovery — see `S9`, which is the only user.
    min_discovery_age: timedelta | None = None
    #: True for the reproduction of the live wallet. Ranked alongside, labelled
    #: apart, and never a candidate for promotion — it is already what we do.
    benchmark: bool = False

    @property
    def key(self) -> str:
        return f"{self.strategy_id}@{self.version}"

    @property
    def definition_hash(self) -> str:
        """A stable digest of everything that changes a result.

        Name and purpose are excluded on purpose: rewording a description must
        not look like a strategy change, and changing a threshold must.
        """
        return hashlib.sha256(
            json.dumps(self._canonical(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def _canonical(self) -> dict:
        r = self.rules
        return {
            "id": self.strategy_id,
            "version": self.version,
            "entry_size_usd": str(self.entry_size_usd),
            "hold_for_seconds": r.hold_for.total_seconds(),
            "rungs": [[str(x.multiple), str(x.fraction)] for x in r.rungs],
            "trailing": (
                None
                if r.trailing is None
                else {
                    "drawdown": str(r.trailing.drawdown),
                    "activation": (
                        None
                        if r.trailing.activation_multiple is None
                        else str(r.trailing.activation_multiple)
                    ),
                    "fraction": str(r.trailing.fraction),
                }
            ),
            "decay": [
                [d.at.total_seconds(), str(d.never_exceeded), str(d.at_or_below)]
                for d in r.decay
            ],
            "min_discovery_age_seconds": (
                None
                if self.min_discovery_age is None
                else self.min_discovery_age.total_seconds()
            ),
        }

    def matrix_row(self) -> dict[str, bool]:
        """§21's comparison matrix, derived from the definition rather than typed."""
        r = self.rules
        return {
            "entry_25": self.entry_size_usd == _ENTRY,
            "no_initial_stop": r.trailing is None
            or r.trailing.activation_multiple is not None,
            "partial_profits": bool(r.rungs)
            or (r.trailing is not None and r.trailing.fraction < 1),
            "expiry_6h": r.hold_for == _HOLD_6H,
            "runner": r.runner_fraction > 0 and (r.trailing is None or bool(r.rungs)),
            "survival_gate": self.min_discovery_age is not None,
            "time_decay": bool(r.decay),
            "trailing": r.trailing is not None,
        }


def _ladder(*pairs: tuple[str, str]) -> tuple[Rung, ...]:
    return tuple(Rung(multiple=Decimal(m), fraction=Decimal(f)) for m, f in pairs)


S1 = StrategyDefinition(
    strategy_id="S1",
    version="1.0.0",
    name="V2 Ladder Runner",
    purpose=(
        "Three quarter-rungs and a quarter left running to the clock. The "
        "published Paper Wallet V2 ladder, restated here so it is measured on "
        "the same opportunities as everything else."
    ),
    entry_size_usd=_ENTRY,
    rules=StrategyRules(
        rungs=_ladder(("1.25", "0.25"), ("1.50", "0.25"), ("1.75", "0.25")),
        hold_for=_HOLD_6H,
    ),
)

S2 = StrategyDefinition(
    strategy_id="S2",
    version="1.0.0",
    name="Principal Recovery",
    purpose=(
        "Sell half at 2x — approximately the original stake back before "
        "execution costs — and let the rest run free to the clock. Turns a "
        "winner into a position that cannot lose the money that funded it."
    ),
    entry_size_usd=_ENTRY,
    rules=StrategyRules(rungs=_ladder(("2.00", "0.50")), hold_for=_HOLD_6H),
)

S3 = StrategyDefinition(
    strategy_id="S3",
    version="1.0.0",
    name="Early Harvest Runner",
    purpose=(
        "Bank a quarter at 1.25x and another at 1.50x, then hold half to the "
        "clock. Tests whether the third rung in S1 is buying anything."
    ),
    entry_size_usd=_ENTRY,
    rules=StrategyRules(rungs=_ladder(("1.25", "0.25"), ("1.50", "0.25")), hold_for=_HOLD_6H),
)

S4 = StrategyDefinition(
    strategy_id="S4",
    version="1.0.0",
    name="50/50 Runner",
    purpose=(
        "One decision: half off at 1.50x, half held to the clock. The simplest "
        "thing that is not doing nothing."
    ),
    entry_size_usd=_ENTRY,
    rules=StrategyRules(rungs=_ladder(("1.50", "0.50")), hold_for=_HOLD_6H),
)

S5 = StrategyDefinition(
    strategy_id="S5",
    version="1.0.0",
    name="Pure HOLD-6H Control",
    purpose=(
        "No stop, no target, no trail. Holds everything to the clock. **The "
        "control.** If the engineered strategies do not beat this, the exit "
        "engineering is costing money rather than making it, and that is the "
        "single most important thing this lab can find out."
    ),
    entry_size_usd=_ENTRY,
    rules=StrategyRules(hold_for=_HOLD_6H),
)

S6 = StrategyDefinition(
    strategy_id="S6",
    version="1.0.0",
    name="Time-Decay Exit",
    purpose=(
        "Free capital from positions that have gone nowhere, on a deterministic "
        "clock rather than on a price stop. Thresholds are the brief's stated "
        "hypotheses, not fitted values."
    ),
    entry_size_usd=_ENTRY,
    rules=StrategyRules(
        hold_for=_HOLD_6H,
        decay=(
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
        ),
    ),
)

S7 = StrategyDefinition(
    strategy_id="S7",
    version="1.0.0",
    name="Profit-Protected Runner",
    purpose=(
        "Do not try to stop a newborn rug. Take a quarter at 1.50x, and only "
        "then protect the remaining three quarters with a 25% giveback stop "
        "measured from the high set after activation."
    ),
    entry_size_usd=_ENTRY,
    rules=StrategyRules(
        rungs=_ladder(("1.50", "0.25")),
        trailing=TrailingRule(drawdown=Decimal("0.25"), activation_multiple=Decimal("1.50")),
        hold_for=_HOLD_6H,
    ),
)

S8 = StrategyDefinition(
    strategy_id="S8",
    version="1.0.0",
    name="Wide Trailing Runner",
    purpose=(
        "No partial sale at all. Nothing happens below 1.50x; above it a 35% "
        "giveback stop protects the whole position. Maximum exposure to a "
        "large runner, at the cost of giving a third of it back on the way out."
    ),
    entry_size_usd=_ENTRY,
    rules=StrategyRules(
        trailing=TrailingRule(drawdown=Decimal("0.35"), activation_multiple=Decimal("1.50")),
        hold_for=_HOLD_6H,
    ),
)

S9 = StrategyDefinition(
    strategy_id="S9",
    version="1.0.0",
    name="Survival-Aware Ladder",
    purpose=(
        "S1's exits behind an entry gate: only tokens that had already survived "
        "four hours when they became eligible. Measures whether choosing better "
        "opportunities beats engineering better exits."
    ),
    entry_size_usd=_ENTRY,
    rules=StrategyRules(
        rungs=_ladder(("1.25", "0.25"), ("1.50", "0.25"), ("1.75", "0.25")),
        hold_for=_HOLD_6H,
    ),
    min_discovery_age=timedelta(hours=4),
)
#: **What S9's gate actually measures, stated where it cannot be missed.**
#:
#: `min_discovery_age` is time since MEMESCOPE *first discovered* the token, not
#: time since the token or its pool was created. It is a lower bound on true
#: age, and it is the only age this platform records at the moment of
#: eligibility. It is used because it is genuinely point-in-time evidence; it is
#: labelled `discovery_age` everywhere rather than `token_age` so no reader
#: mistakes it for the latter.
#:
#: This gate exists **only inside Strategy Lab**. Radar eligibility, Paper
#: Wallet entry and SEC-2 are unchanged and do not know it exists.
S9_GATE_LIMITATION = (
    "S9's age gate uses time since first discovery by this platform, which is a "
    "lower bound on true token age and not a measurement of it. The gate is "
    "confined to Strategy Lab and changes no upstream eligibility."
)

S10 = StrategyDefinition(
    strategy_id="S10",
    version="1.0.0",
    name="Moonshot Barbell",
    purpose=(
        "Bank half in two early rungs, then leave half completely unprotected "
        "to the clock — no trail, no target, deliberately. Tests whether early "
        "money plus large retained exposure beats either alone."
    ),
    entry_size_usd=_ENTRY,
    rules=StrategyRules(rungs=_ladder(("1.25", "0.25"), ("1.50", "0.25")), hold_for=_HOLD_6H),
)

#: **S10 and S3 have identical exit rules.** Both bank 25% at 1.25x and 25% at
#: 1.50x and hold the remaining half to six hours; the brief describes them
#: differently ("hold the runner" vs "do not close it at 2x") but specifies the
#: same behaviour, and V1 explicitly forbids adding S10's optional profit
#: protection. They are kept as separate registered strategies because they are
#: separate hypotheses in the brief and their results are the evidence that the
#: distinction is not a real one — they should score identically, and if they
#: ever do not, the replay is non-deterministic.
S3_S10_EQUIVALENCE = (
    "S3 and S10 v1 resolve to identical rules. Identical results are the "
    "expected outcome and are a determinism check, not a bug."
)

LEGACY_BASELINE = StrategyDefinition(
    strategy_id="LEGACY",
    version="1.0.0",
    name="Legacy Baseline — original Paper Wallet",
    purpose=(
        "The live wallet's own rule — a 25% trailing stop armed from entry with "
        "a six-hour maximum hold — run over the same canonical opportunities as "
        "everything else. Without it, comparing these ten against the wallet's "
        "recorded history would be comparing them against a different and "
        "much smaller population of tokens."
    ),
    entry_size_usd=Decimal(100),
    rules=StrategyRules(
        trailing=TrailingRule(drawdown=Decimal("0.25"), activation_multiple=None),
        hold_for=_HOLD_6H,
    ),
    benchmark=True,
)

LEGACY_BASELINE_25 = StrategyDefinition(
    strategy_id="LEGACY25",
    version="1.0.0",
    name="Legacy Baseline at $25",
    purpose=(
        "The same legacy rule sized at $25 instead of $100. Present so the gap "
        "between LEGACY and the ten can be attributed: LEGACY differs from them "
        "in both its exit rule and its position size, and one row cannot say "
        "which one mattered."
    ),
    entry_size_usd=_ENTRY,
    rules=StrategyRules(
        trailing=TrailingRule(drawdown=Decimal("0.25"), activation_multiple=None),
        hold_for=_HOLD_6H,
    ),
    benchmark=True,
)

#: Declaration order is display order. The ten hypotheses, then the benchmarks.
ALL: tuple[StrategyDefinition, ...] = (
    S1,
    S2,
    S3,
    S4,
    S5,
    S6,
    S7,
    S8,
    S9,
    S10,
    LEGACY_BASELINE,
    LEGACY_BASELINE_25,
)

BY_ID: dict[str, StrategyDefinition] = {d.strategy_id: d for d in ALL}


def get(strategy_id: str) -> StrategyDefinition | None:
    return BY_ID.get(strategy_id)


def _assert_unique() -> None:
    keys = [d.key for d in ALL]
    if len(set(keys)) != len(keys):
        raise ValueError(f"duplicate strategy keys: {keys}")


_assert_unique()
