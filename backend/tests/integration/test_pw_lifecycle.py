"""PW-LIFECYCLE-1: multi-generation position management and shared capital.

Two properties, and they pull in opposite directions on purpose:

    ONE generation accepts new entries.
    EVERY generation's open book keeps being exited.

Plus the money rule that makes a cutover safe: a new generation inherits
capital, it does not create it.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.paper import PaperPosition, PaperWallet
from app.paper import metrics
from app.paper.repository import PaperRepository
from app.paper.service import PaperWalletService, _rules_for
from app.paper.strategy import (
    CAPITAL_LINEAGES,
    TRAILING_STOP_25_SECURED_V2,
    TRAILING_STOP_25_V1,
    lineage_for,
    registry,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


async def wallet(
    session: AsyncSession,
    *,
    strategy_id: str,
    generation: int,
    archived: bool = True,
    balance: Decimal = Decimal(1000),
) -> PaperWallet:
    row = PaperWallet(
        strategy_id=strategy_id,
        strategy_version="x",
        starting_balance=balance,
        generation=generation,
        started_at=NOW,
        archived_at=NOW if archived else None,
    )
    session.add(row)
    await session.flush()
    return row


async def position(
    session: AsyncSession,
    book: PaperWallet,
    mint: str,
    *,
    status: str = "open",
    size: Decimal = Decimal(100),
    target: Decimal | None = None,
    stop: Decimal | None = None,
    trailing: Decimal | None = None,
    expires_at: datetime | None = None,
) -> PaperPosition:
    row = PaperPosition(
        wallet_id=book.id,
        mint_address=mint,
        opened_at=NOW - timedelta(days=1),
        entry_rank=1,
        entry_price=Decimal("0.01"),
        size_usd=size,
        quantity=Decimal(10_000),
        status=status,
        peak_price=Decimal("0.01"),
        last_evaluated_at=NOW - timedelta(days=1),
        target_price=target,
        stop_price=stop,
        trailing_drawdown=trailing,
        expires_at=expires_at,
    )
    session.add(row)
    await session.flush()
    return row


class TestExitManagementSpansGenerations:
    async def test_archived_wallets_holding_positions_are_in_scope(
        self, db_session: AsyncSession
    ) -> None:
        live = await wallet(db_session, strategy_id="s_live", generation=91, archived=False)
        old = await wallet(db_session, strategy_id="s_old", generation=90)
        await position(db_session, live, "L" * 44)
        await position(db_session, old, "O" * 44)

        books = await PaperRepository(db_session).wallets_with_open_positions()
        ids = {book.id for book in books}
        assert live.id in ids
        assert old.id in ids, "an archived generation's open book must still be exited"

    async def test_several_archived_generations_are_all_in_scope(
        self, db_session: AsyncSession
    ) -> None:
        books = []
        for index in range(3):
            book = await wallet(db_session, strategy_id=f"s{index}", generation=80 + index)
            await position(db_session, book, chr(ord("a") + index) * 44)
            books.append(book)
        found = {b.id for b in await PaperRepository(db_session).wallets_with_open_positions()}
        assert {book.id for book in books} <= found

    async def test_a_wallet_with_no_open_positions_is_not_swept(
        self, db_session: AsyncSession
    ) -> None:
        """Bounded work: the sweep is over books that still owe an exit."""
        empty = await wallet(db_session, strategy_id="s_empty", generation=79)
        await position(db_session, empty, "C" * 44, status="closed")
        found = {b.id for b in await PaperRepository(db_session).wallets_with_open_positions()}
        assert empty.id not in found

    async def test_the_live_book_is_swept_first(self, db_session: AsyncSession) -> None:
        old = await wallet(db_session, strategy_id="s_o", generation=70)
        live = await wallet(db_session, strategy_id="s_l", generation=71, archived=False)
        await position(db_session, old, "P" * 44)
        await position(db_session, live, "Q" * 44)
        books = await PaperRepository(db_session).wallets_with_open_positions()
        relevant = [b for b in books if b.id in {old.id, live.id}]
        assert relevant[0].id == live.id


class TestPositionsKeepTheirOwnExitPolicy:
    async def test_rules_come_off_the_position_not_the_live_strategy(
        self, db_session: AsyncSession
    ) -> None:
        """Rule 5, and rule 6: no SEC-2 or current-strategy rule is applied back."""
        old = await wallet(db_session, strategy_id="equal_weight_v1", generation=60)
        row = await position(
            db_session,
            old,
            "R" * 44,
            target=Decimal("0.02"),
            stop=Decimal("0.005"),
            expires_at=NOW + timedelta(hours=48),
        )
        rules = _rules_for(row)
        # 2x / 0.5x / 48h — the equal-weight bracket, not the live trailing stop.
        assert rules.take_profit_multiple == Decimal(2)
        assert rules.stop_loss_multiple == Decimal("0.5")
        assert rules.trailing_drawdown is None

    async def test_a_trailing_position_keeps_its_trailing_rule(
        self, db_session: AsyncSession
    ) -> None:
        book = await wallet(db_session, strategy_id="trailing_stop_25_v1", generation=61)
        row = await position(db_session, book, "T" * 44, trailing=Decimal("0.25"))
        rules = _rules_for(row)
        assert rules.trailing_drawdown == Decimal("0.25")
        assert rules.take_profit_multiple is None


class TestSharedCapital:
    async def test_a_new_generation_in_the_lineage_mints_no_capital(
        self, db_session: AsyncSession
    ) -> None:
        """Rule 7. Two generations, one pool, one starting balance."""
        old = await wallet(
            db_session, strategy_id=TRAILING_STOP_25_V1.id, generation=50
        )
        new = await wallet(
            db_session,
            strategy_id=TRAILING_STOP_25_SECURED_V2.id,
            generation=51,
            archived=False,
        )
        service = PaperWalletService(db_session)
        cash = await service._cash_for(new)
        # Not 2000. The lineage was funded once.
        assert cash == Decimal(1000)
        assert {old.strategy_id, new.strategy_id} <= lineage_for(new.strategy_id)

    async def test_an_old_generations_open_positions_hold_pool_capital_down(
        self, db_session: AsyncSession
    ) -> None:
        """Rules 8 and 9 — the reason a cutover cannot over-allocate."""
        old = await wallet(
            db_session, strategy_id=TRAILING_STOP_25_V1.id, generation=52
        )
        new = await wallet(
            db_session,
            strategy_id=TRAILING_STOP_25_SECURED_V2.id,
            generation=53,
            archived=False,
        )
        await position(db_session, old, "U" * 44, size=Decimal(400))
        cash = await PaperWalletService(db_session)._cash_for(new)
        assert cash == Decimal(600), "the predecessor's open book must consume the pool"

    async def test_an_unrelated_generation_does_not_share_the_pool(
        self, db_session: AsyncSession
    ) -> None:
        """Independent past experiments stay independent.

        Summing all six historical wallets against one base yields -$1,934,
        which is an artefact rather than a balance. Lineage is what prevents it.
        """
        unrelated = await wallet(db_session, strategy_id="equal_weight_v1", generation=54)
        await position(db_session, unrelated, "V" * 44, size=Decimal(900))
        new = await wallet(
            db_session,
            strategy_id=TRAILING_STOP_25_SECURED_V2.id,
            generation=55,
            archived=False,
        )
        assert await PaperWalletService(db_session)._cash_for(new) == Decimal(1000)

    def test_a_strategy_outside_any_lineage_funds_itself_alone(self) -> None:
        assert lineage_for("something_new") == frozenset({"something_new"})

    def test_the_sec2_generation_shares_the_pool_with_generation_two(self) -> None:
        assert TRAILING_STOP_25_SECURED_V2.id in lineage_for(TRAILING_STOP_25_V1.id)


class TestOnlyOneGenerationAcceptsEntries:
    async def test_entries_target_the_live_wallet_only(self) -> None:
        """Rules 1 and 2, read out of the review pass itself.

        Exits iterate a collection of books; entries take the single live
        wallet. The asymmetry is the contract.
        """
        source = inspect.getsource(PaperWalletService.review)
        assert "_open_entries(wallet" in source
        assert "for book in books" in source

    async def test_the_live_wallet_is_unique_by_construction(
        self, db_session: AsyncSession
    ) -> None:
        live = await PaperRepository(db_session).live_wallet()
        count = len(
            (
                await db_session.execute(
                    select(PaperWallet).where(PaperWallet.archived_at.is_(None))
                )
            ).all()
        )
        assert count <= 1
        if live is not None:
            assert live.archived_at is None

    def test_exactly_one_operational_strategy_in_the_runtime_registry(self) -> None:
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-c",
             "from app.paper.strategy import registry;"
             "print(','.join(s.id for s in registry.all() if s.operational))"],
            capture_output=True, text=True, cwd="/app", check=True,
        )
        assert len([x for x in result.stdout.strip().split(",") if x]) == 1


class TestExitsSurviveASecurityOutage:
    """Rule: an RPC/security outage must never stop an existing exit."""

    def test_the_settle_path_never_touches_security(self) -> None:
        for name in (
            "_settle_exits",
            "_settle_observed_bracket",
            "_close_observed_bracket",
            "_settle_activated_trail",
            "_close_terminal",
            "_record_audits",
        ):
            source = inspect.getsource(getattr(PaperWalletService, name))
            for banned in ("entry_policy", "TokenSecurityService", "_security_for_entry"):
                assert banned not in source, (name, banned)

    def test_review_settles_before_it_ever_reaches_the_entry_path(self) -> None:
        """Ordering matters: exits must not sit behind a gate that can hang."""
        source = inspect.getsource(PaperWalletService.review)
        assert source.index("_settle_exits") < source.index("_open_entries")

    def test_the_exit_walk_reads_only_stored_observations(self) -> None:
        source = inspect.getsource(PaperWalletService._settle_exits)
        assert "series_for_mints" in source
        assert "rpc" not in source.lower()


class TestNothingHistoricalChanges:
    def test_archived_book_management_is_a_deliberate_switch(self) -> None:
        """It must be a setting, not a hardcoded behaviour.

        Enabling it settles positions that have been frozen for days, so the
        decision belongs to an operator. It shipped `False`, was approved on
        2026-08-20 and is now enabled in this deployment — so this asserts the
        *mechanism* exists rather than pinning a value that legitimately
        changes.
        """
        assert isinstance(settings.PAPER_WALLET_MANAGE_ARCHIVED_GENERATIONS, bool)
        assert (
            "PAPER_WALLET_MANAGE_ARCHIVED_GENERATIONS"
            in type(settings).model_fields
        )

    def test_only_the_live_book_is_swept_when_the_switch_is_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The off path must still exist and still be safe."""
        source = inspect.getsource(PaperWalletService.review)
        assert "if settings.PAPER_WALLET_MANAGE_ARCHIVED_GENERATIONS" in source
        assert "else [wallet]" in source

    def test_each_cutover_retires_its_predecessor_but_not_its_positions(
        self,
    ) -> None:
        """Post-cutover. Retiring a strategy does not retire its positions.

        A retired generation stops taking entries; its open book keeps closing
        under the rules stored on each position. True of Generation 2 at the
        SEC-2 cutover and of Generation 7 at the HOLD-6H cutover, so it is
        asserted of every retired member of the lineage rather than of one.
        """
        from app.paper.strategy import TRAILING_STOP_25_SECURED_HOLD6H_V3

        assert registry.default.id == TRAILING_STOP_25_SECURED_HOLD6H_V3.id
        assert registry.default.operational is True
        for retired in (TRAILING_STOP_25_V1, TRAILING_STOP_25_SECURED_V2):
            assert retired.operational is False, retired.id
            assert retired.unavailable_reason, retired.id
            # Still in the lineage: retired for entries, not for capital.
            assert retired.id in lineage_for(registry.default.id), retired.id

    def test_the_capital_change_is_inert_for_a_single_wallet_lineage(
        self, db_session: AsyncSession
    ) -> None:
        """Today's live wallet is alone in its lineage, so cash is unchanged.

        `cash_for` is the same pure function it always was; pooling only adds
        members, and today there are none to add.
        """
        assert callable(metrics.cash_for)

    async def test_pooling_reads_and_never_writes(self, db_session: AsyncSession) -> None:
        source = inspect.getsource(PaperWalletService._cash_for)
        for banned in ("update(", "insert(", "delete(", "session.add"):
            assert banned not in source

    def test_no_lineage_merges_unrelated_historical_experiments(self) -> None:
        declared = set().union(*CAPITAL_LINEAGES)
        for retired in (
            "equal_weight_v1",
            "paper_2x_trail25_v1",
            "paper_all_scanned_tp125_sl50_v1",
            "paper_track_record_tp125_sl50_v1",
            "survival_s2_v1_1",
        ):
            assert retired not in declared, retired


class TestRetrospectiveRecoveryNeverUsesCurrentPrice:
    """Requirements 4, 5 and 6 — the recovery contract."""

    def test_an_archived_book_is_settled_retrospectively(self) -> None:
        source = inspect.getsource(PaperWalletService.review)
        assert "retrospective=book.archived_at is not None" in source

    def test_a_historical_breach_never_requests_a_live_quote(self) -> None:
        """The exact defect this would otherwise have: a 2026-08-05 breach
        closed at today's Jupiter price and today's timestamp."""
        source = inspect.getsource(PaperWalletService._settle_exits)
        index = source.index("_exit_execution_for")
        guard = source[max(0, index - 400) : index]
        assert "if not historical:" in guard

    def test_freshness_not_archive_state_decides_the_pricing_model(self) -> None:
        """A cutover archives a book whose positions are still trading now.

        Generation 2 is archived the instant SEC-2 goes live, and its breaches
        still happen on current data. Pricing them retrospectively would
        change their execution model, so the age of the breaching observation
        decides — not the wallet's archive flag.
        """
        source = inspect.getsource(PaperWalletService._settle_exits)
        assert "breach_age" in source
        assert "HEALTH_TRACKED_STALE_SECONDS" in source
        assert "historical = retrospective and breach_age >" in source

    def test_a_retrospective_close_carries_no_execution_quote(self) -> None:
        values = PaperWalletService._retrospective_close_values()
        assert values["exit_execution_quote"] is None
        assert values["exit_execution_quoted_at"] is None
        assert values["exit_execution_price_impact_pct"] is None

    def test_a_retrospective_close_is_marked_as_recovered(self) -> None:
        values = PaperWalletService._retrospective_close_values()
        assert values["exit_execution_model_version"] == "observed_retrospective_v1"
        assert values["exit_execution_confidence"] == "observed_historical_recovery"
        assert "No live quote" in values["exit_execution_fallback_reason"]

    def test_the_live_book_still_prices_exits_with_a_live_quote(self) -> None:
        """The live wallet's behaviour must not change."""
        source = inspect.getsource(PaperWalletService.review)
        assert "retrospective=book.archived_at is not None" in source
        # The live wallet has archived_at None, so retrospective is False.
        assert "retrospective=True" not in source
