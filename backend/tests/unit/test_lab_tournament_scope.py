"""Two tournaments in one table, and every query that forgot to say which.

V6.1 opened at $100 beside V6's $1,000 record and the board rendered V6's rows
underneath a 1.1.0 header — same page, two book sizes, no error anywhere. The
queries were never wrong before, because "the only tournament" and "the current
tournament" are the same set until they are not.

These tests read the source rather than exercising the database: what must hold
is that no Lab query reaches a strategy, a position or a decision without naming
the record it belongs to, and that is a property of the query, not of a fixture
that happens to contain one tournament.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from app.lab import api, leaderboard, spec

pytestmark = pytest.mark.unit


def test_the_leaderboard_cannot_be_asked_for_every_tournament_at_once():
    """`tournament_id` is required, not defaulted. A default is what let this
    happen silently the first time."""
    for fn in (leaderboard.strategy_rows, leaderboard.mark_open_at_boundary):
        sig = inspect.signature(fn)
        p = sig.parameters["tournament_id"]
        assert p.kind is inspect.Parameter.KEYWORD_ONLY, fn.__name__
        assert p.default is inspect.Parameter.empty, fn.__name__


def _selects_without_scope(module) -> list[str]:
    """Every ORM select over a per-tournament table that never mentions one."""
    PER_TOURNAMENT = {"LabStrategy", "LabPosition", "LabDecision"}
    tree = ast.parse(Path(module.__file__).read_text())
    bad = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for call in ast.walk(fn):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                    and call.func.id == "select"):
                continue
            names = {n.id for n in ast.walk(call) if isinstance(n, ast.Name)} | {
                n.attr for n in ast.walk(call) if isinstance(n, ast.Attribute)}
            if not (names & PER_TOURNAMENT):
                continue
            # The whole statement it belongs to must scope it: either directly,
            # or through a strategy row that was itself scoped.
            stmt = ast.unparse(fn)
            if "tournament_id" in stmt or "strategy_row_id" in stmt:
                continue
            bad.append(f"{fn.name}: {ast.unparse(call)[:70]}")
    return bad


def test_no_endpoint_reads_across_tournaments():
    assert _selects_without_scope(api) == []


def test_the_leaderboard_module_scopes_every_read():
    assert _selects_without_scope(leaderboard) == []


def test_the_disclosure_states_the_book_that_is_actually_running():
    """It said "$1,000 portfolios" for as long as that was true and would have
    gone on saying it. Interpolated now, so it cannot drift again."""
    assert f"${spec.STARTING_EQUITY:,.0f}" in api.DISCLOSURE
    assert "$1,000" not in api.DISCLOSURE or spec.STARTING_EQUITY == 1000
