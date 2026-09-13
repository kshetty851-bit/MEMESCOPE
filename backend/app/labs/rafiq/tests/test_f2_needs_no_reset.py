"""Adding F2 to a lab that is already running must not disturb the five books.

Karthik asked whether the lab wallet has to be reset to run F2. It does not,
and this is the test that says so rather than me saying so: prod carries 823
closed trades across A2-E2 and those rows are the entire evidence base for
`FINDINGS.md`. A reset would delete the only data that says exits are not
where the loss is.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.labs.rafiq import config, registry
from app.labs.rafiq.models import RafiqLabPosition, RafiqLabStrategy
from app.labs.rafiq.service import RafiqLabService
from app.labs.rafiq.tests.test_full_cycle import seed_candidate

pytestmark = pytest.mark.integration

#: The five books as they stand on prod, so this test fails if a later change
#: would have required a reset after all.
EXISTING = ("A2", "B2", "C2", "D2", "E2")


async def _digest(session) -> str:
    """Every stored field of the five pre-existing books, hashed."""
    rows = list((await session.execute(
        select(RafiqLabStrategy)
        .where(RafiqLabStrategy.code.in_(EXISTING))
        .order_by(RafiqLabStrategy.code)
    )).scalars())
    blob = "|".join(
        f"{r.code}:{r.lane}:{r.starting_equity}:{r.profile_digest}:"
        f"{r.activated_at.isoformat()}" for r in rows)
    return f"{len(rows)}:{hashlib.sha256(blob.encode()).hexdigest()}"


async def test_activating_f2_leaves_the_five_books_byte_identical(
    lab_session, monkeypatch
) -> None:
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    service = RafiqLabService(lab_session)

    # The lab as it already runs: five books, activated yesterday. Simulated by
    # inserting them WITHOUT F2, which is exactly prod's ledger today.
    yesterday = datetime.now(UTC) - timedelta(days=1)
    for code in EXISTING:
        spec = registry.BY_CODE[code]
        lab_session.add(RafiqLabStrategy(
            code=code, lane=spec.profile.lane,
            starting_equity=config.STARTING_EQUITY,
            profile_digest=spec.digest, activated_at=yesterday))
    await lab_session.flush()
    before = await _digest(lab_session)

    rows = await service.activate(now=datetime.now(UTC))

    assert await _digest(lab_session) == before, \
        "activating F2 modified an existing book's record"
    assert {r.code for r in rows} == {*EXISTING, "F2"}

    f2 = next(r for r in rows if r.code == "F2")
    assert f2.starting_equity == Decimal("1000.00"), "F2 did not start clean"
    assert f2.activated_at > yesterday, \
        "F2 inherited the old activation boundary and could trade stale admissions"


async def test_a_second_activation_does_not_refund_f2(
    lab_session, monkeypatch
) -> None:
    """The idempotence that makes a restart safe. If this broke, every worker
    restart would hand F2 a fresh $1,000 and the book would never fall to its
    floor."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    service = RafiqLabService(lab_session)
    first = await service.activate(now=datetime.now(UTC) - timedelta(hours=2))
    opened_at = next(r for r in first if r.code == "F2").activated_at

    again = await service.activate(now=datetime.now(UTC))
    f2 = next(r for r in again if r.code == "F2")

    assert len(again) == len(first)
    assert f2.activated_at == opened_at, "activation boundary moved"


async def test_a_retired_book_keeps_settling_but_opens_nothing(
    lab_session, monkeypatch
) -> None:
    """`enters=False` stops entries without abandoning open positions, and
    without force-closing them — selling into a drained pool is what produces
    the -100% rows.

    No book carries `enters=False` today (all six trade), so this patches one
    rather than relying on a book's current setting. That is the point: the
    mechanism has to keep working for whenever it is next used, and a test
    that only passed while A2 happened to be retired stopped testing it the
    moment A2 was re-armed.
    """
    import dataclasses

    from app.labs.rafiq import registry

    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    now = datetime.now(UTC)
    service = RafiqLabService(lab_session)
    await service.activate(now=now - timedelta(hours=2))

    a2 = (await lab_session.execute(
        select(RafiqLabStrategy).where(RafiqLabStrategy.code == "A2")
    )).scalars().one()
    retired = dataclasses.replace(registry.BY_CODE["A2"], enters=False)
    monkeypatch.setitem(registry.BY_CODE, "A2", retired)
    monkeypatch.setattr(
        registry, "STRATEGIES",
        tuple(retired if s.code == "A2" else s for s in registry.STRATEGIES))

    # A real market behind the legacy position, or `_settle` has nothing to
    # mark it against and the test would pass for the wrong reason.
    legacy_mint = await seed_candidate(lab_session, now, tag="legacyopen")
    lab_session.add(RafiqLabPosition(
        strategy_id=a2.id, mint_address=legacy_mint, leg=1,
        opened_at=now - timedelta(minutes=30),
        # Priced at the seeded market, so the mark neither stops it out nor
        # takes profit and the only thing under test is whether it is still
        # being evaluated at all.
        entry_price=Decimal("0.001"), entry_observed_price=Decimal("0.001"),
        quantity=Decimal(50_000), cost_basis=Decimal(50),
        stop_price=Decimal("0.00088"), target_price=Decimal("0.0013"),
        stop_pct=Decimal(12), max_hold_seconds=14400, status="open",
        peak_price=Decimal("0.001"), last_mark_price=Decimal("0.001"),
        last_evaluated_at=now - timedelta(minutes=1)))
    await seed_candidate(lab_session, now, tag="noreset")
    await lab_session.flush()

    await service.tick(now=now)

    a2_positions = list((await lab_session.execute(
        select(RafiqLabPosition).where(RafiqLabPosition.strategy_id == a2.id)
    )).scalars())
    assert len(a2_positions) == 1, "a retired book opened a new position"
    legacy = a2_positions[0]
    assert legacy.status == "open", "a retired book force-closed its position"
    # It is still being marked, so its exits can still fire on their own terms.
    assert legacy.last_evaluated_at == now, "a retired book stopped settling"
