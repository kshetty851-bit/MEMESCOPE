"""`GET /fivemin/trades` — the Five-Minute Lab's own record.

The whole risk of reusing `/lab/trades` is scope. Positions carry a bare
`strategy_id` and every lab writes into the same two tables, so a trades view
that forgets to scope by tournament reports the V6 book and this one under a
single heading, at two different stakes. Both directions are tested here.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal as D

from sqlalchemy import select

import pytest
from app.compound.service import CompoundService
from app.fivemin import spec as fmspec
from app.fivemin.api import trades as fivemin_trades
from app.lab.api import trades as lab_trades
from app.lab.service import LabService
from app.models.lab import LabDecision, LabPosition, LabStrategy, LabTournament
from tests.integration.test_lab_accounting import NOW, VALID_FROM, _radar_token

pytestmark = pytest.mark.integration


async def _seed_both(db_session):
    """One five-minute wallet and one V6 tournament, each holding something.

    FM-01's position is written directly rather than driven through the FLOW
    entry: this file is about whether the VIEW scopes to its own tournament,
    and routing that through the entry rule would make these tests fail for
    reasons that have nothing to do with scoping.
    """
    # V6, holding real positions from its own entry path.
    lab = LabService(db_session)
    await lab.activate(valid_from=VALID_FROM)
    await _radar_token(db_session, mint="V" + "6" * 20,
                       detected=NOW - timedelta(hours=2), liq=D("600000"),
                       price=D("0.001"), pool="PV601")
    await lab.evaluate_due(now=NOW)

    # The five-minute wallet, and one position hung off its strategy row.
    await CompoundService(db_session, registry=fmspec).tick(now=NOW)
    row = (await db_session.execute(
        select(LabStrategy)
        .join(LabTournament, LabTournament.id == LabStrategy.tournament_id)
        .where(LabTournament.spec_version == fmspec.SPEC_VERSION)
    )).scalars().first()
    assert row is not None, "the five-minute tick must create its wallet"

    tok = await _radar_token(db_session, mint="F" + "m" * 20,
                             detected=NOW - timedelta(hours=2), liq=D("600000"),
                             price=D("0.001"), pool="PFM01")
    decision = LabDecision(
        strategy_row_id=row.id, strategy_id="FM-01", mint_address=tok.mint_address,
        checkpoint_at=NOW, checkpoint_minutes=0, decided_at=NOW, eligible=True,
    )
    db_session.add(decision)
    await db_session.flush()
    db_session.add(LabPosition(
        decision_id=decision.id, strategy_row_id=row.id, strategy_id="FM-01",
        mint_address=tok.mint_address, token_id=tok.id, opened_at=NOW,
        entry_price=D("0.001"), size_usd=D("5"), quantity=D("5000"),
        quantity_remaining=D("5000"), banked_proceeds_usd=D("0"),
        entry_source="flow", status="open", peak_exec_multiple=D("1"),
        last_exec_multiple=D("0.97"), last_open_value_usd=D("4.85"),
    ))
    await db_session.flush()


async def test_it_returns_only_this_lab_s_trades(db_session):
    await _seed_both(db_session)

    everything = len(list((await db_session.execute(select(LabPosition))).scalars()))
    got = await fivemin_trades(db_session, status=None, limit=500)

    assert got["trades"], "the five-minute wallet must be holding something"
    assert {t["strategy_id"] for t in got["trades"]} == {"FM-01"}, (
        "a V6 position in this list is the same book twice at two stakes"
    )
    assert got["total"] < everything, "the fixture must also leave V6 holding"


async def test_the_v6_view_does_not_show_five_minute_trades(db_session):
    """The dangerous direction: this lab leaking into the established record."""
    await _seed_both(db_session)

    got = await lab_trades(db_session, strategy_id=None, status=None, limit=500)

    assert got["trades"]
    assert "FM-01" not in {t["strategy_id"] for t in got["trades"]}


async def test_every_row_carries_its_own_pnl_and_full_mint(db_session):
    """The two numbers the page exists to show, and the address it exists to
    let a reader check."""
    await _seed_both(db_session)

    got = await fivemin_trades(db_session, status=None, limit=500)
    row = got["trades"][0]

    # Whole address, character for character — the view exists to be copied.
    assert row["mint"] == "F" + "m" * 20
    assert "…" not in row["mint"] and "..." not in row["mint"]
    assert row["size_usd"] is not None
    if row["status"] == "open":
        # Marked at what it could be SOLD for, so a fresh position is down.
        assert row["unrealised_pnl"] is not None
        assert row["realised_pnl"] is None
    else:
        assert row["realised_pnl"] is not None


async def test_the_status_filter_narrows_to_open_or_closed(db_session):
    await _seed_both(db_session)

    opens = await fivemin_trades(db_session, status="open", limit=500)
    assert {t["status"] for t in opens["trades"]} == {"open"}

    closed = await fivemin_trades(db_session, status="closed", limit=500)
    assert all(t["status"] == "closed" for t in closed["trades"])


async def test_it_carries_this_lab_s_own_disclosure(db_session):
    """The reason to distrust this lab is specific to it — one coin of 138 did
    47.97x. The V6 disclosure here would be the wrong warning."""
    await _seed_both(db_session)

    got = await fivemin_trades(db_session, status=None, limit=500)
    assert "47.97x" in got["disclosure"]
    assert "RESEARCH SIMULATION" not in got["disclosure"]
