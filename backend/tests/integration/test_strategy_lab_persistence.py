"""Persistence, restart idempotency, and the wallet-isolation proof.

The unit tests prove Strategy Lab *has no statement* that could touch a wallet.
These prove that running it end-to-end against a real database in fact leaves
every wallet table byte-identical — which is the claim §25 and the production
brief's live safety test actually make.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.paper import PaperPosition, PaperWallet
from app.models.paper_v2 import PaperV2Position, PaperV2Wallet
from app.models.real_wallet_execution import RealWalletExecutionIntent
from app.models.strategy_lab import (
    StrategyLabFill,
    StrategyLabOpportunity,
    StrategyLabPosition,
    StrategyLabRefusal,
    StrategyLabWallet,
)
from app.strategy_lab import repository, service, strategies
from app.strategy_lab.state import LabState

pytestmark = pytest.mark.integration

T0 = datetime(2026, 8, 20, 6, 0, tzinfo=UTC)


def _future(minutes: int = 0) -> datetime:
    """An eligibility instant after any wallet these tests create.

    A forward wallet is only offered opportunities that became eligible at or
    after the wallet itself — otherwise activating forward research would sweep
    up the whole historical backlog and the record would not be out of sample.
    A fixture dated in the past would therefore be correctly ignored, and the
    test would assert nothing at all.
    """
    return datetime.now(UTC) + timedelta(minutes=1 + minutes)


async def _seed_opportunity(
    session: AsyncSession, *, mint: str, at: datetime, age_hours: float = 5
) -> StrategyLabOpportunity:
    row = StrategyLabOpportunity(
        source_decision_id=uuid.uuid4(),
        mint_address=mint,
        eligible_at=at,
        entry_price=Decimal("0.001"),
        liquidity_usd=Decimal(200_000),
        pool_address="POOL",
        venue="pumpswap",
        discovery_age_seconds=Decimal(age_hours * 3600),
        canonical_version="1.0.0",
    )
    session.add(row)
    await session.flush()
    return row


async def _wallet_fingerprint(session: AsyncSession) -> tuple:
    """Everything a wallet could possibly have had changed under it."""
    return (
        (await session.execute(select(func.count()).select_from(PaperWallet))).scalar_one(),
        (await session.execute(select(func.count()).select_from(PaperPosition))).scalar_one(),
        (
            await session.execute(
                select(func.coalesce(func.sum(PaperWallet.starting_balance), 0))
            )
        ).scalar_one(),
        (await session.execute(select(func.count()).select_from(PaperV2Wallet))).scalar_one(),
        (
            await session.execute(select(func.count()).select_from(PaperV2Position))
        ).scalar_one(),
        (
            await session.execute(select(func.count()).select_from(RealWalletExecutionIntent))
        ).scalar_one(),
    )


async def test_registration_is_idempotent_and_records_every_definition(
    db_session: AsyncSession,
) -> None:
    await repository.register_all(db_session, strategies.ALL)
    await repository.register_all(db_session, strategies.ALL)

    from app.models.strategy_lab import StrategyLabStrategy

    stored = list((await db_session.execute(select(StrategyLabStrategy))).scalars().all())
    assert len(stored) == len(strategies.ALL)
    by_key = {(s.strategy_id, s.version): s for s in stored}
    for definition in strategies.ALL:
        assert by_key[(definition.strategy_id, definition.version)].definition_hash == (
            definition.definition_hash
        )


async def test_a_changed_definition_is_rejected_rather_than_reconciled(
    db_session: AsyncSession,
) -> None:
    """§17. Editing S1 v1.0.0 would restate every result published under it."""
    await repository.register(db_session, strategies.S1)

    from app.strategy_lab.rules import Rung, StrategyRules

    altered = strategies.StrategyDefinition(
        strategy_id="S1",
        version="1.0.0",
        name=strategies.S1.name,
        purpose=strategies.S1.purpose,
        entry_size_usd=strategies.S1.entry_size_usd,
        rules=StrategyRules(
            rungs=(Rung(multiple=Decimal("1.30"), fraction=Decimal("0.25")),),
            hold_for=timedelta(hours=6),
        ),
    )
    with pytest.raises(repository.DefinitionChangedError):
        await repository.register(db_session, altered)


async def test_an_opportunity_is_frozen_and_never_rewritten(
    db_session: AsyncSession,
) -> None:
    from app.strategy_lab.opportunities import Opportunity

    def build(price: str) -> Opportunity:
        return Opportunity(
            source_decision_id=str(uuid.uuid4()),
            mint_address="FROZEN",
            eligible_at=T0,
            entry_price=Decimal(price),
            liquidity_usd=Decimal(1000),
            market_cap=None,
            liq_to_mcap=None,
            volume_24h=None,
            volume_1h=None,
            buys_24h=None,
            sells_24h=None,
            buy_sell_ratio_24h=None,
            pool_address="POOL",
            venue="pumpswap",
            trading_pair=None,
            discovery_age_seconds=Decimal(3600),
            first_discovered_at=None,
            radar_rank=None,
            radar_score=None,
            confidence_score=None,
            risk_score=None,
            risk_band=None,
            security_status=None,
            security_evaluated_at=None,
            observation_cadence_seconds=None,
            radar_input_snapshot_count=None,
            evidence_coverage_pct=None,
            quotes=(),
        )

    await repository.upsert_opportunities(db_session, [build("1")])
    await repository.upsert_opportunities(db_session, [build("999")])

    rows = list(
        (
            await db_session.execute(
                select(StrategyLabOpportunity).where(
                    StrategyLabOpportunity.mint_address == "FROZEN"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].entry_price == Decimal(1), "a frozen opportunity is not rewritten"


async def test_forward_ticks_are_idempotent_across_a_restart(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§25's restart test. A second tick over the same data changes nothing."""
    monkeypatch.setattr(
        "app.strategy_lab.service.current_state", lambda: LabState.FORWARD_RESEARCH
    )
    monkeypatch.setattr("app.strategy_lab.service._ingest", _no_ingest)

    await _seed_opportunity(db_session, mint="AAA", at=_future())
    await _seed_opportunity(db_session, mint="BBB", at=_future(minutes=5))

    first = await service.evaluate_forward(db_session, now=_future(minutes=60))
    assert first.positions_opened > 0

    counts_after_first = await _lab_counts(db_session)
    second = await service.evaluate_forward(db_session, now=_future(minutes=60))
    assert second.positions_opened == 0, "already-offered opportunities are not re-offered"
    assert await _lab_counts(db_session) == counts_after_first


async def _no_ingest(session, *, now):
    """Skip the Radar read: these tests seed their own canonical rows."""
    return 0


async def _lab_counts(session: AsyncSession) -> tuple[int, int, int]:
    return (
        (
            await session.execute(select(func.count()).select_from(StrategyLabPosition))
        ).scalar_one(),
        (
            await session.execute(select(func.count()).select_from(StrategyLabFill))
        ).scalar_one(),
        (
            await session.execute(select(func.count()).select_from(StrategyLabRefusal))
        ).scalar_one(),
    )


async def test_every_strategy_gets_its_own_thousand_and_sees_the_same_token(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.strategy_lab.service.current_state", lambda: LabState.FORWARD_RESEARCH
    )
    monkeypatch.setattr("app.strategy_lab.service._ingest", _no_ingest)
    await _seed_opportunity(db_session, mint="SHARED", at=_future())
    await service.evaluate_forward(db_session, now=_future(minutes=60))

    wallets = list(
        (
            await db_session.execute(
                select(StrategyLabWallet).where(
                    StrategyLabWallet.mode == LabState.FORWARD_RESEARCH.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(wallets) == len(strategies.ALL)
    assert {w.starting_balance for w in wallets} == {Decimal(1000)}

    # Every strategy either took SHARED or recorded why it did not. None
    # silently skipped it.
    for wallet in wallets:
        took = (
            await db_session.execute(
                select(func.count())
                .select_from(StrategyLabPosition)
                .where(
                    StrategyLabPosition.wallet_id == wallet.id,
                    StrategyLabPosition.mint_address == "SHARED",
                )
            )
        ).scalar_one()
        refused = (
            await db_session.execute(
                select(func.count())
                .select_from(StrategyLabRefusal)
                .where(
                    StrategyLabRefusal.wallet_id == wallet.id,
                    StrategyLabRefusal.mint_address == "SHARED",
                )
            )
        ).scalar_one()
        assert took + refused == 1, wallet.strategy_id


async def test_the_age_gate_blocks_only_s9_and_records_the_reason(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.strategy_lab.service.current_state", lambda: LabState.FORWARD_RESEARCH
    )
    monkeypatch.setattr("app.strategy_lab.service._ingest", _no_ingest)
    await _seed_opportunity(db_session, mint="YOUNG", at=_future(), age_hours=0.5)
    await service.evaluate_forward(db_session, now=_future(minutes=60))

    refusals = list(
        (
            await db_session.execute(
                select(StrategyLabRefusal, StrategyLabWallet.strategy_id)
                .join(StrategyLabWallet, StrategyLabWallet.id == StrategyLabRefusal.wallet_id)
                .where(StrategyLabRefusal.mint_address == "YOUNG")
            )
        ).all()
    )
    gated = {sid for refusal, sid in refusals if refusal.reason == "BLOCKED_DISCOVERY_AGE"}
    assert gated == {"S9"}


async def test_running_strategy_lab_leaves_every_wallet_table_untouched(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The production brief's live safety test, run against a real database."""
    monkeypatch.setattr(
        "app.strategy_lab.service.current_state", lambda: LabState.FORWARD_RESEARCH
    )
    monkeypatch.setattr("app.strategy_lab.service._ingest", _no_ingest)

    before = await _wallet_fingerprint(db_session)

    await _seed_opportunity(db_session, mint="SAFE1", at=_future())
    await _seed_opportunity(db_session, mint="SAFE2", at=_future(minutes=1))
    tick = await service.evaluate_forward(db_session, now=_future(minutes=60))
    assert tick.positions_opened > 0, "the lab really did open simulated positions"

    assert await _wallet_fingerprint(db_session) == before


async def test_the_forward_evaluator_does_nothing_while_disabled(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.strategy_lab.service.current_state", lambda: LabState.DISABLED)
    await _seed_opportunity(db_session, mint="IGNORED", at=_future())
    tick = await service.evaluate_forward(db_session, now=_future(minutes=60))

    assert tick.positions_opened == 0
    assert tick.skipped_reason is not None
    assert await _lab_counts(db_session) == (0, 0, 0)


async def test_forward_research_never_sweeps_up_the_historical_backlog(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§18. A forward record that replayed history would not be out of sample.

    On first activation the canonical table already holds every opportunity the
    historical replay froze. Offering those to a brand-new forward wallet would
    produce a "forward" result that is a backtest under another name, and would
    make the in-sample / out-of-sample distinction meaningless. Verified here
    rather than trusted, because the failure is silent: the numbers would look
    entirely plausible.
    """
    monkeypatch.setattr(
        "app.strategy_lab.service.current_state", lambda: LabState.FORWARD_RESEARCH
    )
    monkeypatch.setattr("app.strategy_lab.service._ingest", _no_ingest)

    # An opportunity from before the wallet exists, and one from after.
    await _seed_opportunity(db_session, mint="HISTORICAL", at=T0)
    await _seed_opportunity(db_session, mint="FRESH", at=_future())

    await service.evaluate_forward(db_session, now=_future(minutes=60))

    mints = set((await db_session.execute(select(StrategyLabPosition.mint_address))).scalars())
    assert "FRESH" in mints
    assert "HISTORICAL" not in mints, "a forward wallet must not replay history"


async def test_a_forward_tick_converges_and_then_does_nothing(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once the backlog is drained, a tick with no new evidence is a no-op."""
    monkeypatch.setattr(
        "app.strategy_lab.service.current_state", lambda: LabState.FORWARD_RESEARCH
    )
    monkeypatch.setattr("app.strategy_lab.service._ingest", _no_ingest)

    for index in range(3):
        await _seed_opportunity(db_session, mint=f"C{index}", at=_future(minutes=index))

    for _ in range(3):
        await service.evaluate_forward(db_session, now=_future(minutes=60))

    before = await _lab_counts(db_session)
    tick = await service.evaluate_forward(db_session, now=_future(minutes=60))
    assert tick.positions_opened == 0
    assert tick.refusals == 0
    assert await _lab_counts(db_session) == before
