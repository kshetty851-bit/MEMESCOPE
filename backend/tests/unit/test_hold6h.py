"""HOLD-6H: a position sells at six hours, at a price somebody would pay.

The rule is one line — "whichever comes first, and at six hours sell regardless"
— and it has exactly two ways of going wrong, both covered here.

    A cutoff nobody observes is not a cutoff.
    A fill nobody could have got is not a fill.

The first is why the holding period is checked against the clock as well as
against the series: a rugged token stops producing observations, and that is
the position a maximum hold exists to leave. The second is why the clock is
allowed to decide *when* and never *what*.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.paper import execution, exits
from app.paper.execution import ExecutionQuote
from app.paper.models import ExitReason, Quote
from app.paper.service import PaperWalletService
from app.paper.strategy import TRAILING_STOP_25_SECURED_HOLD6H_V3 as HOLD6H

pytestmark = pytest.mark.unit

ENTRY = Decimal(100)
OPENED = datetime(2026, 8, 20, tzinfo=UTC)


def q(hours: float, price: str) -> Quote:
    return Quote(price_usd=Decimal(price), captured_at=OPENED + timedelta(hours=hours))


class TestTheRuleItself:
    def test_six_hours_closes_a_position_that_never_breached_anything(self) -> None:
        """The whole point: a flat position is not held forever."""
        found, _ = exits.resolve(
            HOLD6H.exit_rules,
            entry_price=ENTRY,
            opened_at=OPENED,
            quotes=[q(1, "100"), q(5, "99"), q(6.5, "97")],
        )
        assert found is not None
        assert found.reason is ExitReason.EXPIRY
        assert found.at == OPENED + timedelta(hours=6.5)
        assert found.price_usd == Decimal(97)

    def test_the_trailing_stop_still_wins_when_it_comes_first(self) -> None:
        """One rule was added, not substituted."""
        found, _ = exits.resolve(
            HOLD6H.exit_rules,
            entry_price=ENTRY,
            opened_at=OPENED,
            quotes=[q(1, "200"), q(2, "140")],
        )
        assert found is not None
        assert found.reason is ExitReason.STOP
        assert found.trigger_price == Decimal(150)
        assert found.price_usd == Decimal(140)

    def test_a_loss_at_the_cutoff_is_taken_and_not_deferred(self) -> None:
        """"Regardless of profit or loss" — the loss half, stated as a test."""
        found, _ = exits.resolve(
            HOLD6H.exit_rules,
            entry_price=ENTRY,
            opened_at=OPENED,
            quotes=[q(7, "40")],
        )
        assert found is not None
        # Nothing but the clock could have closed this. The strategy has no
        # fixed stop, and the trail never armed because no high above entry was
        # ever printed - so without the cutoff, -60% would simply keep running.
        assert found.reason is ExitReason.EXPIRY
        assert found.price_usd == Decimal(40)

    def test_before_the_cutoff_nothing_closes(self) -> None:
        found, _ = exits.resolve(
            HOLD6H.exit_rules,
            entry_price=ENTRY,
            opened_at=OPENED,
            quotes=[q(5.9, "90")],
        )
        assert found is None


def _position(*, expires_at: datetime | None) -> SimpleNamespace:
    return SimpleNamespace(
        id="pos",
        mint_address="probe",
        opened_at=OPENED,
        entry_price=ENTRY,
        quantity=Decimal(1),
        peak_price=ENTRY,
        expires_at=expires_at,
    )


def _service(*, quote: object) -> tuple[PaperWalletService, AsyncMock]:
    """A service reduced to the two collaborators this path uses."""
    close = AsyncMock(return_value=True)
    service = Mock(spec=PaperWalletService)
    service._exit_execution_for = AsyncMock(return_value=quote)
    service._execution_close_values = PaperWalletService._execution_close_values.__get__(
        service
    )
    service._repository = SimpleNamespace(close=close)
    return service, close


class TestTheCutoffWithNoObservationBehindIt:
    """A token that stopped printing must still be sold at six hours."""

    async def test_an_elapsed_hold_closes_on_a_live_route(self) -> None:
        quote = Mock(spec=ExecutionQuote)
        quote.estimated_price_usd = Decimal("3")
        quote.model_version = execution.JUPITER_MODEL_VERSION
        quote.as_json.return_value = {}
        quote.quoted_at = OPENED + timedelta(hours=7)
        quote.context_slot = 1
        quote.price_impact_pct = Decimal("0.1")
        quote.platform_fee_usd = None
        quote.route = "r"
        quote.confidence = "quoted"

        service, close = _service(quote=quote)
        closed = await PaperWalletService._settle_elapsed_hold(
            service,
            _position(expires_at=OPENED + timedelta(hours=6)),
            now=OPENED + timedelta(hours=7),
        )

        assert closed is True
        kwargs = close.await_args.kwargs
        assert kwargs["exit_reason"] == ExitReason.EXPIRY.value
        # The route decides the price. Not the entry, not a stored snapshot.
        assert kwargs["exit_price"] == Decimal("3")
        assert kwargs["closed_at"] == OPENED + timedelta(hours=7)
        # No observation existed, so none is invented.
        assert kwargs["exit_observed_price"] is None
        # And it cannot predate its own entry. The manual-sell fallback could,
        # and the negative durations that produced corrupted every hold-time
        # figure computed over the book before it was clamped.
        assert kwargs["closed_at"] > OPENED

    async def test_no_executable_route_leaves_the_position_open(self) -> None:
        """The failure is recorded by *not* closing. An exit nobody could have
        got is the fiction this path was rewritten to stop telling."""
        service, close = _service(quote=execution.LegacyExecution("no route"))
        closed = await PaperWalletService._settle_elapsed_hold(
            service,
            _position(expires_at=OPENED + timedelta(hours=6)),
            now=OPENED + timedelta(hours=7),
        )

        assert closed is False
        close.assert_not_awaited()

    async def test_a_position_still_inside_its_hold_is_not_quoted_at_all(self) -> None:
        service, close = _service(quote=None)
        closed = await PaperWalletService._settle_elapsed_hold(
            service,
            _position(expires_at=OPENED + timedelta(hours=6)),
            now=OPENED + timedelta(hours=5),
        )
        assert closed is False
        service._exit_execution_for.assert_not_awaited()
        close.assert_not_awaited()

    async def test_a_position_with_no_holding_period_is_untouched(self) -> None:
        """Every position opened before HOLD-6H. The sweep must be inert."""
        service, close = _service(quote=None)
        closed = await PaperWalletService._settle_elapsed_hold(
            service, _position(expires_at=None), now=OPENED + timedelta(days=30)
        )
        assert closed is False
        service._exit_execution_for.assert_not_awaited()
        close.assert_not_awaited()
