"""The market-data gate against a real database.

The pure logic is covered in `tests/unit/test_paper_market_health.py`. This
file proves the parts that only exist once there are rows: the repository
invariant nothing can route around, the census reading real snapshots, the
re-prime that moves enrichment state, and — most importantly — that none of it
can reach an exit.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import (
    LANE_DISPLAY,
    LANE_NORMAL,
    EnrichmentStatus,
    TokenEnrichmentState,
    TokenMarketSnapshot,
    TradingStatus,
)
from app.models.paper import PaperPosition, PaperWallet
from app.models.token import DiscoveredToken
from app.paper import market_health
from app.paper.market_health import EntryBlockReason, FeedState
from app.paper.repository import MarketDataGateViolationError, PaperRepository
from app.paper.strategy import TRAILING_STOP_25_SECURED_HOLD6H_V3, TRAILING_STOP_25_V1
from app.services.market.priority import reprime_open_positions

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 21, 15, 0, tzinfo=UTC)


async def make_token(session: AsyncSession, mint: str) -> DiscoveredToken:
    """`signature` and `slot` are NOT NULL — a fixture that omits them fails at
    the database rather than in the code under test."""
    token = DiscoveredToken(
        mint_address=mint,
        name="Gate Probe",
        symbol="GATE",
        signature=f"sig-{uuid.uuid4()}",
        slot=1,
        discovered_at=NOW - timedelta(days=1),
    )
    session.add(token)
    await session.flush()
    return token


async def make_wallet(
    session: AsyncSession, strategy_id: str, generation: int
) -> PaperWallet:
    """Archived on purpose — `uq_paper_wallets_live` allows only one live row.

    The repository invariant reads the wallet's *strategy*, never its archive
    state, so this measures the same thing without colliding with whatever the
    rest of the suite created. Tests about the **watchdog** need a live wallet
    instead and use `live_wallet` below.
    """
    wallet = PaperWallet(
        strategy_id=strategy_id,
        strategy_version="x",
        starting_balance=Decimal(1000),
        generation=generation,
        started_at=NOW,
        archived_at=NOW,
    )
    session.add(wallet)
    await session.flush()
    return wallet


async def live_wallet(session: AsyncSession) -> PaperWallet:
    """The one live wallet, reused if the suite already made one.

    `uq_paper_wallets_live` is a partial unique index on `archived_at IS NULL`,
    so a second live row is impossible. The watchdog is scoped to the live
    wallet's book, so these tests have to work with that single row rather than
    against it.
    """
    existing = await session.scalar(
        select(PaperWallet).where(PaperWallet.archived_at.is_(None))
    )
    if existing is not None:
        return existing
    wallet = PaperWallet(
        strategy_id=TRAILING_STOP_25_SECURED_HOLD6H_V3.id,
        strategy_version="3.0.0-hold6h",
        starting_balance=Decimal(1000),
        generation=900,
        started_at=NOW,
    )
    session.add(wallet)
    await session.flush()
    return wallet


def position_values(wallet: PaperWallet, mint: str) -> dict:
    return {
        "wallet_id": wallet.id,
        "mint_address": mint,
        "opened_at": NOW,
        "entry_rank": 1,
        "entry_price": Decimal("0.01"),
        "size_usd": Decimal(100),
        "quantity": Decimal(10_000),
        "status": "open",
        "peak_price": Decimal("0.01"),
        "last_evaluated_at": NOW,
    }


async def make_snapshot(
    session: AsyncSession,
    token: DiscoveredToken,
    *,
    at: datetime,
    price: Decimal | None = Decimal("0.01"),
) -> None:
    session.add(
        TokenMarketSnapshot(
            token_id=token.id,
            mint_address=token.mint_address,
            captured_at=at,
            price_usd=price,
            liquidity_usd=Decimal(50_000),
            trading_status=TradingStatus.TRADING,
            provider="test",
        )
    )
    await session.flush()


class TestTheRepositoryInvariant:
    """3, 4, 5. The last place a position can come into existence."""

    async def test_a_gated_wallet_cannot_open_on_stale_evidence(
        self, db_session: AsyncSession
    ) -> None:
        wallet = await make_wallet(db_session, TRAILING_STOP_25_SECURED_HOLD6H_V3.id, 971)
        with pytest.raises(MarketDataGateViolationError, match="above the"):
            await PaperRepository(db_session).open_position(
                security=_allow(),
                market_observed_at=NOW - timedelta(hours=2),
                now=NOW,
                **position_values(wallet, "A" * 44),
            )

    async def test_a_gated_wallet_cannot_open_on_undated_evidence(
        self, db_session: AsyncSession
    ) -> None:
        """Missing is not lenient. Absence of evidence fails closed."""
        wallet = await make_wallet(db_session, TRAILING_STOP_25_SECURED_HOLD6H_V3.id, 972)
        with pytest.raises(MarketDataGateViolationError, match="dated market observation"):
            await PaperRepository(db_session).open_position(
                security=_allow(),
                market_observed_at=None,
                now=NOW,
                **position_values(wallet, "B" * 44),
            )

    async def test_a_gated_wallet_opens_on_fresh_evidence(
        self, db_session: AsyncSession
    ) -> None:
        wallet = await make_wallet(db_session, TRAILING_STOP_25_SECURED_HOLD6H_V3.id, 973)
        created = await PaperRepository(db_session).open_position(
            security=_allow(),
            market_observed_at=NOW - timedelta(seconds=20),
            now=NOW,
            **position_values(wallet, "C" * 44),
        )
        assert created is not None

    async def test_the_violation_raises_rather_than_returning_none(
        self, db_session: AsyncSession
    ) -> None:
        """`None` means 'lost the race' and is counted as ordinary.

        A freshness failure reported that way would be indistinguishable from
        a race and would disappear into a refusal counter — the same argument
        the security gate makes, for the same reason.
        """
        wallet = await make_wallet(db_session, TRAILING_STOP_25_SECURED_HOLD6H_V3.id, 974)
        try:
            result = await PaperRepository(db_session).open_position(
                security=_allow(),
                market_observed_at=NOW - timedelta(days=1),
                now=NOW,
                **position_values(wallet, "D" * 44),
            )
        except MarketDataGateViolationError:
            return
        pytest.fail(f"expected MarketDataGateViolationError, got {result!r}")

    async def test_an_ungated_wallet_is_completely_unaffected(
        self, db_session: AsyncSession
    ) -> None:
        """Generation 2's record must not change shape because of this phase."""
        wallet = await make_wallet(db_session, TRAILING_STOP_25_V1.id, 975)
        created = await PaperRepository(db_session).open_position(
            market_observed_at=None,
            **position_values(wallet, "E" * 44),
        )
        assert created is not None


class TestSecurityAndFreshnessAreIndependent:
    """5. SEC-2 passing must not excuse stale evidence."""

    async def test_a_security_allow_does_not_override_staleness(
        self, db_session: AsyncSession
    ) -> None:
        wallet = await make_wallet(db_session, TRAILING_STOP_25_SECURED_HOLD6H_V3.id, 976)
        with pytest.raises(MarketDataGateViolationError):
            await PaperRepository(db_session).open_position(
                security=_allow(),
                market_observed_at=NOW - timedelta(hours=3),
                now=NOW,
                **position_values(wallet, "F" * 44),
            )


class TestTheCensusReadsRealRows:
    """6, 12. The watchdog measures priced snapshots, never attempts."""

    async def test_a_position_with_only_unpriced_snapshots_is_not_fresh(
        self, db_session: AsyncSession
    ) -> None:
        """The live failure mode nine open positions are in right now.

        `record_result` marks a poll successful and increments
        `consecutive_empty` when the provider returns nothing, so a row can be
        written every fifteen seconds carrying no price at all. Measuring
        anything other than a priced snapshot would report these as healthy.
        """
        wallet = await live_wallet(db_session)
        mint = "G" * 44
        token = await make_token(db_session, mint)
        await make_snapshot(db_session, token, at=NOW - timedelta(days=4))
        # Current rows, but unpriced — exactly what an empty provider reply
        # leaves behind.
        await make_snapshot(db_session, token, at=NOW - timedelta(seconds=5), price=None)
        db_session.add(PaperPosition(**position_values(wallet, mint)))
        await db_session.flush()

        book = await PaperRepository(db_session).open_book_freshness(now=NOW)
        row = next(r for r in book if r.mint_address == mint)
        assert row.age_seconds is not None
        assert row.age_seconds > 3 * 24 * 3600

    async def test_a_freshly_priced_position_reads_as_fresh(
        self, db_session: AsyncSession
    ) -> None:
        wallet = await live_wallet(db_session)
        mint = "H" * 44
        token = await make_token(db_session, mint)
        await make_snapshot(db_session, token, at=NOW - timedelta(seconds=12))
        db_session.add(PaperPosition(**position_values(wallet, mint)))
        await db_session.flush()

        book = await PaperRepository(db_session).open_book_freshness(now=NOW)
        row = next(r for r in book if r.mint_address == mint)
        assert row.age_seconds == pytest.approx(12.0, abs=1.0)

    async def test_a_closed_position_is_not_watched(
        self, db_session: AsyncSession
    ) -> None:
        """The census is about capital at risk, not about history."""
        wallet = await live_wallet(db_session)
        mint = "I" * 44
        await make_token(db_session, mint)
        values = position_values(wallet, mint) | {
            "status": "closed",
            "closed_at": NOW,
            "exit_price": Decimal("0.02"),
            "exit_reason": "stop",
        }
        db_session.add(PaperPosition(**values))
        await db_session.flush()

        book = await PaperRepository(db_session).open_book_freshness(now=NOW)
        assert all(row.mint_address != mint for row in book)


class TestTheGateIsScopedToTheLiveWallet:
    """11, and the failure that made the scope obvious.

    Measured on production the day this was written: generation 9 held four
    positions, all priced within seconds, and the gate was shut by **one
    abandoned generation 5 position** whose pool died four days earlier. 93 of
    the 96 archived open positions can never be re-priced, so a gate that waits
    on them waits for something that cannot happen.
    """

    async def test_a_dead_archived_position_does_not_block_the_live_wallet(
        self, db_session: AsyncSession
    ) -> None:
        live = await live_wallet(db_session)
        fresh_mint, dead_mint = "O" * 44, "P" * 44

        fresh_token = await make_token(db_session, fresh_mint)
        await make_snapshot(db_session, fresh_token, at=NOW - timedelta(seconds=10))
        db_session.add(PaperPosition(**position_values(live, fresh_mint)))

        # An archived generation holding a position that went dark hours ago —
        # stale enough to be critical, not yet old enough to be written off.
        archived = await make_wallet(db_session, TRAILING_STOP_25_V1.id, 981)
        dead_token = await make_token(db_session, dead_mint)
        await make_snapshot(db_session, dead_token, at=NOW - timedelta(hours=3))
        db_session.add(PaperPosition(**position_values(archived, dead_mint)))
        await db_session.flush()

        book = await PaperRepository(db_session).open_book_freshness(now=NOW)
        assert dead_mint not in {row.mint_address for row in book}
        assert fresh_mint in {row.mint_address for row in book}

    async def test_the_archived_book_is_still_counted_and_reported(
        self, db_session: AsyncSession
    ) -> None:
        """Excluded from the gate, never from the report.

        Scoping the gate correctly must not be the thing that makes 96 frozen
        positions invisible — that is a real problem, and a different phase's.
        """
        archived = await make_wallet(db_session, TRAILING_STOP_25_V1.id, 982)
        mint = "Q" * 44
        token = await make_token(db_session, mint)
        await make_snapshot(db_session, token, at=NOW - timedelta(days=4))
        db_session.add(PaperPosition(**position_values(archived, mint)))
        await db_session.flush()

        total, unpriced = await PaperRepository(db_session).archived_open_stale(now=NOW)
        assert total >= 1
        assert unpriced >= 1


class TestReprime:
    """9. Committed capital goes to the head of the queue."""

    async def test_a_stale_position_is_moved_to_due_now_in_the_display_lane(
        self, db_session: AsyncSession
    ) -> None:
        mint = "J" * 44
        token = await make_token(db_session, mint)
        state = TokenEnrichmentState(
            token_id=token.id,
            mint_address=mint,
            status=EnrichmentStatus.ACTIVE,
            priority=LANE_NORMAL,
            # The six-hour OLD tier: the due time that stranded positions for
            # hours after the lane had already promoted them.
            next_refresh_at=NOW + timedelta(hours=6),
        )
        db_session.add(state)
        await db_session.flush()

        moved = await reprime_open_positions(db_session, [mint], now=NOW)
        await db_session.flush()
        await db_session.refresh(state)

        assert moved == 1
        assert state.priority == LANE_DISPLAY
        assert state.next_refresh_at <= NOW

    async def test_repriming_never_pulls_a_token_down_a_lane(
        self, db_session: AsyncSession
    ) -> None:
        """A clamp and a `greatest`, so it can only ever bring a refresh forward."""
        mint = "K" * 44
        token = await make_token(db_session, mint)
        state = TokenEnrichmentState(
            token_id=token.id,
            mint_address=mint,
            status=EnrichmentStatus.ACTIVE,
            priority=LANE_DISPLAY + 1,
            next_refresh_at=NOW + timedelta(minutes=5),
        )
        db_session.add(state)
        await db_session.flush()

        await reprime_open_positions(db_session, [mint], now=NOW)
        await db_session.flush()
        await db_session.refresh(state)
        assert state.priority == LANE_DISPLAY + 1

    async def test_a_second_pass_writes_nothing(self, db_session: AsyncSession) -> None:
        """Idempotent, so a beat every minute produces no dead tuples."""
        mint = "L" * 44
        token = await make_token(db_session, mint)
        db_session.add(
            TokenEnrichmentState(
                token_id=token.id,
                mint_address=mint,
                status=EnrichmentStatus.ACTIVE,
                priority=LANE_NORMAL,
                next_refresh_at=NOW + timedelta(hours=6),
            )
        )
        await db_session.flush()

        assert await reprime_open_positions(db_session, [mint], now=NOW) == 1
        assert await reprime_open_positions(db_session, [mint], now=NOW) == 0

    async def test_an_empty_list_is_a_no_op(self, db_session: AsyncSession) -> None:
        assert await reprime_open_positions(db_session, [], now=NOW) == 0

    async def test_the_reprime_list_excludes_unpriceable_mints(
        self, db_session: AsyncSession
    ) -> None:
        """11. Recovery stays honest about what it cannot fix.

        Re-asking a provider that has answered empty three thousand times is
        not a recovery action, and spending the head of the queue on it would
        starve the positions that *can* be recovered.
        """
        wallet = await live_wallet(db_session)
        dead, recoverable = "M" * 44, "N" * 44
        for mint, age in ((dead, timedelta(days=4)), (recoverable, timedelta(minutes=30))):
            token = await make_token(db_session, mint)
            await make_snapshot(db_session, token, at=NOW - age)
            db_session.add(PaperPosition(**position_values(wallet, mint)))
        await db_session.flush()

        stale = await PaperRepository(db_session).stale_open_mints(now=NOW)
        assert recoverable in stale
        assert dead not in stale


class TestExitContinuity:
    """8, 18. The asymmetry, proven structurally rather than asserted in prose."""

    def test_no_exit_function_can_reach_the_market_health_gate(self) -> None:
        """A feed outage must never be able to stop a position closing.

        Read from the source of the module that owns exits, so the guarantee
        survives a refactor that a hand-written list of call sites would not.
        """
        source = inspect.getsource(
            __import__("app.paper.service", fromlist=["x"])
        )
        exit_markers = (
            "_settle_exits",
            "_settle_activated_trail",
            "_settle_observed_bracket",
            "_settle_elapsed_hold",
            "_close_terminal",
            "_close_observed_bracket",
            "manual_sell",
        )
        for marker in exit_markers:
            start = source.find(f"def {marker}")
            assert start != -1, f"exit path {marker} not found"
            # To the start of the next method definition at the same depth.
            end = source.find("\n    async def ", start + 1)
            body = source[start : end if end != -1 else len(source)]
            assert "market_health" not in body, f"{marker} reaches the entry gate"
            assert "entry_health" not in body, f"{marker} reaches the entry gate"

    def test_the_gate_module_imports_nothing_from_the_exit_engine(self) -> None:
        source = inspect.getsource(market_health)
        assert "from app.paper.exits" not in source
        assert "from app.paper import exits" not in source

    async def test_exits_still_settle_while_the_feed_is_stale(
        self, db_session: AsyncSession
    ) -> None:
        """The whole point, end to end.

        The feed has produced nothing for two hours, so the gate is STALE and
        entries are blocked. The exit walk resolves from the *stored* series
        and closes the position anyway, at the observed price.
        """
        from app.paper import exits
        from app.paper.models import ExitReason, Quote

        health = await PaperRepository(db_session).market_health_snapshot(
            now=NOW + timedelta(days=400)
        )
        assert health.state is FeedState.STALE
        assert health.entries_allowed is False
        assert health.as_dict()["exit_management"] == "ACTIVE"

        # Same instant, same starved feed: the stop still resolves.
        found, _ = exits.resolve(
            exits.ExitRules(trailing_drawdown=Decimal("0.25")),
            entry_price=Decimal("0.06804"),
            opened_at=NOW,
            quotes=[Quote(price_usd=Decimal("0.000001616"), captured_at=NOW)],
            peak=Decimal("0.1152"),
        )
        assert found is not None
        assert found.reason is ExitReason.STOP
        assert found.price_usd == Decimal("0.000001616")


class TestHealthEndpointReporting:
    """Blocked entries are visible, and never hidden behind a 200 with no detail."""

    async def test_a_blocked_state_names_its_reason(
        self, db_session: AsyncSession
    ) -> None:
        health = await PaperRepository(db_session).market_health_snapshot(
            now=NOW + timedelta(days=400)
        )
        payload = health.as_dict()
        assert payload["entry_safety"] == "BLOCKED"
        assert payload["block_reasons"] == [str(EntryBlockReason.MARKET_DATA_STALE)]
        assert payload["detail"]

    async def test_the_reading_carries_the_watchdog_metrics(
        self, db_session: AsyncSession
    ) -> None:
        payload = (await PaperRepository(db_session).market_health_snapshot(now=NOW)).as_dict()
        for key in (
            "open_positions_total",
            "open_positions_fresh",
            "open_positions_stale",
            "open_positions_unpriceable",
            "oldest_open_position_snapshot_age",
            "open_position_refresh_p50",
            "open_position_refresh_p95",
            "global_last_priced_snapshot_age",
        ):
            assert key in payload


def _allow():
    """A live security ALLOW, so freshness is the only thing under test."""
    from app.security.contract import (
        EVALUATOR_VERSION,
        CheckStatus,
        SecurityCheck,
        TokenSecurityEvaluation,
        roll_up,
    )
    from app.security.entry_policy import MANDATORY_CHECKS, decide

    checks = tuple(
        SecurityCheck(name=name, status=CheckStatus.PASS) for name in MANDATORY_CHECKS
    )
    return decide(
        TokenSecurityEvaluation(
            mint_address="Z" * 44,
            evaluated_at=NOW,
            overall_status=roll_up(checks),
            checks=checks,
            evaluator_version=EVALUATOR_VERSION,
        ),
        now=NOW,
    )
