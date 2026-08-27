"""The Lab valued dying positions at par.

`618dCC…` fell from $727,062 of liquidity at entry to $1,722 and was still marked
at $3.07 against a $3.00 cost, because the CPMM model prices impact against the
REPORTED liquidity and a $3 position looks negligible even against $1,722. Jupiter
would have paid nothing. Karthik found it by hand on DexScreener before any of
this existed.

The correction is to a FACT the frozen exits consume, not to a rule — which is
why `SPEC_HASH` must not move.
"""

from __future__ import annotations

import ast
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.lab import sellability, service, spec

pytestmark = pytest.mark.unit


def test_the_frozen_spec_is_untouched():
    """A running tournament whose rules changed mid-flight would be worthless.
    Every strategy already exits on `dead_zero`; none were firing because nothing
    told them the position was dead."""
    assert spec.SPEC_VERSION == "1.1.0"
    assert spec.SPEC_HASH == (
        "a5f0c2ed0fd29a1ce9ac6bc98efdafd96dea974a5db6c523f98e23bdcc447a41"
    )


def test_a_failed_quote_never_condemns_a_token():
    """Rate limiting and a dead pool raise the same way. Treating a `429` as a
    death would have killed healthy positions — the first sweep returned
    `429 Too Many Requests` on essentially every call."""
    src = Path(sellability.__file__).read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "refresh")
    handler = next(h for n in ast.walk(fn) if isinstance(n, ast.Try)
                   for h in n.handlers)
    body = ast.unparse(handler)
    # It counts the failure and moves on; it must not write a row claiming the
    # sell side refused, because that is what `sell_route_ok` would read.
    assert "ResearchQuote" not in body
    assert "failed" in body


def test_the_sweep_paces_itself_against_a_measured_rate_limit():
    assert sellability.QUOTE_INTERVAL_SECONDS >= 1.0
    src = ast.unparse(ast.parse(Path(sellability.__file__).read_text()))
    assert "asyncio.sleep(QUOTE_INTERVAL_SECONDS)" in src


def test_an_unquoted_mint_leaves_the_existing_model_alone():
    """`None` means nobody asked recently enough to know. Inventing a death from
    an absence of information is the same error in the other direction."""
    tree = ast.parse(Path(service.__file__).read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_mark")
    src = ast.unparse(fn)
    assert "if realisable is not None:" in src


def test_the_quote_can_only_lower_a_mark_never_raise_it():
    """A quote taken at the largest holder's size understates a smaller one.
    Crediting a position with more than the model already allows would be
    inventing value rather than removing it."""
    tree = ast.parse(Path(service.__file__).read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_mark")
    src = ast.unparse(fn)
    # The comparison is against the model's own price, so the quote can only
    # pull a mark down. Written as a guarded condition since the restructure.
    assert "realisable < latest.price_usd" in src
    assert "realisable > latest.price_usd" not in src


def test_worthless_means_a_fraction_of_cost_not_exactly_zero():
    """A pool that would return four cents on a three-dollar position is not
    'cheap', it is untradeable. Exactly-zero would almost never fire."""
    assert Decimal("0") < sellability.DEAD_FRACTION <= Decimal("0.05")
    tree = ast.parse(Path(service.__file__).read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_mark")
    assert "sellability.DEAD_FRACTION" in ast.unparse(fn)


def test_it_is_scheduled_and_separate_from_the_judging_tick():
    """The sweep is slow by necessity and must not hold up the tick that judges
    checkpoints."""
    from app.lab import scheduler  # noqa: F401  (registers the task)
    from app.workers.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["lab-sellability-refresh"]
    assert entry["task"] == "app.lab.scheduler.lab_sellability_refresh"
    assert "app.lab.scheduler.lab_sellability_refresh" in celery_app.tasks
    # Its own key, so the paced sweep and the real-wallet tasks in the other
    # scheduler never wait on each other.
    from app.real_wallet import scheduler as rw

    assert scheduler.SELLABILITY_LOCK_KEY not in {
        rw.DRY_RUN_LOCK_KEY, rw.DRIVER_LOCK_KEY, rw.EXECUTOR_LOCK_KEY,
        rw.EXIT_LOCK_KEY,
    }


def test_usdc_and_the_token_do_not_share_decimals():
    """The raw ratio is not a price. USDC is 6dp and the token is its own, so
    both sides have to reach whole units before they can be divided."""
    src = ast.unparse(ast.parse(Path(sellability.__file__).read_text()))
    assert "USDC_DECIMALS" in src
    assert "token_decimals" in src


async def test_the_scheduled_task_actually_runs(monkeypatch):
    """Registration is not execution.

    The first version of this suite asserted the task existed in the beat
    schedule and stopped there. It shipped with `utcnow` unimported and every
    scheduled run returned `{"failed": True}` — caught only by reading production
    logs, because the task swallows its own exception by design so a Lab failure
    cannot stop the beat. That containment is right, and it means a test has to
    invoke the body or nothing will.
    """
    from app.lab import scheduler

    called: dict = {}

    async def _fake_refresh(session, *, now, **kw):
        called["now"] = now
        return {"mints": 0, "quoted": 0, "failed": 0, "skipped_fresh": 0}

    class _Session:
        async def scalar(self, *a, **k): return True
        async def commit(self): ...
        async def rollback(self): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(scheduler.sellability, "refresh", _fake_refresh)
    monkeypatch.setattr(scheduler, "SessionFactory", lambda: _Session())
    monkeypatch.setattr(scheduler.settings, "FEATURE_LAB_ENABLED", True)

    result = await scheduler._lab_sellability_refresh()

    assert result.get("failed") is not True, result
    assert called.get("now") is not None, "the task never reached refresh()"


def test_a_fresh_quote_outranks_a_stale_snapshot():
    """The staleness guard was skipping 162 of 224 open positions every tick.

    The skip is self-selecting in the worst way: a dying token stops being
    enriched, so its snapshot goes stale, so it is never marked and never
    evaluated for an exit again. The Lab froze its worst positions at their last
    healthy price and held them for ever.

    Staleness is a statement about the SNAPSHOT, not about the market. A quote
    taken minutes ago is current evidence whatever the snapshot's age, so it is
    consulted BEFORE the guard rather than after it.
    """
    tree = ast.parse(Path(service.__file__).read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_mark")
    src = ast.unparse(fn)
    quote_at = src.index("sellability.realisable_price")
    give_up_at = src.index("if stale:\n        return None")
    assert quote_at < give_up_at, "the guard still runs before the quote"


def test_a_stale_position_with_no_quote_is_still_refused():
    """Consulting the quote first must not turn "we do not know" into a mark.
    Without a quote, an unusable snapshot is still unusable."""
    tree = ast.parse(Path(service.__file__).read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_mark")
    assert "if stale:\n        return None" in ast.unparse(fn)


def test_quotes_are_renewed_before_they_expire():
    """The sweep skipped anything still usable, so a quote was only renewed
    AFTER it had already expired — every mint spent the gap between expiry and
    the next pass uncovered.

    Measured live: one mint quoted at 02:42, 02:57, 03:12 — a fifteen-minute
    rhythm against a twelve-minute window, unusable for three minutes of every
    cycle. Twenty-six of twenty-eight mints covered at any instant, and the two
    that were not held enough value to drag mark quality to 60%.
    """
    assert sellability.REFRESH_AFTER < sellability.MAX_QUOTE_AGE
    # The headroom must exceed one sweep cadence (3 min) or the gap reopens.
    headroom = sellability.MAX_QUOTE_AGE - sellability.REFRESH_AFTER
    assert headroom >= timedelta(minutes=3)

    # And the sweep must actually select on the shorter window.
    src = ast.unparse(ast.parse(Path(sellability.__file__).read_text()))
    assert "fresh_cutoff = now - REFRESH_AFTER" in src


def test_the_read_side_still_accepts_the_full_window():
    """Renewing early must not shorten how long a quote may be USED. A mark is
    still valid to twelve minutes; only the refresh moved."""
    tree = ast.parse(Path(sellability.__file__).read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "realisable_price")
    assert "MAX_QUOTE_AGE" in ast.unparse(fn)


def test_the_sweep_only_quotes_the_current_tournament():
    """Unscoped, it spent its per-run budget on a dormant record's open
    positions — V6 1.0.0 carried 158 — while the live book competed for what was
    left.

    It is not biting today only because that record has closed out, which is the
    worst kind of not-biting: fixed by luck, and back the next time a version is
    bumped with positions still open.
    """
    tree = ast.parse(Path(sellability.__file__).read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "refresh")
    src = ast.unparse(fn)
    assert "LabTournament.spec_version == spec.SPEC_VERSION" in src
