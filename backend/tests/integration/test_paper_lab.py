"""The Strategy Lab over a real database.

Sprint 26. What is asserted here is what the sprint is *for*:

  - every rule replays over the **same** detections, loaded once;
  - the baseline is present, frozen, and compared against rather than replaced;
  - a rule whose marked return is carried by open positions says so, because
    ranking on the marked total would otherwise let it look earned;
  - running the endpoint twice returns byte-identical figures.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import TradingStatus
from app.models.radar import RadarToken
from app.paper import exits
from app.paper.lab_service import load_dataset, replay_all
from app.repositories.market import MarketSnapshotRepository
from app.repositories.token import TokenRepository

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC).replace(microsecond=0)
DETECTED = NOW - timedelta(days=5)


async def _seed(
    session: AsyncSession, mint: str, *prices: tuple[int, str], symbol: str = "PRB"
) -> None:
    """A detection and the prices observed after it."""
    token = await TokenRepository(session).insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}",
            "slot": 1,
            "discovered_at": DETECTED,
            "block_time": DETECTED,
            "name": symbol,
            "symbol": symbol,
        }
    )
    assert token is not None
    session.add(
        RadarToken(
            token_id=token.id,
            mint_address=mint,
            first_detected_at=DETECTED,
            first_market_cap=Decimal("10000"),
            first_opportunity_score=Decimal(70),
            first_confidence=Decimal(40),
            detection_reason=["volume_expanding"],
            category="early_momentum",
            current_opportunity_score=Decimal(70),
            current_confidence=Decimal(40),
            current_category="early_momentum",
            current_multiple=Decimal("1.0"),
            peak_multiple=Decimal("1.0"),
            is_active=True,
            model_version="v1",
        )
    )
    await session.flush()

    market = MarketSnapshotRepository(session)
    for hours, price in prices:
        await market.add_snapshot(
            {
                "token_id": token.id,
                "mint_address": mint,
                "captured_at": DETECTED + timedelta(hours=hours),
                "price_usd": Decimal(price),
                "market_cap": Decimal("124000"),
                "liquidity_usd": Decimal("18000"),
                "volume_24h": Decimal("89000"),
                "dex_name": "pumpswap",
                "trading_status": TradingStatus.TRADING,
                "provider": "test",
            }
        )
    await session.flush()


WINNER = "LabMintWinner11111111111111111111111111111"
LOSER = "LabMintLoser222222222222222222222222222222"
RUNNER = "LabMintRunner33333333333333333333333333333"


async def _dataset(session: AsyncSession) -> None:
    # Doubles then halves — the baseline takes profit, a trailing stop keeps more.
    await _seed(session, WINNER, (0, "10"), (1, "25"), (2, "12"), symbol="WIN")
    # Falls straight through the stop.
    await _seed(session, LOSER, (0, "10"), (1, "3"), symbol="LOSE")
    # Rises slowly and never triggers anything.
    await _seed(session, RUNNER, (0, "10"), (1, "11"), (2, "12"), symbol="RUN")


class TestSharedDataset:
    async def test_every_strategy_replays_the_same_entries(
        self, db_session: AsyncSession
    ) -> None:
        """The basis of the whole comparison. If entries differed, a rule could
        win by having been offered better tokens."""
        await _dataset(db_session)
        await db_session.commit()

        dataset = await load_dataset(db_session, now=NOW)
        results = replay_all(dataset)

        entries = {
            sid: sorted((t.mint_address, t.entry_price, t.opened_at) for t in r.trades)
            for sid, r in results.items()
        }
        first = next(iter(entries.values()))
        for sid, taken in entries.items():
            assert taken == first, f"{sid} entered a different set"

    async def test_the_dataset_is_ordered_deterministically(
        self, db_session: AsyncSession
    ) -> None:
        await _dataset(db_session)
        await db_session.commit()

        first = await load_dataset(db_session, now=NOW)
        second = await load_dataset(db_session, now=NOW)

        assert [d.mint_address for d in first.detections] == [
            d.mint_address for d in second.detections
        ]
        assert first.detections == second.detections

    async def test_a_detection_with_no_prices_is_counted_not_entered(
        self, db_session: AsyncSession
    ) -> None:
        await _seed(db_session, WINNER, (0, "10"), (1, "25"))
        await _seed(db_session, LOSER)  # no snapshots at all
        await db_session.commit()

        dataset = await load_dataset(db_session, now=NOW)

        assert dataset.unpriced == 1
        assert {d.mint_address for d in dataset.detections} == {WINNER}


class TestExitRulesDiffer:
    async def test_the_baseline_and_a_trailing_stop_reach_different_answers(
        self, db_session: AsyncSession
    ) -> None:
        """If they agreed on everything the lab would have nothing to report."""
        await _dataset(db_session)
        await db_session.commit()

        results = replay_all(await load_dataset(db_session, now=NOW))
        baseline = {t.mint_address: t for t in results["equal_weight_v1"].trades}
        trailing = {t.mint_address: t for t in results["trailing_25"].trades}

        assert baseline[WINNER].exit_price != trailing[WINNER].exit_price

    async def test_removing_the_stop_changes_the_losers_outcome(
        self, db_session: AsyncSession
    ) -> None:
        await _dataset(db_session)
        await db_session.commit()

        results = replay_all(await load_dataset(db_session, now=NOW))
        stopped = {t.mint_address: t for t in results["equal_weight_v1"].trades}[LOSER]
        unstopped = {t.mint_address: t for t in results["no_stop_loss"].trades}[LOSER]

        assert stopped.reason is not None
        assert unstopped.reason is None or unstopped.exit_price != stopped.exit_price


class TestApi:
    async def test_the_table_ranks_and_compares_against_the_baseline(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _dataset(db_session)
        await db_session.commit()

        body = (await client.get("/api/v1/paper/lab")).json()

        assert body["baseline_id"] == "equal_weight_v1"
        baselines = [s for s in body["strategies"] if s["is_baseline"]]
        assert len(baselines) == 1
        # A benchmark does not differ from itself.
        assert baselines[0]["baseline_difference_pct"] is None
        assert [s["rank"] for s in body["strategies"]] == list(
            range(1, len(body["strategies"]) + 1)
        )

    async def test_the_baseline_is_never_dropped_even_when_it_loses(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Publishing it whether it wins or loses is the point of the sprint."""
        await _dataset(db_session)
        await db_session.commit()

        body = (await client.get("/api/v1/paper/lab")).json()
        ids = [s["id"] for s in body["strategies"]]

        assert "equal_weight_v1" in ids
        assert len(ids) == len(exits.LAB_STRATEGIES)

    async def test_marked_and_realised_returns_are_both_served(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Win rate and profit factor count closed trades only. A headline
        return that includes open marks would otherwise read as though it had
        been earned."""
        await _dataset(db_session)
        await db_session.commit()

        body = (await client.get("/api/v1/paper/lab")).json()

        for strategy in body["strategies"]:
            assert "realised_return_pct" in strategy
            assert "open_share_pct" in strategy

    async def test_the_methodology_distinguishes_the_lab_from_the_wallet(
        self, client: AsyncClient
    ) -> None:
        """Reporting a lab return as though it were the wallet's balance would
        be the quietest lie available here."""
        body = (await client.get("/api/v1/paper/lab")).json()

        assert "unconstrained" in body["methodology"].lower()
        assert "not the live wallet" in body["methodology"].lower()

    async def test_an_unmeasurable_strategy_is_declared_with_its_reason(
        self, client: AsyncClient
    ) -> None:
        """An ATR needs OHLC this platform does not store. A proxy under ATR's
        name would be worse than the omission."""
        body = (await client.get("/api/v1/paper/lab")).json()

        assert body["unavailable"]
        assert all(item["reason"] for item in body["unavailable"])

    async def test_annualising_a_short_window_is_refused(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _dataset(db_session)
        await db_session.commit()

        body = (await client.get("/api/v1/paper/lab")).json()

        for strategy in body["strategies"]:
            assert strategy["annualised_return_pct"] is None
            assert strategy["annualised_unavailable_reason"]

    async def test_findings_name_the_metric_they_rest_on(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _dataset(db_session)
        await db_session.commit()

        body = (await client.get("/api/v1/paper/lab")).json()

        assert body["findings"]
        for finding in body["findings"]:
            assert finding["headline"] and finding["detail"]

    async def test_nothing_served_reads_as_advice(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _dataset(db_session)
        await db_session.commit()

        text = (await client.get("/api/v1/paper/lab")).text.lower()

        for phrase in ("we recommend", "you should", "switch to", "guaranteed"):
            assert phrase not in text

    async def test_two_calls_return_identical_figures(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Determinism, asserted at the HTTP boundary."""
        await _dataset(db_session)
        await db_session.commit()

        first = (await client.get("/api/v1/paper/lab")).json()
        second = (await client.get("/api/v1/paper/lab")).json()

        for a, b in zip(first["strategies"], second["strategies"], strict=True):
            assert a["id"] == b["id"]
            assert a["total_return_pct"] == b["total_return_pct"]
            assert a["realised_return_pct"] == b["realised_return_pct"]
            assert a["max_drawdown_pct"] == b["max_drawdown_pct"]
            assert a["equity_curve"] == b["equity_curve"]

    async def test_per_token_comparison_covers_every_strategy(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _dataset(db_session)
        await db_session.commit()

        body = (await client.get("/api/v1/paper/lab/tokens")).json()

        assert body["items"]
        ids = set(body["strategy_ids"])
        for item in body["items"]:
            assert set(item["returns"]) == ids

    async def test_a_token_that_never_rose_crowns_nobody(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _dataset(db_session)
        await db_session.commit()

        body = (await client.get("/api/v1/paper/lab/tokens")).json()
        loser = [i for i in body["items"] if i["mint_address"] == LOSER]

        assert loser and loser[0]["best_strategy_id"] is None
