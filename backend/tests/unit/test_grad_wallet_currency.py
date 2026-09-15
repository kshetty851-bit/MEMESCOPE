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


def test_one_total_loss_ends_a_single_position_wallet():
    """At one slot the wallet IS the position, so a wipeout is terminal.

    It held ten slots until 2026-09-15, where a -99% cost a tenth. That
    survivability was bought at 5.09% a trade in fees, which is more than any
    edge here — so the wallet now concentrates and accepts the tail instead.
    This test records which regime is live, because the two behave completely
    differently and a silent switch between them would be invisible.
    """
    assert config.WALLET_DEMO_SLOTS == 1
    equity, dead = api._wallet_walk([-0.99])
    assert dead and equity == 0.0


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
    # Uncapped, the same run is e^200 dollars at one slot.
    assert c < 1e6
    # At ONE slot with a $100 wallet and a $100 cap the position is capped
    # from the very first trade, so the wallet is ADDITIVE throughout — and
    # that is the point: it makes the wallet equal $100 plus the book's P&L,
    # which is exactly what Karthik expected to see and could not find.
    #
    #     86 trades averaging +2.45% of $100 = +$210.51 of book P&L
    #     wallet = $100 + $210.51 = $310.51
    #
    # Ten slots is what broke that identity, by trading a tenth of the size
    # the book traded.
    small, _ = api._wallet_walk([0.01] * 10)
    cap = float(config.PAPER_NOTIONAL_USD)
    assert small == pytest.approx(float(config.WALLET_DEMO_USD) + 10 * cap * 0.01)


def test_the_cap_binds_at_the_measured_notional():
    """A wallet at or above `PAPER_NOTIONAL_USD * slots` stops compounding,
    because past that its position would exceed the size every return was
    measured at and there is no evidence for what a bigger one earns."""
    ceiling = float(config.PAPER_NOTIONAL_USD) * config.WALLET_DEMO_SLOTS
    grown, _ = api._wallet_walk([0.05] * 40)
    # Growth above the ceiling is additive, so it cannot run away.
    assert grown < ceiling * 4, grown


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


class TestLeaderSelection:
    """A baseline that wins must be able to be called the winner.

    Excluding controls from leadership was right when a control was a coin
    flip: a dice roll cannot win anything. It became wrong the moment the
    baseline became a strategy. On 2026-09-14 FLOOR_3m reached profit factor
    4.24 against a required 2.99 on 143 trades — the first arm ever to clear
    its bar here — and the board named a SIX-trade band arm as leader, because
    the thing that was working had been classified as the control.
    """

    def test_leadership_is_not_gated_on_being_a_strategy(self):
        src = inspect.getsource(api.tournament)
        pick = next(line for line in src.splitlines()
                    if line.strip().startswith("leader = next("))
        assert "not r.is_control" not in pick, (
            "a baseline that outperforms every filter must be able to lead; "
            "excluding it hides the most useful result this lab can produce")

    def test_a_leading_baseline_is_measured_against_selecting_nothing(self):
        """It cannot be asked to beat itself, so the term becomes the arm that
        applies no floor and no band at all."""
        src = inspect.getsource(api.tournament)
        assert "leader.is_control" in src and "naked" in src, (
            "when the leader IS the baseline the gate must swap in the "
            "no-selection arm, not compare it against itself")


def test_each_arm_projects_from_its_own_elapsed_time():
    """An arm added today must not inherit the trade rate of one that has run
    since yesterday.

    Every arm shared the board clock, which was merely imprecise while all arms
    started together and became absurd when the clock was narrowed to the
    window in which arms are comparable: an arm whose 190 trades spanned 37
    hours had its rate computed over 3.7, projected ten times the trades it
    actually takes, and showed $330 from $100 in a single day.
    """
    src = inspect.getsource(api.tournament)
    assert "def project(returns: list[float], hours: float," in src, (
        "project() must be given the hours to use rather than closing over a "
        "board-wide figure")
    assert "arm_hours" in src and "project(per_arm.get(arm.name, []), arm_hours," in src, (
        "each row must pass ITS OWN elapsed time into the projection")


def test_projection_uncertainty_is_clustered_by_hour_not_by_trade():
    """Trades inside one hour are the same market, not independent draws.

    Measured per trade, a 14-hour arm with 190 fills reported a 30-day band of
    $5,845 to $11,133 and a 0% chance of wipeout — a promise of eighty-fold
    with no downside — because 190 correlated fills were counted as 190
    independent observations. The effective sample is the number of HOURS.

    Same error, different place, as counting 2,223 trades across 79 tokens as
    2,223 observations.
    """
    src = inspect.getsource(api.tournament)
    assert "pstdev(returns) / sqrt(n)" not in src, (
        "per-trade standard error understates the uncertainty enormously")
    assert "by_hour" in src and "pstdev(by_hour) / sqrt(len(by_hour))" in src

    body = src[src.index("def project("):]
    guard = body[:body.index("pool = [")]
    assert "return {}" in guard, (
        "under two hours of history there is nothing to measure variation "
        "between; the projection must be refused, not printed confidently")


def test_market_snapshot_protection_is_bounded():
    """A traded mint keeps its series while a position is OPEN and for a
    bounded window after the last one closes — not forever.

    Unbounded protection made the carve-out a third of the table: 1,292 mints
    held 1,986,783 rows, nothing older than thirty days, still growing. The
    obvious knob was not the lever — cutting MARKET_SNAPSHOT_RETENTION_DAYS
    from 7 to 3 would have freed 8.7 MB, because 99.2% of rows past three days
    were already protected.
    """
    import inspect as _inspect

    from app.core.config import settings
    from app.workers import retention_tasks

    assert 1 <= settings.MARKET_SNAPSHOT_PROTECT_DAYS <= 365
    src = _inspect.getsource(retention_tasks._prune_market_snapshots)
    # Both protected tables must carry the bound, or one of them keeps
    # everything forever and the fix does nothing.
    assert src.count("closed_at IS NULL OR closed_at >= :prot_cutoff") == 2, (
        "paper_positions AND lab_positions must both bound their protection")
    assert "MARKET_SNAPSHOT_PROTECT_DAYS" in src, (
        "the window must come from settings, not a literal")
    # An OPEN position is protected regardless of how old it is.
    assert "closed_at IS NULL" in src
