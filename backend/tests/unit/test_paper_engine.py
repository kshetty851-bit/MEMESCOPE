"""When a position closed, and why.

These tests exist because the obvious implementation is wrong in a way that
flatters the result. Comparing the *latest* price to the target every few
minutes means a position that spiked through its stop and recovered before
anyone looked never gets stopped out — and a worker outage silently improves the
track record.

So the property under test is not "the exit is correct", it is **"the exit does
not depend on when anybody looked"**. Several of these assert exactly that by
running the same history through in different chunks and demanding one answer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.paper.engine import market_value, peak_before, peak_through, resolve_exit
from app.paper.models import ExitReason, OpenPosition, Quote

pytestmark = pytest.mark.unit

OPENED = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def position(**overrides: object) -> OpenPosition:
    base = {
        "mint_address": "probe",
        "opened_at": OPENED,
        "entry_price": Decimal(100),
        "quantity": Decimal(1),
        "size_usd": Decimal(100),
        "target_price": Decimal(200),
        "stop_price": Decimal(50),
        "expires_at": OPENED + timedelta(hours=48),
        "peak_price": Decimal(100),
    }
    base.update(overrides)
    return OpenPosition(**base)  # type: ignore[arg-type]


def quotes(*pairs: tuple[int, str]) -> list[Quote]:
    """`(hours after entry, price)` pairs, in the order they were observed."""
    return [
        Quote(captured_at=OPENED + timedelta(hours=hours), price_usd=Decimal(price))
        for hours, price in pairs
    ]


class TestFirstBreachWins:
    def test_a_position_still_inside_its_bounds_stays_open(self) -> None:
        assert resolve_exit(position(), quotes((1, "120"), (2, "90"))) is None

    def test_the_target_closes_at_the_target_not_at_the_overshoot(self) -> None:
        """The rule says +100%. A snapshot that happened to catch +140% does not
        mean the strategy sold there — it means the reading was coarse."""
        found = resolve_exit(position(), quotes((1, "240")))
        assert found is not None
        assert found.reason is ExitReason.TARGET
        assert found.price_usd == Decimal(200)

    def test_the_stop_closes_at_the_gap_not_at_the_stop(self) -> None:
        """The mirror of the target rule, and deliberately *not* symmetric.

        A coarse reading is resolved against the wallet in both directions.
        For the target that means booking the level (200) rather than the
        overshoot (240): you may not claim upside the data does not support.
        For the stop the same principle points the other way — booking the
        level (50) rather than the gap (10) claims a fill nobody could have
        got, which is the identical error wearing the opposite sign.

        This test asserted 50 until the exit-realism audit. On real trades that
        cost the wallet its honesty: 28 production exits booked the trailing
        trigger while the observed market was up to 10,258x lower, turning
        -$2,632 of losses into +$20 of recorded profit.

        The file's own next test already says it: "the honest reading of an
        ambiguous bar is the adverse one; the alternative books a win the data
        does not support."
        """
        found = resolve_exit(position(), quotes((1, "10")))
        assert found is not None
        assert found.reason is ExitReason.STOP
        assert found.price_usd == Decimal(10)
        assert found.trigger_price == Decimal(50)

    def test_the_earliest_breach_wins_not_the_best_one(self) -> None:
        """A token that hit its stop on Tuesday and its target on Wednesday is a
        loss. Scanning for the best outcome instead would be hindsight."""
        found = resolve_exit(position(), quotes((1, "40"), (2, "500")))
        assert found is not None
        assert found.reason is ExitReason.STOP

    def test_a_reading_that_satisfies_both_bounds_resolves_to_the_stop(self) -> None:
        """One snapshot cannot distinguish the order of a move that spanned
        both. The honest reading of an ambiguous bar is the adverse one; the
        alternative books a win the data does not support."""
        found = resolve_exit(
            position(stop_price=Decimal(50), target_price=Decimal(60)),
            quotes((1, "45")),
        )
        assert found is not None
        assert found.reason is ExitReason.STOP


class TestExpiry:
    def test_expiry_closes_at_the_first_reading_after_the_deadline(self) -> None:
        found = resolve_exit(position(), quotes((47, "110"), (49, "115")))
        assert found is not None
        assert found.reason is ExitReason.EXPIRY
        assert found.price_usd == Decimal(115)
        assert found.at == OPENED + timedelta(hours=49)

    def test_expiry_uses_the_observation_clock_not_the_evaluator_clock(self) -> None:
        """A position that should have expired at noon closes at noon's price
        even if nothing evaluated it until midnight."""
        found = resolve_exit(position(), quotes((48, "70"), (72, "5")))
        assert found is not None
        assert found.price_usd == Decimal(70)

    def test_a_breach_before_the_deadline_still_wins(self) -> None:
        found = resolve_exit(position(), quotes((10, "220"), (49, "115")))
        assert found is not None
        assert found.reason is ExitReason.TARGET


class TestReproducibility:
    """The guarantee the whole wallet rests on."""

    HISTORY = ((1, "110"), (2, "130"), (3, "45"), (4, "300"))

    def test_evaluating_in_chunks_gives_the_same_exit_as_evaluating_at_once(
        self,
    ) -> None:
        """A worker that ran every minute and one that ran once a day must
        produce the same trade from the same stored history."""
        at_once = resolve_exit(position(), quotes(*self.HISTORY))

        # Evaluated piecewise, carrying the watermark forward as the service does.
        held = position()
        piecewise = None
        for pair in self.HISTORY:
            piecewise = resolve_exit(held, quotes(pair))
            if piecewise is not None:
                break

        assert at_once is not None
        assert piecewise is not None
        assert (at_once.reason, at_once.price_usd, at_once.at) == (
            piecewise.reason,
            piecewise.price_usd,
            piecewise.at,
        )

    def test_a_missed_window_does_not_erase_a_breach(self) -> None:
        """The failure this design exists to prevent: a spike through the stop
        that recovered before anyone looked must still be a stop-out."""
        found = resolve_exit(position(), quotes((1, "40"), (2, "105")))
        assert found is not None
        assert found.reason is ExitReason.STOP

    def test_no_observations_leaves_the_position_untouched(self) -> None:
        assert resolve_exit(position(), []) is None


class TestPeak:
    def test_the_peak_carries_forward_rather_than_being_recomputed(self) -> None:
        """A high observed once is a fact, and must not shrink when the snapshot
        that recorded it is pruned."""
        assert peak_through(position(peak_price=Decimal(180)), quotes((1, "120"))) == Decimal(
            180
        )

    def test_a_new_high_raises_it(self) -> None:
        assert peak_through(position(), quotes((1, "120"), (2, "150"))) == Decimal(150)

    def test_the_trades_peak_stops_at_its_exit(self) -> None:
        """A high printed after the position closed belongs to the token, not to
        the trade. Crediting it would be the most flattering error available."""
        history = quotes((1, "120"), (2, "40"), (3, "900"))
        exit_at = OPENED + timedelta(hours=2)
        assert peak_before(position(), history, exit_at) == Decimal(120)


class TestMarketValue:
    def test_an_unpriced_holding_has_no_value_rather_than_zero(self) -> None:
        assert market_value(position(), None) is None

    def test_value_is_quantity_times_price(self) -> None:
        assert market_value(position(quantity=Decimal(3)), Decimal(7)) == Decimal(21)
