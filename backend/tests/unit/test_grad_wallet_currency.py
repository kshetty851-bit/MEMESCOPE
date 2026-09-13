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


def test_a_position_stops_growing_where_the_evidence_stops():
    """Returns were measured at $100 an order. Uncapped, a 1.6%-per-trade arm
    compounds $100 into nine figures in a month — arithmetic, not a forecast."""
    # Past `cap * slots` of equity, growth is LINEAR: equal stretches of the
    # same winning trade add equal dollars instead of multiplying.
    a, _ = api._wallet_walk([0.10] * 2000)
    b, _ = api._wallet_walk([0.10] * 3000)
    c, _ = api._wallet_walk([0.10] * 4000)
    assert c - b == pytest.approx(b - a)
    # Uncapped, the same run is e^40 dollars.
    assert c < 1e5
    # Below the cap it still compounds.
    small, _ = api._wallet_walk([0.01] * 10)
    assert small == pytest.approx(float(config.WALLET_DEMO_USD) * 1.001 ** 10)


def test_todays_wallets_are_unaffected_by_the_cap():
    """The cap must not silently restate a column the user is already reading:
    a $150 wallet holds $15 positions, nowhere near $100."""
    equity, _ = api._wallet_walk([0.05] * 9)
    assert equity < float(config.PAPER_NOTIONAL_USD) * config.WALLET_DEMO_SLOTS
    assert equity == pytest.approx(float(config.WALLET_DEMO_USD) * 1.005 ** 9)


def test_every_route_reaches_the_endpoint_it_names():
    """The lab went blank for an hour because a helper was inserted between
    `@router.get("/tournament")` and `async def tournament`, so the decorator
    bound the ROUTE to the helper. Its `returns` argument became a required
    query parameter and every call 422'd in 12ms without running.

    Nothing else caught it: the module imported, the page built, the tests
    passed, and `api.tournament(db)` called directly returned a full board —
    because the name was still bound, only the route was not. Only a request
    could see it.
    """
    for route in api.router.routes:
        name = getattr(route, "name", "")
        endpoint = getattr(route, "endpoint", None)
        assert endpoint is not None and not name.startswith("_"), (
            f"route {getattr(route, 'path', '?')} is bound to {name!r} — "
            "a decorator that slid onto the wrong function")
        # A GET endpoint on this router takes no required query parameters:
        # every one of them is a dependency or has a default.
        for param in inspect.signature(endpoint).parameters.values():
            assert param.default is not inspect.Parameter.empty, (
                f"{name}() has a required parameter {param.name!r}, which "
                "FastAPI serves as a mandatory query string — 422, always")


class TestStallAlarm:
    """The alarm must not be silenced by the failure it exists to report."""

    @staticmethod
    def _stalled(watch_set: int, tokens_last_hour: int, age_s: float,
                 threshold_s: float) -> bool:
        """The shipped rule, stated once so the test pins behaviour."""
        has_work = watch_set > 0 or tokens_last_hour > 0
        return has_work and age_s > threshold_s

    def test_a_dead_recorder_still_raises_the_alarm(self):
        """The real incident: the recorder stopped, the watch set emptied
        BECAUSE it stopped, and the page said "polling normally" for 31 min."""
        assert self._stalled(watch_set=0, tokens_last_hour=286,
                             age_s=1854, threshold_s=15)

    def test_a_quiet_lab_with_nothing_to_watch_does_not_cry_wolf(self):
        assert not self._stalled(watch_set=0, tokens_last_hour=0,
                                 age_s=99999, threshold_s=15)

    def test_a_healthy_recorder_is_not_stalled(self):
        assert not self._stalled(watch_set=478, tokens_last_hour=286,
                                 age_s=3, threshold_s=15)
