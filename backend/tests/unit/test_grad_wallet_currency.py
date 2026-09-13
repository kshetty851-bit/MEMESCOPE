"""One wallet model, or the board reports three currencies at once.

The leaderboard once showed an arm as a $152.77 wallet, a $515.55 "bar to
clear" and a +$23,876.96 thirty-day projection — on the same row. Each figure
was individually correct and they were denominated in different accounts: the
column compounded $100 over ten slots, the other two added fixed $100 positions
to a $1,000 book. Nothing errored, and the three numbers read as a strategy
worth deploying.

So: the walk is the only account model, and the projection has to call it.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from app.labs.graduation import api, config

pytestmark = pytest.mark.unit


def test_a_flat_run_leaves_the_wallet_exactly_where_it_started():
    equity, dead = api._wallet_walk([0.0] * 500)
    assert equity == pytest.approx(float(config.WALLET_DEMO_USD))
    assert not dead


def test_one_total_loss_costs_a_tenth_not_the_account():
    """Ten slots is the whole reason the $100 wallet is survivable."""
    equity, dead = api._wallet_walk([-0.99])
    assert not dead
    assert equity == pytest.approx(float(config.WALLET_DEMO_USD) * 0.901)


def test_a_wallet_below_the_payable_size_is_dead_and_stays_dead():
    """Without the floor, $2 'recovers' on trades it could never have placed."""
    equity, dead = api._wallet_walk([-0.99] * 400 + [50.0])
    assert dead
    assert equity == 0.0


def test_the_projection_walks_the_same_wallet():
    """An additive $1,000 book inlined here is exactly the bug above."""
    src = inspect.getsource(api.tournament)
    project = next(n for n in ast.walk(ast.parse(src.lstrip()))
                   if isinstance(n, ast.FunctionDef) and n.name == "project")
    calls = {n.func.id for n in ast.walk(project)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_wallet_walk" in calls
    reads = {n.attr for n in ast.walk(project) if isinstance(n, ast.Attribute)}
    assert not {"PAPER_CAPITAL_USD", "PAPER_NOTIONAL_USD"} & reads


def test_the_board_compares_the_leader_to_controls_in_wallet_dollars():
    """The dot and the stat disagreed: one read wallets, the other P&L."""
    src = ast.parse(inspect.getsource(api.tournament).lstrip())
    band = next(n for n in ast.walk(src)
                if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "band" for t in n.targets))
    assert "wallet_100_usd" in {n.attr for n in ast.walk(band)
                                if isinstance(n, ast.Attribute)}
