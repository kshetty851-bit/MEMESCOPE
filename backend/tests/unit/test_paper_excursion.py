"""MFE, MAE and exit capture from observed snapshots.

These metrics decide which V1.1 experiments are worth running: a poor MFE means
the entry is wrong and no exit rule can save it, while a good MFE with poor
capture means the exit is giving back what the entry earned. Getting the two
confused would send the whole research phase after the wrong lever.

The cases below are the ones that break naive implementations: a single
observation (a reading, not a path), a trade that was never favourable (capture
is undefined, not zero), and a level matched twice (the *first* time it was
reached is the answer a timing metric owes).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import ClassVar

from app.paper.excursion import (
    FIDELITY_NOTE,
    Availability,
    compute,
    summarise,
)
from app.paper.models import Quote

OPENED = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
ENTRY = Decimal("100")


def quote(minutes: int, price: str) -> Quote:
    return Quote(price_usd=Decimal(price), captured_at=OPENED + timedelta(minutes=minutes))


class TestWinner:
    """Up to +50%, back to +20%, exited there."""

    path: ClassVar[list] = [
        quote(5, "110"),
        quote(10, "150"),
        quote(15, "130"),
        quote(20, "120"),
    ]

    def test_mfe_is_the_best_observed_level(self) -> None:
        result = compute(
            entry_price=ENTRY, opened_at=OPENED, quotes=self.path, exit_price=Decimal(120)
        )
        assert result.available
        assert result.mfe_pct == Decimal(50)
        assert result.price_at_mfe == Decimal(150)

    def test_mae_is_the_worst_observed_level(self) -> None:
        result = compute(entry_price=ENTRY, opened_at=OPENED, quotes=self.path)
        # Never below entry: the worst reading is +10%.
        assert result.mae_pct == Decimal(10)

    def test_time_to_extremes_is_measured_from_entry(self) -> None:
        result = compute(entry_price=ENTRY, opened_at=OPENED, quotes=self.path)
        assert result.seconds_to_mfe == 600
        assert result.time_to_mfe == OPENED + timedelta(minutes=10)

    def test_capture_is_realized_over_mfe(self) -> None:
        result = compute(
            entry_price=ENTRY, opened_at=OPENED, quotes=self.path, exit_price=Decimal(120)
        )
        # Took +20 of an available +50.
        assert result.realized_exit_return_pct == Decimal(20)
        assert result.exit_capture_ratio == Decimal("0.4")


class TestLoser:
    path: ClassVar[list] = [quote(5, "90"), quote(10, "70"), quote(15, "75")]

    def test_mae_is_negative_and_mfe_may_be_too(self) -> None:
        result = compute(
            entry_price=ENTRY, opened_at=OPENED, quotes=self.path, exit_price=Decimal(75)
        )
        assert result.mae_pct == Decimal(-30)
        assert result.mfe_pct == Decimal(-10)

    def test_capture_is_undefined_when_never_favourable(self) -> None:
        """A position that was never up offers nothing to capture.

        Zero would be wrong and a ratio against a negative MFE would have a sign
        that says nothing about the exit.
        """
        result = compute(
            entry_price=ENTRY, opened_at=OPENED, quotes=self.path, exit_price=Decimal(75)
        )
        assert result.exit_capture_ratio is None

    def test_negative_capture_when_a_winner_is_given_back(self) -> None:
        """Up 20%, exited at a loss. Capture is negative and that is correct."""
        result = compute(
            entry_price=ENTRY,
            opened_at=OPENED,
            quotes=[quote(5, "120"), quote(10, "80")],
            exit_price=Decimal(90),
        )
        assert result.mfe_pct == Decimal(20)
        assert result.exit_capture_ratio == Decimal("-0.5")


class TestFlat:
    def test_a_flat_path_reports_zero_excursions(self) -> None:
        result = compute(
            entry_price=ENTRY,
            opened_at=OPENED,
            quotes=[quote(5, "100"), quote(10, "100")],
            exit_price=ENTRY,
        )
        assert result.mfe_pct == Decimal(0)
        assert result.mae_pct == Decimal(0)
        # MFE of zero is not favourable, so capture stays undefined.
        assert result.exit_capture_ratio is None


class TestUnavailable:
    def test_single_snapshot_is_not_a_path(self) -> None:
        result = compute(entry_price=ENTRY, opened_at=OPENED, quotes=[quote(5, "120")])
        assert result.availability is Availability.INSUFFICIENT_OBSERVATIONS
        assert result.mfe_pct is None
        assert result.mae_pct is None

    def test_missing_path_is_reported_not_zeroed(self) -> None:
        result = compute(entry_price=ENTRY, opened_at=OPENED, quotes=[])
        assert result.availability is Availability.NO_PATH
        assert result.mfe_pct is None

    def test_no_entry_price_is_refused(self) -> None:
        for price in (None, Decimal(0), Decimal(-1)):
            result = compute(
                entry_price=price, opened_at=OPENED, quotes=[quote(5, "1"), quote(6, "2")]
            )
            assert result.availability is Availability.NO_ENTRY_PRICE


class TestIrregularIntervals:
    def test_uneven_spacing_does_not_affect_the_extremes(self) -> None:
        """Gaps are not interpolated; the extreme is whichever reading is extreme."""
        path = [quote(1, "110"), quote(400, "180"), quote(405, "90")]
        result = compute(entry_price=ENTRY, opened_at=OPENED, quotes=path)
        assert result.mfe_pct == Decimal(80)
        assert result.mae_pct == Decimal(-10)
        assert result.seconds_to_mfe == 400 * 60

    def test_order_given_is_the_order_walked(self) -> None:
        """The first occurrence of an extreme wins, so a repeat does not move it."""
        path = [quote(5, "150"), quote(10, "120"), quote(15, "150")]
        result = compute(entry_price=ENTRY, opened_at=OPENED, quotes=path)
        assert result.seconds_to_mfe == 300


class TestFidelity:
    def test_every_result_carries_the_resolution_note(self) -> None:
        for result in (
            compute(entry_price=ENTRY, opened_at=OPENED, quotes=[]),
            compute(
                entry_price=ENTRY, opened_at=OPENED, quotes=[quote(1, "1"), quote(2, "2")]
            ),
        ):
            assert result.fidelity == FIDELITY_NOTE == "SNAPSHOT_RESOLUTION_ONLY"


class TestEntryIsNotAnObservation:
    def test_mae_can_be_positive(self) -> None:
        """A position never below entry has a positive MAE.

        Seeding the series with the entry price would floor MAE at zero and hide
        that the position was never underwater.
        """
        result = compute(
            entry_price=ENTRY, opened_at=OPENED, quotes=[quote(5, "130"), quote(10, "140")]
        )
        assert result.mae_pct == Decimal(30)


class TestSummary:
    def test_aggregates_and_counts_unavailable(self) -> None:
        excursions = [
            compute(
                entry_price=ENTRY,
                opened_at=OPENED,
                quotes=[quote(5, "150"), quote(10, "120")],
                exit_price=Decimal(120),
            ),
            compute(
                entry_price=ENTRY,
                opened_at=OPENED,
                quotes=[quote(5, "90"), quote(10, "80")],
                exit_price=Decimal(80),
            ),
            compute(entry_price=ENTRY, opened_at=OPENED, quotes=[]),
        ]
        summary = summarise(excursions)

        assert summary.trades == 3
        assert summary.available == 2
        assert summary.unavailable == 1
        assert summary.never_favourable == 1

    def test_counts_winners_given_back(self) -> None:
        """Up 40%, closed at a loss — the clearest exit-rule damage."""
        given_back = compute(
            entry_price=ENTRY,
            opened_at=OPENED,
            quotes=[quote(5, "140"), quote(10, "80")],
            exit_price=Decimal(95),
        )
        summary = summarise([given_back], gave_back_threshold_pct=Decimal(20))
        assert summary.gave_back_winners == 1
