"""Strategy Lab V2 over a real database.

The integration contract is now Generation 2 only. The lab loads the live
`trailing_stop_25_v1` paper wallet, replays alternate exits from market
snapshots, and keeps Generation 1 out of optimisation evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import TradingStatus
from app.models.paper import PaperPosition, PaperTradeAudit, PaperWallet
from app.models.radar import RadarToken
from app.paper import costs, lab
from app.paper.lab_service import load_dataset, replay_all
from app.repositories.market import MarketSnapshotRepository
from app.repositories.token import TokenRepository

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC).replace(microsecond=0)
START = NOW - timedelta(days=5)
WINNER = "LabV2Winner111111111111111111111111111111"
LOSER = "LabV2Loser2222222222222222222222222222222"
RUNNER = "LabV2Runner333333333333333333333333333333"
ARCHIVED = "LabV1Archived444444444444444444444444444"


async def _wallet(session: AsyncSession) -> PaperWallet:
    wallet = PaperWallet(
        strategy_id=lab.STRATEGY_ID,
        strategy_version="1.0.0",
        generation=lab.GENERATION,
        starting_balance=Decimal("1000"),
        started_at=START,
    )
    session.add(wallet)
    await session.flush()
    return wallet


async def _token(session: AsyncSession, mint: str, symbol: str) -> None:
    token = await TokenRepository(session).insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}",
            "slot": 1,
            "discovered_at": START - timedelta(hours=2),
            "block_time": START - timedelta(hours=2),
            "name": symbol,
            "symbol": symbol,
        }
    )
    assert token is not None
    session.add(
        RadarToken(
            token_id=token.id,
            mint_address=mint,
            first_detected_at=START - timedelta(hours=2),
            first_market_cap=Decimal("10000"),
            first_opportunity_score=Decimal("80"),
            first_confidence=Decimal("70"),
            detection_reason=["volume_expanding"],
            category="early_momentum",
            current_opportunity_score=Decimal("80"),
            current_confidence=Decimal("70"),
            current_category="early_momentum",
            current_multiple=Decimal("1.0"),
            peak_multiple=Decimal("1.0"),
            is_active=True,
            model_version="v1",
        )
    )
    await session.flush()


async def _snapshots(
    session: AsyncSession,
    mint: str,
    *prices: tuple[int, str],
    liquidity: str = "18000",
) -> None:
    token = await TokenRepository(session).get_by_mint(mint)
    assert token is not None
    repo = MarketSnapshotRepository(session)
    for hour, price in prices:
        await repo.add_snapshot(
            {
                "token_id": token.id,
                "mint_address": mint,
                "captured_at": START + timedelta(hours=hour),
                "price_usd": Decimal(price),
                "market_cap": Decimal("124000"),
                "liquidity_usd": Decimal(liquidity),
                "volume_24h": Decimal("89000"),
                "dex_name": "pumpswap",
                "trading_status": TradingStatus.TRADING,
                "provider": "test",
            }
        )


async def _position(
    session: AsyncSession,
    wallet: PaperWallet,
    mint: str,
    symbol: str,
    *,
    closed: bool = True,
    manual: bool = False,
) -> None:
    await _token(session, mint, symbol)
    status = "closed" if closed else "open"
    closed_at = START + timedelta(hours=3) if closed else None
    exit_price = Decimal("8") if closed else None
    position = PaperPosition(
        wallet_id=wallet.id,
        mint_address=mint,
        opened_at=START,
        entry_rank=1,
        entry_price=Decimal("10"),
        size_usd=Decimal("100"),
        quantity=Decimal("10"),
        target_price=None,
        stop_price=None,
        expires_at=None,
        trailing_drawdown=Decimal("0.25"),
        entry_market_cap=Decimal("100000"),
        entry_liquidity_usd=Decimal("18000"),
        status=status,
        peak_price=Decimal("20"),
        last_evaluated_at=closed_at or START,
        closed_at=closed_at,
        exit_price=exit_price,
        exit_reason="manual" if manual else ("stop" if closed else None),
        manual_action_at=NOW if manual else None,
    )
    session.add(position)
    await session.flush()
    if closed:
        round_trip = costs.round_trip(
            entry_notional=Decimal("100"),
            entry_liquidity=Decimal("18000"),
            exit_notional=Decimal("80"),
            exit_liquidity=Decimal("18000"),
        )
        assert round_trip is not None
        session.add(
            PaperTradeAudit(
                position_id=position.id,
                wallet_id=wallet.id,
                mint_address=mint,
                symbol=symbol,
                entry_at=position.opened_at,
                entry_price=position.entry_price,
                entry_market_cap=position.entry_market_cap,
                entry_liquidity_usd=position.entry_liquidity_usd,
                size_usd=position.size_usd,
                quantity=position.quantity,
                exit_at=closed_at,
                exit_price=exit_price,
                exit_market_cap=Decimal("90000"),
                exit_liquidity_usd=Decimal("18000"),
                gross_return_usd=Decimal("-20"),
                gross_return_pct=Decimal("-20"),
                fee_usd=round_trip.entry.fee + round_trip.exit.fee,
                slippage_usd=round_trip.entry.impact + round_trip.exit.impact,
                net_return_usd=costs.net_proceeds(
                    entry_notional=Decimal("100"),
                    exit_notional=Decimal("80"),
                    costs=round_trip,
                ),
                net_return_pct=Decimal("-20"),
                exit_reason=position.exit_reason,
                strategy_id=lab.STRATEGY_ID,
                strategy_version="1.0.0",
                wallet_generation=lab.GENERATION,
                swap_fee_bps=Decimal("30"),
                manual_action_at=position.manual_action_at,
            )
        )


async def _archived_wallet(session: AsyncSession) -> None:
    wallet = PaperWallet(
        strategy_id="equal_weight_v1",
        strategy_version="1.0.0",
        generation=1,
        starting_balance=Decimal("1000"),
        started_at=START - timedelta(days=5),
        archived_at=START,
    )
    session.add(wallet)
    await session.flush()
    await _token(session, ARCHIVED, "OLD")
    session.add(
        PaperPosition(
            wallet_id=wallet.id,
            mint_address=ARCHIVED,
            opened_at=START - timedelta(days=4),
            entry_rank=1,
            entry_price=Decimal("10"),
            size_usd=Decimal("100"),
            quantity=Decimal("10"),
            target_price=Decimal("20"),
            stop_price=Decimal("5"),
            expires_at=START,
            trailing_drawdown=None,
            entry_market_cap=Decimal("10000"),
            entry_liquidity_usd=Decimal("18000"),
            status="closed",
            peak_price=Decimal("11"),
            last_evaluated_at=START,
            closed_at=START,
            exit_price=Decimal("5"),
            exit_reason="stop",
        )
    )


async def _dataset(session: AsyncSession) -> None:
    wallet = await _wallet(session)
    await _position(session, wallet, WINNER, "WIN")
    await _position(session, wallet, LOSER, "LOSE")
    await _position(session, wallet, RUNNER, "RUN", closed=False)
    await _snapshots(session, WINNER, (1, "20"), (2, "14"), (3, "50"))
    await _snapshots(session, LOSER, (1, "9"), (2, "7"), (3, "5"))
    await _snapshots(session, RUNNER, (1, "11"), (2, "12"), (3, "13"))


def _by_id(results: tuple[lab.StrategyResult, ...]) -> dict[str, lab.StrategyResult]:
    return {item.id: item for item in results}


class TestSharedDataset:
    async def test_every_strategy_replays_the_same_entries(
        self, db_session: AsyncSession
    ) -> None:
        await _dataset(db_session)
        await db_session.commit()

        results = replay_all(await load_dataset(db_session, now=NOW))
        entries = {
            result.id: sorted(
                (trade.mint_address, trade.entry_price, trade.opened_at)
                for trade in result.trades
            )
            for result in results
        }

        first = next(iter(entries.values()))
        for strategy_id, taken in entries.items():
            assert taken == first, strategy_id

    async def test_dataset_is_generation_two_only(self, db_session: AsyncSession) -> None:
        await _dataset(db_session)
        await _archived_wallet(db_session)
        await db_session.commit()

        dataset = await load_dataset(db_session, now=NOW)

        assert dataset.integrity.scoped_generation == 2
        assert dataset.integrity.archived_generation_positions == 1
        assert dataset.integrity.archived_missing_audit_rows == 1
        assert {entry.mint_address for entry in dataset.entries} == {WINNER, LOSER, RUNNER}

    async def test_a_position_with_no_prices_is_counted_not_fabricated(
        self, db_session: AsyncSession
    ) -> None:
        wallet = await _wallet(db_session)
        await _position(db_session, wallet, WINNER, "WIN")
        await db_session.commit()

        dataset = await load_dataset(db_session, now=NOW)

        assert len(dataset.entries) == 1
        assert dataset.entries[0].quotes == ()


class TestExitResearch:
    async def test_baseline_and_no_stop_reach_different_answers(
        self, db_session: AsyncSession
    ) -> None:
        await _dataset(db_session)
        await db_session.commit()

        results = _by_id(replay_all(await load_dataset(db_session, now=NOW)))
        baseline = {trade.mint_address: trade for trade in results[lab.BASELINE_ID].trades}
        hold = {trade.mint_address: trade for trade in results["hold_until_latest"].trades}

        assert baseline[WINNER].exit_price == Decimal("14")
        assert hold[WINNER].mark_price == Decimal("50")

    async def test_token_comparison_covers_every_strategy(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _dataset(db_session)
        await db_session.commit()

        body = (await client.get("/api/v1/paper/lab/tokens")).json()

        assert body["items"]
        ids = set(body["strategy_ids"])
        for item in body["items"]:
            assert set(item["returns"]) == ids


class TestApi:
    async def test_the_table_ranks_and_compares_against_v1(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _dataset(db_session)
        await db_session.commit()

        body = (await client.get("/api/v1/paper/lab")).json()

        assert body["baseline_id"] == lab.BASELINE_ID
        baselines = [strategy for strategy in body["strategies"] if strategy["is_baseline"]]
        assert len(baselines) == 1
        assert baselines[0]["baseline_difference_pct"] is None
        assert [strategy["rank"] for strategy in body["strategies"]] == list(
            range(1, len(body["strategies"]) + 1)
        )

    async def test_integrity_and_final_decision_are_served(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _dataset(db_session)
        await _archived_wallet(db_session)
        await db_session.commit()

        body = (await client.get("/api/v1/paper/lab")).json()

        assert body["data_integrity"]["scoped_generation"] == 2
        assert body["data_integrity"]["missing_audit_rows"] == 0
        assert body["data_integrity"]["archived_missing_audit_rows"] == 1
        assert body["final_decision_code"] in {"A", "B", "C"}
        assert body["final_decision"]

    async def test_methodology_names_generation_scope(self, client: AsyncClient) -> None:
        body = (await client.get("/api/v1/paper/lab")).json()

        assert "generation 2" in body["methodology"].lower()
        assert "generation 1 is archived" in body["methodology"].lower()
        assert "production trading behaviour is not changed" in body["methodology"].lower()

    async def test_patterns_and_rejections_are_served(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _dataset(db_session)
        await db_session.commit()

        body = (await client.get("/api/v1/paper/lab")).json()

        assert body["pattern_analysis"]["entry_market_cap"]
        assert body["pattern_analysis"]["liquidity"]
        assert body["suggestions"]
        assert "rejected_ideas" in body

    async def test_two_calls_return_identical_figures(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _dataset(db_session)
        await db_session.commit()

        first = (await client.get("/api/v1/paper/lab")).json()
        second = (await client.get("/api/v1/paper/lab")).json()

        for a, b in zip(first["strategies"], second["strategies"], strict=True):
            assert a["id"] == b["id"]
            assert a["total_return_pct"] == b["total_return_pct"]
            assert a["net_return_pct"] == b["net_return_pct"]
            assert a["equity_curve"] == b["equity_curve"]

    async def test_nothing_served_reads_as_advice(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _dataset(db_session)
        await db_session.commit()

        text = (await client.get("/api/v1/paper/lab")).text.lower()

        for phrase in ("we recommend", "you should", "guaranteed"):
            assert phrase not in text


class TestExecutionCosts:
    async def test_gross_is_served_beside_net(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _dataset(db_session)
        await db_session.commit()

        body = (await client.get("/api/v1/paper/lab")).json()

        for strategy in body["strategies"]:
            assert "total_return_pct" in strategy
            assert "net_return_pct" in strategy
            assert strategy["costed_trades"] + strategy["uncosted_trades"] == (
                strategy["closed_count"] + strategy["open_count"]
            )

    async def test_cost_model_disclosure_ships_with_the_page(
        self, client: AsyncClient
    ) -> None:
        body = (await client.get("/api/v1/paper/lab")).json()

        disclosure = body["cost_disclosure"].lower()
        assert "slippage" in disclosure
        assert "mev" in disclosure or "priority" in disclosure
        labels = {rule["label"] for rule in body["cost_rules"]}
        assert "Swap fee" in labels
        assert "Price impact" in labels
