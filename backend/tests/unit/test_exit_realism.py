"""Paper exits must never book a fill the market could not have given.

The audit that produced this file found 28 production exits priced at their
trailing trigger while the observed market was up to 10,258x lower — turning
-$2,632 of real losses into +$20 of recorded profit. Every test here is one
way that can happen.

The governing rule:

    A stop decides WHEN to sell. It does not decide WHAT you receive.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.paper import exits
from app.paper.engine import resolve_exit
from app.paper.models import ExitReason, OpenPosition, Quote

pytestmark = pytest.mark.unit

ENTRY = Decimal(100)
OPENED = datetime(2026, 8, 20, tzinfo=UTC)


def q(hour: int, price: str) -> Quote:
    return Quote(price_usd=Decimal(price), captured_at=OPENED + timedelta(hours=hour))


def trail(pct: str = "0.25") -> exits.ExitRules:
    return exits.ExitRules(trailing_drawdown=Decimal(pct))


class TestGapThroughTrailingStop:
    def test_a_99_percent_gap_fills_at_the_gap_not_the_trigger(self) -> None:
        """The production case, in miniature.

        Peak 200 sets a 150 trigger; the next reading is 2. The wallet used to
        book 150 — a 50% *gain* on a token that had lost 99% — because the
        trigger and the fill were the same field.
        """
        found, _ = exits.resolve(
            trail(), entry_price=ENTRY, opened_at=OPENED,
            quotes=[q(1, "200"), q(2, "2")],
        )
        assert found is not None
        assert found.reason is ExitReason.STOP
        assert found.trigger_price == Decimal(150)
        assert found.price_usd == Decimal(2)

    def test_the_fill_is_never_better_than_the_market(self) -> None:
        """The invariant, over the whole space rather than one case."""
        for peak, crash in (("200", "2"), ("500", "1"), ("120", "89"), ("101", "70")):
            found, _ = exits.resolve(
                trail(), entry_price=ENTRY, opened_at=OPENED,
                quotes=[q(1, peak), q(2, crash)],
            )
            assert found is not None, (peak, crash)
            assert found.price_usd <= found.trigger_price, (peak, crash)
            assert found.price_usd == Decimal(crash), (peak, crash)

    def test_a_continuous_stop_is_unchanged(self) -> None:
        """The ordinary case must not move.

        When the market prints exactly at the trigger there is nothing to
        correct, and this fix must not quietly reprice normal trades.
        """
        found, _ = exits.resolve(
            trail(), entry_price=ENTRY, opened_at=OPENED,
            quotes=[q(1, "200"), q(2, "150")],
        )
        assert found is not None
        assert found.price_usd == Decimal(150) == found.trigger_price


class TestGapThroughFixedStop:
    def test_it_fills_at_the_observed_price(self) -> None:
        found, _ = exits.resolve(
            exits.ExitRules(stop_loss_multiple=Decimal("0.5")),
            entry_price=ENTRY, opened_at=OPENED, quotes=[q(1, "3")],
        )
        assert found is not None
        assert found.trigger_price == Decimal(50)
        assert found.price_usd == Decimal(3)

    def test_the_legacy_engine_agrees(self) -> None:
        """`engine.resolve_exit` is held equivalent to `exits.resolve`, so it
        carries the same rule or the equivalence property is a lie."""
        position = OpenPosition(
            mint_address="m", opened_at=OPENED, entry_price=ENTRY,
            size_usd=Decimal(100), quantity=Decimal(1),
            target_price=Decimal(200), stop_price=Decimal(50),
            expires_at=None, peak_price=ENTRY,
        )
        found = resolve_exit(position, [q(1, "3")])
        assert found is not None
        assert found.price_usd == Decimal(3)
        assert found.trigger_price == Decimal(50)


class TestTargetSemanticsArePreserved:
    def test_a_gap_through_the_target_still_fills_at_the_target(self) -> None:
        """Deliberately *not* symmetric with the stop.

        A take-profit limit does not pay more than it asked. Booking the
        overshoot would be the same error as booking the stop trigger, just
        in the wallet's favour.
        """
        found, _ = exits.resolve(
            exits.ExitRules(take_profit_multiple=Decimal(2)),
            entry_price=ENTRY, opened_at=OPENED, quotes=[q(1, "900")],
        )
        assert found is not None
        assert found.reason is ExitReason.TARGET
        assert found.price_usd == Decimal(200)

    def test_the_coarse_reading_is_always_resolved_against_the_wallet(self) -> None:
        """Both directions, stated as one property."""
        up, _ = exits.resolve(
            exits.ExitRules(take_profit_multiple=Decimal(2)),
            entry_price=ENTRY, opened_at=OPENED, quotes=[q(1, "900")],
        )
        down, _ = exits.resolve(
            exits.ExitRules(stop_loss_multiple=Decimal("0.5")),
            entry_price=ENTRY, opened_at=OPENED, quotes=[q(1, "3")],
        )
        assert up is not None and down is not None
        assert up.price_usd < Decimal(900)   # gave up the overshoot
        assert down.price_usd < Decimal(50)  # took the gap


class TestExpiryAndOrdering:
    def test_expiry_fills_at_the_observed_price(self) -> None:
        found, _ = exits.resolve(
            exits.ExitRules(hold_for=timedelta(hours=1)),
            entry_price=ENTRY, opened_at=OPENED, quotes=[q(2, "7")],
        )
        assert found is not None
        assert found.reason is ExitReason.EXPIRY
        assert found.price_usd == Decimal(7)

    def test_an_exit_is_stamped_with_the_observation_that_caused_it(self) -> None:
        """Timestamp ordering: the exit belongs to the reading, never to the
        clock of whichever worker happened to notice."""
        found, _ = exits.resolve(
            trail(), entry_price=ENTRY, opened_at=OPENED,
            quotes=[q(1, "200"), q(9, "2")],
        )
        assert found is not None
        assert found.at == OPENED + timedelta(hours=9)
        assert found.at > OPENED


class TestTheManualExitCannotPredateThePosition:
    def test_the_service_clamps_a_stale_observation(self) -> None:
        """Seven production trades closed before they opened, one by 250
        hours, because the manual-sell fallback stamped the exit with the last
        stored observation and never checked it came after the entry."""
        import inspect

        from app.paper.service import PaperWalletService

        source = inspect.getsource(PaperWalletService._manual_preview_from)
        assert "if exit_at < position.opened_at:" in source
        assert "exit_at = now" in source


class TestDecimalsNoLongerKillTheQuotePath:
    def test_the_exit_path_reads_decimals_from_the_mint_before_giving_up(self) -> None:
        """114 of 169 exits fell back to the trigger for want of one integer.

        Decimals are not invented here — they are read off the mint account
        with the same decoder the security evaluator uses, and a failed read
        still falls back exactly as before.
        """
        import inspect

        from app.paper.service import PaperWalletService

        source = inspect.getsource(PaperWalletService._exit_execution_for)
        assert "self._mint_decimals(" in source
        helper = inspect.getsource(PaperWalletService._mint_decimals)
        assert "decode_mint_account" in helper
        assert "getAccountInfo" in helper
