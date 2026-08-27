"""The wallet could buy and never sell.

`driver.py` created BUY intents; everything downstream of a SELL was built and
nothing in production ever decided to sell. A wallet that only buys realises no
profit and compounds nothing, which is the whole point of funding one.

These are structural. What must never regress is WHERE the exit rules come from
and WHOSE rules apply — both are properties of the code, not of a fixture.
"""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

import pytest

from app.lab import spec
from app.lab.rules import MarkState, evaluate_exit
from app.real_wallet import exit_driver
# Imported for the side effect: Celery's registry is lazy, so a task is only
# registered once its module is loaded.
from app.real_wallet import scheduler as rw_scheduler
from app.workers.celery_app import celery_app

pytestmark = pytest.mark.unit


def _fn(name: str) -> ast.AsyncFunctionDef:
    tree = ast.parse(Path(exit_driver.__file__).read_text())
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.AsyncFunctionDef) and n.name == name)


def test_it_owns_no_exit_rule_of_its_own():
    """`evaluate_exit` is the Lab's and is imported, not reimplemented. Two
    implementations of 'when do we sell' would eventually disagree, and the paper
    record and the real record would stop describing the same strategy."""
    src = Path(exit_driver.__file__).read_text()
    assert "from app.lab.rules import MarkState, evaluate_exit" in src
    # No local reimplementation of the triggers.
    for trigger in ("take_profit >", "trailing_drawdown >", "runner_target >"):
        assert trigger not in src


def test_positions_exit_by_the_rules_they_entered_under():
    """The strategy comes from the POSITION, never from whatever is nominated
    now. Reading the nominated strategy here would silently rewrite the exit
    rules of every open position the moment the operator changed their mind."""
    fn = _fn("tick")
    src = ast.unparse(fn)
    assert "pos.strategy_id" in src
    assert "AutotradeSwitchService" not in src
    assert "nominated_strategy" not in src


def test_an_unpriceable_position_is_neither_marked_nor_exited():
    """A stale or missing price is an absence of information. Selling on one
    would act on a number nobody currently observes, and the Lab treats
    staleness the same way — the two records have to agree."""
    fn = _fn("_mark")
    src = ast.unparse(fn)
    assert "is_stale" in src
    returns_none = [n for n in ast.walk(fn)
                    if isinstance(n, ast.Return)
                    and isinstance(n.value, ast.Constant) and n.value.value is None]
    assert len(returns_none) >= 3, "every unmeasurable branch must refuse"


def test_the_peak_only_ever_rises():
    """A trailing stop measured against a peak that can fall is not a trailing
    stop."""
    src = ast.unparse(_fn("_mark"))
    assert "if exec_multiple > Decimal(str(pos.peak_exec_multiple or 1))" in src


def test_one_exit_per_position_ever():
    """Keyed by the position, because the position is the thing being closed. A
    timestamp in the key would let a retry open a second exit for one holding."""
    src = ast.unparse(_fn("_request_exit"))
    assert "f'v6exit:{pos.id}'" in src or 'f"v6exit:{pos.id}"' in src
    for volatile in ("now", "uuid4", "timestamp"):
        assert f"idempotency_key=f'v6exit:{{pos.id}}{volatile}" not in src


def test_it_creates_intents_and_never_signs_or_submits():
    src = Path(exit_driver.__file__).read_text()
    for forbidden in ("sign", "execute_signed_order", "transport", "submit"):
        assert f".{forbidden}(" not in src


def test_a_partial_is_promoted_to_a_close_rather_than_silently_dropped():
    """`create_sell_intent` binds the FULL confirmed quantity, so a partial
    cannot be expressed yet. Ignoring it would let the position run past a level
    its rules said to sell at; promoting it banks the profit early and the reason
    records that it happened."""
    src = ast.unparse(_fn("tick"))
    assert "partial_promoted_to_close" in src


def test_the_exit_driver_is_actually_scheduled():
    entry = celery_app.conf.beat_schedule["real-wallet-exit-tick"]
    assert entry["task"] == "app.real_wallet.scheduler.real_wallet_exit_tick"
    assert entry["schedule"].minute == {m for m in range(60)}
    assert "app.real_wallet.scheduler.real_wallet_exit_tick" in celery_app.tasks


def test_a_failure_cannot_stop_the_beat():
    tree = ast.parse(Path(rw_scheduler.__file__).read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef)
              and n.name == "_real_wallet_exit_tick")
    handlers = [h for n in ast.walk(fn) if isinstance(n, ast.Try) for h in n.handlers]
    assert handlers
    assert not any(isinstance(n, ast.Raise) for h in handlers for n in ast.walk(h))


def test_every_trading_strategy_produces_a_reachable_exit():
    """A time exit means no position can be held for ever. Held past it, every
    trading strategy must return a verdict rather than None — which is what makes
    capital recycle and compounding possible at all."""
    for s in spec.STRATEGIES:
        if not s.trades:
            continue
        hours = s.exits.time_exit_hours
        assert hours is not None, s.id
        verdict = evaluate_exit(s.exits, MarkState(
            exec_multiple=Decimal("1.0"), peak_exec_multiple=Decimal("1.0"),
            held_hours=hours + 1, liquidity_usd=Decimal("500000"),
            entry_liquidity_usd=Decimal("500000"), is_dead=False,
            sell_route_ok=None, break_even_armed=False, partial_done=False,
        ))
        assert verdict.action is not None, f"{s.id} can be held for ever"
