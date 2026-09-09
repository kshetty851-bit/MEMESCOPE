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


async def test_the_sole_arm_buys_a_quiet_coin_now_that_the_filter_is_gone(db_session):
    """The turnover arm was retired on 2026-09-09, so a coin at 0.017
    turnover — far below the floor that used to reject it — is now bought.

    This is the behavioural record of what the deletion changed, and it is
    the test that would fail loudest if the filter were ever half-reinstated
    on the surviving wallet without its control.
    """
    svc = CompoundService(db_session, registry=mvspec)
    await svc._lab.activate(valid_from=NOW - timedelta(minutes=15))
    await _pumpfun_token(db_session, mint="M" + "q" * 20,
                         detected=NOW - timedelta(minutes=11), liq=D("600000"),
                         price=D("0.001"), pool="PMOVQ")
    await svc.tick(now=NOW)

    assert await _rows(db_session, "MOV-02"), (
        "the surviving wallet has no turnover condition and must take it"
    )
    assert "turnover_below_floor" not in await _skips(db_session, "MOV-02")
    assert not await _rows(db_session, "MOV-01"), "MOV-01 no longer exists"


async def test_the_turnover_feature_still_computes_though_nothing_reads_it(db_session):
    """`turnover_5m` stays in the engine after the arm that used it was
    retired. Keeping the measurement alive is deliberate — it is the one
    number this lab established (0.63 before a double against 0.11) — and a
    feature that quietly stopped being computed would make reinstating the
    filter look easy and be wrong.
    """
    tok = await _pumpfun_token(db_session, mint="M" + "t" * 20,
                               detected=NOW - timedelta(minutes=11),
                               liq=D("600000"), price=D("0.001"), pool="PMOVT")
    svc = LabService(db_session, registry=mvspec)
    features, _ctx = await svc.observe(
        token_id=tok.id, mint=tok.mint_address,
        detected_at=NOW - timedelta(minutes=11), checkpoint_at=NOW,
    )
    assert features["turnover_5m"] == pytest.approx(D("10000") / D("600000"))


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



async def test_a_retired_arm_disappears_from_the_board_and_the_ledger(db_session):
    """MOV-01's rows survive as the record of what it did, but neither the
    board nor the trades view may keep showing them.

    Both queries used to be scoped to the TOURNAMENT alone, so a retired arm
    went on appearing as a live wallet with a running P&L — the reader would
    have no way to tell it had stopped, and the board would be reporting a
    comparison the spec no longer runs.
    """
    from app.lab import board as shared
    from app.lab.api import build_trades
    from app.models.lab import LabDecision

    svc = CompoundService(db_session, registry=mvspec)
    t = await svc._lab.activate(valid_from=NOW - timedelta(minutes=15))

    # A retired arm, exactly as MOV-01 exists on production: a strategy row
    # and a closed position, with no entry in the registry.
    row = LabStrategy(
        tournament_id=t.id, strategy_id="MOV-01", name="MOVERS-TURNOVER",
        version=mvspec.SPEC_VERSION, spec_hash=mvspec.SPEC_HASH,
        checkpoint_minutes=10, size_usd=D("10"), max_concurrent=10,
        max_exposure_usd=D("100"), rules={}, starting_equity=D("100"),
        cash=D("97"), peak_equity=D("100"), status="active",
    )
    db_session.add(row)
    await db_session.flush()
    tok = await _pumpfun_token(db_session, mint="M" + "r" * 20,
                               detected=NOW - timedelta(minutes=11),
                               liq=D("600000"), price=D("0.001"), pool="PMOVR")
    d = LabDecision(strategy_row_id=row.id, strategy_id="MOV-01",
                    mint_address=tok.mint_address, checkpoint_at=NOW,
                    checkpoint_minutes=10, decided_at=NOW, eligible=True)
    db_session.add(d)
    await db_session.flush()
    db_session.add(LabPosition(
        decision_id=d.id, strategy_row_id=row.id, strategy_id="MOV-01",
        mint_address=tok.mint_address, token_id=tok.id, opened_at=NOW,
        entry_price=D("0.001"), size_usd=D("10"), quantity=D("10000"),
        quantity_remaining=D("0"), banked_proceeds_usd=D("0"),
        entry_source="test", status="closed", closed_at=NOW,
        exit_proceeds_usd=D("9"), exit_reason="arm_retired",
        peak_exec_multiple=D("1"),
    ))
    await db_session.flush()

    board = await shared.build(db_session, registry=mvspec, disclosure="x")
    assert "MOV-01" not in {w["strategy_id"] for w in board["wallets"]}

    trades = await build_trades(db_session, registry=mvspec, disclosure="x")
    assert "MOV-01" not in {t_["strategy_id"] for t_ in trades["trades"]}
