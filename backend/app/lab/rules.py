"""Generic evaluation of the frozen V6 rules. Pure functions, no I/O, no clock.

There is one entry evaluator and one exit evaluator for all twenty strategies.
Writing twenty of each would let a strategy quietly acquire behaviour its
specification does not describe; driving them from `spec.py` means what you read
in the registry is exactly what runs.

Missing data is never imputed. A condition whose input is UNKNOWN evaluates
FALSE and names itself, so a skip always records a measured cause.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.lab.spec import Exits, Strategy


@dataclass(frozen=True)
class Verdict:
    eligible: bool
    #: The FIRST failing condition, in specification order.
    skip_reason: str | None = None


def evaluate_entry(strategy: Strategy, features: dict) -> Verdict:
    """Judge one token for one strategy at its own checkpoint."""
    for condition in strategy.entry:
        if features.get(condition.feature) is None:
            return Verdict(False, f"unknown_{condition.feature}")
        if not condition.evaluate(features):
            return Verdict(False, condition.skip_reason)
    return Verdict(True)


@dataclass(frozen=True)
class MarkState:
    """A position's live state, as of one mark. All multiples are executable."""

    #: sell_proceeds(ORIGINAL quantity) / cost — the frozen trigger basis.
    exec_multiple: Decimal
    peak_exec_multiple: Decimal
    held_hours: float
    liquidity_usd: Decimal | None
    entry_liquidity_usd: Decimal | None
    is_dead: bool
    sell_route_ok: bool | None
    break_even_armed: bool
    partial_done: bool
    #: Hours the executable multiple has sat inside the stagnation band.
    flat_hours: float = 0.0


@dataclass(frozen=True)
class ExitVerdict:
    #: None = keep holding. "PARTIAL" = bank the partial and keep the runner.
    action: str | None = None
    reason: str | None = None
    #: Level whose fill-drift cap applies, or None for a market exit.
    trigger_multiple: Decimal | None = None


STAGNATION_BAND = Decimal("0.05")


def evaluate_exit(exits: Exits, s: MarkState) -> ExitVerdict:
    """Which frozen exit fires, in a fixed order.

    Ordered so that on a single print the harsher outcome wins: a dead pool is
    settled before a target is honoured, because a price from a pool nobody can
    sell into is not a fill. Losses precede gains throughout; where two rules
    could fire on the same mark, the position never gets the benefit of the
    doubt. There are no conventional stop losses because V6 contains none.
    """
    if s.is_dead:
        return ExitVerdict("CLOSE", "dead_zero")

    # liquidity collapse — the cause of most deaths, checked before price
    if exits.liquidity_exit_absolute_usd is not None:
        if s.liquidity_usd is not None and s.liquidity_usd < exits.liquidity_exit_absolute_usd:
            return ExitVerdict("CLOSE", "liquidity_floor")
    if exits.liquidity_exit_frac_of_entry is not None:
        if (s.liquidity_usd is not None and s.entry_liquidity_usd
                and s.entry_liquidity_usd > 0
                and s.liquidity_usd < s.entry_liquidity_usd * exits.liquidity_exit_frac_of_entry):
            return ExitVerdict("CLOSE", "liquidity_decay")

    # sell route gone: only strategies that declared it exit on it
    if s.sell_route_ok is False and exits.sell_route_loss == "exit_at_best_quote":
        return ExitVerdict("CLOSE", "sell_route_lost")

    # break-even, once armed by having been in profit
    if exits.break_even_arm is not None and s.break_even_armed:
        floor = exits.break_even_exit or Decimal(1)
        if s.exec_multiple <= floor:
            return ExitVerdict("CLOSE", "break_even")

    # trailing stop off the executable peak, only once armed
    if exits.trailing_drawdown is not None:
        arm = exits.trailing_arm_at or Decimal(1)
        if s.peak_exec_multiple >= arm:
            if s.exec_multiple <= s.peak_exec_multiple * (1 - exits.trailing_drawdown):
                return ExitVerdict("CLOSE", "trailing_stop")

    # partial: bank half, then the runner target replaces the take profit
    if exits.partial_at is not None and not s.partial_done:
        if s.exec_multiple >= exits.partial_at:
            return ExitVerdict("PARTIAL", "partial_taken", exits.partial_at)

    target = exits.runner_target if (exits.partial_at is not None and s.partial_done) \
        else exits.take_profit
    if target is not None and s.exec_multiple >= target:
        label = "target_runner_2x" if target == exits.runner_target and exits.partial_at \
            else f"target_{str(target).replace('.', '_')}x"
        return ExitVerdict("CLOSE", label, target)

    if exits.stagnation_hours is not None:
        if abs(s.exec_multiple - 1) <= STAGNATION_BAND and s.flat_hours >= exits.stagnation_hours:
            return ExitVerdict("CLOSE", "stagnation")

    if exits.time_exit_hours is not None and s.held_hours >= exits.time_exit_hours:
        return ExitVerdict("CLOSE", f"time_{exits.time_exit_hours}h")

    return ExitVerdict()
