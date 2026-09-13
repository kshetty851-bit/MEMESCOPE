"""The served contract for `/labs/forex-lab`.

Asserted over `app.openapi()["paths"]`, not over `app.routes`. This FastAPI
keeps an included router as ONE lazy object, so walking `app.routes` finds no
lab path at all — an assertion over that list passes just as happily on a
router that was never registered. The NSE tracker's run log records the same
trap; this is the same lesson, held in a test.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from app.api.v1.router import api_router

PREFIX = "/api/v1/labs/forex-lab"


@pytest.fixture(scope="module")
def served() -> dict:
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    return app.openapi()["paths"]


def test_the_three_read_routes_are_actually_served(served):
    assert f"{PREFIX}/latest" in served
    assert f"{PREFIX}/runs" in served
    assert f"{PREFIX}/data" in served


def test_every_served_route_is_read_only(served):
    """Not "the module has no POST decorator" — that is a fact about a file.
    This is a fact about what the API will accept."""
    for path, ops in served.items():
        if not path.startswith(PREFIX):
            continue
        assert set(ops) == {"get"}, f"{path} serves {sorted(ops)}"


def test_the_lab_mounts_under_labs_beside_its_siblings(served):
    """A lab that mounts at the root, or under a name a reader would not look
    for, is a lab nobody finds."""
    ours = [p for p in served if "forex-lab" in p]
    assert ours, "nothing mounted"
    assert all(p.startswith("/api/v1/labs/") for p in ours), ours


def test_registering_this_lab_did_not_unmount_another(served):
    """The include was moved once, from beside `health` to beside the other
    labs. A bad edit there silently drops every route below it."""
    for sibling in ("/api/v1/labs/v6-fast-accum/latest", "/api/v1/labs/graduation/status"):
        assert sibling in served or any(
            p.startswith(sibling.rsplit("/", 1)[0]) for p in served
        ), sibling


# --- the deployed case ---------------------------------------------------------


def test_the_data_route_declares_which_source_answered(served):
    """On a deployed instance `fx_candles` is empty — the 2.4M candles are a
    working set for an offline replay, not something production needs a copy
    of. Reporting zero there would tell a reader the backtest ran on nothing,
    so the route falls back to the published sweep and says which one answered.
    """
    import inspect

    from app.labs.forex_lab import api

    src = inspect.getsource(api.data)
    assert '"published_run"' in src
    assert '"source"' in src
    assert f"{PREFIX}/data" in served
