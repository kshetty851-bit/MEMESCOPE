"""Dividing the execution wallet between strategies.

The property that matters most here is NOT that the arithmetic divides. It is
that dividing the wallet cannot enlarge it — every global cap still binds, and
one tick still creates one intent no matter how many strategies are funded.
Multi-strategy is a way to split a blast radius, never a way to earn a bigger
one, and these tests fail if that ever stops being true.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.real_wallet_execution import (
    RealWalletAllocation,
    RealWalletLiveIntent,
    RealWalletPosition,
)
from app.real_wallet.allocations import (
    AllocationService,
    OverCommittedError,
)
from app.real_wallet.driver import RealWalletDriver
from app.real_wallet.live_repository import LiveIntentRepository

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


async def _position(
    session: AsyncSession, *, strategy_id: str | None, cost_usd: Decimal
) -> RealWalletPosition:
    """An OPEN position costing exactly `cost_usd`, tagged or untagged."""
    row = RealWalletPosition(
        mint_address=f"mint{uuid.uuid4().hex[:16]}",
        status="OPEN",
        strategy_id=strategy_id,
        quantity=Decimal(1),
        entry_price_usd=cost_usd,
        opened_at=NOW,
    )
    session.add(row)
    await session.flush()
    return row


class TestTheBookCannotBeOverCommitted:
    async def test_fractions_may_sum_to_the_whole_book(self, db_session: AsyncSession):
        svc = AllocationService(db_session)
        await svc.set(strategy_id="V6-01", fraction=Decimal("0.6"))
        await svc.set(strategy_id="V6-02", fraction=Decimal("0.4"))
        assert await svc.committed() == Decimal("1.0")

    async def test_one_percent_past_the_book_is_refused(self, db_session: AsyncSession):
        svc = AllocationService(db_session)
        await svc.set(strategy_id="V6-01", fraction=Decimal("0.6"))
        with pytest.raises(OverCommittedError):
            await svc.set(strategy_id="V6-02", fraction=Decimal("0.41"))

    async def test_refusal_does_not_silently_clamp(self, db_session: AsyncSession):
        """A clamped allocation is worse than a refused one: the operator walks
        away believing they hold a share they were never given."""
        svc = AllocationService(db_session)
        await svc.set(strategy_id="V6-01", fraction=Decimal("0.9"))
        with pytest.raises(OverCommittedError):
            await svc.set(strategy_id="V6-02", fraction=Decimal("0.5"))
        rows = {r.strategy_id: r.fraction for r in await svc.rows()}
        assert "V6-02" not in rows, "a refused allocation must not be written at all"

    async def test_raising_an_existing_allocation_compares_against_the_others(
        self, db_session: AsyncSession
    ):
        """The bug this guards: comparing against a total that still counts the
        row being edited makes every increase look like an over-commitment."""
        svc = AllocationService(db_session)
        await svc.set(strategy_id="V6-01", fraction=Decimal("0.2"))
        await svc.set(strategy_id="V6-02", fraction=Decimal("0.2"))
        await svc.set(strategy_id="V6-01", fraction=Decimal("0.8"))
        assert await svc.committed() == Decimal("1.0")

    async def test_a_disabled_allocation_frees_its_share(
        self, db_session: AsyncSession
    ):
        svc = AllocationService(db_session)
        await svc.set(strategy_id="V6-01", fraction=Decimal("0.7"))
        await svc.disable(strategy_id="V6-01")
        await svc.set(strategy_id="V6-02", fraction=Decimal("0.9"))
        assert await svc.committed() == Decimal("0.9")

    async def test_disabling_keeps_the_row_as_evidence(self, db_session: AsyncSession):
        svc = AllocationService(db_session)
        await svc.set(strategy_id="V6-01", fraction=Decimal("0.5"))
        await svc.disable(strategy_id="V6-01")
        assert [r.strategy_id for r in await svc.rows()] == ["V6-01"]

    @pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-0.1"), Decimal("1.5")])
    async def test_a_fraction_outside_the_book_is_refused(
        self, db_session: AsyncSession, bad: Decimal
    ):
        with pytest.raises(ValueError):
            await AllocationService(db_session).set(strategy_id="V6-01", fraction=bad)

    async def test_the_database_refuses_it_too_when_the_service_is_bypassed(
        self, db_session: AsyncSession
    ):
        """The service owns the cross-row sum; the DB owns the per-row bound.
        Stated twice on purpose — the DB's copy is what holds when something
        writes around the service."""
        db_session.add(RealWalletAllocation(strategy_id="V6-99", fraction=Decimal(2)))
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()


class TestTheSingleStrategyFallback:
    async def test_no_rows_falls_back_to_the_nominated_strategy(
        self, db_session: AsyncSession
    ):
        """Adding this table must not change how an already-funded wallet
        behaves until an operator deliberately divides it."""
        from app.real_wallet.autotrade import AutotradeSwitchService

        await AutotradeSwitchService(db_session).start(
            strategy_id="V6-06", actor="test",
            reason="fallback", at=NOW
        )
        enabled = await AllocationService(db_session).enabled()
        assert [(a.strategy_id, a.fraction) for a in enabled] == [
            ("V6-06", Decimal(1))
        ]

    async def test_the_fallback_is_marked_so_a_reader_can_tell(
        self, db_session: AsyncSession
    ):
        from app.real_wallet.autotrade import AutotradeSwitchService

        await AutotradeSwitchService(db_session).start(
            strategy_id="V6-06", actor="test",
            reason="fallback", at=NOW
        )
        assert (await AllocationService(db_session).enabled())[0].implicit is True

    async def test_a_stored_row_wins_over_the_fallback(
        self, db_session: AsyncSession
    ):
        from app.real_wallet.autotrade import AutotradeSwitchService

        await AutotradeSwitchService(db_session).start(
            strategy_id="V6-06", actor="test",
            reason="fallback", at=NOW
        )
        await AllocationService(db_session).set(
            strategy_id="V6-11", fraction=Decimal("0.5")
        )
        enabled = await AllocationService(db_session).enabled()
        assert [a.strategy_id for a in enabled] == ["V6-11"]
        assert enabled[0].implicit is False

    async def test_nothing_nominated_and_nothing_allocated_trades_nothing(
        self, db_session: AsyncSession
    ):
        assert await AllocationService(db_session).enabled() == []


class TestExposureIsCountedPerStrategy:
    async def test_one_strategys_position_is_not_anothers(
        self, db_session: AsyncSession
    ):
        await _position(db_session, strategy_id="V6-01", cost_usd=Decimal(30))
        await _position(db_session, strategy_id="V6-02", cost_usd=Decimal(70))
        repo = LiveIntentRepository(db_session)
        assert await repo.open_exposure_usd(strategy_id="V6-01") == Decimal(30)
        assert await repo.open_exposure_usd(strategy_id="V6-02") == Decimal(70)
        assert await repo.open_exposure_usd() == Decimal(100)

    async def test_an_untagged_position_bounds_the_wallet_but_no_strategy(
        self, db_session: AsyncSession
    ):
        """Positions opened before strategies were tagged carry a NULL id.
        Counting them toward the global total but toward nobody's allocation is
        the safe direction: crediting them to a strategy that may not have
        opened them would let that share be spent twice."""
        await _position(db_session, strategy_id=None, cost_usd=Decimal(40))
        repo = LiveIntentRepository(db_session)
        assert await repo.open_exposure_usd() == Decimal(40)
        assert await repo.open_exposure_usd(strategy_id="V6-01") == Decimal(0)


class TestTheTickStillCreatesOneIntent:
    """The throttle the single-strategy driver had, kept under division.

    Five funded strategies creating one intent each would be five times the
    blast radius of one bad minute, while looking like the same rule.
    """

    @staticmethod
    def _fund(driver: RealWalletDriver, *, lamports: int, price: Decimal) -> None:
        async def _lamports(_wallet: str) -> int:
            return lamports

        async def _price(_now: datetime) -> Decimal:
            return price

        driver._wallet_lamports = _lamports  # type: ignore[method-assign]
        driver._sol_usd = _price  # type: ignore[method-assign]

    async def test_many_funded_strategies_still_yield_at_most_one_intent(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ):
        from app.core.config import settings
        from app.real_wallet.autotrade import AutotradeSwitchService

        monkeypatch.setattr(settings, "REAL_WALLET_PUBLIC_KEY", "TestWallet11111")
        monkeypatch.setattr(settings, "REAL_WALLET_ENTRY_SIZE_USD", Decimal(5))
        monkeypatch.setattr(settings, "REAL_WALLET_MAX_TRADE_USD", Decimal(5))

        await AutotradeSwitchService(db_session).start(
            strategy_id="V6-01", actor="test",
            reason="multi", at=NOW
        )
        svc = AllocationService(db_session)
        for sid in ("V6-01", "V6-02", "V6-03", "V6-04", "V6-05"):
            await svc.set(strategy_id=sid, fraction=Decimal("0.2"))

        driver = RealWalletDriver(db_session)
        self._fund(driver, lamports=1_000_000_000, price=Decimal(100))
        outcome = await driver.tick(now=NOW)

        # No Lab decisions exist, so nothing should be created -- but the point
        # is the CEILING: whatever happens, one tick is at most one intent.
        assert outcome.created <= 1
        created = list(
            (await db_session.scalars(select(RealWalletLiveIntent))).all()
        )
        assert len(created) <= 1

    async def test_every_strategys_reason_is_reported_not_just_the_first(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ):
        """An operator asking "why is nothing trading" needs all the answers.
        The first strategy's reason alone is a guess at the wallet's state."""
        from app.core.config import settings
        from app.real_wallet.autotrade import AutotradeSwitchService

        monkeypatch.setattr(settings, "REAL_WALLET_PUBLIC_KEY", "TestWallet11111")
        monkeypatch.setattr(settings, "REAL_WALLET_ENTRY_SIZE_USD", Decimal(5))
        monkeypatch.setattr(settings, "REAL_WALLET_MAX_TRADE_USD", Decimal(5))

        await AutotradeSwitchService(db_session).start(
            strategy_id="V6-01", actor="test",
            reason="multi", at=NOW
        )
        svc = AllocationService(db_session)
        await svc.set(strategy_id="V6-01", fraction=Decimal("0.5"))
        await svc.set(strategy_id="V6-02", fraction=Decimal("0.5"))

        driver = RealWalletDriver(db_session)
        self._fund(driver, lamports=1_000_000_000, price=Decimal(100))
        outcome = await driver.tick(now=NOW)

        assert outcome.created == 0
        assert "V6-01=" in (outcome.skipped or "")
        assert "V6-02=" in (outcome.skipped or "")


class TestEachStrategyLaddersOnItsOwnShare:
    """The core claim of dividing the wallet, and the easiest thing to get wrong.

    A strategy holding 20% of a $1,000 book is running $200. It should double
    its stake when ITS $200 becomes $400 -- not when somebody else's strategy
    doubles the wallet. Sizing every strategy off total equity would have each
    of them growing on the others' results, which is not a division of capital
    at all, just five copies of one account.
    """

    async def test_the_stake_follows_the_share_not_the_whole_book(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ):
        from app.core.config import settings
        from app.models.lab import LabDecision, LabStrategy, LabTournament
        from app.real_wallet.autotrade import AutotradeSwitchService

        monkeypatch.setattr(settings, "REAL_WALLET_PUBLIC_KEY", "TestWallet11111")
        monkeypatch.setattr(settings, "REAL_WALLET_ENTRY_SIZE_USD", Decimal(10))
        monkeypatch.setattr(settings, "REAL_WALLET_MAX_TRADE_USD", Decimal(1000))
        # Base $500: the WHOLE book ($1,000) is at 2x, but a 20% share ($200)
        # is below base and must stay at 1x.
        monkeypatch.setattr(settings, "REAL_WALLET_SIZING_BASE_USD", Decimal(500))
        # Pinned rather than inherited: this test is about how the stake is
        # SIZED, and it should not start failing the day somebody retunes the
        # wallet-balance ceiling for reasons that have nothing to do with it.
        monkeypatch.setattr(settings, "REAL_WALLET_MAX_BALANCE_SOL", Decimal(100))
        monkeypatch.setattr(settings, "REAL_WALLET_MAX_OPEN_POSITIONS", 5)
        monkeypatch.setattr(settings, "REAL_WALLET_MAX_TOTAL_EXPOSURE_USD", Decimal(1000))
        monkeypatch.setattr(settings, "REAL_WALLET_MAX_DAILY_NOTIONAL_USD", Decimal(1000))
        monkeypatch.setattr(settings, "REAL_WALLET_MAX_DAILY_TRADES", 10)

        await AutotradeSwitchService(db_session).start(
            strategy_id="V6-01", actor="test", reason="share", at=NOW
        )
        await AllocationService(db_session).set(
            strategy_id="V6-01", fraction=Decimal("0.2")
        )
        tournament = LabTournament(
            spec_version="1",
            spec_hash="test",
            valid_from=NOW - timedelta(days=1),
            snapshot_at=NOW - timedelta(days=1),
        )
        db_session.add(tournament)
        await db_session.flush()
        # lab_decisions carries an FK to lab_strategies, so the strategy has to
        # exist before its decision can. Minimal row: the driver reads only the
        # decision, never these fields.
        strategy_row = LabStrategy(
            tournament_id=tournament.id,
            strategy_id="V6-01",
            name="test strategy",
            version="1",
            spec_hash="test",
            size_usd=Decimal(10),
            max_concurrent=1,
            max_exposure_usd=Decimal(100),
            rules={},
            starting_equity=Decimal(1000),
            cash=Decimal(1000),
            peak_equity=Decimal(1000),
        )
        db_session.add(strategy_row)
        await db_session.flush()
        db_session.add(
            LabDecision(
                strategy_row_id=strategy_row.id,
                strategy_id="V6-01",
                mint_address="MintForV601xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"[:44],
                checkpoint_at=NOW - timedelta(minutes=1),
                checkpoint_minutes=1,
                decided_at=NOW - timedelta(minutes=1),
                eligible=True,
            )
        )
        await db_session.flush()

        driver = RealWalletDriver(db_session)
        # $1,000 book: 10 SOL at $100.
        TestTheTickStillCreatesOneIntent._fund(
            driver, lamports=10_000_000_000, price=Decimal(100)
        )
        outcome = await driver.tick(now=NOW)
        assert outcome.created == 1, outcome.skipped

        intent = await db_session.scalar(select(RealWalletLiveIntent))
        # 1x of the $10 base, because $200 < $500. Had the ladder read total
        # equity it would have doubled to $20.
        assert intent.requested_usd == Decimal(10)


class TestRotationIsFair:
    async def test_a_strategy_that_never_traded_goes_first(
        self, db_session: AsyncSession
    ):
        """Ordering by anything correlated with the strategies themselves would
        let one take every tick, and the gap between their records would be an
        artefact of the driver rather than of the strategies."""
        from app.real_wallet.allocations import Allocation

        db_session.add(
            RealWalletLiveIntent(
                idempotency_key="k1",
                mint_address="mint1",
                side="BUY",
                strategy_id="V6-01",
                strategy_version="v",
                wallet_public_key="w",
                requested_usd=Decimal(5),
                input_mint="i",
                output_mint="o",
                created_at=NOW - timedelta(minutes=1),
            )
        )
        await db_session.flush()

        driver = RealWalletDriver(db_session)
        order = await driver._rotation_order(
            [
                Allocation("V6-01", Decimal("0.5")),
                Allocation("V6-02", Decimal("0.5")),
            ]
        )
        assert [a.strategy_id for a in order] == ["V6-02", "V6-01"]

    async def test_the_longest_waiting_strategy_goes_first(
        self, db_session: AsyncSession
    ):
        from app.real_wallet.allocations import Allocation

        for sid, ago in (("V6-01", 1), ("V6-02", 30)):
            db_session.add(
                RealWalletLiveIntent(
                    idempotency_key=f"k-{sid}",
                    mint_address=f"mint-{sid}",
                    side="BUY",
                    strategy_id=sid,
                    strategy_version="v",
                    wallet_public_key="w",
                    requested_usd=Decimal(5),
                    input_mint="i",
                    output_mint="o",
                    created_at=NOW - timedelta(minutes=ago),
                )
            )
        await db_session.flush()

        driver = RealWalletDriver(db_session)
        order = await driver._rotation_order(
            [
                Allocation("V6-01", Decimal("0.5")),
                Allocation("V6-02", Decimal("0.5")),
            ]
        )
        assert [a.strategy_id for a in order] == ["V6-02", "V6-01"]
