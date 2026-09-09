"""`Decimal ** float` must not appear anywhere. Rafiq hit this once.

Python defines Decimal exponentiation against another Decimal or an int and
NOTHING else, so `Decimal(2) ** 0.5` raises `TypeError` at runtime — not at
import, not in review, but on the first call in production. Strategy C's own
comment documents the workaround it needed.

Two tests, because either alone is a hole:

  * a static walk over every power expression in the package, which catches
    the literal form even on a path no test exercises;
  * a live call of the one function that actually exponentiates, on BOTH of
    its branches, which catches the case where the operands are variables and
    a static walk cannot know their types.
"""

from __future__ import annotations

import ast
import pathlib
from decimal import Decimal

import pytest

from app.labs.rafiq.strategies.strategy_c_volatility_adjusted import (
    VolatilityAdjustedPolicy,
    stop_distance_for,
)

PACKAGE = pathlib.Path(__file__).resolve().parent.parent
#: Shipping code only. This file deliberately contains the forbidden shape
#: once, in `test_python_really_does_reject_it`, and scanning itself would
#: turn the guard's own premise into a failure.
SOURCES = sorted(p for p in PACKAGE.rglob("*.py") if "tests" not in p.parts)


def test_python_really_does_reject_it() -> None:
    """The premise. If this ever stops raising, the tests below are theatre."""
    with pytest.raises(TypeError):
        Decimal(2) ** 0.5


def test_no_power_expression_mixes_a_decimal_with_a_float_literal() -> None:
    """`x ** 0.5` where either side is a float literal is the shape that bit
    him. Catch it as source, everywhere, including code no test runs."""
    offenders = []
    for path in SOURCES:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow)):
                continue
            for side in (node.left, node.right):
                if isinstance(side, ast.Constant) and isinstance(side.value, float):
                    offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, offenders


@pytest.mark.parametrize("sensitivity", [Decimal("0.5"), Decimal(1),
                                         Decimal("0.75"), Decimal(2)])
def test_stop_distance_survives_every_sensitivity(sensitivity: Decimal) -> None:
    """The live half. 0.5 goes through `Decimal.sqrt()`; every other value
    takes the float round-trip branch. Both must return a Decimal and neither
    may raise."""
    policy = VolatilityAdjustedPolicy(sensitivity=sensitivity)
    for liquidity in (Decimal(1_000), Decimal(50_000), Decimal(100_000),
                      Decimal(1_000_000)):
        result = stop_distance_for(liquidity, policy=policy)
        assert isinstance(result, Decimal)
        assert policy.min_stop_pct <= result <= policy.max_stop_pct
