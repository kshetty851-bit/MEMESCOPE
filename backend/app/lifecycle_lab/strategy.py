"""Meme Lifecycle Lab — the baseline strategy and its control arms.

One strategy, untuned: **Attention Acceleration + Market Confirmation**. A
position is opened iff, at the decision instant,

  attention  — acceleration ≥ ``min_acceleration``
             — baseline_multiple ≥ ``min_baseline_multiple``
  market     — volume_growth ≥ ``min_volume_growth``
             — at least ``min_market_points`` visible readings in the window
             — price run-up over ``run_up_window`` ≤ ``max_price_run_up``
  execution  — the newest market reading is no older than
               ``max_market_data_age`` (a fill needs a current price)

**An ``Unavailable`` input is never a pass and never a zero.** It fails its
condition with ``<condition>_unavailable`` and the reason goes into the
evidence, so "no entry because nothing was measured" stays distinguishable
from "no entry because the measurement said no".

Control arms are compositions of the same condition functions, so an arm
differs from the baseline only in which conditions it applies:

* ``CONTROL_B_MARKET_ONLY`` — the market conditions, no attention.
* ``CONTROL_C_ATTENTION_ONLY`` — the attention conditions, no market
  confirmation.
* ``CONTROL_D_COMBINED`` — both; identical conditions to ``BASELINE`` and
  registered separately so the control table has an explicit combined row.
* ``CONTROL_A_EXISTING`` — MEMESCOPE's existing scoring strategy. **Not wired**
  in Phase 1-4: replaying it honestly needs the existing scorer's own
  point-in-time inputs (score history as it stood at ``T``), which this
  package does not load. It returns ``not_wired`` rather than an imitation.

Every arm, including the controls, carries the execution guard: it is about
whether a fill at the observed price is honest, not about the signal, and
leaving it off one arm would make that arm look better for a reason that has
nothing to do with what it measures.

Reason codes are stable strings; prose is rendered elsewhere. None of them is
a recommendation.

Pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from app.lifecycle_lab.config import BaselineStrategyConfig
from app.lifecycle_lab.domain import (
    Arm,
    AttentionFeatures,
    MarketFeatures,
    Measured,
    Unavailable,
)

STRATEGY_VERSION = "mll-strategy-v1"
BASELINE_NAME = "attention_acceleration_market_confirmation"

STATUS_ENTER = "enter"
STATUS_NO_ENTRY = "no_entry"
STATUS_NOT_WIRED = "not_wired"

REASON_CONDITIONS_MET = "conditions_met"
REASON_CONDITIONS_NOT_MET = "conditions_not_met"
#: At least one failed condition was Unavailable (rather than measured and
#: below threshold).
REASON_INPUTS_UNAVAILABLE = "inputs_unavailable"
REASON_CONTROL_A_NOT_WIRED = "control_a_not_wired"


@dataclass(frozen=True, slots=True)
class StrategyInputs:
    """What a strategy may see. Built only from an ``InformationState``."""

    attention: AttentionFeatures
    market: MarketFeatures
    #: Fractional price change over ``run_up_window`` (0.5 = +50%).
    run_up: Measured
    #: Visible market readings for this mint inside the run-up window.
    market_points: int


@dataclass(frozen=True, slots=True)
class Decision:
    arm: Arm
    status: str
    reason_code: str
    failed_conditions: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def enter(self) -> bool:
        return self.status == STATUS_ENTER

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm.value,
            "status": self.status,
            "reason_code": self.reason_code,
            "failed_conditions": list(self.failed_conditions),
            "evidence": self.evidence,
        }


# --------------------------------------------------------------------------
# Conditions. Each returns (name, passed, failure_code_or_None, evidence).
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Check:
    name: str
    passed: bool
    failure: str | None
    evidence: Any


def _ev(value: Measured | None) -> Any:
    if isinstance(value, Unavailable):
        return {"unavailable": value.reason}
    if value is None:
        return {"unavailable": "missing"}
    return str(value)


def _at_least(name: str, value: Measured | None, floor: Decimal) -> _Check:
    if not isinstance(value, Decimal):
        return _Check(name, False, f"{name}_unavailable", _ev(value))
    ok = value >= floor
    return _Check(name, ok, None if ok else f"{name}_below_min", _ev(value))


def _at_most(name: str, value: Measured | None, ceiling: Decimal) -> _Check:
    if not isinstance(value, Decimal):
        return _Check(name, False, f"{name}_unavailable", _ev(value))
    ok = value <= ceiling
    return _Check(name, ok, None if ok else f"{name}_above_max", _ev(value))


def attention_checks(inp: StrategyInputs, cfg: BaselineStrategyConfig) -> list[_Check]:
    return [
        _at_least("acceleration", inp.attention.acceleration, cfg.min_acceleration),
        _at_least(
            "baseline_multiple", inp.attention.baseline_multiple, cfg.min_baseline_multiple
        ),
    ]


def execution_checks(inp: StrategyInputs, cfg: BaselineStrategyConfig) -> list[_Check]:
    return [
        _at_most(
            "market_data_age",
            inp.market.data_age_seconds,
            Decimal(int(cfg.max_market_data_age.total_seconds())),
        )
    ]


def market_checks(inp: StrategyInputs, cfg: BaselineStrategyConfig) -> list[_Check]:
    points_ok = inp.market_points >= cfg.min_market_points
    return [
        _at_least("volume_growth", inp.market.volume_growth, cfg.min_volume_growth),
        _Check(
            "market_points",
            points_ok,
            None if points_ok else "market_points_below_min",
            inp.market_points,
        ),
        _at_most("price_run_up", inp.run_up, cfg.max_price_run_up),
    ]


def _decide(arm: Arm, checks: list[_Check]) -> Decision:
    failed = tuple(c.failure for c in checks if c.failure is not None)
    evidence = {c.name: c.evidence for c in checks}
    if not failed:
        return Decision(arm, STATUS_ENTER, REASON_CONDITIONS_MET, (), evidence)
    reason = (
        REASON_INPUTS_UNAVAILABLE
        if any(f.endswith("_unavailable") for f in failed)
        else REASON_CONDITIONS_NOT_MET
    )
    return Decision(arm, STATUS_NO_ENTRY, reason, failed, evidence)


def baseline(inp: StrategyInputs, cfg: BaselineStrategyConfig) -> Decision:
    """Attention Acceleration + Market Confirmation (also CONTROL_D)."""
    return _decide(
        Arm.BASELINE,
        attention_checks(inp, cfg) + market_checks(inp, cfg) + execution_checks(inp, cfg),
    )


def control_b_market_only(inp: StrategyInputs, cfg: BaselineStrategyConfig) -> Decision:
    return _decide(
        Arm.CONTROL_B_MARKET_ONLY, market_checks(inp, cfg) + execution_checks(inp, cfg)
    )


def control_c_attention_only(inp: StrategyInputs, cfg: BaselineStrategyConfig) -> Decision:
    return _decide(
        Arm.CONTROL_C_ATTENTION_ONLY, attention_checks(inp, cfg) + execution_checks(inp, cfg)
    )


def control_d_combined(inp: StrategyInputs, cfg: BaselineStrategyConfig) -> Decision:
    return _decide(
        Arm.CONTROL_D_COMBINED,
        attention_checks(inp, cfg) + market_checks(inp, cfg) + execution_checks(inp, cfg),
    )


def control_a_existing(inp: StrategyInputs, cfg: BaselineStrategyConfig) -> Decision:
    """Not wired — see the module docstring. Never enters."""
    return Decision(Arm.CONTROL_A_EXISTING, STATUS_NOT_WIRED, REASON_CONTROL_A_NOT_WIRED)


StrategyFn = Callable[[StrategyInputs, BaselineStrategyConfig], Decision]

REGISTRY: dict[Arm, StrategyFn] = {
    Arm.BASELINE: baseline,
    Arm.CONTROL_A_EXISTING: control_a_existing,
    Arm.CONTROL_B_MARKET_ONLY: control_b_market_only,
    Arm.CONTROL_C_ATTENTION_ONLY: control_c_attention_only,
    Arm.CONTROL_D_COMBINED: control_d_combined,
}

_CONDITIONS: dict[Arm, tuple[str, ...]] = {
    Arm.BASELINE: ("attention", "market", "execution"),
    Arm.CONTROL_A_EXISTING: (),
    Arm.CONTROL_B_MARKET_ONLY: ("market", "execution"),
    Arm.CONTROL_C_ATTENTION_ONLY: ("attention", "execution"),
    Arm.CONTROL_D_COMBINED: ("attention", "market", "execution"),
}


def decide(arm: Arm, inp: StrategyInputs, cfg: BaselineStrategyConfig) -> Decision:
    return REGISTRY[arm](inp, cfg)


def is_wired(arm: Arm) -> bool:
    return arm is not Arm.CONTROL_A_EXISTING


def strategy_spec(arm: Arm, cfg: BaselineStrategyConfig) -> dict[str, Any]:
    """Everything that defines this arm's entry rule, for ``spec_hash``."""
    if not is_wired(arm):
        return {"arm": arm.value, "version": STRATEGY_VERSION, "wired": False}
    return {
        "arm": arm.value,
        "strategy": BASELINE_NAME,
        "version": STRATEGY_VERSION,
        "wired": True,
        "condition_groups": list(_CONDITIONS[arm]),
        "params": asdict(cfg),
    }
