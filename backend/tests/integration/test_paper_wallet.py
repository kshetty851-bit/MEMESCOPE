"""The paper wallet end to end: entries, exits, and what the API refuses to say.

Sprint 25 built it; Sprint 30 relaunched it. The wallet is a deterministic
simulation over stored market history — no wallet is connected, no order is
routed, no chain is touched. These tests hold it to that: every trade must be
explainable by the published rule, and no figure may appear that the rows do not
support.

The constraints carrying product meaning are asserted directly, because they are
the difference between a track record and a demo:

  - a token is entered **once, ever**, which is the entry rule as a constraint;
  - the entry block is **never rewritten**, so an exit level cannot be recomputed
    favourably after the outcome is known;
  - exactly **one wallet is live**, so a relaunch archives rather than mixes;
  - the audit log is **append-only**, so a completed trade is permanent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.market import TradingStatus
from app.models.paper import PaperPosition, PaperTradeAudit, PaperWallet
from app.models.radar import RadarToken
from app.paper.eligibility import Refusal
from app.paper.repository import PaperRepository
from app.paper.service import PaperWalletService
from app.repositories.market import MarketSnapshotRepository
from app.repositories.token import TokenRepository

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC).replace(microsecond=0)


@pytest.fixture(autouse=True)
def _wallet_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "FEATURE_PAPER_WALLET_ENABLED", True)
    monkeypatch.setattr(settings, "PAPER_WALLET_STARTING_BALANCE", 1000.0)
    monkeypatch.setattr(settings, "PAPER_WALLET_STRATEGY_ID", "trailing_stop_25_v1")


async def _token(session: AsyncSession, mint: str) -> object:
    token = await TokenRepository(session).insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}",
            "slot": 1,
            "discovered_at": NOW - timedelta(days=1),
            "block_time": NOW - timedelta(days=1),
            "name": f"Probe {mint[-1]}",
            "symbol": f"P{mint[-1]}",
        }
    )
    assert token is not None
    return token


async def _radar_entry(session: AsyncSession, token: object, mint: str, *, score: int) -> None:
    session.add(
        RadarToken(
            token_id=token.id,  # type: ignore[attr-defined]
            mint_address=mint,
            first_detected_at=NOW - timedelta(days=1),
            first_price=Decimal("10"),
            first_market_cap=Decimal("10000"),
            first_opportunity_score=Decimal(score),
            first_confidence=Decimal(40),
            detection_reason=["volume_expanding"],
            category="early_momentum",
            current_opportunity_score=Decimal(score),
            current_confidence=Decimal(40),
            current_category="early_momentum",
            current_multiple=Decimal("1.0"),
            peak_multiple=Decimal("1.0"),
            is_active=True,
            model_version="v1",
            last_evaluated_at=NOW,
        )
    )
    await session.flush()


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
            "market_cap": Decimal("124000"),
            "liquidity_usd": None if liquidity is None else Decimal(liquidity),
            "volume_24h": Decimal("89000"),
            "dex_name": "pumpswap",
            "trading_status": status,
            "provider": "test",
        }
    )


async def _seed(
    session: AsyncSession, mint: str, *, score: int, price: str, **kwargs: object
) -> object:
    token = await _token(session, mint)
    await _radar_entry(session, token, mint, score=score)
    await _price(session, token, mint, at=NOW, price=price, **kwargs)  # type: ignore[arg-type]
    return token


MINT_A = "PaperWalletMintAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
MINT_B = "PaperWalletMintBBBBBBBBBBBBBBBBBBBBBBBBBBBB"


class TestEntries:
    async def test_an_eligible_token_is_bought_at_the_published_size(
        self, db_session: AsyncSession
    ) -> None:
        await _seed(db_session, MINT_A, score=90, price="10")
        await db_session.commit()

        outcome = await PaperWalletService(db_session).review(now=NOW)
        await db_session.commit()

        assert outcome.opened == 1
        position = (await db_session.scalars(select(PaperPosition))).one()
        assert position.size_usd == Decimal(100)
        assert position.entry_price == Decimal(10)
        assert position.quantity == Decimal(10)
        assert position.entry_rank == 1
        # The one exit rule is fixed at entry; the three it does not have are
        # NULL rather than set out of reach.
        assert position.trailing_drawdown == Decimal("0.25")
        assert position.target_price is None
        assert position.stop_price is None
        assert position.expires_at is None
        # The market at entry is recorded, because the audit needs it later and
        # the snapshot that carries it is prunable.
        assert position.entry_market_cap == Decimal("124000")
        assert position.entry_liquidity_usd == Decimal("18000")

    async def test_a_token_is_entered_once_ever(self, db_session: AsyncSession) -> None:
        """The entry rule as a database constraint. "Once, ever" is true because
        re-entry is a state the schema cannot hold."""
        await _seed(db_session, MINT_A, score=90, price="10")
        await db_session.commit()
        service = PaperWalletService(db_session)

        first = await service.review(now=NOW)
        await db_session.commit()
        second = await service.review(now=NOW + timedelta(minutes=5))
        await db_session.commit()

        assert first.opened == 1
        assert second.opened == 0
        assert second.refusals[Refusal.ALREADY_HELD] == 1
        assert len((await db_session.scalars(select(PaperPosition))).all()) == 1

    async def test_a_closed_token_is_never_re_entered(self, db_session: AsyncSession) -> None:
        """One lifetime trade per token, closed or not. A wallet that could buy
        the same mint twice would be measuring its own re-entry timing rather
        than the Radar."""
        token = await _seed(db_session, MINT_A, score=90, price="10")
        await db_session.commit()
        service = PaperWalletService(db_session)
        await service.review(now=NOW)
        await db_session.commit()

        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=1), price="20")
        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=2), price="14")
        await db_session.commit()
        await service.review(now=NOW + timedelta(hours=3))
        await db_session.commit()

        outcome = await service.review(now=NOW + timedelta(hours=4))
        await db_session.commit()

        assert outcome.opened == 0
        assert outcome.refusals[Refusal.ALREADY_TRADED] == 1
        assert len((await db_session.scalars(select(PaperPosition))).all()) == 1

    async def test_a_second_pass_is_a_no_op(self, db_session: AsyncSession) -> None:
        """Beat has no lock and every Radar refresh enqueues a pass, so overlap
        is ordinary. It must cost nothing."""
        await _seed(db_session, MINT_A, score=90, price="10")
        await db_session.commit()
        service = PaperWalletService(db_session)

        await service.review(now=NOW)
        await db_session.commit()
        before = (await db_session.scalars(select(PaperPosition))).one()
        opened_at, entry = before.opened_at, before.entry_price

        await service.review(now=NOW + timedelta(minutes=1))
        await db_session.commit()
        after = (await db_session.scalars(select(PaperPosition))).one()

        assert (after.opened_at, after.entry_price) == (opened_at, entry)

    async def test_an_unpriced_token_is_not_bought(self, db_session: AsyncSession) -> None:
        """Unpriced is not free. Sizing against a price nobody observed would be
        the estimate this platform refuses to make."""
        token = await _token(db_session, MINT_A)
        await _radar_entry(db_session, token, MINT_A, score=90)
        await db_session.commit()

        outcome = await PaperWalletService(db_session).review(now=NOW)
        await db_session.commit()

        assert outcome.opened == 0
        assert outcome.refusals[Refusal.NO_MARKET_DATA] == 1

    async def test_a_token_with_no_pool_depth_is_not_bought(
        self, db_session: AsyncSession
    ) -> None:
        """Sprint 30 §5 added liquidity to the entry gate, and it earns its
        place twice: a bonding-curve pair reports no depth at all, and a trade
        whose cost cannot be computed cannot be audited."""
        await _seed(db_session, MINT_A, score=90, price="10", liquidity=None)
        await db_session.commit()

        outcome = await PaperWalletService(db_session).review(now=NOW)
        await db_session.commit()

        assert outcome.opened == 0
        assert outcome.refusals[Refusal.NO_LIQUIDITY] == 1

    async def test_a_token_the_provider_does_not_call_tradeable_is_not_bought(
        self, db_session: AsyncSession
    ) -> None:
        await _seed(db_session, MINT_A, score=90, price="10", status=TradingStatus.INACTIVE)
        await db_session.commit()

        outcome = await PaperWalletService(db_session).review(now=NOW)
        await db_session.commit()

        assert outcome.opened == 0
        assert outcome.refusals[Refusal.NOT_TRADEABLE] == 1

    async def test_the_wallet_can_run_out_of_money(self, db_session: AsyncSession) -> None:
        """Declining is the published behaviour. A wallet that quietly halved
        its size would report a return the rule did not produce."""
        for index in range(12):
            await _seed(db_session, f"PaperFund{index:034d}", score=90 - index, price="10")
        await db_session.commit()

        outcome = await PaperWalletService(db_session).review(now=NOW)
        await db_session.commit()

        # $1,000 at $100 each. The cut is cash, not rank — the strategy reads
        # the whole Radar.
        assert outcome.opened == 10
        assert outcome.refusals[Refusal.INSUFFICIENT_CASH] == 2

    async def test_entries_fill_from_the_top_of_the_radar_down(
        self, db_session: AsyncSession
    ) -> None:
        """When cash is short the order must follow the published ranking, not
        whichever row the query plan returned first."""
        await _seed(db_session, MINT_A, score=95, price="10")
        await _seed(db_session, MINT_B, score=60, price="10")
        await db_session.commit()

        await PaperWalletService(db_session).review(now=NOW)
        await db_session.commit()

        ranks = {
            row.mint_address: row.entry_rank
            for row in (await db_session.scalars(select(PaperPosition))).all()
        }
        assert ranks[MINT_A] == 1
        assert ranks[MINT_B] == 2

    async def test_cash_freed_by_an_exit_is_redeployed_in_the_same_pass(
        self, db_session: AsyncSession
    ) -> None:
        """Sprint 30 §4's loop, asserted end to end: exit, cash returns, the next
        highest-ranked eligible token is bought. Exits before entries is the
        published order — the other way round would decline a position the
        strategy could actually have funded.
        """
        # Ten tokens fill the wallet; an eleventh waits with no cash for it.
        for index in range(10):
            await _seed(db_session, f"PaperLoop{index:034d}", score=90 - index, price="10")
        await db_session.commit()
        service = PaperWalletService(db_session)
        await service.review(now=NOW)
        await db_session.commit()

        waiting = "PaperLoopWaiting000000000000000000000000000"
        await _seed(db_session, waiting, score=50, price="10")
        # The top-ranked holding gives back a quarter of its high and exits.
        first = f"PaperLoop{0:034d}"
        token = await TokenRepository(db_session).get_by_mint(first)
        await _price(db_session, token, first, at=NOW + timedelta(hours=1), price="20")
        await _price(db_session, token, first, at=NOW + timedelta(hours=2), price="14")
        await db_session.commit()

        outcome = await service.review(now=NOW + timedelta(hours=3))
        await db_session.commit()

        assert outcome.closed == 1
        assert outcome.opened == 1
        held = {
            row.mint_address
            for row in (await db_session.scalars(select(PaperPosition))).all()
            if row.status == "open"
        }
        assert waiting in held


class TestExits:
    async def _open_one(self, db_session: AsyncSession, *, price: str = "10") -> object:
        token = await _seed(db_session, MINT_A, score=90, price=price)
        await db_session.commit()
        await PaperWalletService(db_session).review(now=NOW)
        await db_session.commit()
        return token

    async def test_the_trailing_stop_closes_at_a_quarter_back_from_the_high(
        self, db_session: AsyncSession
    ) -> None:
        token = await self._open_one(db_session)
        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=1), price="20")
        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=2), price="14")
        await db_session.commit()

        outcome = await PaperWalletService(db_session).review(now=NOW + timedelta(hours=3))
        await db_session.commit()

        position = (await db_session.scalars(select(PaperPosition))).one()
        assert outcome.closed == 1
        assert position.status == "closed"
        assert position.exit_reason == "stop"
        # 25% back from the running high of 20, not the 14 that breached it.
        assert position.exit_price == Decimal(15)
        assert position.peak_price == Decimal(20)

    async def test_a_rise_alone_never_closes_a_position(
        self, db_session: AsyncSession
    ) -> None:
        """There is no profit target. A token that quadruples stays open, and
        the trailing stop simply rises with it."""
        token = await self._open_one(db_session)
        for hour, price in ((1, "20"), (2, "30"), (3, "40")):
            await _price(
                db_session, token, MINT_A, at=NOW + timedelta(hours=hour), price=price
            )
        await db_session.commit()

        outcome = await PaperWalletService(db_session).review(now=NOW + timedelta(hours=4))
        await db_session.commit()

        position = (await db_session.scalars(select(PaperPosition))).one()
        assert outcome.closed == 0
        assert position.status == "open"
        assert position.peak_price == Decimal(40)

    async def test_time_alone_never_closes_a_position(self, db_session: AsyncSession) -> None:
        """No holding period. A position runs until the rule triggers, however
        long that takes — a real consequence of the published strategy, and one
        the equity curve is left to show rather than hide."""
        token = await self._open_one(db_session)
        await _price(db_session, token, MINT_A, at=NOW + timedelta(days=30), price="9")
        await db_session.commit()

        outcome = await PaperWalletService(db_session).review(now=NOW + timedelta(days=31))
        await db_session.commit()

        position = (await db_session.scalars(select(PaperPosition))).one()
        assert outcome.closed == 0
        assert position.status == "open"

    async def test_a_dip_through_the_trail_still_stops_out(
        self, db_session: AsyncSession
    ) -> None:
        """The failure this design exists to prevent. A position that breached
        its trail and recovered before anyone evaluated it is still closed."""
        token = await self._open_one(db_session)
        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=1), price="2")
        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=2), price="11")
        await db_session.commit()

        await PaperWalletService(db_session).review(now=NOW + timedelta(hours=3))
        await db_session.commit()

        position = (await db_session.scalars(select(PaperPosition))).one()
        assert position.exit_reason == "stop"
        # The high before the breach was the entry itself, so the trail sat at
        # 7.50 — that is where it books, not at the 2 that was printed.
        assert position.exit_price == Decimal("7.5")

    async def test_the_close_is_dated_to_the_observation_not_the_evaluation(
        self, db_session: AsyncSession
    ) -> None:
        """A worker that ran a day late must record the close when it happened."""
        token = await self._open_one(db_session)
        breach = NOW + timedelta(hours=1)
        await _price(db_session, token, MINT_A, at=breach, price="5")
        await db_session.commit()

        await PaperWalletService(db_session).review(now=NOW + timedelta(days=1))
        await db_session.commit()

        position = (await db_session.scalars(select(PaperPosition))).one()
        assert position.closed_at == breach

    async def test_a_closed_position_is_never_reopened_or_rewritten(
        self, db_session: AsyncSession
    ) -> None:
        """A closed trade is part of the permanent record."""
        token = await self._open_one(db_session)
        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=1), price="5")
        await db_session.commit()
        service = PaperWalletService(db_session)
        await service.review(now=NOW + timedelta(hours=2))
        await db_session.commit()
        first = (await db_session.scalars(select(PaperPosition))).one()
        recorded = (first.exit_price, first.closed_at, first.exit_reason)

        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=3), price="1")
        await db_session.commit()
        await service.review(now=NOW + timedelta(hours=4))
        await db_session.commit()

        after = (await db_session.scalars(select(PaperPosition))).one()
        assert (after.exit_price, after.closed_at, after.exit_reason) == recorded

    async def test_the_entry_block_is_never_rewritten(self, db_session: AsyncSession) -> None:
        """The anti-hindsight guarantee. A trailing distance that could move
        after the outcome is known could move favourably."""
        token = await self._open_one(db_session)
        before = (await db_session.scalars(select(PaperPosition))).one()
        entry = (
            before.entry_price,
            before.trailing_drawdown,
            before.size_usd,
            before.opened_at,
        )

        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=1), price="14")
        await db_session.commit()
        await PaperWalletService(db_session).review(now=NOW + timedelta(hours=2))
        await db_session.commit()

        after = (await db_session.scalars(select(PaperPosition))).one()
        assert (
            after.entry_price,
            after.trailing_drawdown,
            after.size_usd,
            after.opened_at,
        ) == entry
        # Still open, and the peak moved — so the row was written to.
        assert after.status == "open"
        assert after.peak_price == Decimal(14)


class TestReproducibility:
    async def test_evaluating_late_gives_the_same_trade_as_evaluating_often(
        self, db_session: AsyncSession
    ) -> None:
        """The claim the whole wallet rests on, asserted against a real database:
        the same stored history must produce the same trade whatever the worker
        did or when it ran."""
        token = await _seed(db_session, MINT_A, score=90, price="10")
        await db_session.commit()
        service = PaperWalletService(db_session)
        await service.review(now=NOW)
        await db_session.commit()

        for hour, price in ((1, "12"), (2, "8"), (3, "30")):
            await _price(
                db_session, token, MINT_A, at=NOW + timedelta(hours=hour), price=price
            )
        await db_session.commit()

        # One late pass over the whole history.
        await service.review(now=NOW + timedelta(hours=9))
        await db_session.commit()
        late = (await db_session.scalars(select(PaperPosition))).one()

        assert late.exit_reason == "stop"
        # A quarter back from the high of 12.
        assert late.exit_price == Decimal(9)
        assert late.closed_at == NOW + timedelta(hours=2)
        # The peak stops at the exit: the 30 printed afterwards is the token's,
        # not the trade's.
        assert late.peak_price == Decimal(12)


class TestTheAuditLog:
    async def _close_one(self, db_session: AsyncSession) -> None:
        token = await _seed(db_session, MINT_A, score=90, price="10")
        await db_session.commit()
        service = PaperWalletService(db_session)
        await service.review(now=NOW)
        await db_session.commit()
        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=1), price="20")
        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=2), price="14")
        await db_session.commit()
        await service.review(now=NOW + timedelta(hours=3))
        await db_session.commit()

    async def test_every_closed_trade_records_what_sprint_30_asked_for(
        self, db_session: AsyncSession
    ) -> None:
        await self._close_one(db_session)

        row = (await db_session.scalars(select(PaperTradeAudit))).one()

        assert row.mint_address == MINT_A
        assert row.symbol == "PA"
        assert row.entry_at is not None and row.exit_at is not None
        assert row.entry_price == Decimal(10)
        assert row.exit_price == Decimal(15)
        assert row.entry_market_cap == Decimal("124000")
        assert row.exit_market_cap == Decimal("124000")
        assert row.exit_reason == "stop"
        assert row.strategy_id == "trailing_stop_25_v1"
        assert row.strategy_version == "1.0.0"

    async def test_gross_and_net_are_both_recorded_with_their_components(
        self, db_session: AsyncSession
    ) -> None:
        """Entry $100 at 10, exit 10 units at 15 = $150 of proceeds, against a
        pool reporting $18,000 total depth — $9,000 a side.

        Fee: 30 bps of 100 plus 30 bps of 150.
        Impact: 100 x (100/9000) on the way in, 150 x (150/9000) on the way out.
        """
        await self._close_one(db_session)

        row = (await db_session.scalars(select(PaperTradeAudit))).one()

        assert row.gross_return_usd == Decimal("50.0000")
        assert row.gross_return_pct == Decimal("50.0000")
        assert row.fee_usd == Decimal("0.7500")
        assert row.slippage_usd == Decimal("3.6111")
        assert row.net_return_usd == Decimal("45.6389")
        assert row.cost_unavailable_reason is None
        # The exit costs more than the entry: it sells a bigger position. Cost
        # is progressive, which is the whole reason it is charged at each end.
        assert row.slippage_usd > Decimal("2.2222")

    async def test_a_trade_is_recorded_once_however_many_passes_run(
        self, db_session: AsyncSession
    ) -> None:
        """The permanent record has one INSERT and no UPDATE. A repeated pass
        conflicts and does nothing."""
        await self._close_one(db_session)
        service = PaperWalletService(db_session)

        second = await service.review(now=NOW + timedelta(hours=4))
        await db_session.commit()

        assert second.audited == 0
        assert len((await db_session.scalars(select(PaperTradeAudit))).all()) == 1

    async def test_the_api_serves_the_record_with_its_refusals(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await self._close_one(db_session)

        body = (await client.get("/api/v1/paper/audit")).json()

        assert body["total"] == 1
        entry = body["items"][0]
        assert entry["exit_reason"] == "stop"
        assert Decimal(entry["net_return_usd"]) == Decimal("45.6389")
        assert "MEV" in body["disclosure"]


class TestTheWaitingState:
    async def test_an_idle_wallet_says_what_it_is_waiting_for(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Sprint 30 §9. The wallet never buys a lower-quality token to avoid an
        empty screen, so it has to be able to say why the screen is empty."""
        await _seed(db_session, MINT_A, score=90, price="10", liquidity=None)
        await db_session.commit()
        await PaperWalletService(db_session).review(now=NOW)
        await db_session.commit()

        body = (await client.get("/api/v1/paper")).json()

        assert body["waiting"] is not None
        assert body["waiting"]["message"] == (
            "Waiting for the next qualified Radar opportunity."
        )
        assert body["waiting"]["considered"] == 1
        assert body["waiting"]["refusals"]["no_liquidity"] == 1
        # Prose comes from the server, rendered off a stable code.
        assert "pool depth" in body["waiting"]["labels"]["no_liquidity"]

    async def test_a_wallet_with_a_qualified_token_in_front_of_it_is_not_waiting(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A page that claimed to be waiting while an opportunity sat in front of
        it would be worse than one that said nothing."""
        await _seed(db_session, MINT_A, score=90, price="10")
        await db_session.commit()

        body = (await client.get("/api/v1/paper")).json()

        assert body["waiting"] is None


class TestArchival:
    async def test_only_one_wallet_is_ever_live(self, db_session: AsyncSession) -> None:
        """Enforced by `uq_paper_wallets_live`, not by convention. Two live
        wallets would double every trade and halve every figure."""
        repository = PaperRepository(db_session)
        first = await repository.ensure_wallet(
            strategy_id="trailing_stop_25_v1",
            strategy_version="1.0.0",
            starting_balance=Decimal(1000),
            generation=1,
            started_at=NOW,
        )
        second = await repository.ensure_wallet(
            strategy_id="trailing_stop_25_v1",
            strategy_version="1.0.0",
            starting_balance=Decimal(1000),
            generation=2,
            started_at=NOW,
        )
        assert first.id == second.id

    async def test_an_archived_wallet_is_never_advanced(
        self, db_session: AsyncSession
    ) -> None:
        """The relaunch's central promise: the old wallet's trades are a record,
        not a book. Nothing opens into it and nothing closes out of it."""
        await _seed(db_session, MINT_A, score=90, price="10")
        await db_session.commit()
        service = PaperWalletService(db_session)
        await service.review(now=NOW)
        await db_session.commit()

        live = await PaperRepository(db_session).live_wallet()
        assert live is not None
        live.archived_at = NOW
        live.archive_reason = "probe"
        await db_session.commit()

        # A fresh pass launches a new generation rather than touching the old.
        await service.review(now=NOW + timedelta(minutes=5))
        await db_session.commit()

        wallets = (await db_session.scalars(select(PaperWallet))).all()
        assert len(wallets) == 2
        generations = sorted(wallet.generation for wallet in wallets)
        assert generations == [1, 2]
        archived = next(wallet for wallet in wallets if wallet.archived_at is not None)
        positions = (
            await db_session.scalars(
                select(PaperPosition).where(PaperPosition.wallet_id == archived.id)
            )
        ).all()
        assert len(positions) == 1
        assert positions[0].status == "open"

    async def test_the_archive_endpoint_states_that_open_positions_never_settle(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed(db_session, MINT_A, score=90, price="10")
        await db_session.commit()
        await PaperWalletService(db_session).review(now=NOW)
        await db_session.commit()
        live = await PaperRepository(db_session).live_wallet()
        assert live is not None
        live.archived_at = NOW
        live.archive_reason = "Superseded by a relaunch."
        await db_session.commit()

        body = (await client.get("/api/v1/paper/archive")).json()

        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["open_positions"] == 1
        assert "never settle" in item["frozen_note"]
        assert "internal" in body["note"].lower()


class TestBenchmarks:
    async def test_both_comparisons_start_where_the_wallet_started(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Sprint 30 §2. A benchmark measured over a period the wallet did not
        trade credits or punishes the strategy for free."""
        token = await _seed(db_session, MINT_A, score=90, price="10")
        await db_session.commit()
        await PaperWalletService(db_session).review(now=NOW)
        await db_session.commit()
        # The token doubles after the wallet launched.
        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=1), price="20")
        await db_session.commit()

        body = (await client.get("/api/v1/paper")).json()
        by_id = {item["id"]: item for item in body["benchmarks"]}

        assert body["started_at"] is not None
        # Bought at 10 at the wallet's start, marked at 20: +100%, both ways.
        assert Decimal(by_id["buy_every_radar_token"]["return_pct"]) == Decimal(100)
        assert Decimal(by_id["equal_weight_radar"]["return_pct"]) == Decimal(100)

    async def test_the_two_benchmarks_say_when_they_coincide(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """They are distinct measurements that happen to hold the same tokens
        while fewer qualify than $1,000 can fund. Saying so beats hiding one."""
        await _seed(db_session, MINT_A, score=90, price="10")
        await db_session.commit()

        body = (await client.get("/api/v1/paper")).json()

        assert body["benchmark_note"] is not None
        assert "separate" in body["benchmark_note"]

    async def test_holding_sol_is_unavailable_with_its_reason(
        self, client: AsyncClient
    ) -> None:
        """The platform stores no SOL series, so the comparison would be
        fabricated. It says so rather than showing a number."""
        body = (await client.get("/api/v1/paper")).json()
        sol = [item for item in body["benchmarks"] if item["id"] == "hold_sol"]

        assert sol and sol[0]["return_pct"] is None
        assert "fabricated" in sol[0]["unavailable_reason"]


class TestApi:
    async def test_the_wallet_reports_its_metrics_and_its_disclosure(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed(db_session, MINT_A, score=90, price="10")
        await db_session.commit()
        await PaperWalletService(db_session).review(now=NOW)
        await db_session.commit()

        body = (await client.get("/api/v1/paper")).json()

        assert body["enabled"] is True
        assert Decimal(body["metrics"]["starting_balance"]) == Decimal(1000)
        assert Decimal(body["metrics"]["cash"]) == Decimal(900)
        assert Decimal(body["metrics"]["invested_usd"]) == Decimal(100)
        assert body["metrics"]["open_positions"] == 1
        assert "no order is placed" in body["disclosure"].lower()
        assert body["strategy"]["is_active"] is True

    async def test_the_dashboard_carries_what_sprint_30_asked_it_to_show(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed(db_session, MINT_A, score=90, price="10")
        await db_session.commit()
        await PaperWalletService(db_session).review(now=NOW)
        await db_session.commit()

        body = (await client.get("/api/v1/paper")).json()

        for field in (
            "generation",
            "started_at",
            "next_radar_evaluation_at",
            "last_trade",
            "audited_trades",
        ):
            assert field in body
        assert body["last_trade"]["action"] == "opened"
        assert body["last_trade"]["mint_address"] == MINT_A
        for field in (
            "equity",
            "cash",
            "invested_usd",
            "open_positions",
            "closed_positions",
            "roi_pct",
            "win_rate_pct",
            "max_drawdown_pct",
            "average_hold_hours",
            "average_win",
            "average_loss",
            "largest_winner",
            "largest_loser",
        ):
            assert field in body["metrics"]

    async def test_nothing_served_reads_as_advice(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed(db_session, MINT_A, score=90, price="10")
        await db_session.commit()
        await PaperWalletService(db_session).review(now=NOW)
        await db_session.commit()

        text = (await client.get("/api/v1/paper")).text.lower()

        for phrase in ("we recommend", "you should", "buy now", "guaranteed"):
            assert phrase not in text

    async def test_positions_carry_what_the_position_page_shows(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed(db_session, MINT_A, score=90, price="10")
        await db_session.commit()
        await PaperWalletService(db_session).review(now=NOW)
        await db_session.commit()

        items = (await client.get("/api/v1/paper/positions")).json()["items"]

        assert len(items) == 1
        row = items[0]
        for field in (
            "entry_price",
            "current_price",
            "current_pct",
            "peak_pct",
            "trailing_drawdown",
            "trailing_stop_price",
            "status",
            "symbol",
        ):
            assert field in row
        assert row["status"] == "open"
        assert row["exit_reason"] is None
        # The live trail, derived from the running high rather than stored.
        assert Decimal(row["trailing_stop_price"]) == Decimal("7.5")

    async def test_the_strategies_endpoint_publishes_one_running_rule(
        self, client: AsyncClient
    ) -> None:
        body = (await client.get("/api/v1/paper/strategies")).json()

        assert body["active_id"] == "trailing_stop_25_v1"
        active = [item for item in body["items"] if item["is_active"]]
        assert len(active) == 1
        labels = {rule["label"] for rule in active[0]["rules"]}
        assert {"Trade size", "Trailing stop", "Entry", "Take profit"} <= labels
        # Exactly one strategy runs; the retired one says why it does not.
        operational = [item for item in body["items"] if item["operational"]]
        assert len(operational) == 1
        retired = [item for item in body["items"] if not item["operational"]]
        assert retired and all(item["unavailable_reason"] for item in retired)

    async def test_there_is_no_way_to_open_a_position_by_hand(
        self, client: AsyncClient
    ) -> None:
        """No manual intervention, asserted at the HTTP boundary: a button that
        opened a trade would make this a record of judgement, not of a rule."""
        for path in ("/api/v1/paper", "/api/v1/paper/positions", "/api/v1/paper/audit"):
            assert (await client.post(path, json={})).status_code == 405


class TestDisabled:
    async def test_a_switched_off_wallet_says_so_rather_than_looking_empty(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ "Not switched on here" and "this strategy traded nothing" are
        different facts, and only the second is a result."""
        monkeypatch.setattr(settings, "FEATURE_PAPER_WALLET_ENABLED", False)

        body = (await client.get("/api/v1/paper")).json()

        assert body["enabled"] is False
        assert body["metrics"]["closed_positions"] == 0
        assert body["strategy"]["id"] == "trailing_stop_25_v1"

    async def test_nothing_is_opened_while_the_flag_is_off(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.paper.scheduler import _paper_review

        monkeypatch.setattr(settings, "FEATURE_PAPER_WALLET_ENABLED", False)
        assert await _paper_review() == {"skipped": "wallet_disabled"}


class TestWalletCreation:
    async def test_the_starting_balance_is_pinned_at_creation(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Changing the setting later must not restate returns that were already
        published."""
        service = PaperWalletService(db_session)
        first = await service.wallet(now=NOW)
        await db_session.commit()

        monkeypatch.setattr(settings, "PAPER_WALLET_STARTING_BALANCE", 5000.0)
        again = await PaperWalletService(db_session).wallet(now=NOW + timedelta(hours=1))

        assert again.id == first.id
        assert again.starting_balance == Decimal(1000)
        # And the start instant is pinned too — every benchmark runs from it.
        assert again.started_at == first.started_at

    async def test_a_configuration_change_does_not_silently_relaunch(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Relaunching is an operation with a record, not a side effect of an
        environment variable."""
        service = PaperWalletService(db_session)
        first = await service.wallet(now=NOW)
        await db_session.commit()

        monkeypatch.setattr(settings, "PAPER_WALLET_STRATEGY_ID", "equal_weight_v1")
        again = await PaperWalletService(db_session).wallet(now=NOW + timedelta(hours=1))

        assert again.id == first.id
        assert again.strategy_id == "trailing_stop_25_v1"
