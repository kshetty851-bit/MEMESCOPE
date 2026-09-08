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
import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.lab import sellability, service, spec

pytestmark = pytest.mark.unit


def test_the_frozen_spec_is_untouched():
    """A running tournament whose rules changed mid-flight would be worthless.
    Every strategy already exits on `dead_zero`; none were firing because nothing
    told them the position was dead."""
    # Updated deliberately at the V6.1 -> V7 cutover on 2026-09-04, which is the
    # only circumstance in which these two lines may change. If this test fails
    # and nobody bumped the version on purpose, a live tournament's rules moved
    # underneath it and the results are void.
    assert spec.SPEC_VERSION == "1.2.0"
    assert spec.SPEC_HASH == (
        "ae1627b4ec0d3f9f4202e874333582f0deba1e306068a6401e7c9bf6a396f70c"
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
        called["versions"] = kw.get("spec_versions")
        return {"mints": 0, "quoted": 0, "failed": 0, "skipped_fresh": 0}

    class _Result:
        def scalars(self): return self
        def __iter__(self): return iter(())

    class _Session:
        async def scalar(self, *a, **k): return True
        # `_swept_versions` asks the database which tournaments hold open
        # positions; an empty answer leaves just the live list, which is what
        # this test is about.
        async def execute(self, *a, **k): return _Result()
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


def test_the_sweep_only_quotes_the_tournaments_that_are_running():
    """Unscoped, it spent its per-run budget on a dormant record's open
    positions — V6 1.0.0 carried 158 — while the live book competed for what was
    left.

    The scope became a SET, not a single version, when a second tournament
    started running (the Compound Lab). The invariant is unchanged and is the
    one that matters: quote what is live, never everything that exists. The
    default is still exactly one version, so a caller that forgets the argument
    narrows the sweep rather than widening it to every dormant record.
    """
    import inspect

    tree = ast.parse(Path(sellability.__file__).read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "refresh")
    src = ast.unparse(fn)
    assert "LabTournament.spec_version.in_(spec_versions)" in src
    assert (inspect.signature(sellability.refresh)
            .parameters["spec_versions"].default == (spec.SPEC_VERSION,))


def test_strategy_ids_are_globally_unique():
    """`LabService._my_strategy_rows` scopes on `strategy_id`, so this must hold.

    It scopes that way so a registry follows its OWN book across version bumps
    — a superseded tournament keeps settling instead of stranding its open
    positions. The safety of that depends entirely on ids not colliding: a
    shared id would let one registry settle another's position under its own
    exit rules, which is worse than the KeyError the old `spec_hash` scope
    prevented, because it is silent.

    Ids are prefix-namespaced (V7-, CMP-, MOM-, DPT-, CPY-, SOC-) so this holds
    by construction. This test is what keeps it true when someone adds a lab.
    """
    import importlib
    import pkgutil

    import app

    owners: dict[str, list[str]] = {}
    for mod in pkgutil.iter_modules(app.__path__):
        if not mod.ispkg:
            continue
        try:
            m = importlib.import_module(f"app.{mod.name}.spec")
        except ModuleNotFoundError:
            continue
        if not hasattr(m, "BY_ID") or not hasattr(m, "SPEC_VERSION"):
            continue
        for sid in m.BY_ID:
            owners.setdefault(sid, []).append(mod.name)

    assert owners, "no registries discovered — the walk is broken, not the invariant"
    collisions = {k: v for k, v in owners.items() if len(v) > 1}
    assert not collisions, f"strategy ids shared across registries: {collisions}"


def test_the_sweep_covers_every_registry_that_holds_positions():
    """The list of swept tournaments must not be able to fall behind the list
    of tournaments that exist.

    It fell behind twice: the Compound Lab, then Momentum V2 and Depth. The
    failure is silent — an unquoted book is marked from the CPMM model over
    reported liquidity, the condition that froze 72% of the Lab's book on
    2026-08-26 — and for the ratchet labs it is worse than a wrong number,
    because the +10% target is TESTED against those marks.

    DISCOVERED, not enumerated. The first version of this test listed the five
    registries by hand and so had the same defect as the code it guards: adding
    the Social Lab made the TEST wrong rather than catching anything. Anything
    under `app/` that declares a `SPEC_VERSION` and a `STRATEGIES` is a
    tournament, and a tournament that holds positions must be swept.
    """
    import importlib
    import pkgutil

    import app
    from app.lab import scheduler

    found = {}
    for mod in pkgutil.iter_modules(app.__path__):
        if not mod.ispkg:
            continue
        try:
            registry = importlib.import_module(f"app.{mod.name}.spec")
        except ModuleNotFoundError:
            continue
        if hasattr(registry, "SPEC_VERSION") and hasattr(registry, "STRATEGIES"):
            found[registry.SPEC_VERSION] = f"app.{mod.name}.spec"

    assert len(found) >= 6, "registry discovery found less than we know exists"
    missing = {v: m for v, m in found.items()
               if v not in set(scheduler.LIVE_SPEC_VERSIONS)}
    assert not missing, (
        f"these tournaments hold positions nothing re-quotes: {missing}"
    )
    assert len(set(scheduler.LIVE_SPEC_VERSIONS)) == len(
        scheduler.LIVE_SPEC_VERSIONS), "no duplicates"


def test_the_beat_sweeps_every_live_tournament():
    """The Compound Lab's book was invisible to this sweep for as long as it was
    scoped to one version, so it was marked from the CPMM model over reported
    liquidity — the condition that froze 72% of the Lab's book on 2026-08-26 —
    with nothing saying so. One sweep covers both, rather than a second beat
    entry halving the Jupiter budget."""
    from app.compound import spec as cspec
    from app.lab import scheduler

    # Asserted on the versions the task ACTUALLY passes to `refresh`, not on
    # its source. The source-grep version of this test broke the moment the
    # list moved behind a helper — while the behaviour it cared about was
    # unchanged — which is the whole argument against grepping source.
    captured: dict = {}

    async def _fake_refresh(session, *, now, spec_versions, **kw):
        captured["versions"] = spec_versions
        return {"mints": 0, "quoted": 0, "failed": 0, "skipped_fresh": 0}

    async def _fake_swept(session):
        return tuple(scheduler.LIVE_SPEC_VERSIONS)

    class _Session:
        async def scalar(self, *a, **k): return True
        async def commit(self): ...
        async def rollback(self): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    import asyncio

    from unittest.mock import patch

    with patch.object(scheduler.sellability, "refresh", _fake_refresh), \
            patch.object(scheduler, "_swept_versions", _fake_swept), \
            patch.object(scheduler, "SessionFactory", lambda: _Session()), \
            patch.object(scheduler.settings, "FEATURE_LAB_ENABLED", True):
        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            scheduler._lab_sellability_refresh())

    assert cspec.SPEC_VERSION in captured["versions"]
    assert spec.SPEC_VERSION in captured["versions"]
    assert cspec.SPEC_VERSION != spec.SPEC_VERSION


# --------------------------------------------------------------------------
# a superseded book still gets quoted
# --------------------------------------------------------------------------


async def test_the_swept_list_always_contains_every_live_tournament(db_session):
    """The two previous versions of this list were hand-maintained tuples and
    BOTH were missed on the deploy that needed them — the Compound Lab, then
    Momentum V2 and Depth. Derived from a query it cannot fall behind, but it
    must never derive its way into DROPPING a live one."""
    from app.lab.scheduler import LIVE_SPEC_VERSIONS, _swept_versions

    assert set(LIVE_SPEC_VERSIONS) <= set(await _swept_versions(db_session))


async def test_a_superseded_tournament_with_an_open_position_is_swept(db_session):
    """The gap the pumpfun 1.2.0 bump would have opened.

    A version bump drops the old tournament out of `LIVE_SPEC_VERSIONS` — its
    registry now reports the new version — while its book can still be open.
    Those positions then get no fresh quote and are marked from the CPMM model
    over reported liquidity, the condition that froze 72% of the Lab's book on
    2026-08-26. It is not a stranding, because `resolve_membership` keeps the
    mint in the priority lane regardless of tournament, but a modelled mark is
    a worse number and the ratchet targets are TESTED against these marks.
    """
    import uuid as _uuid
    from datetime import timedelta
    from decimal import Decimal as D

    from app.lab.scheduler import LIVE_SPEC_VERSIONS, _swept_versions
    from app.models.lab import (LabDecision, LabPosition, LabStrategy,
                                LabTournament)

    now = datetime.now(UTC)
    retired = "retired-9.9.9"
    assert retired not in LIVE_SPEC_VERSIONS

    t = LabTournament(spec_version=retired, spec_hash="dead" * 16,
                      valid_from=now - timedelta(days=3), snapshot_at=now,
                      status="active", protocol_note="superseded")
    db_session.add(t)
    await db_session.flush()
    row = LabStrategy(tournament_id=t.id, strategy_id="OLD-01", name="OLD",
                      version=retired, spec_hash="dead" * 16,
                      checkpoint_minutes=30, size_usd=D("10"),
                      max_concurrent=5, max_exposure_usd=D("100"), rules={},
                      starting_equity=D("100"), cash=D("50"),
                      peak_equity=D("100"), status="active")
    db_session.add(row)
    await db_session.flush()
    d = LabDecision(strategy_row_id=row.id, strategy_id="OLD-01",
                    mint_address="Old" + "1" * 41, checkpoint_at=now,
                    checkpoint_minutes=30, decided_at=now, eligible=True)
    db_session.add(d)
    await db_session.flush()

    # No open position yet -> the retired version is NOT swept.
    assert retired not in await _swept_versions(db_session)

    db_session.add(LabPosition(
        decision_id=d.id, strategy_row_id=row.id, strategy_id="OLD-01",
        mint_address=d.mint_address, opened_at=now, entry_price=D("0.001"),
        entry_liquidity_usd=D("50000"), size_usd=D("10"), quantity=D("1000"),
        quantity_remaining=D("1000"), banked_proceeds_usd=D("0"),
        status="open", entry_source="test", peak_exec_multiple=D("1"),
        last_exec_multiple=D("1"), last_open_value_usd=D("10")))
    await db_session.flush()

    swept = await _swept_versions(db_session)
    assert retired in swept, "a superseded book holding a position must be quoted"
    # And the live ones are never dropped in the process.
    assert set(LIVE_SPEC_VERSIONS) <= set(swept)
