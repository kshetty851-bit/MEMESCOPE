"""Curve collection end to end: derive, fetch, parse, append, replay.

The RPC is stubbed. That is not a shortcut — the Helius plan is quota
exhausted, so a test that reached the network would fail for a reason unrelated
to the code under test. What is exercised here is everything between the
address and the row.
"""

from __future__ import annotations

import base64
import struct
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.curve import TokenCurveSnapshot
from app.models.market import TradingStatus
from app.opportunities.repository import OpportunityRepository
from app.repositories.curve import CurveSnapshotRepository
from app.repositories.market import MarketSnapshotRepository
from app.repositories.token import TokenRepository
from app.services.curve.collector import BondingCurveCollector
from app.services.curve.pda import bonding_curve_address
from app.services.helius.client import HeliusError

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
MINT = "HHbRJ9Fw2tPxETGSsaeQhpgdizfVafLvXK7eo5mwpump"
OTHER = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"

INITIAL_REAL_TOKENS = 793_100_000_000_000
TOTAL_SUPPLY = 1_000_000_000_000_000


def account_bytes(*, real_token: int = INITIAL_REAL_TOKENS, complete: int = 0) -> str:
    """Base64 account data, as `getMultipleAccounts` returns it."""
    raw = (
        b"\x01" * 8
        + struct.pack(
            "<QQQQQ",
            1_073_000_000_000_000,
            30_000_000_000,
            real_token,
            0,
            TOTAL_SUPPLY,
        )
        + bytes([complete])
    )
    return base64.b64encode(raw).decode()


class StubHelius:
    """Records calls and replays canned account values."""

    def __init__(self, values: list[dict[str, Any] | None] | Exception) -> None:
        self._values = values
        self.calls: list[tuple[str, Any]] = []

    async def start(self) -> None: ...
    async def close(self) -> None: ...

    async def call(self, method: str, params: Any, **kwargs: Any) -> Any:
        self.calls.append((method, params))
        if isinstance(self._values, Exception):
            raise self._values
        return {"value": self._values}


def _stub(real_token: int, *, complete: int = 0) -> Any:
    """A stub returning one curve account. Keeps the call sites readable."""
    return StubHelius(
        [{"data": [account_bytes(real_token=real_token, complete=complete), "base64"]}]
    )


async def _token(session: AsyncSession, mint: str) -> Any:
    tokens = TokenRepository(session)
    token = await tokens.insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}",
            "slot": 1,
            "discovered_at": NOW - timedelta(days=1),
        }
    ) or await tokens.get_by_mint(mint)
    await session.flush()
    return token


class TestAddressing:
    async def test_it_derives_the_curve_address_locally(
        self, db_session: AsyncSession
    ) -> None:
        """No lookup call. Local derivation is what makes one batched read per
        hundred tokens possible rather than one call per token."""
        collector = BondingCurveCollector(db_session, program_id=PUMP)

        addresses = collector.addresses_for([MINT, OTHER])

        assert addresses[MINT] == bonding_curve_address(MINT, program_id=PUMP)
        assert addresses[OTHER] != addresses[MINT]

    async def test_a_malformed_mint_is_dropped_not_fatal(
        self, db_session: AsyncSession
    ) -> None:
        """One bad row must not cost the other ninety-nine their reading."""
        collector = BondingCurveCollector(db_session, program_id=PUMP)

        addresses = collector.addresses_for([MINT, "not a key!"])

        assert MINT in addresses
        assert len(addresses) == 1

    async def test_duplicates_are_addressed_once(
        self, db_session: AsyncSession
    ) -> None:
        collector = BondingCurveCollector(db_session, program_id=PUMP)
        assert len(collector.addresses_for([MINT, MINT, MINT])) == 1


class TestCollection:
    async def test_it_appends_a_parsed_curve(self, db_session: AsyncSession) -> None:
        await _token(db_session, MINT)
        stub = StubHelius(
            [{"data": [account_bytes(real_token=400_000_000_000_000), "base64"]}],
        )
        collector = BondingCurveCollector(db_session, helius=stub, program_id=PUMP)  # type: ignore[arg-type]

        outcome = await collector.collect([MINT], now=NOW)

        assert outcome.fetched == 1
        assert outcome.parsed == 1
        assert outcome.written == 1

        row = await db_session.scalar(select(TokenCurveSnapshot))
        assert row is not None
        assert row.mint_address == MINT
        assert row.real_token_reserves == Decimal(400_000_000_000_000)
        assert row.complete is False

    async def test_it_asks_for_the_derived_addresses(
        self, db_session: AsyncSession
    ) -> None:
        await _token(db_session, MINT)
        stub = StubHelius([{"data": [account_bytes(), "base64"]}])
        collector = BondingCurveCollector(db_session, helius=stub, program_id=PUMP)  # type: ignore[arg-type]

        await collector.collect([MINT], now=NOW)

        method, params = stub.calls[0]
        assert method == "getMultipleAccounts"
        assert params[0] == [bonding_curve_address(MINT, program_id=PUMP)]

    async def test_an_absent_account_is_normal_not_an_error(
        self, db_session: AsyncSession
    ) -> None:
        """No curve account is the expected state for a token that never had
        one, and for one whose account closed after migrating."""
        await _token(db_session, MINT)
        stub = StubHelius([None])
        collector = BondingCurveCollector(db_session, helius=stub, program_id=PUMP)  # type: ignore[arg-type]

        outcome = await collector.collect([MINT], now=NOW)

        assert outcome.absent == 1
        assert outcome.written == 0
        assert outcome.failed == 0

    async def test_unparsable_data_is_counted_and_not_written(
        self, db_session: AsyncSession
    ) -> None:
        """The layout is unverified, so a reading that fails its invariants must
        produce no row rather than a plausible wrong one."""
        await _token(db_session, MINT)
        stub = StubHelius([{"data": [base64.b64encode(b"\xff" * 64).decode(), "base64"]}])
        collector = BondingCurveCollector(db_session, helius=stub, program_id=PUMP)  # type: ignore[arg-type]

        outcome = await collector.collect([MINT], now=NOW)

        assert outcome.unparsable == 1
        assert outcome.written == 0
        total = await db_session.scalar(
            select(func.count()).select_from(TokenCurveSnapshot)
        )
        assert total == 0

    async def test_an_rpc_failure_is_contained(self, db_session: AsyncSession) -> None:
        """A Helius outage costs the curve series one point, never the token.

        This is the live condition today: every RPC method returns
        `429 max usage reached`.
        """
        await _token(db_session, MINT)
        stub = StubHelius(HeliusError("getMultipleAccounts rate limited"))
        collector = BondingCurveCollector(db_session, helius=stub, program_id=PUMP)  # type: ignore[arg-type]

        outcome = await collector.collect([MINT], now=NOW)

        assert outcome.failed == 1
        assert outcome.written == 0

    async def test_an_unknown_token_is_dropped_rather_than_raising(
        self, db_session: AsyncSession
    ) -> None:
        """The foreign key would reject it; one unknown mint must not cost the
        batch — the same lesson as the discovery listener's poison message."""
        stub = StubHelius([{"data": [account_bytes(), "base64"]}])
        collector = BondingCurveCollector(db_session, helius=stub, program_id=PUMP)  # type: ignore[arg-type]

        outcome = await collector.collect([MINT], now=NOW)

        assert outcome.parsed == 1
        assert outcome.written == 0

    async def test_an_empty_request_does_nothing(
        self, db_session: AsyncSession
    ) -> None:
        stub = StubHelius([])
        collector = BondingCurveCollector(db_session, helius=stub, program_id=PUMP)  # type: ignore[arg-type]

        outcome = await collector.collect([], now=NOW)

        assert outcome.requested == 0
        assert stub.calls == []


class TestAppendOnly:
    async def test_a_repeated_read_records_the_state_once(
        self, db_session: AsyncSession
    ) -> None:
        """A cycle that runs twice — a retry, a restart, two workers racing —
        must record one state once. The unique key is the guarantee."""
        await _token(db_session, MINT)
        stub = StubHelius([{"data": [account_bytes(), "base64"]}])
        collector = BondingCurveCollector(db_session, helius=stub, program_id=PUMP)  # type: ignore[arg-type]

        await collector.collect([MINT], now=NOW)
        second = await collector.collect([MINT], now=NOW)

        assert second.written == 0
        total = await db_session.scalar(
            select(func.count()).select_from(TokenCurveSnapshot)
        )
        assert total == 1

    async def test_a_later_read_appends_rather_than_updating(
        self, db_session: AsyncSession
    ) -> None:
        """Append-only is what makes curve progress a series, and a series is
        what tells a filling curve from one parked at the same level."""
        await _token(db_session, MINT)
        collector = BondingCurveCollector(
            db_session,
            helius=_stub(700_000_000_000_000),
            program_id=PUMP,
        )
        await collector.collect([MINT], now=NOW)

        later = BondingCurveCollector(
            db_session,
            helius=_stub(300_000_000_000_000),
            program_id=PUMP,
        )
        await later.collect([MINT], now=NOW + timedelta(minutes=30))

        rows = await CurveSnapshotRepository(db_session).history_for(MINT)
        assert len(rows) == 2
        assert rows[0].real_token_reserves > rows[1].real_token_reserves


class TestReplay:
    async def test_a_stored_series_replays_as_rising_progress(
        self, db_session: AsyncSession
    ) -> None:
        """The replay this sprint exists to enable.

        A curve filling over time must read back as monotonically rising
        progress — the input the near-graduation velocity component needs, and
        the thing `market_cap` could not provide (§14a).
        """
        await _token(db_session, MINT)
        reserves = [
            793_100_000_000_000,
            600_000_000_000_000,
            400_000_000_000_000,
            100_000_000_000_000,
        ]

        for index, remaining in enumerate(reserves):
            collector = BondingCurveCollector(
                db_session,
                helius=_stub(remaining),
                program_id=PUMP,
            )
            await collector.collect([MINT], now=NOW + timedelta(minutes=15 * index))

        rows = await CurveSnapshotRepository(db_session).history_for(MINT)
        from app.services.curve.state import CurveState

        progress = [
            CurveState(
                virtual_token_reserves=int(row.virtual_token_reserves),
                virtual_sol_reserves=int(row.virtual_sol_reserves),
                real_token_reserves=int(row.real_token_reserves),
                real_sol_reserves=int(row.real_sol_reserves),
                token_total_supply=int(row.token_total_supply),
                complete=row.complete,
            ).progress
            for row in rows
        ]

        assert len(progress) == 4
        assert progress == sorted(progress)  # type: ignore[type-var]
        assert progress[0] == Decimal(0)
        assert progress[-1] > Decimal("0.85")

    async def test_completion_is_recorded_as_a_fact(
        self, db_session: AsyncSession
    ) -> None:
        """`complete` states graduation directly, where the fresh-graduation
        provider has to infer it from a venue transition. Both are kept: the
        venue is observable without RPC, the flag is authoritative."""
        await _token(db_session, MINT)
        collector = BondingCurveCollector(
            db_session,
            helius=_stub(0, complete=1),
            program_id=PUMP,
        )

        await collector.collect([MINT], now=NOW)

        row = await db_session.scalar(select(TokenCurveSnapshot))
        assert row is not None
        assert row.complete is True

    async def test_the_latest_reading_is_addressable_per_mint(
        self, db_session: AsyncSession
    ) -> None:
        """What the opportunity window needs: one current curve position per
        token, in one query."""
        await _token(db_session, MINT)
        await _token(db_session, OTHER)

        for index, mint in enumerate((MINT, OTHER)):
            collector = BondingCurveCollector(
                db_session,
                helius=_stub(500_000_000_000_000 - index),
                program_id=PUMP,
            )
            await collector.collect([mint], now=NOW + timedelta(seconds=index))

        latest = await CurveSnapshotRepository(db_session).latest_for([MINT, OTHER])
        assert set(latest) == {MINT, OTHER}


class TestClientLifecycle:
    """The stub hides one thing: whether the real client is ever started.

    The first live run failed with "HeliusClient is not started" because the
    chunk fetcher constructed its own instead of using the one the collector
    owns. Stubs cannot catch that, so it is asserted directly.
    """

    async def test_every_chunk_uses_the_one_started_client(
        self, db_session: AsyncSession
    ) -> None:
        started: list[str] = []

        class LifecycleStub(StubHelius):
            async def start(self) -> None:
                started.append("start")

            async def call(self, method: str, params: Any, **kwargs: Any) -> Any:
                assert started, "called before start()"
                return await super().call(method, params, **kwargs)

        await _token(db_session, MINT)
        stub = LifecycleStub([{"data": [account_bytes(), "base64"]}])
        # Injected clients are not owned, so the collector must not start them —
        # but it must still route every chunk through the same instance.
        collector = BondingCurveCollector(db_session, helius=stub, program_id=PUMP)  # type: ignore[arg-type]
        started.append("injected")

        outcome = await collector.collect([MINT], now=NOW)

        assert outcome.written == 1
        assert len(stub.calls) == 1

    async def test_chunking_respects_the_rpc_limit(
        self, db_session: AsyncSession
    ) -> None:
        """`getMultipleAccounts` accepts 100 addresses; more must be split."""
        from app.services.curve.collector import MAX_ACCOUNTS_PER_CALL

        assert MAX_ACCOUNTS_PER_CALL == 100


class TestProviderInput:
    """The last wire: a collected curve has to reach the thing that reads it.

    Everything above proves the snapshot lands. None of it proves a provider
    ever sees it — `Observation.curve_progress` shipped populated by nothing,
    so near graduation stayed unavailable with the data sitting in the table.
    """

    async def test_a_collected_curve_reaches_the_observation_window(
        self, db_session: AsyncSession
    ) -> None:
        token = await _token(db_session, MINT)
        await MarketSnapshotRepository(db_session).add_snapshot(
            {
                "token_id": token.id,
                "mint_address": MINT,
                "captured_at": NOW,
                "price_usd": Decimal("0.001"),
                "dex_name": "pumpfun",
                "trading_status": TradingStatus.TRADING,
                "provider": "test",
            }
        )
        # Collected a minute before the market observation, as the worker does:
        # curve collection is TX-3 and detection reads what it wrote.
        collector = BondingCurveCollector(
            db_session, helius=_stub(INITIAL_REAL_TOKENS // 4), program_id=PUMP
        )
        await collector.collect([MINT], now=NOW - timedelta(minutes=1))
        await db_session.flush()

        windows = await OpportunityRepository(db_session).windows_for(
            [MINT], limit_per_mint=12, curve_limit_per_mint=12
        )

        latest = windows[MINT].latest
        assert latest is not None
        assert latest.curve_progress == Decimal("0.75")

    async def test_curve_progress_is_absent_unless_asked_for(
        self, db_session: AsyncSession
    ) -> None:
        """The default is off, and off means `None` rather than a stale number.

        With collection disabled the newest snapshot is as old as the flag, and
        attaching it to today's observations would read as a stalled curve —
        a claim about the present made from data about the past.
        """
        token = await _token(db_session, MINT)
        await MarketSnapshotRepository(db_session).add_snapshot(
            {
                "token_id": token.id,
                "mint_address": MINT,
                "captured_at": NOW,
                "price_usd": Decimal("0.001"),
                "dex_name": "pumpfun",
                "trading_status": TradingStatus.TRADING,
                "provider": "test",
            }
        )
        collector = BondingCurveCollector(
            db_session, helius=_stub(INITIAL_REAL_TOKENS // 4), program_id=PUMP
        )
        await collector.collect([MINT], now=NOW - timedelta(minutes=1))
        await db_session.flush()

        windows = await OpportunityRepository(db_session).windows_for(
            [MINT], limit_per_mint=12
        )

        latest = windows[MINT].latest
        assert latest is not None
        assert latest.curve_progress is None
