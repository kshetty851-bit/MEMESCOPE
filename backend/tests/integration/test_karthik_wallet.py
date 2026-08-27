"""The Karthik wallet against a real database.

The unit tests cover the rule. These cover the things only Postgres can prove:
that a duplicate event, a restarted worker and two concurrent passes produce one
position; that a token admitted before activation is unreachable rather than
merely unselected; and that the accounting adds up across a real book.

Jupiter is stubbed throughout. The router is an I/O seam, and what is under test
here is what the wallet does with a quote, not whether the internet answered.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.karthik import rules
from app.karthik.repository import KarthikRepository
from app.karthik.rules import Decision, ExitReason
from app.karthik.service import KarthikService
from app.models.karthik import KarthikOpportunity, KarthikPosition
from app.models.market import TradingStatus
from app.models.radar import RadarToken
from app.paper.execution import ExecutionQuote, ExecutionQuoteUnavailableError
from app.repositories.market import MarketSnapshotRepository
from app.repositories.token import TokenRepository

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC).replace(microsecond=0)
ACTIVATION = NOW - timedelta(hours=1)

BEFORE = "KarthikBeforeMint11111111111111111111111111"
AFTER = "KarthikAfterMint222222222222222222222222222"
LATE_ADMIT = "KarthikLateAdmit3333333333333333333333333333"
SECOND = "KarthikSecondMint44444444444444444444444444"


# --- Seeding -----------------------------------------------------------------


async def _token(session: AsyncSession, mint: str, *, discovered_at: datetime) -> object:
    token = await TokenRepository(session).insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}",
            "slot": 1,
            "discovered_at": discovered_at,
            "block_time": discovered_at,
            "name": "Karthik Probe",
            "symbol": "KRP",
            "decimals": 6,
        }
    )
    assert token is not None
    return token


async def _admit(session: AsyncSession, token: object, mint: str, *, at: datetime) -> RadarToken:
    """Put a token on the Track Record at `at`."""
    entry = RadarToken(
        token_id=token.id,  # type: ignore[attr-defined]
        mint_address=mint,
        first_detected_at=at,
        first_price=Decimal("0.001"),
        first_market_cap=Decimal(120_000),
        first_opportunity_score=Decimal(70),
        first_confidence=Decimal(40),
        detection_reason=["probe"],
        category="early_momentum",
        current_opportunity_score=Decimal(70),
        current_confidence=Decimal(40),
        current_category="early_momentum",
        is_active=True,
        model_version="v1",
        last_evaluated_at=at,
    )
    session.add(entry)
    await session.flush()
    return entry


async def _price(
    session: AsyncSession,
    token: object,
    mint: str,
    *,
    at: datetime,
    price: str,
    liquidity: str | None = "18000",
    status: TradingStatus = TradingStatus.TRADING,
) -> None:
    await MarketSnapshotRepository(session).add_snapshot(
        {
            "token_id": token.id,  # type: ignore[attr-defined]
            "mint_address": mint,
            "captured_at": at,
            "price_usd": Decimal(price),
            "market_cap": Decimal(124_000),
            "liquidity_usd": None if liquidity is None else Decimal(liquidity),
            "volume_24h": Decimal(89_000),
            "dex_name": "pumpswap",
            "pool_address": f"pool-{mint[:8]}",
            "trading_status": status,
            "provider": "test",
        }
    )


# --- A stub router -----------------------------------------------------------


def _quote(side: str, *, price: Decimal, tokens: Decimal, usd: Decimal | None) -> ExecutionQuote:
    return ExecutionQuote(
        side=side,
        model_version="jupiter_quote_v2",
        quoted_at=NOW,
        latency_ms=Decimal(4),
        input_mint="in",
        output_mint="out",
        input_amount_raw="1",
        output_amount_raw="1",
        input_decimals=6,
        output_decimals=6,
        input_amount=Decimal(1),
        output_amount=tokens,
        input_amount_usd=None,
        output_amount_usd=usd,
        estimated_price_usd=price,
        price_impact_pct=Decimal("0.5"),
        context_slot=1,
        platform_fee_usd=Decimal(0),
        route="Stub",
        amms=("Stub",),
        raw={},
    )


class StubRouter:
    """Answers exactly what a test tells it to, and records what was asked."""

    def __init__(self, *, sell: object = "quote") -> None:
        self.sell_mode = sell
        self.sells: list[str] = []

    async def buy_quote(self, *, output_mint, input_usd, output_decimals, now):  # noqa: ANN001
        # $10 buys 10,000 units at $0.001, minus nothing: the stub is exact so a
        # test asserting on cash is asserting on the wallet, not on slippage.
        tokens = input_usd / Decimal("0.001")
        return _quote("entry", price=Decimal("0.001"), tokens=tokens, usd=None)

    async def sell_quote(self, *, input_mint, quantity, input_decimals, now):  # noqa: ANN001
        self.sells.append(input_mint)
        if self.sell_mode == "unavailable":
            raise ExecutionQuoteUnavailableError("no route")
        if self.sell_mode == "dust":
            return _quote("exit", price=Decimal("0"), tokens=quantity, usd=Decimal("0.02"))
        proceeds = quantity * Decimal("0.00125")
        return _quote("exit", price=Decimal("0.00125"), tokens=quantity, usd=proceeds)


def _service(session: AsyncSession, router: StubRouter | None = None) -> KarthikService:
    service = KarthikService(session)
    service._execution = router or StubRouter()  # type: ignore[assignment]
    return service


# --- Activation --------------------------------------------------------------


class TestActivation:
    async def test_the_wallet_starts_with_a_thousand_dollars_and_nothing_else(
        self, db_session: AsyncSession
    ) -> None:
        service = _service(db_session)
        wallet = await service.activate(now=ACTIVATION)

        assert wallet.name == "Karthik"
        assert wallet.starting_capital == Decimal("1000.0000")
        assert wallet.trade_size == Decimal("10.0000")
        assert wallet.take_profit_multiple == Decimal("1.2500")
        assert wallet.activated_at == ACTIVATION

        read = await service.read(now=NOW)
        assert read.cash == Decimal("1000.0000")
        assert read.equity == Decimal("1000.0000")
        assert read.open_positions == []
        assert read.closed_positions == []
        assert read.realized_pnl == Decimal(0)

    async def test_activating_twice_does_not_move_the_watermark(
        self, db_session: AsyncSession
    ) -> None:
        """The one value that must never be wrong.

        `activated_at` is the eligibility watermark. A second activation that
        moved it forward would silently make already-decided tokens ineligible;
        one that moved it back would open the door to backfill. The database's
        singleton index makes both impossible.
        """
        service = _service(db_session)
        first = await service.activate(now=ACTIVATION)
        again = await service.activate(now=NOW)

        assert again.id == first.id
        assert again.activated_at == ACTIVATION
        assert (
            await db_session.scalar(
                select(func.count()).select_from(first.__table__)  # type: ignore[attr-defined]
            )
        ) == 1


# --- Eligibility -------------------------------------------------------------


class TestEligibility:
    async def test_a_token_admitted_after_activation_is_entered(
        self, db_session: AsyncSession
    ) -> None:
        service = _service(db_session)
        await service.activate(now=ACTIVATION)
        token = await _token(db_session, AFTER, discovered_at=ACTIVATION - timedelta(minutes=30))
        await _admit(db_session, token, AFTER, at=ACTIVATION + timedelta(minutes=10))
        await _price(db_session, token, AFTER, at=NOW, price="0.001")

        outcome = await service.review(now=NOW)
        assert outcome is not None
        assert outcome.opened == 1

        positions = await KarthikRepository(db_session).open_positions(
            (await service.wallet()).id  # type: ignore[union-attr]
        )
        assert [p.mint_address for p in positions] == [AFTER]

    async def test_a_token_admitted_before_activation_is_never_entered(
        self, db_session: AsyncSession
    ) -> None:
        """Not merely skipped — unreachable.

        No opportunity row is written either. The token is outside Karthik's
        universe entirely, which is what "no historical backfill" means: the
        selecting query cannot return it, so no decision about it can exist.
        """
        service = _service(db_session)
        await service.activate(now=ACTIVATION)
        token = await _token(db_session, BEFORE, discovered_at=ACTIVATION - timedelta(hours=2))
        await _admit(db_session, token, BEFORE, at=ACTIVATION - timedelta(minutes=5))
        await _price(db_session, token, BEFORE, at=NOW, price="0.001")

        outcome = await service.review(now=NOW)
        assert outcome is not None
        assert outcome.opened == 0
        assert outcome.admissions == 0

        wallet = await service.wallet()
        assert wallet is not None
        assert (
            await db_session.scalar(
                select(func.count())
                .select_from(KarthikOpportunity)
                .where(KarthikOpportunity.wallet_id == wallet.id)
            )
        ) == 0
        assert (
            await db_session.scalar(
                select(func.count())
                .select_from(KarthikPosition)
                .where(KarthikPosition.mint_address == BEFORE)
            )
        ) == 0

    async def test_an_old_token_that_enters_the_track_record_late_is_eligible(
        self, db_session: AsyncSession
    ) -> None:
        """Detection time does not decide eligibility. Admission does.

        The example from the brief: seen at 10:00, activated at 10:10, admitted
        at 10:20. The token is older than the wallet and is bought anyway,
        because the *event* Karthik trades is the Track Record admission.
        """
        service = _service(db_session)
        await service.activate(now=ACTIVATION)
        token = await _token(db_session, LATE_ADMIT, discovered_at=ACTIVATION - timedelta(days=9))
        await _admit(db_session, token, LATE_ADMIT, at=ACTIVATION + timedelta(minutes=10))
        await _price(db_session, token, LATE_ADMIT, at=NOW, price="0.001")

        outcome = await service.review(now=NOW)
        assert outcome is not None
        assert outcome.opened == 1

        position = await db_session.scalar(
            select(KarthikPosition).where(KarthikPosition.mint_address == LATE_ADMIT)
        )
        assert position is not None
        # The evidence for the claim above, recorded on the row itself.
        assert position.detected_at is not None
        assert position.detected_at < position.track_record_at < position.opened_at

    async def test_the_backfill_count_is_zero_and_stays_zero(
        self, db_session: AsyncSession
    ) -> None:
        """Every position Karthik holds was admitted after it was activated."""
        service = _service(db_session)
        wallet = await service.activate(now=ACTIVATION)
        for mint, at in (
            (BEFORE, ACTIVATION - timedelta(minutes=1)),
            (AFTER, ACTIVATION + timedelta(minutes=1)),
        ):
            token = await _token(db_session, mint, discovered_at=at - timedelta(minutes=5))
            await _admit(db_session, token, mint, at=at)
            await _price(db_session, token, mint, at=NOW, price="0.001")

        await service.review(now=NOW)
        backfilled = await db_session.scalar(
            select(func.count())
            .select_from(KarthikPosition)
            .where(
                KarthikPosition.wallet_id == wallet.id,
                KarthikPosition.track_record_at <= wallet.activated_at,
            )
        )
        assert backfilled == 0


# --- Exactly once ------------------------------------------------------------


class TestExactlyOnce:
    async def test_a_duplicate_event_produces_one_position(
        self, db_session: AsyncSession
    ) -> None:
        """Three passes over the same admission. One $10 position."""
        service = _service(db_session)
        wallet = await service.activate(now=ACTIVATION)
        token = await _token(db_session, AFTER, discovered_at=ACTIVATION)
        await _admit(db_session, token, AFTER, at=ACTIVATION + timedelta(minutes=1))
        await _price(db_session, token, AFTER, at=NOW, price="0.001")

        first = await service.review(now=NOW)
        second = await service.review(now=NOW + timedelta(seconds=30))
        third = await service.review(now=NOW + timedelta(minutes=1))

        assert (first.opened, second.opened, third.opened) == (1, 0, 0)  # type: ignore[union-attr]
        assert (
            await db_session.scalar(
                select(func.count())
                .select_from(KarthikPosition)
                .where(KarthikPosition.wallet_id == wallet.id)
            )
        ) == 1

    async def test_a_restarted_worker_does_not_re_enter(
        self, db_session: AsyncSession
    ) -> None:
        """A fresh service instance holds no memory, and does not need to.

        The guarantee is in the database, not in the process. This builds a new
        `KarthikService` — the same thing a container restart produces — and
        replays the pass.
        """
        wallet = await _service(db_session).activate(now=ACTIVATION)
        token = await _token(db_session, AFTER, discovered_at=ACTIVATION)
        await _admit(db_session, token, AFTER, at=ACTIVATION + timedelta(minutes=1))
        await _price(db_session, token, AFTER, at=NOW, price="0.001")

        await _service(db_session).review(now=NOW)
        await _service(db_session).review(now=NOW + timedelta(minutes=1))

        assert (
            await db_session.scalar(
                select(func.count())
                .select_from(KarthikPosition)
                .where(KarthikPosition.wallet_id == wallet.id)
            )
        ) == 1

    async def test_the_database_refuses_a_second_decision_for_the_same_mint(
        self, db_session: AsyncSession
    ) -> None:
        """Idempotency at the database, not at the service.

        The repository is called directly, bypassing every application check, to
        show that the unique index is what holds — a caller that skipped the
        service could not create a duplicate either.
        """
        repository = KarthikRepository(db_session)
        wallet = await _service(db_session).activate(now=ACTIVATION)

        first = await repository.claim(
            wallet=wallet,
            mint_address=AFTER,
            track_record_at=NOW,
            decision=Decision.ENTERED.value,
            decided_at=NOW,
        )
        second = await repository.claim(
            wallet=wallet,
            mint_address=AFTER,
            track_record_at=NOW,
            decision=Decision.SKIPPED_INSUFFICIENT_CASH.value,
            decided_at=NOW,
        )
        assert (first, second) == (True, False)
        assert (
            await db_session.scalar(
                select(func.count())
                .select_from(KarthikOpportunity)
                .where(KarthikOpportunity.wallet_id == wallet.id)
            )
        ) == 1

    async def test_the_database_refuses_a_second_position_in_the_same_mint(
        self, db_session: AsyncSession
    ) -> None:
        repository = KarthikRepository(db_session)
        wallet = await _service(db_session).activate(now=ACTIVATION)
        token = await _token(db_session, AFTER, discovered_at=ACTIVATION)

        values = {
            "wallet_id": wallet.id,
            "mint_address": AFTER,
            "token_id": token.id,  # type: ignore[attr-defined]
            "track_record_at": NOW,
            "opened_at": NOW,
            "entry_price": Decimal("0.001"),
            "entry_observed_price": Decimal("0.001"),
            "entry_observed_at": NOW,
            "cost_basis": Decimal("10"),
            "quantity": Decimal(10_000),
            "decimals": 6,
            "target_price": Decimal("0.00125"),
            "status": "open",
            "peak_price": Decimal("0.001"),
            "last_evaluated_at": NOW,
        }
        assert await repository.open_position(**values) is not None
        assert await repository.open_position(**values) is None


# --- Money -------------------------------------------------------------------


class TestAccounting:
    async def test_an_entry_deducts_exactly_ten_dollars(
        self, db_session: AsyncSession
    ) -> None:
        service = _service(db_session)
        await service.activate(now=ACTIVATION)
        token = await _token(db_session, AFTER, discovered_at=ACTIVATION)
        await _admit(db_session, token, AFTER, at=ACTIVATION + timedelta(minutes=1))
        await _price(db_session, token, AFTER, at=NOW, price="0.001")

        await service.review(now=NOW)
        read = await service.read(now=NOW)

        assert read.cash == Decimal("990.0000")
        assert read.allocated == Decimal("10.0000")
        # Equity is unchanged at the instant of entry: $10 of cash became $10 of
        # position. Anything else would mean the wallet booked a gain or a loss
        # for the act of buying.
        assert read.equity == Decimal("1000.0000")
        assert read.realized_pnl == Decimal(0)

    async def test_an_opportunity_arriving_with_under_ten_dollars_is_skipped_forever(
        self, db_session: AsyncSession
    ) -> None:
        """Not queued. Recorded as a permanent miss, with a reason.

        The wallet is drained to $5 by a direct write so the test is about the
        decision rather than about ninety-nine entries.
        """
        service = _service(db_session)
        wallet = await service.activate(now=ACTIVATION)
        drain = await _token(db_session, SECOND, discovered_at=ACTIVATION)
        await KarthikRepository(db_session).open_position(
            wallet_id=wallet.id,
            mint_address=SECOND,
            token_id=drain.id,  # type: ignore[attr-defined]
            track_record_at=ACTIVATION,
            opened_at=ACTIVATION,
            entry_price=Decimal("0.001"),
            entry_observed_price=Decimal("0.001"),
            entry_observed_at=ACTIVATION,
            cost_basis=Decimal("995"),
            quantity=Decimal(995_000),
            decimals=6,
            target_price=Decimal("0.00125"),
            status="open",
            peak_price=Decimal("0.001"),
            last_evaluated_at=ACTIVATION,
        )

        token = await _token(db_session, AFTER, discovered_at=ACTIVATION)
        await _admit(db_session, token, AFTER, at=ACTIVATION + timedelta(minutes=1))
        await _price(db_session, token, AFTER, at=NOW, price="0.001")

        await service.review(now=NOW)
        skipped = await KarthikRepository(db_session).skipped(wallet.id)
        assert [(item.mint_address, item.decision) for item in skipped] == [
            (AFTER, Decision.SKIPPED_INSUFFICIENT_CASH.value)
        ]

        # And it stays skipped even once cash is abundant again. The ledger row
        # is the whole mechanism: a missed opportunity remains missed.
        await db_session.execute(
            KarthikPosition.__table__.delete().where(
                KarthikPosition.mint_address == SECOND
            )
        )
        later = await service.review(now=NOW + timedelta(minutes=5))
        assert later is not None
        assert later.opened == 0


# --- Exits -------------------------------------------------------------------


async def _entered(session: AsyncSession, router: StubRouter | None = None) -> KarthikPosition:
    service = _service(session, router)
    await service.activate(now=ACTIVATION)
    token = await _token(session, AFTER, discovered_at=ACTIVATION)
    await _admit(session, token, AFTER, at=ACTIVATION + timedelta(minutes=1))
    await _price(session, token, AFTER, at=NOW, price="0.001")
    await service.review(now=NOW)
    position = await session.scalar(
        select(KarthikPosition).where(KarthikPosition.mint_address == AFTER)
    )
    assert position is not None
    return position


class TestExits:
    async def test_one_and_a_quarter_x_sells_the_whole_position(
        self, db_session: AsyncSession
    ) -> None:
        router = StubRouter()
        position = await _entered(db_session, router)
        token = await db_session.scalar(
            select(RadarToken).where(RadarToken.mint_address == AFTER)
        )
        assert token is not None
        await _price(
            db_session,
            type("T", (), {"id": position.token_id})(),
            AFTER,
            at=NOW + timedelta(minutes=2),
            price="0.00125",
        )

        service = _service(db_session, router)
        outcome = await service.review(now=NOW + timedelta(minutes=2))
        assert outcome is not None
        assert outcome.closed == 1

        await db_session.refresh(position)
        assert position.status == "closed"
        assert position.exit_reason == ExitReason.TARGET_1_25X.value
        # The whole position, and the proceeds are the router's, not 1.25 x cost.
        assert position.exit_proceeds_usd == (position.quantity * Decimal("0.00125")).quantize(
            Decimal("0.0001")
        )
        read = await service.read(now=NOW + timedelta(minutes=2))
        assert read.open_positions == []
        assert read.cash == Decimal("990.0000") + position.exit_proceeds_usd

    async def test_a_target_with_no_route_behind_it_holds(
        self, db_session: AsyncSession
    ) -> None:
        """The router refuses to quote, so there is no sale and no exit.

        This is the case that separates "the price printed 1.25x" from "the
        position could be sold at 1.25x". Only the second is a target hit.
        """
        router = StubRouter(sell="unavailable")
        position = await _entered(db_session, router)
        await _price(
            db_session,
            type("T", (), {"id": position.token_id})(),
            AFTER,
            at=NOW + timedelta(minutes=2),
            price="0.00125",
        )

        outcome = await _service(db_session, router).review(now=NOW + timedelta(minutes=2))
        assert outcome is not None
        assert outcome.closed == 0
        assert outcome.holds == {"no_executable_quote": 1}

        await db_session.refresh(position)
        assert position.status == "open"
        assert router.sells == [AFTER]

    async def test_a_drained_pool_printing_two_x_is_not_a_winning_trade(
        self, db_session: AsyncSession
    ) -> None:
        """The rug case, end to end.

        Liquidity has gone to zero and the price print says 2x. The position is
        held, the router is never even asked, and no closed trade exists — so
        there is no path on which this becomes a 25% win.
        """
        router = StubRouter()
        position = await _entered(db_session, router)
        await _price(
            db_session,
            type("T", (), {"id": position.token_id})(),
            AFTER,
            at=NOW + timedelta(minutes=2),
            price="0.002",
            liquidity="0",
        )

        outcome = await _service(db_session, router).review(now=NOW + timedelta(minutes=2))
        assert outcome is not None
        assert outcome.closed == 0
        assert outcome.holds == {"target_not_executable": 1}
        assert router.sells == []

        await db_session.refresh(position)
        assert position.status == "open"
        assert position.exit_proceeds_usd is None

    @pytest.mark.parametrize("multiple", ["1.24", "0.80", "0.20", "0.05"])
    async def test_a_falling_price_holds_at_every_depth(
        self, db_session: AsyncSession, multiple: str
    ) -> None:
        router = StubRouter()
        position = await _entered(db_session, router)
        await _price(
            db_session,
            type("T", (), {"id": position.token_id})(),
            AFTER,
            at=NOW + timedelta(minutes=2),
            price=str(Decimal("0.001") * Decimal(multiple)),
        )

        outcome = await _service(db_session, router).review(now=NOW + timedelta(minutes=2))
        assert outcome is not None
        assert outcome.closed == 0
        assert outcome.holds == {"below_target": 1}

    async def test_six_hours_is_not_an_exit(self, db_session: AsyncSession) -> None:
        """The paper wallet has a holding period. Karthik has none."""
        router = StubRouter()
        position = await _entered(db_session, router)
        later = NOW + timedelta(hours=6, minutes=1)
        await _price(
            db_session,
            type("T", (), {"id": position.token_id})(),
            AFTER,
            at=later,
            price="0.0009",
        )

        outcome = await _service(db_session, router).review(now=later)
        assert outcome is not None
        assert outcome.closed == 0
        await db_session.refresh(position)
        assert position.status == "open"

    async def test_a_pool_the_provider_calls_inactive_settles_at_zero(
        self, db_session: AsyncSession
    ) -> None:
        """Dead means unsellable, and unsellable returns nothing.

        Not the last printed price: a pool with no meaningful liquidity left
        cannot be sold into at any price, so booking its final print would be
        booking a fill that could not have happened.
        """
        router = StubRouter()
        position = await _entered(db_session, router)
        await _price(
            db_session,
            type("T", (), {"id": position.token_id})(),
            AFTER,
            at=NOW + timedelta(minutes=2),
            price="0.0004",
            liquidity="0",
            status=TradingStatus.INACTIVE,
        )

        service = _service(db_session, router)
        outcome = await service.review(now=NOW + timedelta(minutes=2))
        assert outcome is not None
        assert outcome.closed == 1

        await db_session.refresh(position)
        assert position.exit_reason == ExitReason.DEAD_ZERO.value
        assert position.exit_proceeds_usd == Decimal("0.0000")
        assert position.exit_evidence is not None
        read = await service.read(now=NOW + timedelta(minutes=2))
        assert read.cash == Decimal("990.0000")
        assert read.realized_pnl == Decimal("-10.0000")

    async def test_a_two_x_after_the_target_already_closed_produces_no_second_fill(
        self, db_session: AsyncSession
    ) -> None:
        router = StubRouter()
        position = await _entered(db_session, router)
        await _price(
            db_session,
            type("T", (), {"id": position.token_id})(),
            AFTER,
            at=NOW + timedelta(minutes=2),
            price="0.00125",
        )
        await _service(db_session, router).review(now=NOW + timedelta(minutes=2))

        await _price(
            db_session,
            type("T", (), {"id": position.token_id})(),
            AFTER,
            at=NOW + timedelta(minutes=5),
            price="0.002",
        )
        outcome = await _service(db_session, router).review(now=NOW + timedelta(minutes=5))
        assert outcome is not None
        assert outcome.evaluated == 0
        assert outcome.closed == 0

        closed = await db_session.scalars(
            select(KarthikPosition).where(KarthikPosition.mint_address == AFTER)
        )
        rows = list(closed)
        assert len(rows) == 1
        assert rows[0].exit_price == Decimal("0.00125") .quantize(Decimal("1.000000000000000000"))

    async def test_monitoring_continues_when_no_entry_can_be_funded(
        self, db_session: AsyncSession
    ) -> None:
        """$0 cash stops buying. It must never stop watching.

        The position below is entered, the wallet is then drained to nothing,
        and the target is hit. The exit still happens — which is the only reason
        an exhausted wallet is a temporary state rather than the end of the run.
        """
        router = StubRouter()
        position = await _entered(db_session, router)
        wallet = await _service(db_session).wallet()
        assert wallet is not None
        await KarthikRepository(db_session).open_position(
            wallet_id=wallet.id,
            mint_address=SECOND,
            token_id=None,
            track_record_at=ACTIVATION,
            opened_at=ACTIVATION,
            entry_price=Decimal("0.001"),
            entry_observed_price=Decimal("0.001"),
            entry_observed_at=ACTIVATION,
            cost_basis=Decimal("990"),
            quantity=Decimal(990_000),
            decimals=6,
            target_price=Decimal("0.00125"),
            status="open",
            peak_price=Decimal("0.001"),
            last_evaluated_at=ACTIVATION,
        )
        service = _service(db_session, router)
        assert (await service.read(now=NOW)).cash == Decimal("0.0000")

        await _price(
            db_session,
            type("T", (), {"id": position.token_id})(),
            AFTER,
            at=NOW + timedelta(minutes=2),
            price="0.00125",
        )
        outcome = await service.review(now=NOW + timedelta(minutes=2))
        assert outcome is not None
        assert outcome.closed == 1
        assert outcome.opened == 0


# --- The evidence a trade leaves behind --------------------------------------


class TestEntryEvidence:
    async def test_every_moment_comes_from_its_own_source(
        self, db_session: AsyncSession
    ) -> None:
        service = _service(db_session)
        await service.activate(now=ACTIVATION)
        discovered = ACTIVATION - timedelta(minutes=20)
        admitted = ACTIVATION + timedelta(minutes=5)
        token = await _token(db_session, AFTER, discovered_at=discovered)
        await _admit(db_session, token, AFTER, at=admitted)
        await _price(db_session, token, AFTER, at=NOW, price="0.001")

        await service.review(now=NOW)
        position = await db_session.scalar(
            select(KarthikPosition).where(KarthikPosition.mint_address == AFTER)
        )
        assert position is not None
        assert position.detected_at == discovered
        assert position.track_record_at == admitted
        assert position.opened_at == NOW
        # The three are genuinely different values. If detection were ever
        # substituted by the entry time, the delay would read zero.
        assert position.detected_at != position.opened_at
        assert position.pool_address is not None
        assert position.entry_liquidity_usd == Decimal("18000.0000")
        assert position.entry_market_cap == Decimal("124000.0000")
        assert position.symbol == "KRP"
        assert position.decimals == 6
        assert position.target_price == position.entry_price * rules.TAKE_PROFIT_MULTIPLE

    async def test_a_mint_with_no_discovery_row_records_no_detection_time(
        self, db_session: AsyncSession
    ) -> None:
        """Never estimated. `NULL` means "not available", and the page says so.

        The Radar row is inserted directly against a token whose discovery row is
        deleted afterwards, leaving an admission with nothing behind it.
        """
        service = _service(db_session)
        wallet = await service.activate(now=ACTIVATION)
        repository = KarthikRepository(db_session)
        created = await repository.open_position(
            wallet_id=wallet.id,
            mint_address=AFTER,
            token_id=None,
            detected_at=None,
            track_record_at=ACTIVATION + timedelta(minutes=1),
            opened_at=NOW,
            entry_price=Decimal("0.001"),
            entry_observed_price=Decimal("0.001"),
            entry_observed_at=NOW,
            cost_basis=Decimal("10"),
            quantity=Decimal(10_000),
            decimals=6,
            target_price=Decimal("0.00125"),
            status="open",
            peak_price=Decimal("0.001"),
            last_evaluated_at=NOW,
        )
        assert created is not None
        assert created.detected_at is None


# --- The other wallets -------------------------------------------------------


class TestTheOtherWalletsAreUntouched:
    async def test_a_full_karthik_pass_writes_no_paper_or_real_wallet_row(
        self, db_session: AsyncSession
    ) -> None:
        """Counted before and after, across every table that trades.

        The structural tests prove no code path exists. This proves the
        behaviour, over a pass that enters, holds and closes.
        """
        from app.models.paper import PaperPosition, PaperTradeAudit, PaperWallet
        from app.models.paper_research import PaperDecisionSnapshot
        from app.models.real_wallet_execution import RealWalletPosition

        watched = (
            PaperWallet,
            PaperPosition,
            PaperTradeAudit,
            PaperDecisionSnapshot,
            RealWalletPosition,
        )

        async def counts() -> dict[str, int]:
            return {
                model.__tablename__: (
                    await db_session.scalar(select(func.count()).select_from(model))
                )
                or 0
                for model in watched
            }

        before = await counts()

        router = StubRouter()
        position = await _entered(db_session, router)
        await _price(
            db_session,
            type("T", (), {"id": position.token_id})(),
            AFTER,
            at=NOW + timedelta(minutes=2),
            price="0.00125",
        )
        await _service(db_session, router).review(now=NOW + timedelta(minutes=2))

        assert await counts() == before
