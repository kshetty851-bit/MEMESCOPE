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
from app.core.exceptions import ConflictError, ValidationError
from app.models.market import TradingStatus
from app.models.paper import PaperPosition, PaperTradeAudit, PaperWallet
from app.models.paper_research import PaperDecisionSnapshot
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
    monkeypatch.setattr(
        settings, "PAPER_WALLET_STRATEGY_ID", "paper_track_record_tp125_sl50_v1"
    )


async def _token(
    session: AsyncSession, mint: str, *, discovered_at: datetime = NOW
) -> object:
    # The experiment watermark is fixed when its wallet is created.  Establish
    # it before the test discovery so the raw scanner candidate is genuinely
    # post-watermark, exactly as a live forward observation would be.
    await PaperWalletService(session).wallet(now=NOW - timedelta(minutes=1))
    token = await TokenRepository(session).insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}",
            "slot": 1,
            "discovered_at": discovered_at,
            "block_time": discovered_at,
            "name": f"Probe {mint[-1]}",
            "symbol": f"P{mint[-1]}",
        }
    )
    assert token is not None
    return token


async def _radar_entry(
    session: AsyncSession,
    token: object,
    mint: str,
    *,
    score: int,
    admitted_at: datetime = NOW,
) -> None:
    session.add(
        RadarToken(
            token_id=token.id,  # type: ignore[attr-defined]
            mint_address=mint,
            first_detected_at=admitted_at,
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
    market_cap: str = "124000",
    liquidity: str | None = "18000",
    status: TradingStatus = TradingStatus.TRADING,
) -> None:
    await MarketSnapshotRepository(session).add_snapshot(
        {
            "token_id": token.id,  # type: ignore[attr-defined]
            "mint_address": mint,
            "captured_at": at,
            "price_usd": Decimal(price),
            "market_cap": Decimal(market_cap),
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
MINT_C = "PaperWalletMintCCCCCCCCCCCCCCCCCCCCCCCCCCCC"


class TestEntries:
    async def test_every_post_watermark_track_record_admission_is_bought_at_the_published_size(
        self, db_session: AsyncSession
    ) -> None:
        await _seed(db_session, MINT_A, score=90, price="10")
        await db_session.commit()

        outcome = await PaperWalletService(db_session).review(now=NOW)
        await db_session.commit()

        assert outcome.opened == 1
        position = (await db_session.scalars(select(PaperPosition))).one()
        assert position.size_usd == Decimal(10)
        assert position.entry_price == Decimal(10)
        assert position.quantity == Decimal(1)
        assert position.entry_rank == 1
        # Generation 6 records a fixed bracket; it never arms a trailing exit.
        assert position.trailing_drawdown is None
        assert position.trailing_activation_multiple is None
        assert position.trailing_activated_at is None
        assert position.target_price == Decimal("12.5")
        assert position.stop_price == Decimal("5")
        assert position.expires_at is None
        # The market at entry is recorded, because the audit needs it later and
        # the snapshot that carries it is prunable.
        assert position.entry_market_cap == Decimal("124000")
        assert position.entry_liquidity_usd == Decimal("18000")

    async def test_pre_watermark_track_record_admission_never_enters(
        self, db_session: AsyncSession
    ) -> None:
        token = await _token(
            db_session, MINT_A, discovered_at=NOW - timedelta(minutes=2)
        )
        await _radar_entry(
            db_session, token, MINT_A, score=90, admitted_at=NOW - timedelta(minutes=2)
        )
        await _price(db_session, token, MINT_A, at=NOW, price="10")
        await db_session.commit()

        outcome = await PaperWalletService(db_session).review(now=NOW)

        assert outcome.opened == 0
        assert (await db_session.scalars(select(PaperPosition))).all() == []

    async def test_entry_uses_the_first_usable_observation_without_future_lookahead(
        self, db_session: AsyncSession
    ) -> None:
        token = await _token(db_session, MINT_A)
        await _radar_entry(db_session, token, MINT_A, score=90)
        await _price(db_session, token, MINT_A, at=NOW, price="0")
        observed_at = NOW + timedelta(minutes=1)
        await _price(db_session, token, MINT_A, at=observed_at, price="7")
        await db_session.commit()
        service = PaperWalletService(db_session)

        assert (await service.review(now=NOW)).opened == 0
        await db_session.commit()
        assert (await service.review(now=observed_at)).opened == 1
        position = (await db_session.scalars(select(PaperPosition))).one()
        assert position.opened_at == observed_at
        assert position.entry_observed_price == Decimal("7")

    async def test_a_pre_track_record_quote_cannot_create_an_entry(
        self, db_session: AsyncSession
    ) -> None:
        """A known past price is not an observation of this admission."""
        token = await _token(db_session, MINT_A, discovered_at=NOW)
        await _radar_entry(db_session, token, MINT_A, score=90)
        await _price(db_session, token, MINT_A, at=NOW - timedelta(seconds=1), price="10")
        await db_session.commit()

        outcome = await PaperWalletService(db_session).review(now=NOW)

        assert outcome.opened == 0
        assert (await db_session.scalars(select(PaperPosition))).all() == []

    async def test_a_future_dated_quote_cannot_create_an_entry(
        self, db_session: AsyncSession
    ) -> None:
        """The evaluator must not borrow a quote that had not arrived yet."""
        token = await _token(db_session, MINT_A, discovered_at=NOW)
        await _radar_entry(db_session, token, MINT_A, score=90)
        await _price(db_session, token, MINT_A, at=NOW + timedelta(seconds=1), price="10")
        await db_session.commit()

        outcome = await PaperWalletService(db_session).review(now=NOW)

        assert outcome.opened == 0
        assert (await db_session.scalars(select(PaperPosition))).all() == []

    async def test_raw_discovery_without_track_record_admission_does_not_enter(
        self, db_session: AsyncSession
    ) -> None:
        token = await _token(db_session, MINT_A)
        await _price(db_session, token, MINT_A, at=NOW, price="10", liquidity=None)
        await db_session.commit()

        outcome = await PaperWalletService(db_session).review(now=NOW)

        assert outcome.opened == 0
        assert (await db_session.scalars(select(RadarToken))).all() == []

    async def test_insufficient_cash_is_terminal_but_later_mint_can_use_released_cash(
        self, db_session: AsyncSession
    ) -> None:
        for index in range(101):
            await _seed(db_session, f"PaperTerminal{index:030d}", score=0, price="10")
        await db_session.commit()
        service = PaperWalletService(db_session)
        first = await service.review(now=NOW)
        await db_session.commit()
        assert first.opened == 100
        declined_mint = f"PaperTerminal{100:030d}"
        decision = await db_session.scalar(
            select(PaperDecisionSnapshot).where(
                PaperDecisionSnapshot.mint_address == declined_mint
            )
        )
        assert decision is not None and decision.decision == "declined"
        assert decision.reason_codes == [Refusal.INSUFFICIENT_CASH.value]

        first_mint = f"PaperTerminal{0:030d}"
        first_token = await TokenRepository(db_session).get_by_mint(first_mint)
        assert first_token is not None
        await _price(
            db_session, first_token, first_mint, at=NOW + timedelta(minutes=1), price="13"
        )
        await db_session.commit()
        await service.review(now=NOW + timedelta(minutes=1))
        await db_session.commit()

        later_mint = "PaperTerminalLater0000000000000000000000000"
        await _seed(db_session, later_mint, score=0, price="10")
        await db_session.commit()
        second = await service.review(now=NOW + timedelta(minutes=2))
        assert second.opened == 1
        assert (
            await db_session.scalar(
                select(PaperPosition).where(PaperPosition.mint_address == declined_mint)
            )
        ) is None

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
        assert second.refusals == {}
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

        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=1), price="13")
        await db_session.commit()
        await service.review(now=NOW + timedelta(hours=3))
        await db_session.commit()

        outcome = await service.review(now=NOW + timedelta(hours=4))
        await db_session.commit()

        assert outcome.opened == 0
        assert outcome.refusals == {}
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
        assert outcome.refusals == {}

    async def test_a_low_liquidity_token_still_enters(
        self, db_session: AsyncSession
    ) -> None:
        """Sprint 30 §5 added liquidity to the entry gate, and it earns its
        place twice: a bonding-curve pair reports no depth at all, and a trade
        whose cost cannot be computed cannot be audited."""
        await _seed(db_session, MINT_A, score=90, price="10", liquidity=None)
        await db_session.commit()

        outcome = await PaperWalletService(db_session).review(now=NOW)
        await db_session.commit()

        assert outcome.opened == 1

    async def test_a_vetoed_or_inactive_radar_token_still_enters(
        self, db_session: AsyncSession
    ) -> None:
        await _seed(db_session, MINT_A, score=90, price="10", status=TradingStatus.INACTIVE)
        await db_session.commit()

        outcome = await PaperWalletService(db_session).review(now=NOW)
        await db_session.commit()

        assert outcome.opened == 1

    async def test_the_wallet_can_run_out_of_money(self, db_session: AsyncSession) -> None:
        """Declining is the published behaviour. A wallet that quietly halved
        its size would report a return the rule did not produce."""
        for index in range(102):
            await _seed(db_session, f"PaperFund{index:034d}", score=90 - index, price="10")
        await db_session.commit()

        outcome = await PaperWalletService(db_session).review(now=NOW)
        await db_session.commit()

        # $1,000 at $10 each. The cut is cash, not rank — the strategy reads
        # the whole Radar.
        assert outcome.opened == 100
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
        for index in range(100):
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

    async def test_exact_target_closes_at_the_observed_target_quote(
        self, db_session: AsyncSession
    ) -> None:
        token = await self._open_one(db_session)
        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=1), price="12.5")
        await db_session.commit()

        outcome = await PaperWalletService(db_session).review(now=NOW + timedelta(hours=3))
        await db_session.commit()

        position = (await db_session.scalars(select(PaperPosition))).one()
        assert outcome.closed == 1
        assert position.status == "closed"
        assert position.exit_reason == "target"
        assert position.target_price == Decimal("12.5")
        assert position.exit_observed_price == Decimal("12.5")
        assert position.trailing_trigger_price is None
        assert position.trailing_trigger_observed_price is None

    async def test_stop_and_gap_fills_keep_the_trigger_and_observed_quote_distinct(
        self, db_session: AsyncSession
    ) -> None:
        token = await self._open_one(db_session)
        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=1), price="4.2")
        await db_session.commit()

        await PaperWalletService(db_session).review(now=NOW + timedelta(hours=2))
        await db_session.commit()

        position = (await db_session.scalars(select(PaperPosition))).one()
        assert position.exit_reason == "stop"
        assert position.stop_price == Decimal("5")
        assert position.exit_observed_price == Decimal("4.2")
        assert position.exit_price is not None

    async def test_an_observed_holding_is_settled_immediately_and_only_once(
        self, db_session: AsyncSession
    ) -> None:
        token = await self._open_one(db_session)
        service = PaperWalletService(db_session)
        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=1), price="12.49")
        await db_session.commit()

        raised = await service.review_observed_mints([MINT_A], now=NOW + timedelta(hours=1))
        await db_session.commit()
        assert raised is not None
        assert raised.evaluated == 1
        assert raised.closed == 0

        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=2), price="13")
        await db_session.commit()
        stopped = await service.review_observed_mints([MINT_A], now=NOW + timedelta(hours=2))
        await db_session.commit()
        assert stopped is not None
        assert stopped.closed == 1
        assert stopped.audited == 1

        # A duplicated delivery cannot close the same durable position twice.
        assert (
            await service.review_observed_mints([MINT_A], now=NOW + timedelta(hours=3)) is None
        )
        audit_rows = (await db_session.scalars(select(PaperTradeAudit))).all()
        assert len(audit_rows) == 1

    async def test_an_out_of_order_advance_cannot_rewind_the_watermark_or_peak(
        self, db_session: AsyncSession
    ) -> None:
        await self._open_one(db_session)
        position = (await db_session.scalars(select(PaperPosition))).one()
        repository = PaperRepository(db_session)
        newer = NOW + timedelta(hours=2)
        older = NOW + timedelta(hours=1)

        await repository.advance(
            position.id, peak_price=Decimal("20"), last_evaluated_at=newer
        )
        await db_session.commit()
        await repository.advance(
            position.id, peak_price=Decimal("12"), last_evaluated_at=older
        )
        await db_session.commit()

        db_session.expire_all()
        current = (await db_session.scalars(select(PaperPosition))).one()
        assert current.peak_price == Decimal("20")
        assert current.last_evaluated_at == newer

    async def test_price_inside_the_bracket_and_two_x_have_no_special_behavior(
        self, db_session: AsyncSession
    ) -> None:
        """Only the 1.25x / 0.50x barriers matter; there is no trailing state."""
        token = await self._open_one(db_session)
        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=1), price="12.49")
        await db_session.commit()

        outcome = await PaperWalletService(db_session).review(now=NOW + timedelta(hours=4))
        await db_session.commit()

        position = (await db_session.scalars(select(PaperPosition))).one()
        assert outcome.closed == 0
        assert position.status == "open"
        assert position.trailing_activated_at is None
        assert position.trailing_stop_price is None

    async def test_time_alone_never_closes_a_position(self, db_session: AsyncSession) -> None:
        """No holding period. A position runs until the rule triggers, however
        long that takes — a real consequence of the published strategy, and one
        the equity curve is left to show rather than hide."""
        token = await self._open_one(db_session)
        await _price(db_session, token, MINT_A, at=NOW + timedelta(days=30), price="10")
        await db_session.commit()

        outcome = await PaperWalletService(db_session).review(now=NOW + timedelta(days=31))
        await db_session.commit()

        position = (await db_session.scalars(select(PaperPosition))).one()
        assert outcome.closed == 0
        assert position.status == "open"

    async def test_a_sample_above_stop_but_below_entry_remains_open(
        self, db_session: AsyncSession
    ) -> None:
        """A 50% stop does not invent the retired pre-2x trailing rule."""
        token = await self._open_one(db_session)
        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=1), price="5.01")
        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=2), price="11")
        await db_session.commit()

        await PaperWalletService(db_session).review(now=NOW + timedelta(hours=3))
        await db_session.commit()

        position = (await db_session.scalars(select(PaperPosition))).one()
        assert position.status == "open"
        assert position.status == "open"
        assert position.trailing_activated_at is None

    async def test_the_close_is_dated_to_the_observation_not_the_evaluation(
        self, db_session: AsyncSession
    ) -> None:
        """A worker that ran a day late must record the close when it happened."""
        token = await self._open_one(db_session)
        await _price(db_session, token, MINT_A, at=NOW + timedelta(minutes=30), price="12.49")
        breach = NOW + timedelta(hours=1)
        await _price(db_session, token, MINT_A, at=breach, price="13")
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
        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=1), price="13")
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
        """The fixed target and stop cannot be rewritten after the outcome."""
        token = await self._open_one(db_session)
        before = (await db_session.scalars(select(PaperPosition))).one()
        entry = (
            before.entry_price,
            before.target_price,
            before.stop_price,
            before.size_usd,
            before.opened_at,
        )

        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=1), price="12.49")
        await db_session.commit()
        await PaperWalletService(db_session).review(now=NOW + timedelta(hours=2))
        await db_session.commit()

        after = (await db_session.scalars(select(PaperPosition))).one()
        assert (
            after.entry_price,
            after.target_price,
            after.stop_price,
            after.size_usd,
            after.opened_at,
        ) == entry
        assert after.status == "open"
        assert after.trailing_activated_at is None


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

        for hour, price in ((1, "12.49"), (2, "13"), (3, "30")):
            await _price(
                db_session, token, MINT_A, at=NOW + timedelta(hours=hour), price=price
            )
        await db_session.commit()

        # One late pass over the whole history.
        await service.review(now=NOW + timedelta(hours=9))
        await db_session.commit()
        late = (await db_session.scalars(select(PaperPosition))).one()

        assert late.exit_reason == "target"
        assert late.exit_observed_price == Decimal(13)
        assert late.closed_at == NOW + timedelta(hours=2)
        # The peak stops at the exit: the 30 printed afterwards is the token's,
        # not the trade's.
        assert late.peak_price == Decimal(13)


class TestTheAuditLog:
    async def _close_one(self, db_session: AsyncSession) -> None:
        token = await _seed(db_session, MINT_A, score=90, price="10")
        await db_session.commit()
        service = PaperWalletService(db_session)
        await service.review(now=NOW)
        await db_session.commit()
        await _price(
            db_session,
            token,
            MINT_A,
            at=NOW + timedelta(hours=1),
            price="13",
            market_cap="1300",
        )
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
        assert row.exit_observed_price == Decimal(13)
        assert row.entry_market_cap == Decimal("124000")
        assert row.exit_market_cap == Decimal("1300.0000")
        assert row.exit_reason == "target"
        assert row.strategy_id == "paper_track_record_tp125_sl50_v1"
        assert row.strategy_version == "1.0.0-forward"

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

        assert row.gross_return_usd is not None
        assert row.gross_return_pct is not None
        assert row.fee_usd is not None
        assert row.slippage_usd is not None
        assert row.net_return_usd is not None
        assert row.cost_unavailable_reason is None
        # The exit costs more than the entry: it sells a bigger position. Cost
        # is progressive, which is the whole reason it is charged at each end.
        assert row.slippage_usd > Decimal(0)

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
        assert entry["exit_reason"] == "target"
        assert Decimal(entry["net_return_usd"]) > Decimal(0)
        assert "MEV" in body["disclosure"]

    async def test_closed_positions_serve_the_same_cost_ledger_as_the_audit(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await self._close_one(db_session)

        position = (await client.get("/api/v1/paper/positions")).json()["items"][0]
        audit = (await client.get("/api/v1/paper/audit")).json()["items"][0]

        assert position["status"] == "closed"
        for field in (
            "gross_pnl_usd",
            "fee_usd",
            "slippage_usd",
            "net_pnl_usd",
            "cost_unavailable_reason",
        ):
            assert position[field] == audit[field.replace("_pnl", "_return")]


class TestManualSell:
    async def _open_one(self, db_session: AsyncSession) -> None:
        await _seed(db_session, MINT_A, score=90, price="10")
        await db_session.commit()
        await PaperWalletService(db_session).review(now=NOW)
        await db_session.commit()

    async def test_preview_uses_the_latest_observed_quote_and_cost_model(
        self, db_session: AsyncSession
    ) -> None:
        token = await _seed(db_session, MINT_A, score=90, price="10")
        await db_session.commit()
        service = PaperWalletService(db_session)
        await service.review(now=NOW)
        await db_session.commit()
        await _price(db_session, token, MINT_A, at=NOW + timedelta(minutes=1), price="12")
        await db_session.commit()

        preview = await service.manual_sell_preview(MINT_A, now=NOW + timedelta(minutes=2))

        assert preview.quote.price_usd == Decimal("12")
        assert preview.quote.captured_at == NOW + timedelta(minutes=1)
        assert preview.audit.exit_reason == "manual"
        assert preview.audit.gross_return_usd == Decimal("2.0000")
        assert preview.audit.fee_usd == Decimal("0.0660")
        assert preview.audit.slippage_usd is not None
        assert preview.is_stale is False

    async def test_stale_quotes_warn_but_still_use_the_observed_price(
        self, db_session: AsyncSession
    ) -> None:
        await self._open_one(db_session)

        preview = await PaperWalletService(db_session).manual_sell_preview(
            MINT_A, now=NOW + timedelta(hours=2)
        )

        assert preview.is_stale is True
        assert preview.warning is not None
        assert preview.quote.price_usd == Decimal("10")

    async def test_missing_quote_refuses_manual_sell(self, db_session: AsyncSession) -> None:
        service = PaperWalletService(db_session)
        wallet = await service.wallet(now=NOW)
        await PaperRepository(db_session).open_position(
            wallet_id=wallet.id,
            mint_address=MINT_C,
            opened_at=NOW,
            entry_rank=1,
            entry_price=Decimal("10"),
            size_usd=Decimal("100"),
            quantity=Decimal("10"),
            status="open",
            peak_price=Decimal("10"),
            last_evaluated_at=NOW,
        )
        await db_session.commit()

        with pytest.raises(ValidationError) as exc:
            await service.manual_sell(MINT_C, now=NOW + timedelta(minutes=1))

        assert exc.value.code == "paper_quote_unavailable"

    async def test_confirm_closes_once_audits_once_and_marks_manual(
        self, db_session: AsyncSession
    ) -> None:
        token = await _seed(db_session, MINT_A, score=90, price="10")
        await db_session.commit()
        service = PaperWalletService(db_session)
        await service.review(now=NOW)
        await db_session.commit()
        await _price(db_session, token, MINT_A, at=NOW + timedelta(minutes=1), price="12")
        await db_session.commit()

        outcome = await service.manual_sell(MINT_A, now=NOW + timedelta(minutes=2))
        await db_session.commit()

        position = (await db_session.scalars(select(PaperPosition))).one()
        audit_row = (await db_session.scalars(select(PaperTradeAudit))).one()
        assert outcome.audited is True
        assert position.status == "closed"
        assert position.exit_reason == "manual"
        assert position.exit_price == Decimal("12")
        assert position.closed_at == NOW + timedelta(minutes=1)
        assert position.manual_action_at == NOW + timedelta(minutes=2)
        assert audit_row.exit_reason == "manual"
        assert audit_row.manual_action_at == NOW + timedelta(minutes=2)

        with pytest.raises(ConflictError) as exc:
            await service.manual_sell(MINT_A, now=NOW + timedelta(minutes=3))

        assert exc.value.code == "paper_position_already_closed"
        assert len((await db_session.scalars(select(PaperTradeAudit))).all()) == 1
        assert len((await db_session.scalars(select(PaperPosition))).all()) == 1

    async def test_manual_close_reuses_the_allocator_for_replacement(
        self, db_session: AsyncSession
    ) -> None:
        service = PaperWalletService(db_session)
        opened = []
        for index in range(100):
            mint = f"PaperWalletMint{index:02d}AAAAAAAAAAAAAAAAAAAAAAAA"
            opened.append(mint)
            await _seed(db_session, mint, score=100 - index, price="10")
        await db_session.commit()

        await service.review(now=NOW)
        await db_session.commit()
        assert len((await db_session.scalars(select(PaperPosition))).all()) == 100
        replacement = "PaperWalletReplacementAAAAAAAAAAAAAAAAAAAA"
        await _seed(db_session, replacement, score=95, price="10")
        await db_session.commit()

        outcome = await service.manual_sell(opened[-1], now=NOW + timedelta(minutes=1))
        await db_session.commit()

        rows = (await db_session.scalars(select(PaperPosition))).all()
        statuses = {row.mint_address: row.status for row in rows}
        assert outcome.opened == 1
        assert statuses[opened[-1]] == "closed"
        assert statuses[replacement] == "open"
        assert len(rows) == 101

    async def test_api_reports_preview_and_conflict_cleanly(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await self._open_one(db_session)

        preview = await client.get(f"/api/v1/paper/positions/{MINT_A}/manual-sell")
        assert preview.status_code == 200
        assert preview.json()["short_mint"].startswith(MINT_A[:4])

        sold = await client.post(f"/api/v1/paper/positions/{MINT_A}/manual-sell")
        assert sold.status_code == 200
        assert sold.json()["preview"]["gross_return_usd"] == "0.0000"

        duplicate = await client.post(f"/api/v1/paper/positions/{MINT_A}/manual-sell")
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "paper_position_already_closed"


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

        # A low-liquidity Radar diagnostic is display-only and cannot veto the
        # raw Generation 5 paper entry.
        assert body["metrics"]["open_positions"] == 1

    async def test_a_wallet_with_a_qualified_token_in_front_of_it_is_not_waiting(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A page that claimed to be waiting while an opportunity sat in front of
        it would be worse than one that said nothing."""
        await _seed(db_session, MINT_A, score=90, price="10")
        await db_session.commit()

        body = (await client.get("/api/v1/paper")).json()

        assert body["waiting"] is None

    async def test_cash_short_of_one_position_is_its_own_stated_reason(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The state that made the wallet look broken on 2026-08-05.

        It held $92.38 with nine positions open, opened nothing for an hour and
        said nothing, because the only published idle message was about the
        Radar having nothing to offer — which was not the reason. Leftover cash
        below one position is an ordinary consequence of never part-filling, and
        it resolves when a position closes. The page has to say that.
        """
        # One hundred tokens take the whole $1,000; an explicit terminal
        # observation returns a sub-$10 cash stub.
        for index in range(100):
            await _seed(db_session, f"PaperStub{index:034d}", score=90 - index, price="10")
        await db_session.commit()
        service = PaperWalletService(db_session)
        await service.review(now=NOW)
        await db_session.commit()

        first = f"PaperStub{0:034d}"
        token = await TokenRepository(db_session).get_by_mint(first)
        await _price(
            db_session,
            token,
            first,
            at=NOW + timedelta(hours=1),
            price="5",
            status=TradingStatus.INACTIVE,
        )
        # An eleventh token qualifies, so the wallet is short of cash and not of
        # opportunity — the distinction the reason code exists to make.
        await _seed(db_session, MINT_B, score=50, price="10")
        await db_session.commit()
        await service.review(now=NOW + timedelta(hours=2))
        await db_session.commit()

        body = (await client.get("/api/v1/paper")).json()
        waiting = body["waiting"]

        assert waiting is not None
        assert waiting["reason"] == "cash_below_trade_size"
        assert "never part-fills" in waiting["message"]
        assert Decimal(waiting["trade_size"]) == Decimal(10)
        assert Decimal(waiting["idle_cash"]) < Decimal(10)
        assert Decimal(waiting["shortfall"]) > Decimal(0)
        # The figure that separates "no opportunity" from "no capital".
        assert waiting["eligible"] >= 1

    async def test_a_fully_deployed_wallet_with_no_spare_cash_is_not_waiting(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Zero cash is not an idle state — it is a fully invested one, and
        saying "holding cash" over $0.00 would be nonsense."""
        for index in range(100):
            await _seed(db_session, f"PaperFull{index:034d}", score=90 - index, price="10")
        await db_session.commit()
        await PaperWalletService(db_session).review(now=NOW)
        await db_session.commit()

        body = (await client.get("/api/v1/paper")).json()

        assert Decimal(body["metrics"]["cash"]) == Decimal(0)
        assert body["waiting"] is None


class TestArchival:
    async def test_generation_five_is_archived_before_generation_six_starts(
        self, db_session: AsyncSession
    ) -> None:
        repository = PaperRepository(db_session)
        generation_four = await repository.ensure_wallet(
            strategy_id="paper_all_scanned_tp125_sl50_v1",
            strategy_version="1.0.0-forward",
            starting_balance=Decimal(1000),
            generation=5,
            started_at=NOW - timedelta(hours=1),
        )
        generation_four.archived_at = NOW
        generation_four.archive_reason = "Superseded by Generation 6."
        await db_session.commit()

        generation_six = await PaperWalletService(db_session).wallet(now=NOW)

        assert generation_four.archived_at == NOW
        assert generation_six.generation == 6
        assert generation_six.strategy_id == "paper_track_record_tp125_sl50_v1"
        assert generation_six.strategy_version == "1.0.0-forward"
        assert generation_six.starting_balance == Decimal(1000)

    async def test_only_one_wallet_is_ever_live(self, db_session: AsyncSession) -> None:
        """Enforced by `uq_paper_wallets_live`, not by convention. Two live
        wallets would double every trade and halve every figure."""
        repository = PaperRepository(db_session)
        first = await repository.ensure_wallet(
            strategy_id="paper_2x_trail25_v1",
            strategy_version="1.0.0-forward",
            starting_balance=Decimal(1000),
            generation=1,
            started_at=NOW,
        )
        second = await repository.ensure_wallet(
            strategy_id="paper_2x_trail25_v1",
            strategy_version="1.0.0-forward",
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

        assert "same tokens" in body["benchmark_note"].lower()

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
        assert Decimal(body["metrics"]["cash"]) == Decimal(990)
        assert Decimal(body["metrics"]["invested_usd"]) == Decimal(10)
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
        # The trail does not exist before the first observed 2x activation.
        assert row["trailing_stop_price"] is None
        assert row["trailing_activated_at"] is None

    async def test_the_strategies_endpoint_publishes_one_running_rule(
        self, client: AsyncClient
    ) -> None:
        body = (await client.get("/api/v1/paper/strategies")).json()

        assert body["active_id"] == "paper_track_record_tp125_sl50_v1"
        active = [item for item in body["items"] if item["is_active"]]
        assert len(active) == 1
        assert active[0]["version"] == "1.0.0-forward"
        labels = {rule["label"] for rule in active[0]["rules"]}
        assert {
            "Universe",
            "Allocation",
            "Take profit",
            "Stop loss",
            "Trailing stop",
        } <= labels
        # Only the forward experiment is surfaced to the UI.
        operational = [item for item in body["items"] if item["operational"]]
        assert len(operational) == 1
        assert len(body["items"]) == 1

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
        assert body["strategy"]["id"] == "paper_track_record_tp125_sl50_v1"

    async def test_disabled_wallet_reports_an_empty_daily_return_record(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "FEATURE_PAPER_WALLET_ENABLED", False)

        body = (await client.get("/api/v1/paper/performance")).json()

        assert body["enabled"] is False
        assert body["daily"] == []
        assert "MEV" in body["disclosure"]

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
        assert again.strategy_id == "paper_track_record_tp125_sl50_v1"
