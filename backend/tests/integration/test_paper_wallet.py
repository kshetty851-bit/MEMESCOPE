"""The paper wallet end to end: entries, exits, and what the API refuses to say.

Sprint 25. The wallet is a deterministic simulation over stored market history —
no wallet is connected, no order is routed, no chain is touched. These tests
hold it to that: every trade must be explainable by the published rule, and no
figure may appear that the rows do not support.

The two constraints carrying product meaning are asserted directly, because
they are the difference between a track record and a demo:

  - a token is entered **once, ever**, which is the entry rule as a constraint;
  - the entry block is **never rewritten**, so a target cannot be recomputed
    favourably after the outcome is known.
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
from app.models.paper import PaperPosition
from app.models.radar import RadarToken
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
    monkeypatch.setattr(settings, "PAPER_WALLET_STRATEGY_ID", "equal_weight_v1")


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
        )
    )
    await session.flush()


async def _price(
    session: AsyncSession, token: object, mint: str, *, at: datetime, price: str
) -> None:
    await MarketSnapshotRepository(session).add_snapshot(
        {
            "token_id": token.id,  # type: ignore[attr-defined]
            "mint_address": mint,
            "captured_at": at,
            "price_usd": Decimal(price),
            "market_cap": Decimal("124000"),
            "liquidity_usd": Decimal("18000"),
            "volume_24h": Decimal("89000"),
            "dex_name": "pumpswap",
            "trading_status": TradingStatus.TRADING,
            "provider": "test",
        }
    )


async def _seed(session: AsyncSession, mint: str, *, score: int, price: str) -> object:
    token = await _token(session, mint)
    await _radar_entry(session, token, mint, score=score)
    await _price(session, token, mint, at=NOW, price=price)
    return token


MINT_A = "PaperWalletMintAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
MINT_B = "PaperWalletMintBBBBBBBBBBBBBBBBBBBBBBBBBBBB"


class TestEntries:
    async def test_a_top_ten_token_is_bought_at_the_published_size(
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
        # The exits are fixed at entry, from the published multiples.
        assert position.target_price == Decimal(20)
        assert position.stop_price == Decimal(5)

    async def test_a_token_is_entered_once_ever(self, db_session: AsyncSession) -> None:
        """The entry rule as a database constraint. "The first time it enters the
        top ten" is true because re-entry is a state the schema cannot hold."""
        await _seed(db_session, MINT_A, score=90, price="10")
        await db_session.commit()
        service = PaperWalletService(db_session)

        first = await service.review(now=NOW)
        await db_session.commit()
        second = await service.review(now=NOW + timedelta(minutes=5))
        await db_session.commit()

        assert first.opened == 1
        assert second.opened == 0
        assert second.skipped_held == 1
        assert len((await db_session.scalars(select(PaperPosition))).all()) == 1

    async def test_a_second_pass_is_a_no_op(self, db_session: AsyncSession) -> None:
        """Beat has no lock, so a run that outlives its interval overlaps. That
        must cost nothing."""
        await _seed(db_session, MINT_A, score=90, price="10")
        await db_session.commit()
        service = PaperWalletService(db_session)

        await service.review(now=NOW)
        await db_session.commit()
        before = (await db_session.scalars(select(PaperPosition))).one()
        opened_at, target = before.opened_at, before.target_price

        await service.review(now=NOW + timedelta(minutes=1))
        await db_session.commit()
        after = (await db_session.scalars(select(PaperPosition))).one()

        assert (after.opened_at, after.target_price) == (opened_at, target)

    async def test_an_unpriced_token_is_not_bought(self, db_session: AsyncSession) -> None:
        """Unpriced is not free. Sizing against a price nobody observed would be
        the estimate this platform refuses to make."""
        token = await _token(db_session, MINT_A)
        await _radar_entry(db_session, token, MINT_A, score=90)
        await db_session.commit()

        outcome = await PaperWalletService(db_session).review(now=NOW)
        await db_session.commit()

        assert outcome.opened == 0

    async def test_the_wallet_can_run_out_of_money(self, db_session: AsyncSession) -> None:
        """Declining is the published behaviour. A wallet that quietly halved
        its size would report a return the rule did not produce."""
        for index in range(12):
            await _seed(
                db_session,
                f"PaperFund{index:034d}",
                score=90 - index,
                price="10",
            )
        await db_session.commit()

        outcome = await PaperWalletService(db_session).review(now=NOW)
        await db_session.commit()

        # $1000 at $100 each, over a top-10 cut.
        assert outcome.opened == 10

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


class TestExits:
    async def _open_one(self, db_session: AsyncSession, *, price: str = "10") -> object:
        token = await _seed(db_session, MINT_A, score=90, price=price)
        await db_session.commit()
        await PaperWalletService(db_session).review(now=NOW)
        await db_session.commit()
        return token

    async def test_the_target_closes_the_position(self, db_session: AsyncSession) -> None:
        token = await self._open_one(db_session)
        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=1), price="25")
        await db_session.commit()

        outcome = await PaperWalletService(db_session).review(now=NOW + timedelta(hours=2))
        await db_session.commit()

        position = (await db_session.scalars(select(PaperPosition))).one()
        assert outcome.closed == 1
        assert position.status == "closed"
        assert position.exit_reason == "target"
        # Closed at the published target, not at the overshoot the snapshot saw.
        assert position.exit_price == Decimal(20)

    async def test_a_spike_through_the_stop_still_stops_out(
        self, db_session: AsyncSession
    ) -> None:
        """The failure this design exists to prevent. A position that breached
        its stop and recovered before anyone evaluated it is still a loss."""
        token = await self._open_one(db_session)
        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=1), price="2")
        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=2), price="11")
        await db_session.commit()

        await PaperWalletService(db_session).review(now=NOW + timedelta(hours=3))
        await db_session.commit()

        position = (await db_session.scalars(select(PaperPosition))).one()
        assert position.exit_reason == "stop"
        assert position.exit_price == Decimal(5)

    async def test_the_close_is_dated_to_the_observation_not_the_evaluation(
        self, db_session: AsyncSession
    ) -> None:
        """A worker that ran a day late must record the close when it happened."""
        token = await self._open_one(db_session)
        breach = NOW + timedelta(hours=1)
        await _price(db_session, token, MINT_A, at=breach, price="25")
        await db_session.commit()

        await PaperWalletService(db_session).review(now=NOW + timedelta(days=1))
        await db_session.commit()

        position = (await db_session.scalars(select(PaperPosition))).one()
        assert position.closed_at == breach

    async def test_expiry_closes_at_the_first_reading_past_the_deadline(
        self, db_session: AsyncSession
    ) -> None:
        token = await self._open_one(db_session)
        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=49), price="12")
        await db_session.commit()

        await PaperWalletService(db_session).review(now=NOW + timedelta(hours=50))
        await db_session.commit()

        position = (await db_session.scalars(select(PaperPosition))).one()
        assert position.exit_reason == "expiry"
        assert position.exit_price == Decimal(12)

    async def test_a_closed_position_is_never_reopened_or_rewritten(
        self, db_session: AsyncSession
    ) -> None:
        """A closed trade is part of the permanent record."""
        token = await self._open_one(db_session)
        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=1), price="25")
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
        """The anti-hindsight guarantee. A target that could move after the
        outcome is known could move favourably."""
        token = await self._open_one(db_session)
        before = (await db_session.scalars(select(PaperPosition))).one()
        entry = (before.entry_price, before.target_price, before.stop_price, before.opened_at)

        await _price(db_session, token, MINT_A, at=NOW + timedelta(hours=1), price="14")
        await db_session.commit()
        await PaperWalletService(db_session).review(now=NOW + timedelta(hours=2))
        await db_session.commit()

        after = (await db_session.scalars(select(PaperPosition))).one()
        assert (
            after.entry_price,
            after.target_price,
            after.stop_price,
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

        for hour, price in ((1, "12"), (2, "4"), (3, "30")):
            await _price(
                db_session, token, MINT_A, at=NOW + timedelta(hours=hour), price=price
            )
        await db_session.commit()

        # One late pass over the whole history.
        await service.review(now=NOW + timedelta(hours=9))
        await db_session.commit()
        late = (await db_session.scalars(select(PaperPosition))).one()

        assert late.exit_reason == "stop"
        assert late.exit_price == Decimal(5)
        assert late.closed_at == NOW + timedelta(hours=2)
        # The peak stops at the exit: the 30 printed afterwards is the token's,
        # not the trade's.
        assert late.peak_price == Decimal(12)


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
        assert body["metrics"]["open_positions"] == 1
        assert "no order is placed" in body["disclosure"].lower()
        assert body["strategy"]["is_active"] is True

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

    async def test_holding_sol_is_unavailable_with_its_reason(
        self, client: AsyncClient
    ) -> None:
        """The platform stores no SOL series, so the comparison would be
        fabricated. It says so rather than showing a number."""
        body = (await client.get("/api/v1/paper")).json()
        sol = [item for item in body["benchmarks"] if item["id"] == "hold_sol"]

        assert sol and sol[0]["return_pct"] is None
        assert "fabricated" in sol[0]["unavailable_reason"]

    async def test_the_two_named_equal_weight_benchmarks_are_reported_once(
        self, client: AsyncClient
    ) -> None:
        """ "Buy every Radar token" and "equal-weight Radar" are the same
        measurement here. One number under two labels is duplication."""
        body = (await client.get("/api/v1/paper")).json()
        ids = [item["id"] for item in body["benchmarks"]]

        assert ids.count("equal_weight_radar") == 1
        assert len(ids) == len(set(ids))

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
            "stop_price",
            "target_price",
            "status",
            "symbol",
        ):
            assert field in row
        assert row["status"] == "open"
        assert row["exit_reason"] is None

    async def test_the_strategies_endpoint_publishes_the_rules(
        self, client: AsyncClient
    ) -> None:
        body = (await client.get("/api/v1/paper/strategies")).json()

        assert body["active_id"] == "equal_weight_v1"
        active = [item for item in body["items"] if item["is_active"]]
        assert len(active) == 1
        labels = {rule["label"] for rule in active[0]["rules"]}
        assert {"Trade size", "Take profit", "Stop loss", "Entry"} <= labels
        # The declared-but-idle ones are published, each with its reason.
        idle = [item for item in body["items"] if not item["operational"]]
        assert idle and all(item["unavailable_reason"] for item in idle)

    async def test_there_is_no_way_to_open_a_position_by_hand(
        self, client: AsyncClient
    ) -> None:
        """No manual intervention, asserted at the HTTP boundary: a button that
        opened a trade would make this a record of judgement, not of a rule."""
        for path in ("/api/v1/paper", "/api/v1/paper/positions"):
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
        assert body["strategy"]["id"] == "equal_weight_v1"

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
        first = await service.wallet()
        await db_session.commit()

        monkeypatch.setattr(settings, "PAPER_WALLET_STARTING_BALANCE", 5000.0)
        again = await PaperWalletService(db_session).wallet()

        assert again.id == first.id
        assert again.starting_balance == Decimal(1000)

    async def test_one_wallet_per_strategy(self, db_session: AsyncSession) -> None:
        repository = PaperRepository(db_session)
        first = await repository.ensure_wallet(
            strategy_id="equal_weight_v1",
            strategy_version="1.0.0",
            starting_balance=Decimal(1000),
        )
        second = await repository.ensure_wallet(
            strategy_id="equal_weight_v1",
            strategy_version="1.0.0",
            starting_balance=Decimal(1000),
        )
        assert first.id == second.id
