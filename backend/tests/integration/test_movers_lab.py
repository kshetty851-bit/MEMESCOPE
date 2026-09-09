"""The Movers Lab end to end: the feature is computed, and it gates entry.

The spec tests assert the rules are what they claim. These assert the engine
actually behaves that way — the distinction that has bitten this project
before, when six pairing tests passed vacuously against a helper that raised.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from app.compound.service import CompoundService
from app.lab.service import LabService
from app.models.lab import LabDecision, LabPosition, LabStrategy, LabTournament
from app.movers import spec as mvspec
from tests.integration.test_lab_accounting import NOW, _radar_token

pytestmark = pytest.mark.integration

#: The real pump.fun bonding-curve program. `_radar_token` defaults
#: `source_program` to the string "pumpfun", which is NOT in
#: `SCANNER_WATCH_PROGRAMS`, so `is_pumpfun` reads 0 and both arms skip on
#: `not_a_pumpfun_token` before they ever reach the turnover condition. That is
#: exactly how a pairing test can pass while testing nothing, so the fixture
#: is corrected here rather than worked around.
PUMPFUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"


async def _pumpfun_token(db_session, **kw):
    tok = await _radar_token(db_session, **kw)
    tok.source_program = PUMPFUN_PROGRAM
    await db_session.flush()
    return tok


async def _rows(db_session, strategy_id: str):
    return list((await db_session.execute(
        select(LabPosition)
        .join(LabStrategy, LabStrategy.id == LabPosition.strategy_row_id)
        .join(LabTournament, LabTournament.id == LabStrategy.tournament_id)
        .where(LabTournament.spec_version == mvspec.SPEC_VERSION,
               LabPosition.strategy_id == strategy_id)
    )).scalars())


async def _skips(db_session, strategy_id: str) -> set[str | None]:
    return {
        d.skip_reason for d in (await db_session.execute(
            select(LabDecision)
            .join(LabStrategy, LabStrategy.id == LabDecision.strategy_row_id)
            .join(LabTournament, LabTournament.id == LabStrategy.tournament_id)
            .where(LabTournament.spec_version == mvspec.SPEC_VERSION,
                   LabDecision.strategy_id == strategy_id,
                   LabDecision.eligible.is_(False))
        )).scalars()
    }


async def test_the_turnover_feature_is_actually_computed(db_session):
    """`turnover_5m` must reach the rule engine as a number.

    A feature the builder never sets is not a failing condition, it is an
    ABSENT one — and depending on the engine that either skips silently or
    passes silently. Either way the arm would stop being what its spec says.
    """
    tok = await _radar_token(db_session, mint="M" + "v" * 20,
                             detected=NOW - timedelta(hours=2), liq=D("600000"),
                             price=D("0.001"), pool="PMOV1")
    svc = LabService(db_session)
    features, _ctx = await svc.observe(
        token_id=tok.id, mint=tok.mint_address,
        detected_at=NOW - timedelta(hours=2), checkpoint_at=NOW,
    )

    assert "turnover_5m" in features, "the rule would be reading nothing"
    assert features["turnover_5m"] is not None
    # The fixture writes volume_5m 10,000 against liquidity 600,000.
    assert features["turnover_5m"] == pytest.approx(D("10000") / D("600000"))


async def test_the_floor_keeps_the_signal_arm_out_of_a_quiet_coin(db_session):
    """The whole hypothesis, tested as behaviour.

    The fixture's coin is deep and well-routed but quiet — turnover 0.017,
    below the 1.0 floor. The control must buy it and the signal must not, and
    the signal's refusal must name the turnover condition rather than some
    other gate it happened to fail first.
    """
    svc = CompoundService(db_session, registry=mvspec)
    # Activate FIRST, then present a coin whose 5-minute checkpoint falls after
    # the freeze: the engine excludes any checkpoint older than the tournament
    # on purpose, so a two-hour-old fixture is history and buys nothing in
    # either arm — which would pass this test for entirely the wrong reason.
    await svc._lab.activate(valid_from=NOW - timedelta(minutes=15))
    await _pumpfun_token(db_session, mint="M" + "q" * 20,
                       detected=NOW - timedelta(minutes=11), liq=D("600000"),
                       price=D("0.001"), pool="PMOVQ")
    await svc.tick(now=NOW)

    signal = await _rows(db_session, "MOV-01")
    control = await _rows(db_session, "MOV-02")

    assert control, "the control must take the coin the signal declines"
    assert not signal, "turnover 0.017 is far below the 1.0 floor"
    assert "turnover_below_floor" in await _skips(db_session, "MOV-01")


async def test_both_arms_take_a_coin_that_clears_the_floor(db_session):
    """The mirror of the test above, and the one that makes it mean something.

    Without this, a signal arm that never traded at all would pass the test
    above for entirely the wrong reason.
    """
    svc = CompoundService(db_session, registry=mvspec)
    await svc._lab.activate(valid_from=NOW - timedelta(minutes=15))
    tok = await _pumpfun_token(db_session, mint="M" + "h" * 20,
                             detected=NOW - timedelta(minutes=11), liq=D("600000"),
                             price=D("0.001"), pool="PMOVH")
    # Lift ONLY the volume, on the rows the engine actually reads. Appending a
    # fresh snapshot does not work: the fixture already writes one at every
    # whole minute including the checkpoint itself, and `observe` reads the
    # last row at-or-before it — so a row added after that is invisible and a
    # row added before it is shadowed. Turnover becomes 1000000/600000 = 1.67.
    from sqlalchemy import update
    from app.models.market import TokenMarketSnapshot
    await db_session.execute(
        update(TokenMarketSnapshot)
        .where(TokenMarketSnapshot.token_id == tok.id)
        .values(volume_5m=D("1000000"))
    )
    await db_session.flush()

    await svc.tick(now=NOW)

    assert await _rows(db_session, "MOV-01"), (
        "a coin at 1.67 turnover clears the 1.0 floor and must be bought"
    )
    assert await _rows(db_session, "MOV-02")


async def test_the_movers_tick_leaves_other_tournaments_alone(db_session):
    """Six registries share these tables. `settle` selecting every open
    position is how one lab's tick reaches into another's book — it has
    happened here before, and a KeyError on a foreign strategy id would stop
    whichever tick got there first."""
    lab = LabService(db_session)
    await lab.activate(valid_from=NOW - timedelta(days=1))
    await _radar_token(db_session, mint="M" + "x" * 20,
                       detected=NOW - timedelta(hours=2), liq=D("600000"),
                       price=D("0.001"), pool="PMOVX")
    await lab.evaluate_due(now=NOW)
    before = len(list((await db_session.execute(
        select(LabPosition).where(LabPosition.status == "open")
    )).scalars()))
    assert before > 0, "the fixture must leave the other lab holding something"

    await CompoundService(db_session, registry=mvspec).tick(now=NOW)

    still = list((await db_session.execute(
        select(LabPosition).where(LabPosition.status == "open",
                                  LabPosition.strategy_id.notin_(["MOV-01", "MOV-02"]))
    )).scalars())
    assert len(still) == before

