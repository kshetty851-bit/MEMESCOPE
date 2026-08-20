"""SEC-2: the invariant, the generation boundary, and exit isolation.

The two most important files in the phase are this one and
`test_sec2_entry_gate.py`. This one proves the gate cannot be routed around
and — just as important — that it cannot reach the exit path.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.paper import PaperPosition, PaperWallet
from app.paper.repository import PaperRepository, SecurityGateViolationError
from app.paper.strategy import (
    SECURITY_GATED_STRATEGY_IDS,
    TRAILING_STOP_25_SECURED_V2,
    TRAILING_STOP_25_V1,
    registry,
)
from app.security.contract import (
    EVALUATOR_VERSION,
    CheckStatus,
    SecurityCheck,
    TokenSecurityEvaluation,
    roll_up,
)
from app.security.entry_policy import MANDATORY_CHECKS, EntryOutcome, decide

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
MINT = "S" * 44


def verified(at: datetime = NOW) -> TokenSecurityEvaluation:
    checks = tuple(
        SecurityCheck(name=name, status=CheckStatus.PASS) for name in MANDATORY_CHECKS
    )
    return TokenSecurityEvaluation(
        mint_address=MINT,
        evaluated_at=at,
        overall_status=roll_up(checks),
        checks=checks,
        evaluator_version=EVALUATOR_VERSION,
    )


async def make_wallet(session: AsyncSession, strategy_id: str, generation: int) -> PaperWallet:
    """A wallet to open positions against.

    Deliberately created archived. `uq_paper_wallets_live` allows exactly one
    row with `archived_at IS NULL`, so a fixture that made a *live* wallet
    would collide with whatever the rest of the suite had already created and
    would pass alone while failing in company. The invariant under test reads
    the wallet's strategy, not its archive state.
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


def position_values(wallet: PaperWallet, mint: str = MINT) -> dict:
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


class TestTheRepositoryInvariant:
    async def test_a_gated_wallet_cannot_open_without_a_decision(
        self, db_session: AsyncSession
    ) -> None:
        wallet = await make_wallet(db_session, TRAILING_STOP_25_SECURED_V2.id, 99)
        with pytest.raises(SecurityGateViolationError):
            await PaperRepository(db_session).open_position(**position_values(wallet))

    async def test_a_gated_wallet_cannot_open_on_a_refusal(
        self, db_session: AsyncSession
    ) -> None:
        wallet = await make_wallet(db_session, TRAILING_STOP_25_SECURED_V2.id, 99)
        refusal = decide(None, now=NOW)
        assert refusal.outcome is EntryOutcome.REFUSED_UNAVAILABLE
        with pytest.raises(SecurityGateViolationError):
            await PaperRepository(db_session).open_position(
                security=refusal, **position_values(wallet)
            )

    async def test_a_gated_wallet_cannot_open_on_stale_evidence(
        self, db_session: AsyncSession
    ) -> None:
        wallet = await make_wallet(db_session, TRAILING_STOP_25_SECURED_V2.id, 99)
        stale = decide(verified(at=NOW - timedelta(days=1)), now=NOW)
        with pytest.raises(SecurityGateViolationError):
            await PaperRepository(db_session).open_position(
                security=stale, **position_values(wallet)
            )

    async def test_a_gated_wallet_opens_on_a_fresh_allow(
        self, db_session: AsyncSession
    ) -> None:
        wallet = await make_wallet(db_session, TRAILING_STOP_25_SECURED_V2.id, 99)
        allow = decide(verified(), now=NOW)
        assert allow.allowed is True
        created = await PaperRepository(db_session).open_position(
            security=allow, **position_values(wallet)
        )
        assert created is not None

    async def test_an_ungated_wallet_is_completely_unaffected(
        self, db_session: AsyncSession
    ) -> None:
        """Generation 2 must keep trading exactly as before the cutover."""
        wallet = await make_wallet(db_session, TRAILING_STOP_25_V1.id, 98)
        created = await PaperRepository(db_session).open_position(**position_values(wallet))
        assert created is not None

    async def test_a_violation_raises_rather_than_returning_none(
        self, db_session: AsyncSession
    ) -> None:
        """`None` means 'lost the race' and is swallowed as ordinary.

        A missing gate reported that way would vanish into a refusal counter,
        so it must be an exception instead.
        """
        wallet = await make_wallet(db_session, TRAILING_STOP_25_SECURED_V2.id, 99)
        try:
            result = await PaperRepository(db_session).open_position(
                **position_values(wallet)
            )
        except SecurityGateViolationError:
            return
        pytest.fail(f"expected SecurityGateViolationError, got {result!r}")


class TestNoBypassExists:
    def test_every_position_insert_goes_through_open_position(self) -> None:
        """§41: the invariant is only worth anything if nothing routes around it."""
        import pathlib

        root = pathlib.Path(inspect.getfile(PaperRepository)).parent.parent
        offenders = []
        for path in root.rglob("*.py"):
            if "__pycache__" in str(path):
                continue
            source = path.read_text()
            if "insert(PaperPosition)" in source and path.name != "repository.py":
                offenders.append(str(path))
        assert offenders == []

    async def test_the_gate_reads_the_wallets_own_strategy(
        self, db_session: AsyncSession
    ) -> None:
        """A caller must not be able to declare itself ungated."""
        source = inspect.getsource(PaperRepository._assert_security_authorized)
        assert "select(PaperWallet.strategy_id)" in source


class TestGenerationBoundary:
    def test_exactly_one_strategy_is_operational_in_the_real_registry(self) -> None:
        """Read the registry as the *runtime* sees it — §26, done properly.

        An in-process assertion cannot answer this question. `conftest` has an
        autouse fixture that flips the archived Track Record strategy to
        operational for the whole suite, so anything asserting inside pytest
        is measuring the fixture rather than the product. (SEC-2 also fixed
        that fixture to restore afterwards, but "the test only passes because
        another fixture happened to clean up" is not an invariant.)

        So this launches a clean interpreter with no conftest loaded. What it
        prints is what the worker, the scheduler and the API actually import.
        """
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from app.paper.strategy import registry;"
                "print(','.join(s.id for s in registry.all() if s.operational))",
            ],
            capture_output=True,
            text=True,
            cwd="/app",
            check=True,
        )
        operational = [item for item in result.stdout.strip().split(",") if item]
        assert len(operational) == 1, operational
        assert operational == [registry.default.id]

    def test_the_operational_strategy_is_the_gated_one(self) -> None:
        """After the cutover, the only strategy taking entries is gated."""
        assert TRAILING_STOP_25_SECURED_V2.operational is True
        assert TRAILING_STOP_25_SECURED_V2.id in SECURITY_GATED_STRATEGY_IDS
        assert registry.default.id in SECURITY_GATED_STRATEGY_IDS

    def test_only_the_new_strategy_is_gated(self) -> None:
        assert TRAILING_STOP_25_SECURED_V2.id in SECURITY_GATED_STRATEGY_IDS
        assert TRAILING_STOP_25_V1.id not in SECURITY_GATED_STRATEGY_IDS

    def test_the_alpha_rules_are_identical_across_the_boundary(self) -> None:
        """§13: same strategy, cleaner entry. Nothing else may move.

        If sizing or the trailing stop differed, a comparison between the two
        generations would be measuring two changes at once.
        """
        for field in ("trade_size_usd", "trailing_drawdown", "top_n"):
            assert getattr(TRAILING_STOP_25_SECURED_V2, field) == getattr(
                TRAILING_STOP_25_V1, field
            ), field

    def test_the_version_changed_because_the_entry_contract_changed(self) -> None:
        assert TRAILING_STOP_25_SECURED_V2.version != TRAILING_STOP_25_V1.version


class TestExitPathIsolation:
    """§43/§44: the gate is ENTRY only. This is the critical safety property."""

    def test_no_exit_function_consults_the_security_gate(self) -> None:
        from app.paper import exits, service

        for module in (exits,):
            source = inspect.getsource(module)
            for banned in ("entry_policy", "TokenSecurityService", "SECURITY_GATED"):
                assert banned not in source, (module.__name__, banned)

        # And in the service, security must appear only on the entry path.
        for name in (
            "_settle_exits",
            "_settle_observed_bracket",
            "_close_observed_bracket",
            "_settle_activated_trail",
            "_close_terminal",
        ):
            source = inspect.getsource(getattr(service.PaperWalletService, name))
            for banned in ("entry_policy", "_security_for_entry", "TokenSecurityService"):
                assert banned not in source, (name, banned)

    def test_the_gate_helper_is_only_called_from_the_entry_path(self) -> None:
        from app.paper import service

        source = inspect.getsource(service)
        callers = [
            line.strip()
            for line in source.splitlines()
            if "_security_for_entry(" in line and "async def" not in line
        ]
        assert len(callers) == 1

    def test_manual_sell_does_not_consult_security(self) -> None:
        from app.paper.service import PaperWalletService

        source = inspect.getsource(PaperWalletService.manual_sell)
        assert "security" not in source.lower()


class TestNoHistoricalFabrication:
    async def test_an_old_position_gains_no_security_record(
        self, db_session: AsyncSession
    ) -> None:
        """§22: history must not become retroactively verified."""
        wallet = await make_wallet(db_session, TRAILING_STOP_25_V1.id, 98)
        created = await PaperRepository(db_session).open_position(
            **position_values(wallet)
        )
        assert created is not None
        # The position row carries no security column at all, so there is
        # nowhere for a fabricated PASS to live.
        columns = {column.name for column in PaperPosition.__table__.columns}
        assert not {name for name in columns if "security" in name}
